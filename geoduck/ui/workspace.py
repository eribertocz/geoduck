# SPDX-License-Identifier: GPL-2.0-or-later
"""Contenido único del workspace de GeoDuck (ui-ux-spec §8, ADR-0013): sesión, bases, SQL y diagnóstico.

Es el mismo widget en la ventana propia y en el panel acoplado (`ui.shells`); cambiar de presentación lo
traslada de contenedor sin recrearlo. Nada aquí depende del contenedor que lo muestra.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QResizeEvent
from qgis.PyQt.QtWidgets import (
    QAction,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
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
    DatabaseAttached,
    DatabaseDetached,
    DetachFailed,
    LoadFinished,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
    SpatialActivated,
    SpatialActivationFailed,
    SpatialChecked,
    TransactionFailed,
)
from geoduck.domain.catalog import AttachRequest, OpenAction
from geoduck.domain.diagnostics import CheckStatus, DiagnosticReport
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.session import ErrorCause, SessionState
from geoduck.domain.transaction import CloseChoice
from geoduck.domain.versions import release_stage
from geoduck.ui.about_dialog import AboutDialog
from geoduck.ui.attach_dialog import AttachDialog
from geoduck.ui.close_dialog import CloseTransactionDialog
from geoduck.ui.diagnostics_dialog import DiagnosticsDialog
from geoduck.ui.explorer import CatalogExplorer
from geoduck.ui.i18n import tr
from geoduck.ui.load_flow import LoadFlow
from geoduck.ui.sql_panel import SqlPanel
from geoduck.ui.widgets import secondary

STATE_TEXT = {
    SessionState.DISCONNECTED: "Sin sesión",
    SessionState.CONNECTING: "Conectando…",
    SessionState.READY: "Lista",
    SessionState.BUSY: "Ejecutando…",
    SessionState.DETACHING: "Desadjuntando…",
    SessionState.CLOSING: "Cerrando…",
    SessionState.ERROR_RECOVERABLE: "Fallo recuperable",
}

#: Ancho inicial (px) del explorador lateral en la ventana propia, como en la maqueta.
EXPLORER_WIDTH = 280

_CAN_CLOSE = {SessionState.CONNECTING, SessionState.READY, SessionState.BUSY, SessionState.ERROR_RECOVERABLE}


class WorkspaceContent(QWidget):
    """Explorador, editor SQL, resultados, mensajes y estado. Una sola instancia por GeoDuck (ADR-0013)."""

    def __init__(
        self,
        coordinator: SessionCoordinator,
        run_diagnostics: Callable[[], DiagnosticReport],
        parent: QWidget | None = None,
        *,
        ask_close_choice: Callable[[CloseConfirmationRequired, QWidget], CloseChoice] | None = None,
        ask_attach_request: Callable[[OpenAction, QWidget], AttachRequest | None] | None = None,
        ask_yes_no: Callable[[QWidget, str, str], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("GeoDuckWorkspaceContent")
        self._coordinator = coordinator
        self._run_diagnostics = run_diagnostics
        self._report: DiagnosticReport | None = None
        self._ask_close_choice = ask_close_choice or CloseTransactionDialog.ask
        self._ask_attach_request = ask_attach_request or AttachDialog.ask
        self._ask_yes_no = ask_yes_no or _ask_yes_no

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(8)
        layout.addWidget(self._build_session_bar())
        # Dos disposiciones del mismo explorador y del mismo panel SQL (ui-ux-spec §8): pestañas en el panel
        # acoplado; explorador lateral y SQL con un divisor en la ventana propia. Nunca se recrean.
        self.databases_card = self._build_databases_card()
        self.load_flow = LoadFlow(coordinator, self._show_plain_message, self)
        self.sql_panel = SqlPanel(coordinator, on_message=self._show_plain_message, load_flow=self.load_flow)
        self.tabs = QTabWidget()
        self.side_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.side_splitter.setChildrenCollapsible(False)
        self.side_splitter.setObjectName("geoduckSideSplitter")
        self.side_splitter.hide()
        self._side_sized = False
        self._presented = False
        self.wide = False
        self.set_presentation(wide=False)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.side_splitter, 1)
        layout.addWidget(self._build_message())
        layout.addWidget(self._build_env_banner())
        layout.addWidget(self._build_footer_bar())
        self._setup_compaction()

        self.start_button.clicked.connect(self._start)
        self.rollback_button.clicked.connect(self._coordinator.rollback_transaction)
        self.close_button.clicked.connect(self._close)
        self.spatial_action.triggered.connect(self._check_spatial)
        self.diagnostics_button.clicked.connect(self.show_diagnostics)
        self.about_button.clicked.connect(self.show_about)
        self.open_action.triggered.connect(lambda: self._attach(OpenAction.OPEN_EXISTING))
        self.create_action.triggered.connect(lambda: self._attach(OpenAction.CREATE_NEW))
        self.detach_action.triggered.connect(self._detach)
        self.refresh_button.clicked.connect(self._refresh_catalog)
        self.map_button.clicked.connect(self._view_map)
        #: Capas de la última carga (ids) y quién las lleva al mapa (lo conecta el complemento).
        self.last_layers: list[str] = []
        self.on_view_map: Callable[[list[str]], str | None] | None = None
        QgsProject.instance().layersRemoved.connect(self._layers_removed)
        self.sql_panel.log_counts_changed.connect(self._update_log_tab)
        self.explorer.itemSelectionChanged.connect(lambda: self._render(self._coordinator.state))
        self.explorer.load_requested.connect(self.load_flow.start)
        self._unsubscribe = coordinator.subscribe(self._on_event)

        self.refresh_environment()
        self._render(coordinator.state)

    # -- construcción ------------------------------------------------------------------------------

    @staticmethod
    def _bold(label: QLabel) -> QLabel:
        font = QFont(label.font())
        font.setBold(True)
        label.setFont(font)
        return label

    def _build_session_bar(self) -> QFrame:
        """Barra de sesión (ui-ux-spec §8): estado y motor; «Iniciar sesión» sin sesión activa; «Revertir
        transacción» solo con la transacción abortada; «Cerrar sesión»; menú «⋯» con «Activar spatial…»."""
        bar = QFrame()
        self.session_bar = bar
        bar.setFrameShape(QFrame.Shape.StyledPanel)
        bar.setToolTip(
            tr(
                "Sesión DuckDB temporal (:memory:). Las tablas que cree desaparecen al cerrar la sesión; "
                "las capas ya entregadas a QGIS no dependen de ella."
            )
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        self.session_title = self._bold(QLabel(tr("Sesión DuckDB")))
        row.addWidget(self.session_title)
        self.state_label = QLabel()
        self.state_label.setObjectName("geoduckStateLabel")
        self.state_label.setAccessibleName(tr("Estado de la sesión"))
        row.addWidget(self.state_label)
        self.engine_label = secondary(QLabel())
        # Recortable: no fija el ancho mínimo del panel; el texto completo, en la ayuda
        self.engine_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.engine_label, 1)
        self.start_button = QPushButton(tr("Iniciar sesión"))
        self.start_button.setAccessibleName(tr("Iniciar sesión en memoria"))
        self.start_button.setDefault(True)
        self.rollback_button = QPushButton(tr("Revertir transacción"))
        self.rollback_button.setToolTip(
            tr("La transacción está abortada: ROLLBACK para volver a usar la sesión")
        )
        self.rollback_button.hide()
        self.close_button = QPushButton(tr("Cerrar sesión"))
        self.close_button.setAccessibleName(tr("Cerrar la sesión DuckDB"))
        self.spatial_action = QAction(tr("Activar spatial…"), self)
        self.spatial_action.setToolTip(
            tr("Carga la extensión spatial de DuckDB en esta sesión, con su permiso. GeoDuck no la necesita.")
        )
        self.more_button = QToolButton()
        self.more_button.setText("⋯")
        self.more_button.setToolTip(tr("Más acciones de la sesión"))
        self.more_button.setAccessibleName(tr("Más acciones de la sesión"))
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_menu = QMenu(self.more_button)
        self.more_menu.setToolTipsVisible(True)
        self.more_menu.addAction(self.spatial_action)
        self.more_button.setMenu(self.more_menu)
        for widget in (self.start_button, self.rollback_button, self.close_button, self.more_button):
            row.addWidget(widget)
        return bar

    def _build_databases_card(self) -> QFrame:
        """Bases de la sesión y sus esquemas, tablas y vistas (GD-CAT-001)."""
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)
        # «+» = Abrir existente / Crear nueva; actualizar el catálogo; «Desadjuntar» en el menú de la base
        self.open_action = QAction(tr("Abrir existente…"), self)
        self.open_action.setToolTip(tr("Adjunta un archivo DuckDB existente; nunca crea uno"))
        self.create_action = QAction(tr("Crear nueva…"), self)
        self.create_action.setToolTip(tr("Crea un archivo DuckDB nuevo; nunca sobrescribe uno existente"))
        self.detach_action = QAction(tr("Desadjuntar"), self)
        self.detach_action.setToolTip(tr("Desadjunta la base seleccionada y libera el archivo"))
        self.add_button = QToolButton()
        self.add_button.setIcon(QgsApplication.getThemeIcon("symbologyAdd.svg"))
        self.add_button.setText("+")
        self.add_button.setToolTip(tr("Abrir o crear una base DuckDB"))
        self.add_button.setAccessibleName(tr("Abrir o crear una base DuckDB"))
        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(self.add_button)
        add_menu.setToolTipsVisible(True)
        add_menu.addAction(self.open_action)
        add_menu.addAction(self.create_action)
        self.add_button.setMenu(add_menu)
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(QgsApplication.getThemeIcon("mActionRefresh.svg"))
        self.refresh_button.setText(tr("Actualizar"))
        self.refresh_button.setToolTip(tr("Vuelve a leer las bases, esquemas, tablas y vistas"))
        self.refresh_button.setAccessibleName(tr("Actualizar el catálogo"))
        title = QHBoxLayout()
        title.addWidget(self._bold(QLabel(tr("Bases de datos"))))
        title.addStretch(1)
        title.addWidget(self.add_button)
        title.addWidget(self.refresh_button)
        card_layout.addLayout(title)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(tr("Buscar bases, esquemas y tablas…"))
        self.search_edit.setAccessibleName(tr("Buscar en el explorador"))
        self.search_edit.setClearButtonEnabled(True)
        card_layout.addWidget(self.search_edit)
        self.explorer = CatalogExplorer()
        self.explorer.database_actions = [self.detach_action]
        self.search_edit.textChanged.connect(self.explorer.set_filter)
        card_layout.addWidget(self.explorer, 1)
        card_layout.addWidget(secondary(QLabel(tr("Doble clic o clic derecho → Cargar en QGIS…"))))
        return card

    def set_presentation(self, *, wide: bool) -> None:
        """Ventana (`wide`): explorador lateral | SQL. Panel: pestañas Explorador / SQL. Los mismos widgets,
        trasladados (no se recrean: el texto, los resultados y la selección se conservan)."""
        if self._presented and wide == self.wide:
            return  # ya está así: rehacer las pestañas movería la pestaña activa
        self._presented = True
        if wide:
            self.side_splitter.addWidget(self.databases_card)  # addWidget saca el widget de la pestaña
            self.side_splitter.addWidget(self.sql_panel)
            self.sql_panel.dock_log(None)  # registro debajo del editor y los resultados, plegable
            self.side_splitter.setStretchFactor(0, 0)
            self.side_splitter.setStretchFactor(1, 1)
            if not self._side_sized:  # ancho inicial del explorador; luego, el del usuario (preferencia)
                self.side_splitter.setSizes([EXPLORER_WIDTH, 4 * EXPLORER_WIDTH])
                self._side_sized = True
            self.tabs.hide()
            self.side_splitter.show()
            self.databases_card.show()
            self.sql_panel.show()
            self.sql_panel.log_section.show()
        else:  # en pestañas, QTabWidget muestra solo la activa: mostrar las demás las dibujaría encima
            self.tabs.insertTab(0, self.databases_card, tr("Explorador"))
            self.tabs.insertTab(1, self.sql_panel, tr("SQL"))
            self.sql_panel.dock_log(self.tabs)  # pestaña «Registro» con el número de errores
            self._update_log_tab(*self.sql_panel.log_counts())
            self.tabs.setCurrentIndex(0)  # Explorador; la pestaña guardada la restaura el controlador
            self.side_splitter.hide()
            self.tabs.show()
        self.wide = wide

    # -- panel estrecho: etiquetas cortas, nunca menos acciones (ui-ux-spec §8, AT-UX-013) --------------

    def _setup_compaction(self) -> None:
        self._labels = [
            (self.session_title, tr("Sesión DuckDB"), tr("Sesión")),
            (self.start_button, tr("Iniciar sesión"), tr("Iniciar")),
            (self.rollback_button, tr("Revertir transacción"), tr("Revertir")),
            (self.close_button, tr("Cerrar sesión"), tr("Cerrar")),
            (self.map_button, tr("Ver en el mapa"), tr("Mapa")),
            (self.diagnostics_button, tr("Diagnóstico del entorno…"), tr("Diagnóstico…")),
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

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self.set_compact(event.size().width() < self._wide_width)

    def _build_message(self) -> QLabel:
        """Errores recuperables: texto comprensible + código, seleccionable (ui-ux-spec §3)."""
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message_label.setAccessibleName(tr("Mensaje"))
        self.message_label.hide()
        return self.message_label

    def _build_env_banner(self) -> QFrame:
        self.env_banner = QFrame()
        self.env_banner.setFrameShape(QFrame.Shape.StyledPanel)
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
        """Barra de estado (ui-ux-spec §8): «Ver en el mapa», diagnóstico, «Acerca de…» y versión. El mensaje
        de la última carga (modalidad, origen y acceso) queda encima, completo y seleccionable."""
        footer = QHBoxLayout()
        self.map_button = QPushButton(tr("Ver en el mapa"))
        self.map_button.setFlat(True)
        self.map_button.setToolTip(tr("Trae QGIS al frente, selecciona la última capa cargada y hace zoom"))
        self.map_button.setEnabled(False)
        footer.addWidget(self.map_button)
        self.diagnostics_button = QPushButton(tr("Diagnóstico del entorno…"))
        self.diagnostics_button.setFlat(True)
        self.diagnostics_button.setToolTip(
            tr("Comprueba Python, QGIS, DuckDB, PyArrow y la extensión spatial")
        )
        self.about_button = QPushButton(tr("Acerca de…"))
        self.about_button.setFlat(True)
        self.about_button.setToolTip(tr("Versión, licencia, enlaces y componentes detectados"))
        footer.addWidget(self.diagnostics_button)
        footer.addWidget(self.about_button)
        footer.addStretch(1)
        stage = release_stage(__version__)
        self.version_label = secondary(QLabel(f"v{__version__}" + (f" · {stage}" if stage else "")))
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
            self.tabs.setTabText(index, tr("Registro") + (f" ({errors})" if errors else ""))

    def _check_spatial(self) -> None:
        try:
            self._coordinator.check_spatial()
        except GeoDuckError as exc:
            self._show_plain_message(exc.message)

    def _confirm_spatial(self, event: SpatialChecked) -> None:
        """Consentimiento de `LOAD` y, aparte, de `INSTALL` (spatial-spec §10). Vale para esta sesión."""
        if event.loaded:
            self._show_plain_message(tr("La extensión spatial ya está cargada en esta sesión."))
            return
        if not self._ask_yes_no(
            self,
            tr("Activar spatial"),
            tr(
                "¿Cargar la extensión spatial de DuckDB en esta sesión (LOAD spatial)?\n\n"
                "Añade funciones ST_* y SRC EPSG para su SQL. GeoDuck no la necesita para cargar capas. "
                "El permiso vale solo para esta sesión."
            ),
        ):
            self._show_plain_message(tr("No se cargó spatial. Todo lo demás sigue funcionando."))
            return
        install = False
        if not event.installed:
            install = self._ask_yes_no(
                self,
                tr("Instalar spatial"),
                tr(
                    "La extensión spatial no está instalada. ¿Descargarla e instalarla ahora "
                    "(INSTALL spatial)?\n\nSe descarga del repositorio oficial de DuckDB, con firma "
                    "verificada. Necesita conexión a internet."
                ),
            )
            if not install:
                self._show_plain_message(tr("No se instaló spatial. Todo lo demás sigue funcionando."))
                return
        self._show_plain_message(tr("Activando spatial…"))
        try:
            self._coordinator.activate_spatial(install=install)
        except GeoDuckError as exc:
            self._show_plain_message(exc.message)

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
                tr("El entorno no está listo para GeoDuck: ")
                + ", ".join(failing)
                + ". "
                + tr("Abra «Diagnóstico del entorno» para ver qué hacer.")
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

    def _on_spatial_event(self, event: AppEvent) -> bool:
        if isinstance(event, SpatialChecked):
            self._confirm_spatial(event)
        elif isinstance(event, SpatialActivated):
            axis = f" · geometry_always_xy: {event.always_xy}" if event.always_xy else ""
            version = f" {event.version}" if event.version else ""
            self._show_plain_message(tr("Extensión spatial{} cargada en esta sesión").format(version) + axis)
        elif isinstance(event, SpatialActivationFailed):
            self._show_message(
                tr("No se pudo activar spatial. Todo lo demás sigue funcionando."),
                event.code.value,
                event.message,
            )
        else:
            return False
        return True

    def _on_event(self, event: AppEvent) -> None:  # noqa: PLR0912 - un despacho por evento
        if self._on_spatial_event(event):
            return
        if isinstance(event, LoadFinished):
            report = event.report
            self.last_layers = [i for i, _ in report.layers] or [report.layer_id]
            self.map_button.setEnabled(True)
            return
        if isinstance(event, SessionStateChanged):
            self._render(event.current)
        elif isinstance(event, SessionStarted):
            info = event.info
            cancel = (
                tr("cancelación inmediata disponible")
                if info.interrupt_enabled
                else tr("cancelación entre lotes")
            )
            self.engine_label.setText(f"DuckDB {info.duckdb_version} · {cancel}")
            self.engine_label.setToolTip(self.engine_label.text())
        elif isinstance(event, CatalogChanged):
            self.explorer.show_catalog(event.catalog)
            self._render(self._coordinator.state)
        elif isinstance(event, CatalogUnavailable):
            self._show_message(tr("No se pudo leer el catálogo."), event.code.value, event.message)
        elif isinstance(event, DatabaseAttached):
            self.explorer.select_database(event.database.name)
        elif isinstance(event, DatabaseDetached):
            self._render(self._coordinator.state)
        elif isinstance(event, AttachFailed):
            self._show_message(tr("No se adjuntó la base."), event.code.value, event.message)
        elif isinstance(event, DetachFailed):
            self._show_message(tr("No se desadjuntó la base."), event.code.value, event.message)
        elif isinstance(event, CloseConfirmationRequired):
            self._coordinator.resolve_close(self._ask_close_choice(event, self))
        elif isinstance(event, SessionInvalidated):
            self.message_label.setText(
                tr("Sesión invalidada:")
                + f" {event.message} [{event.code.value}] "
                + tr("Inicie una sesión nueva o cierre.")
            )
            self.message_label.show()
        elif isinstance(event, TransactionFailed):
            self.message_label.setText(
                tr("No se completó la operación sobre la transacción.")
                + f" [{event.code.value}] {event.message}"
            )
            self.message_label.show()
        elif isinstance(event, SessionFailed):
            self.message_label.setText(
                tr("No se pudo completar la operación.") + f" [{event.code.value}] {event.message}"
            )
            self.message_label.show()

    def show_text(self, text: str) -> None:
        """Mensaje para el usuario desde fuera del panel (p. ej. el diagnóstico de geometrías)."""
        self._show_plain_message(text)

    def _show_plain_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.show()

    def _show_message(self, summary: str, code: str, detail: str) -> None:
        self.message_label.setText(f"{summary} [{code}] {detail}")
        self.message_label.show()

    def _render(self, state: SessionState) -> None:
        env_ok = self._report is None or self._report.ok
        can_start = env_ok and self._coordinator.can_start
        ready = state is SessionState.READY
        self.explorer.loading_enabled = ready
        self.state_label.setText(tr(STATE_TEXT[state]))
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
        self.spatial_action.setEnabled(ready)
        if state is SessionState.DISCONNECTED:
            self.engine_label.setText(tr("Sin sesión activa."))


def _ask_yes_no(parent: QWidget, title: str, text: str) -> bool:
    answer = QMessageBox.question(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes
