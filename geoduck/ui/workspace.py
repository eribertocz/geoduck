# SPDX-License-Identifier: GPL-2.0-or-later
"""Contenido único del workspace de GeoDuck (ui-ux-spec §8, ADR-0013): sesión, bases, SQL y diagnóstico.

Es el mismo widget en la ventana propia y en el panel acoplado (`ui.shells`); cambiar de presentación lo
traslada de contenedor sin recrearlo. Nada aquí depende del contenedor que lo muestra.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont, QKeySequence, QResizeEvent
from qgis.PyQt.QtWidgets import (
    QAction,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from geoduck import __version__
from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    AppEvent,
    AttachFailed,
    CatalogChanged,
    CatalogUnavailable,
    CloseConfirmationRequired,
    ColumnsListed,
    ColumnsUnavailable,
    DatabaseAttached,
    DatabaseDetached,
    DetachFailed,
    LoadFailed,
    LoadFinished,
    LoadPrepareFailed,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
    TransactionFailed,
)
from geoduck.domain.catalog import AttachRequest, OpenAction
from geoduck.domain.diagnostics import CheckStatus, DiagnosticReport
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.session import ErrorCause, SessionState
from geoduck.domain.sql_text import sql_name
from geoduck.domain.transaction import CloseChoice
from geoduck.domain.versions import release_stage
from geoduck.ui import theme
from geoduck.ui.about_dialog import AboutDialog
from geoduck.ui.attach_dialog import AttachDialog
from geoduck.ui.close_dialog import CloseTransactionDialog
from geoduck.ui.diagnostics_dialog import DiagnosticsDialog
from geoduck.ui.explorer import CatalogExplorer
from geoduck.ui.i18n import N_, tr
from geoduck.ui.load_flow import LoadFlow
from geoduck.ui.sql_panel import SqlPanel, muted
from geoduck.ui.widgets import ElidedLabel

STATE_TEXT = {
    SessionState.DISCONNECTED: N_("No session"),
    SessionState.CONNECTING: N_("Connecting…"),
    SessionState.READY: N_("Ready"),
    SessionState.BUSY: N_("Running…"),
    SessionState.DETACHING: N_("Detaching…"),
    SessionState.CLOSING: N_("Closing…"),
    SessionState.ERROR_RECOVERABLE: N_("Recoverable failure"),
}

#: Ancho inicial (px) del explorador lateral en la ventana propia, como en la maqueta.
EXPLORER_WIDTH = 280
#: Altura inicial de la lista «Cuadernos» en la ventana (luego, la del usuario).
NOTEBOOKS_HEIGHT = 140

_CAN_CLOSE = {SessionState.CONNECTING, SessionState.READY, SessionState.BUSY, SessionState.ERROR_RECOVERABLE}


class WorkspaceContent(QWidget):
    """Explorador, editor SQL, resultados, mensajes y estado. Una sola instancia por GeoDuck (ADR-0013)."""

    #: La barra lateral de la ventana se abrió o se plegó (se recuerda).
    sidebar_changed = pyqtSignal(bool)

    def __init__(
        self,
        coordinator: SessionCoordinator,
        run_diagnostics: Callable[[], DiagnosticReport],
        parent: QWidget | None = None,
        *,
        ask_close_choice: Callable[[CloseConfirmationRequired, QWidget], CloseChoice] | None = None,
        ask_attach_request: Callable[[OpenAction, QWidget], AttachRequest | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("geoduckWorkspace")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.palette_colors = theme.palette_for(self)
        self._engine_version = ""
        self.compact_session = False
        self.setStyleSheet(theme.stylesheet(self.palette_colors))  # solo GeoDuck (inventario §0.3)
        self._coordinator = coordinator
        self._run_diagnostics = run_diagnostics
        self._report: DiagnosticReport | None = None
        self._ask_close_choice = ask_close_choice or CloseTransactionDialog.ask
        self._ask_attach_request = ask_attach_request or AttachDialog.ask

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_session_bar())
        self.body = QVBoxLayout()  # tarjetas, mensaje y pie con margen; la barra de sesión, a todo el ancho
        self.body.setContentsMargins(12, 12, 12, 8)
        self.body.setSpacing(10)
        layout.addLayout(self.body, 1)
        # Dos disposiciones del mismo explorador y del mismo panel SQL (ui-ux-spec §8): pestañas en el panel
        # acoplado; explorador lateral y SQL con un divisor en la ventana propia. Nunca se recrean.
        self.databases_card = self._build_databases_card()
        self.load_flow = LoadFlow(coordinator, self._show_plain_message, self)
        self.sql_panel = SqlPanel(coordinator, on_message=self._show_plain_message, load_flow=self.load_flow)
        self.tabs = QTabWidget()
        self.tabs.setProperty("geoduck", "panel-tabs")
        self.tabs.setDocumentMode(True)
        self.side_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.side_splitter.setHandleWidth(12)
        self.side_splitter.setChildrenCollapsible(False)
        self.side_splitter.setObjectName("geoduckSideSplitter")
        self.side_splitter.hide()
        # Columna izquierda de la ventana (G7 · E3): «Cuadernos» encima de «Bases de datos»
        # Siempre con padre: sin él, al arrancar en el panel salía como ventana suelta (propietario)
        self.left_column = QSplitter(Qt.Orientation.Vertical, self)
        self.left_column.hide()
        self.left_column.setObjectName("geoduckLeftColumn")
        self.left_column.setChildrenCollapsible(False)
        self.left_column.addWidget(self.sql_panel.notebook_list)
        self._setup_sidebar_toggle()
        self._side_sized = False
        self._presented = False
        self.wide = False
        self.body.addWidget(self.tabs, 1)
        self.body.addWidget(self.side_splitter, 1)
        self.body.addWidget(self._build_env_banner())
        self._build_message()
        self.body.addWidget(self._build_footer_bar())
        self._setup_compaction()
        self.set_presentation(wide=False)

        self._connect(coordinator)

        self.refresh_environment()
        self._render(coordinator.state)

    # -- construcción ------------------------------------------------------------------------------

    def _connect(self, coordinator: SessionCoordinator) -> None:
        """Conexiones de señales, una sola vez (ADR-0013: alternar nunca vuelve a conectar)."""
        self.start_button.clicked.connect(self._start)
        self.rollback_button.clicked.connect(self._coordinator.rollback_transaction)
        self.close_button.clicked.connect(self._close)
        self.diagnostics_button.clicked.connect(self.show_diagnostics)
        self.about_button.clicked.connect(self.show_about)
        self.open_action.triggered.connect(lambda: self._attach(OpenAction.OPEN_EXISTING))
        self.create_action.triggered.connect(lambda: self._attach(OpenAction.CREATE_NEW))
        self.detach_action.triggered.connect(self._detach)
        self.refresh_button.clicked.connect(self._refresh_catalog)
        self.map_button.clicked.connect(self._view_map)
        #: Capas de la última carga (ids) y quién las lleva al mapa (lo conecta el complemento).
        self.last_layers: list[str] = []
        #: Tabla que «Abrir» seleccionará cuando llegue al catálogo (base, esquema, nombre).
        self._pending_open: tuple[str, str, str] | None = None
        self.on_view_map: Callable[[list[str]], str | None] | None = None
        QgsProject.instance().layersRemoved.connect(self._layers_removed)
        self.sql_panel.log_counts_changed.connect(self._update_log_tab)
        self.explorer.itemSelectionChanged.connect(lambda: self._render(self._coordinator.state))
        self.explorer.load_requested.connect(self.load_flow.start)
        self.explorer.columns_requested.connect(self._request_columns)
        self.explorer.insert_requested.connect(self._insert_in_editor)
        self.explorer.name_for_sql = lambda name: sql_name(name, self._coordinator.reserved_words)
        self._unsubscribe = coordinator.subscribe(self._on_event)

    @staticmethod
    def _bold(label: QLabel) -> QLabel:
        font = QFont(label.font())
        font.setBold(True)
        label.setFont(font)
        return label

    def _build_session_bar(self) -> QFrame:
        """Barra de sesión (inventario V2–V5, P2): ● estado, «Sesión DuckDB», «Lista · DuckDB 2.0.0 · en
        memoria»; a la derecha «Revertir transacción» (solo con la transacción abortada) y «Acoplar a QGIS»
        (ventana). «Iniciar sesión» y «Cerrar sesión» van al pie de «Bases de datos» (decisión del
        propietario, 2026-11-02)."""
        bar = QFrame()
        bar.setObjectName("geoduckSessionBar")
        self.session_bar = bar
        bar.setToolTip(
            tr(
                "Temporary DuckDB session (:memory:). The tables you create disappear when the "
                "session closes; layers already delivered to QGIS do not depend on it."
            )
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(8)
        self.state_dot = QLabel("●")
        self.state_dot.setAccessibleName(tr("Status indicator"))
        row.addWidget(self.state_dot)
        self.session_title = self._bold(QLabel(tr("DuckDB session")))
        row.addWidget(self.session_title)
        detail = QHBoxLayout()  # «Lista · DuckDB 2.0.0 · en memoria», como una sola línea
        detail.setSpacing(4)
        self.state_label = muted(QLabel())
        self.state_label.setObjectName("geoduckStateLabel")
        self.state_label.setAccessibleName(tr("Session status"))
        detail.addWidget(self.state_label)
        self.engine_label = muted(QLabel())
        # Recortable: no fija el ancho mínimo del panel; el texto completo, en la ayuda
        self.engine_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.engine_label.setWordWrap(False)
        detail.addWidget(self.engine_label, 1)
        row.addLayout(detail, 1)
        self._build_session_buttons(row)
        return bar

    def _build_session_buttons(self, row: QHBoxLayout) -> None:
        #: «Acoplar a QGIS»: lo conecta el controlador como botón de alternancia de la ventana (ADR-0013).
        self.dock_button = QPushButton(QgsApplication.getThemeIcon("mDockify.svg"), tr("Dock to QGIS"))
        self.dock_button.setObjectName("geoduckDockButton")
        self.dock_button.setProperty("geoduck", "secondary")
        self.dock_button.setToolTip(tr("Shows GeoDuck as a panel docked to QGIS, with the same session"))
        self.start_button = QPushButton(tr("Start session"))
        self.start_button.setProperty("geoduck", "primary")
        self.start_button.setAccessibleName(tr("Start in-memory session"))
        self.start_button.setDefault(True)
        self.rollback_button = QPushButton(tr("Roll back transaction"))
        self.rollback_button.setProperty("geoduck", "danger")
        self.rollback_button.setToolTip(tr("The transaction is aborted: ROLLBACK to use the session again"))
        self.rollback_button.hide()
        self.close_button = QPushButton(tr("Close session"))
        self.close_button.setProperty("geoduck", "secondary")
        self.close_button.setAccessibleName(tr("Close the DuckDB session"))
        row.addWidget(self.rollback_button)  # aviso de estado: solo con la transacción abortada
        row.addWidget(self.dock_button)

    def _build_catalog_actions(self) -> None:
        # «+» = Abrir existente / Crear nueva; actualizar el catálogo; «Desadjuntar» en el menú de la base
        self.open_action = QAction(tr("Open existing…"), self)
        self.open_action.setToolTip(tr("Attaches an existing DuckDB file; never creates one"))
        self.create_action = QAction(tr("Create new…"), self)
        self.create_action.setToolTip(tr("Creates a new DuckDB file; never overwrites an existing one"))
        #: «Importar capas de QGIS…» (G8, qgis-import-spec §2): lo conecta el complemento.
        self.import_layers_action = QAction(tr("Import QGIS layers…"), self)
        self.import_layers_action.setObjectName("geoduckImportLayers")
        self.import_layers_action.setToolTip(tr("Copies layers of the QGIS project into DuckDB tables"))
        self.detach_action = QAction(tr("Detach"), self)
        self.detach_action.setToolTip(tr("Detaches the selected database and releases the file"))
        self.add_button = QToolButton()
        self.add_button.setProperty("geoduck", "square")
        self.add_button.setText("+")
        self.add_button.setToolTip(tr("Open or create a DuckDB database, or import QGIS layers"))
        self.add_button.setAccessibleName(tr("Open or create a DuckDB database, or import QGIS layers"))
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(self.add_button)
        add_menu.setToolTipsVisible(True)
        add_menu.addAction(self.open_action)
        add_menu.addAction(self.create_action)
        add_menu.addSeparator()
        add_menu.addAction(self.import_layers_action)
        self.add_button.setMenu(add_menu)
        self.refresh_button = QToolButton()
        self.refresh_button.setProperty("geoduck", "square")
        self.refresh_button.setIcon(QgsApplication.getThemeIcon("mActionRefresh.svg"))
        self.refresh_button.setText(tr("Refresh"))
        self.refresh_button.setToolTip(tr("Reads the databases, schemas, tables and views again"))
        self.refresh_button.setAccessibleName(tr("Refresh the catalog"))

    def _build_databases_card(self) -> QFrame:
        """Bases de la sesión y sus esquemas, tablas y vistas (GD-CAT-001)."""
        card = QFrame()
        card.setProperty("geoduck", "card")
        card.setObjectName("geoduckExplorerCard")
        card_layout = QVBoxLayout(card)
        # Nunca más estrecha que su contenido: «Bases de datos» se cortaba con «+» y «⟳» (Qt lo mantiene
        # aunque cambien los botones de la sesión)
        card_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        card_layout.setContentsMargins(12, 12, 12, 0)
        card_layout.setSpacing(10)
        self._build_catalog_actions()
        title = QHBoxLayout()
        title.addWidget(self._bold(QLabel(tr("Databases"))))
        title.addStretch(1)
        title.addWidget(self.add_button)
        title.addWidget(self.refresh_button)
        card_layout.addLayout(title)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("Search databases, schemas and tables…"))
        self.search_edit.setAccessibleName(tr("Search the explorer"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setProperty("geoduck", "search")
        self.search_edit.addAction(
            QgsApplication.getThemeIcon("search.svg"), QLineEdit.ActionPosition.LeadingPosition
        )
        card_layout.addWidget(self.search_edit)
        self.explorer = CatalogExplorer()
        self.explorer.database_actions = [self.detach_action]
        self.search_edit.textChanged.connect(self.explorer.set_filter)
        card_layout.addWidget(self.explorer, 1)
        footer = QFrame()
        footer.setProperty("geoduck", "card-footer")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(2, 8, 2, 10)
        # Pie de «Bases de datos»: iniciar o cerrar la sesión (decisión del propietario, 2026-11-02). La
        # ayuda «Doble clic o clic derecho → Cargar en QGIS…» va en cada tabla y vista del árbol.
        footer_row.addWidget(self.start_button)
        footer_row.addWidget(self.close_button)
        footer_row.addStretch(1)
        card_layout.addWidget(footer)
        return card

    def _setup_sidebar_toggle(self) -> None:
        self.sql_panel.sidebar_button.toggled.connect(self.set_sidebar_open)
        self.sidebar_shortcut = QShortcut(QKeySequence("Ctrl+B"), self)
        self.sidebar_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.sidebar_shortcut.activated.connect(self._toggle_sidebar)

    def _toggle_sidebar(self) -> None:
        if self.wide:
            self.sql_panel.sidebar_button.toggle()

    def set_sidebar_open(self, open_: bool) -> None:
        """Ventana: muestra u oculta la barra lateral «Cuadernos + Bases de datos» (las celdas ocupan el
        resto)."""
        self.sql_panel.sidebar_button.blockSignals(True)
        self.sql_panel.sidebar_button.setChecked(open_)
        self.sql_panel.sidebar_button.blockSignals(False)
        if self.wide:
            self.left_column.setVisible(open_)
        self.sidebar_changed.emit(open_)

    def set_presentation(self, *, wide: bool) -> None:
        """Ventana (`wide`): explorador lateral | SQL. Panel: pestañas Explorador / SQL. Los mismos widgets,
        trasladados (no se recrean: el texto, los resultados y la selección se conservan)."""
        if self._presented and wide == self.wide:
            return  # ya está así: rehacer las pestañas movería la pestaña activa
        self._presented = True
        if wide:
            self.left_column.insertWidget(1, self.databases_card)  # insertWidget lo saca de la pestaña
            self.side_splitter.addWidget(self.left_column)
            self.side_splitter.addWidget(self.sql_panel)
            self.sql_panel.set_presentation(wide=True)  # registro debajo; «Cargar en QGIS ▾» junto a pestañas
            self.side_splitter.setStretchFactor(0, 0)
            self.side_splitter.setStretchFactor(1, 1)
            if not self._side_sized:  # ancho inicial del explorador; luego, el del usuario (preferencia)
                self.side_splitter.setSizes([EXPLORER_WIDTH, 4 * EXPLORER_WIDTH])
                self.left_column.setSizes([NOTEBOOKS_HEIGHT, 4 * NOTEBOOKS_HEIGHT])
                self._side_sized = True
            self.tabs.hide()
            self.side_splitter.show()
            self.databases_card.show()
            self.sql_panel.notebook_list.show()
            self.sql_panel.show()
            self.sql_panel.log_section.show()
        else:  # en pestañas, QTabWidget muestra solo la activa: mostrar las demás las dibujaría encima
            self.tabs.insertTab(0, self.databases_card, tr("Explorer"))
            self.tabs.insertTab(1, self.sql_panel, tr("SQL"))
            self.sql_panel.set_presentation(wide=False, tabs=self.tabs)  # pestaña «Registro»; carga al pie
            self._update_log_tab(*self.sql_panel.log_counts())
            self.tabs.setCurrentIndex(0)  # Explorador; la pestaña guardada la restaura el controlador
            self.side_splitter.hide()
            self.tabs.show()
        self.wide = wide
        # En el panel no hay barra lateral: sus cuadernos van en el selector y sus bases, en «Explorador»
        self.left_column.setVisible(wide and self.sql_panel.sidebar_button.isChecked())
        self.dock_button.setVisible(wide)  # en el panel, «Abrir en ventana» va en su barra de título
        self._place_message(wide)
        self.set_compact(self.compact)

    # -- panel estrecho: etiquetas cortas, nunca menos acciones (ui-ux-spec §8, AT-UX-013) --------------

    def _setup_compaction(self) -> None:
        self.compact = False
        self.wide = True
        self._labels = [
            (self.session_title, tr("DuckDB session"), tr("Session")),
            (self.rollback_button, tr("Roll back transaction"), tr("Roll back")),
            (self.dock_button, tr("Dock to QGIS"), tr("Dock")),
            (self.map_button, tr("View on map"), tr("Map")),
            (self.diagnostics_button, tr("Environment diagnostics…"), tr("Diagnostics…")),
        ]
        for widget, long_text, _short in self._labels:
            if not widget.accessibleName():
                widget.setAccessibleName(long_text)
        bars = (self.session_bar, self.footer_bar)
        self._wide_width = max(bar.sizeHint().width() for bar in bars)  # con las etiquetas largas
        self.set_compact(True)
        for bar in bars:  # el mínimo de cada barra: con las etiquetas cortas
            bar.setMinimumWidth(bar.sizeHint().width())
        self.set_compact(False)

    def set_compact(self, compact: bool) -> None:
        for widget, long_text, short_text in self._labels:
            widget.setText(short_text if compact else long_text)
        self.compact = compact
        if not self.wide:  # panel (inventario P2, P11): «Sesión», «Diagnóstico…»
            self.session_title.setText(tr("Session"))
            self.diagnostics_button.setText(tr("Diagnostics…"))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self.set_compact(event.size().width() < self._wide_width)

    def _build_message(self) -> QLabel:
        """Mensaje de la última operación (inventario V40, P10, P3). Ventana: una línea en la barra de estado,
        recortada, con el texto completo en la ayuda. Panel: recuadro verde (éxito) o rojo (error) completo.
        Siempre seleccionable y con nombre accesible."""
        self.message_label = ElidedLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message_label.setAccessibleName(tr("Message"))
        self.message_label.setProperty("geoduck", "message-info")
        self.message_kind = "info"
        self.message_label.hide()
        return self.message_label

    def _place_message(self, wide: bool) -> None:
        label = self.message_label
        if wide:
            self.body.removeWidget(label)
            self.footer_row.insertWidget(0, label, 1)
        else:
            self.footer_row.removeWidget(label)
            self.body.insertWidget(self.body.indexOf(self.footer_bar), label)
        label.set_elide(wide)
        self._style_message()

    def _style_message(self) -> None:
        kind = "info" if self.wide or self.message_kind == "info" else f"message-{self.message_kind}"
        self._restyle(self.message_label, "message-info" if kind == "info" else kind)
        if self.wide and self.message_kind == "error":
            self._restyle(self.message_label, "error-text")

    @staticmethod
    def _restyle(widget: QWidget, role: str) -> None:
        if widget.property("geoduck") != role:
            widget.setProperty("geoduck", role)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _build_env_banner(self) -> QFrame:
        self.env_banner = QFrame()
        self.env_banner.setProperty("geoduck", "message-error")
        banner_layout = QHBoxLayout(self.env_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        self.env_label = QLabel()
        self.env_label.setWordWrap(True)
        self.env_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        banner_layout.addWidget(self.env_label, 1)
        self.env_banner.hide()
        return self.env_banner

    def _build_footer_bar(self) -> QWidget:
        self.footer_bar = QWidget()
        footer = self._build_footer()
        footer.setContentsMargins(0, 0, 0, 0)
        self.footer_bar.setLayout(footer)
        return self.footer_bar

    def _build_footer(self) -> QHBoxLayout:
        """Barra de estado (inventario V40–V44, P11): en la ventana, el mensaje de la última carga y «Ver en
        el mapa» a la izquierda; «Diagnóstico del entorno…», «Acerca de…» y la versión a la derecha."""
        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.footer_row = footer
        self.map_button = QPushButton(tr("View on map"))
        self.map_button.setIcon(QgsApplication.getThemeIcon("mLayoutItemMap.svg"))
        self.map_button.setProperty("geoduck", "link")
        self.map_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.map_button.setToolTip(
            tr("Brings QGIS to the front, selects the last loaded layer and zooms to it")
        )
        self.map_button.setEnabled(False)
        footer.addWidget(self.map_button)
        footer.addStretch(1)
        self.diagnostics_button = QPushButton(tr("Environment diagnostics…"))
        self.diagnostics_button.setProperty("geoduck", "link")
        self.diagnostics_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.diagnostics_button.setToolTip(
            tr("Checks Python, QGIS, DuckDB, PyArrow and the spatial extension")
        )
        self.about_button = QPushButton(tr("About…"))
        self.about_button.setProperty("geoduck", "link")
        self.about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_button.setToolTip(tr("Version, license, links and detected components"))
        footer.addWidget(self.diagnostics_button)
        footer.addWidget(self.about_button)
        stage = release_stage(__version__)
        self.version_label = muted(QLabel(f"v{__version__}" + (f" · {stage}" if stage else "")))
        footer.addWidget(self.version_label)
        return footer

    # -- acciones ----------------------------------------------------------------------------------

    def _start(self) -> None:
        self.message_label.hide()
        self._coordinator.start_memory_session()

    def _close(self) -> None:
        try:
            self._coordinator.request_close()
        except GeoDuckError as exc:  # p. ej. capas Conectadas con cambios sin guardar (§5.5)
            self._show_plain_message(exc.message)

    def _attach(self, action: OpenAction) -> None:
        request = self._ask_attach_request(action, self)
        if request is None:
            return
        self.message_label.hide()
        if self._coordinator.can_start:
            self._coordinator.start_file_session(request)  # StartSession(mode=file)
        else:
            self._coordinator.attach_database(request)

    def _view_map(self) -> None:
        if self.on_view_map is None or not self.last_layers:
            return
        message = self.on_view_map(list(self.last_layers))
        if message:
            self._show_plain_message(message)

    def _layers_removed(self, _ids: list[str]) -> None:
        """«Ver en el mapa» se desactiva si las capas de la última carga ya no están en el proyecto."""
        project = QgsProject.instance()
        self.map_button.setEnabled(any(project.mapLayer(i) is not None for i in self.last_layers))

    def _refresh_catalog(self) -> None:
        try:
            self._coordinator.refresh_catalog()
        except GeoDuckError as exc:
            self._show_plain_message(exc.message)

    def _update_log_tab(self, _total: int, _ok: int, errors: int) -> None:
        """Pestaña «Registro» del panel con el número de errores (§8)."""
        index = self.tabs.indexOf(self.sql_panel.log_section)
        if index >= 0:
            self.tabs.setTabText(index, tr("Log") + (f" ({errors})" if errors else ""))

    def _detach(self) -> None:
        name = self.explorer.selected_database()
        if name is not None:
            self.message_label.hide()
            try:
                self._coordinator.detach_database(name)
            except GeoDuckError as exc:
                self._show_plain_message(exc.message)

    def refresh_environment(self) -> DiagnosticReport:
        self._report = self._run_diagnostics()
        if self._report.ok:
            self.env_banner.hide()
        else:
            failing = [c.title for c in self._report.checks if c.status is CheckStatus.FAIL]
            self.env_label.setText(
                tr("The environment is not ready for GeoDuck: ")
                + ", ".join(failing)
                + ". "
                + tr("Open «Environment diagnostics» to see what to do.")
            )
            self.env_banner.show()
        self._render(self._coordinator.state)
        return self._report

    def show_diagnostics(self) -> None:
        report = self.refresh_environment()
        DiagnosticsDialog(report, self).exec()

    def show_about(self) -> None:
        AboutDialog(self._report, self._coordinator.engine_info, self).exec()

    def detach(self) -> None:
        self._unsubscribe()
        with contextlib.suppress(TypeError, RuntimeError):
            QgsProject.instance().layersRemoved.disconnect(self._layers_removed)
        self.sql_panel.detach()
        self.load_flow.detach()

    # -- render ------------------------------------------------------------------------------------

    def _request_columns(self, source: tuple[str, str, str]) -> None:
        try:
            self._coordinator.list_columns(source)
        except GeoDuckError as exc:  # sin sesión utilizable: el nodo lo dice y se reintenta al expandir
            self.explorer.show_columns_error(source, exc.message)

    def _insert_in_editor(self, text: str) -> None:
        """Doble clic en una columna (GD-CAT-002): al editor; en el panel, se pasa a la pestaña SQL."""
        if not self.wide:
            self.tabs.setCurrentWidget(self.sql_panel)
        self.sql_panel.insert_text(text)

    def _on_event(self, event: AppEvent) -> None:  # noqa: PLR0912, PLR0915 - un despacho por evento
        if isinstance(event, LoadFinished):
            report = event.report
            self.last_layers = [i for i, _ in report.layers] or [report.layer_id]
            self.map_button.setEnabled(True)
            self._set_message_kind("success")  # el texto lo pone el flujo de carga (se suscribió antes)
            return
        if isinstance(event, LoadFailed):
            self._set_message_kind("info" if event.cancelled else "error")
            return
        if isinstance(event, LoadPrepareFailed):
            self._set_message_kind("error")
            return
        if isinstance(event, SessionStateChanged):
            self._render(event.current)
        elif isinstance(event, SessionStarted):
            info = event.info
            cancel = (
                tr("immediate cancellation available")
                if info.interrupt_enabled
                else tr("cancellation between batches")
            )
            self._engine_version = f"DuckDB {info.duckdb_version}"
            self.engine_label.setToolTip(f"DuckDB {info.duckdb_version} · {cancel}")
            self._update_engine_label()
        elif isinstance(event, CatalogChanged):
            self.explorer.show_catalog(event.catalog)
            if self._pending_open is not None and self.explorer.select_object(*self._pending_open):
                self._pending_open = None
            self._update_engine_label()
            self._render(self._coordinator.state)
        elif isinstance(event, ColumnsListed):
            self.explorer.show_columns(event.source, event.columns)
        elif isinstance(event, ColumnsUnavailable):
            self.explorer.show_columns_error(event.source, event.message)
        elif isinstance(event, CatalogUnavailable):
            self._show_message(tr("The catalog could not be read."), event.code.value, event.message)
        elif isinstance(event, DatabaseAttached):
            self.explorer.select_database(event.database.name)
        elif isinstance(event, DatabaseDetached):
            self._render(self._coordinator.state)
        elif isinstance(event, AttachFailed):
            self._show_message(tr("The database was not attached."), event.code.value, event.message)
        elif isinstance(event, DetachFailed):
            self._show_message(tr("The database was not detached."), event.code.value, event.message)
        elif isinstance(event, CloseConfirmationRequired):
            self._coordinator.resolve_close(self._ask_close_choice(event, self))
        elif isinstance(event, SessionInvalidated):
            self._set_message_kind("error")
            self.message_label.setText(
                tr("Session invalidated:")
                + f" {event.message} [{event.code.value}] "
                + tr("Start a new session or close.")
            )
            self.message_label.show()
        elif isinstance(event, TransactionFailed):
            self._set_message_kind("error")
            self.message_label.setText(
                tr("The transaction operation did not complete.") + f" [{event.code.value}] {event.message}"
            )
            self.message_label.show()
        elif isinstance(event, SessionFailed):
            self._set_message_kind("error")
            self.message_label.setText(
                tr("The operation could not be completed.") + f" [{event.code.value}] {event.message}"
            )
            self.message_label.show()

    def open_table(self, database: str, schema: str, name: str) -> None:
        """«Abrir» tras enviar capas (G8): la tabla, seleccionada en el explorador. Si el catálogo aún no la
        tiene (se está releyendo), se selecciona en cuanto llegue."""
        self._pending_open = None
        if not self.explorer.select_object(database, schema, name):
            self._pending_open = (database, schema, name)

    def show_text(self, text: str) -> None:
        """Mensaje para el usuario desde fuera del panel (p. ej. el diagnóstico de geometrías)."""
        self._show_plain_message(text)

    def _show_plain_message(self, text: str) -> None:
        self._set_message_kind("info")
        self.message_label.setText(text)
        self.message_label.show()

    def _show_message(self, summary: str, code: str, detail: str) -> None:
        self._set_message_kind("error")
        self.message_label.setText(f"{summary} [{code}] {detail}")
        self.message_label.show()

    def _set_message_kind(self, kind: str) -> None:
        """«success» (carga terminada), «error» o «info»: el color del recuadro del panel o del texto."""
        self.message_kind = kind
        self._style_message()

    def _update_engine_label(self) -> None:
        """«· DuckDB 2.0.0 · en memoria» o «· DuckDB 2.0.0 · datos.duckdb» (inventario V4)."""
        if not self._engine_version:
            return
        parts = [self._engine_version]
        catalog = self._coordinator.catalog
        root = catalog.get(catalog.root) if catalog is not None else None
        if root is not None and not self.compact_session:
            parts.append(tr("in memory") if root.in_memory else os.path.basename(root.path or ""))
        self.engine_label.setText("· " + " · ".join(parts))

    def _paint_state(self, state: SessionState) -> None:
        p = self.palette_colors
        if state is SessionState.READY:
            colour = p.primary
        elif state is SessionState.ERROR_RECOVERABLE:
            colour = p.error
        elif state is SessionState.DISCONNECTED:
            colour = p.muted
        else:  # conectando, ejecutando, desadjuntando, cerrando
            colour = p.busy
        self.state_dot.setStyleSheet(f"color: {colour};")

    def _render(self, state: SessionState) -> None:
        env_ok = self._report is None or self._report.ok
        can_start = env_ok and self._coordinator.can_start
        ready = state is SessionState.READY
        self.explorer.loading_enabled = ready
        self.state_label.setText(tr(STATE_TEXT[state]))
        self._paint_state(state)
        self.close_button.setVisible(state is not SessionState.DISCONNECTED)
        self.start_button.setEnabled(can_start)
        self.start_button.setVisible(state is SessionState.DISCONNECTED)
        aborted = (
            state is SessionState.ERROR_RECOVERABLE
            and self._coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
        )
        self.rollback_button.setVisible(aborted)
        self.open_action.setEnabled(can_start or ready)
        self.create_action.setEnabled(can_start or ready)
        self.refresh_button.setEnabled(ready)
        selected = self.explorer.selected_database()
        catalog = self._coordinator.catalog
        self.detach_action.setEnabled(
            ready and selected is not None and catalog is not None and not catalog.is_root(selected)
        )
        self.close_button.setEnabled(state in _CAN_CLOSE)
        if state is SessionState.DISCONNECTED:
            self._engine_version = ""
            self.engine_label.setText("")
            self.engine_label.setToolTip("")
