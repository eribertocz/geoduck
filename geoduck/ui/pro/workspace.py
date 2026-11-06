# SPDX-License-Identifier: GPL-2.0-or-later
"""Workspace Pro: estructura de la interfaz nueva (workspace-pro-spec §3, §6, §8, §11; GD-WSP-002, 005, 007).

`ProWorkspace` es el contenido único que muestran la ventana propia y el panel acoplado (`shell`). Tiene la
barra lateral (`sidebar`), la cabecera con las pestañas (`tabs`), «Buscar» (Ctrl+K, `palette`) y «Acoplar a
QGIS», el área de pestañas con sus estados (sin sesión, iniciando, error, ninguna pestaña) y el pie con el
último aviso. Escucha al coordinador y le pide acciones; nunca ejecuta SQL por su cuenta.

Ancho («ventana») y compacto («panel»): en el panel no hay barra lateral; la cabecera del panel
(`DockHeader`, en `shell`) lleva la sesión y una búsqueda que abre Ctrl+K, y ninguna acción desaparece.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QShortcut,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from geoduck.app.events import (
    AppEvent,
    AttachFailed,
    CatalogChanged,
    CatalogUnavailable,
    CloseConfirmationRequired,
    DatabaseAttached,
    DatabaseDetached,
    DetachFailed,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
    TransactionFailed,
)
from geoduck.domain.catalog import AttachRequest, ObjectKind, OpenAction
from geoduck.domain.diagnostics import CheckStatus, DiagnosticReport
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.session import ErrorCause, SessionState
from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons, style
from geoduck.ui.pro.drag import LAYERS_MIME, layer_ids
from geoduck.ui.pro.history import History, HistoryPage
from geoduck.ui.pro.load import QuickLoad, finished_title
from geoduck.ui.pro.palette import CommandPalette, Entry
from geoduck.ui.pro.places import (
    HISTORY,
    QUERY,
    Place,
    Places,
    Store,
    icon_name,
    missing_reason,
    place_of,
    read_tabs,
    save_tabs,
)
from geoduck.ui.pro.project_copies import ProjectCopies
from geoduck.ui.pro.query_page import QueryPage
from geoduck.ui.pro.recovery import QueryRecovery, read_query
from geoduck.ui.pro.send import QuickSend
from geoduck.ui.pro.sidebar import Sidebar
from geoduck.ui.pro.table_page import TablePage
from geoduck.ui.pro.tabs import TabArea
from geoduck.ui.pro.tokens import METRICS
from geoduck.ui.pro.widgets import Toast, button, icon_button, label

#: Páginas del cuerpo: estado de la sesión, pestañas, o «abre una tabla» (sesión lista sin pestañas).
STATE, TABS, WELCOME = 0, 1, 2


def session_parts(coordinator: Any) -> tuple[str, str, str]:
    """Punto de estado (`ok`, `busy`, `error`, `off`), motor («DuckDB 2.0.0») y estado con la base raíz
    («Lista · en memoria») de la sesión (§3)."""
    state: SessionState = coordinator.state
    info = coordinator.engine_info
    if state is SessionState.DISCONNECTED or info is None:
        if state is SessionState.CONNECTING:
            return "busy", "DuckDB", tr("Starting…")
        return "off", "DuckDB", tr("Not started")
    engine = f"DuckDB {info.duckdb_version}"
    catalog = coordinator.catalog
    where = tr("in memory")
    if catalog is not None and not catalog.root_database.in_memory:
        where = catalog.root_database.name
    known = {
        SessionState.READY: ("ok", tr("Ready") + " · " + where),
        SessionState.BUSY: ("busy", tr("Busy") + " · " + where),
        SessionState.ERROR_RECOVERABLE: ("error", tr("With error") + " · " + where),
        SessionState.DETACHING: ("busy", tr("Closing database…")),
    }
    dot, text = known.get(state, ("busy", tr("Closing the session…")))
    return dot, engine, text


def session_text(coordinator: Any) -> tuple[str, str]:
    """Punto de estado y texto completo de la sesión: «Lista · DuckDB 2.0.0 · en memoria»."""
    dot, engine, status = session_parts(coordinator)
    if dot == "off" or engine == "DuckDB":
        return dot, status
    state, _, where = status.partition(" · ")
    return dot, " · ".join(part for part in (state, engine, where) if part)


class ProWorkspace(QWidget):
    """Contenido de GeoDuck (interfaz nueva). Lo alojan `shell.ProWindow` y `shell.ProDock`."""

    #: «+» › «Enviar capas de QGIS a DuckDB…» y su acción de Ctrl+K (el complemento abre el diálogo de G8).
    send_layers_requested = pyqtSignal()
    #: «Acoplar a QGIS» (ventana) o «Ventana» (panel): el controlador cambia la presentación.
    presentation_requested = pyqtSignal(bool)  # True = ventana
    #: La barra lateral se abrió o se plegó (Ctrl+B): el controlador lo recuerda.
    sidebar_changed = pyqtSignal(bool)
    #: Cambió el estado de la sesión: punto y texto (para la cabecera del panel).
    status_changed = pyqtSignal(str, str)

    def __init__(  # noqa: PLR0915 - la estructura se arma en un solo lugar
        self,
        coordinator: Any,
        run_diagnostics: Callable[[], DiagnosticReport],
        settings: Store | None = None,
        *,
        ask_attach: Callable[[OpenAction, QWidget], AttachRequest | None] | None = None,
        ask_close: Callable[[CloseConfirmationRequired, QWidget], Any] | None = None,
        page_factory: Callable[[Place], QWidget] | None = None,
        ask_path: Callable[[str, str, str], str] | None = None,
        confirm_close: Callable[[str], str] | None = None,
        recovery: Any = None,
        ask_crs: Any = None,
        ask_save_copies: Any = None,
        copies_bridge: Any = None,
    ) -> None:
        super().__init__()
        self._pending_query: tuple[str, str | None] | None = None
        self._ask_path = ask_path or self._file_dialog
        self._confirm_close = confirm_close or self._confirm
        self._coordinator = coordinator
        self._run_diagnostics = run_diagnostics
        self._report: DiagnosticReport | None = None
        self._settings: Store = settings if settings is not None else QgsSettings()
        self._ask_attach = ask_attach
        self._ask_close = ask_close
        self.wide = True
        self.sidebar_open = True
        self.colors = style.apply(self)
        self.places = Places(self._settings)

        self.sidebar = Sidebar(self.colors, self.places)
        self.recovery = QueryRecovery(self, recovery)
        self.loader = QuickLoad(coordinator, self, self.notify, ask_crs)
        #: Lo ejecutado en la sesión (E6): la pestaña «Historial» lo muestra.
        self.history = History(coordinator, self)
        #: «Ver en el mapa» (E6): selecciona las capas y hace zoom; lo pone el complemento (necesita `iface`).
        self.on_view_map: Callable[[list[str]], str | None] | None = None
        self.loader.on_loaded = self._loaded
        #: Capas de QGIS soltadas sobre GeoDuck (E5): sin diálogo si no hay nada que decidir.
        self.quick_send = QuickSend(coordinator, self)
        self.last_toast: Toast | None = None
        self.aborted_toast: Toast | None = None
        self.setAcceptDrops(True)
        #: «Guardar las copias junto al proyecto»: solo con `copies_bridge` (`qgis_bridge.copies`, que pasa el
        #: complemento; la interfaz no importa el puente, ADR-0010).
        self.project_copies = (
            ProjectCopies(self, self.notify, copies_bridge, ask_save_copies)
            if copies_bridge is not None
            else None
        )
        self.tabs = TabArea(self.colors, page_factory or self._make_page, self)
        self.tabs.can_close = self._ask_save
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.sidebar)
        self.divider = QFrame()
        self.divider.setProperty("pro", "divider")
        self.divider.setFixedWidth(1)
        outer.addWidget(self.divider)
        main = QVBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        outer.addLayout(main, 1)
        main.addWidget(self._build_head())
        self.body = QStackedWidget()
        self.body.addWidget(self._build_state_page())
        self.body.addWidget(self.tabs.stack)
        self.body.addWidget(self._build_welcome())
        main.addWidget(self.body, 1)
        main.addWidget(self._build_footer())
        self.command_palette = CommandPalette(self, self.colors, self.palette_entries)

        self._connect_sidebar()
        self.tabs.changed.connect(self._tabs_changed)
        self._shortcut("Ctrl+K", self.open_palette)
        self._shortcut("Ctrl+B", self.toggle_sidebar)
        self._shortcut("Ctrl+W", self.tabs.close_current)
        self._shortcut("Ctrl+O", self.open_query_file)
        tabs, current = read_tabs(self._settings)
        for place in tabs:
            if place.is_query and missing_reason(place, None) is not None:
                continue  # su archivo ya no existe
            self.tabs.open_place(place, activate=False)
        if tabs:
            self.tabs.bar.setCurrentIndex(current)
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self.sidebar.render(coordinator.catalog)  # una sesión ya abierta (p. ej. al cambiar de interfaz)
        self.refresh_environment()
        self.recovery.offer()

    # -- construcción ---------------------------------------------------------------------------------

    def _build_head(self) -> QWidget:
        head = QFrame()
        head.setProperty("pro", "head")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        head.setFixedHeight(METRICS.bar)
        row = QHBoxLayout(head)
        row.setContentsMargins(8, 0, 12, 0)
        row.setSpacing(4)
        self.sidebar_button = icon_button("sidebar", tr("Show or hide the sidebar (Ctrl+B)"), self.colors)
        self.sidebar_button.clicked.connect(self.toggle_sidebar)
        row.addWidget(self.sidebar_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.tabs.bar, 0, Qt.AlignmentFlag.AlignBottom)
        self.new_query_button = icon_button("plus", tr("New query"), self.colors)
        self.new_query_button.clicked.connect(self.new_query)
        row.addWidget(self.new_query_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        self.search_button = button(tr("Search"), "ghost", icon="search", colors=self.colors)
        self.search_button.setToolTip(tr("Go to a table or run an action (Ctrl+K)"))
        self.search_button.clicked.connect(self.open_palette)
        row.addWidget(self.search_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.search_kbd = label("Ctrl K", "kbd")
        row.addWidget(self.search_kbd, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(8)
        self.dock_button = button(
            tr("Dock to QGIS"),
            icon="dock",
            tooltip=tr("Shows GeoDuck as a QGIS panel, with the same session"),
            colors=self.colors,
        )
        self.dock_button.clicked.connect(lambda: self.presentation_requested.emit(False))
        row.addWidget(self.dock_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return head

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        if self.command_palette.isVisible():
            self.command_palette.refresh(self.command_palette.edit.text())

    def _empty_page(self, icon: str, buttons: list[QWidget]) -> tuple[QWidget, QLabel, QLabel, QLabel]:
        """Página de estado: icono, título, texto (con ajuste de línea) y botones, centrados. Las columnas van
        en un contenedor de ancho máximo sin alineación de diseño, para que el texto calcule bien su alto."""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        column = QWidget()
        column.setMaximumWidth(560)  # cabe la fila de botones más larga (con «Diagnóstico»)
        box = QVBoxLayout(column)
        box.setContentsMargins(16, 0, 16, 0)
        box.setSpacing(8)
        glyph = label("")
        glyph.setPixmap(icons.pixmap(icon, self.colors.faint, 36))
        title = label("", "title")
        text = label("", "muted")
        text.setWordWrap(True)
        for widget in (glyph, title, text):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(widget)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.setContentsMargins(0, 10, 0, 0)
        actions.addStretch(1)
        for widget in buttons:
            actions.addWidget(widget)
        actions.addStretch(1)
        box.addLayout(actions)
        row.addWidget(column, 1)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        return page, glyph, title, text

    def _build_state_page(self) -> QWidget:
        self.start_button = button(
            tr("Start DuckDB"), "primary", tooltip=tr("Starts DuckDB in memory, in its own thread")
        )
        self.start_button.clicked.connect(self.start)
        self.open_button = button(tr("Open database…"), tooltip=tr("Opens a .duckdb file"))
        self.open_button.clicked.connect(lambda: self.attach(OpenAction.OPEN_EXISTING))
        self.create_button = button(tr("Create database…"), tooltip=tr("Creates a new .duckdb file"))
        self.create_button.clicked.connect(lambda: self.attach(OpenAction.CREATE_NEW))
        self.diagnostics_button = button(tr("Diagnostics"), tooltip=tr("What is missing and what to do"))
        self.diagnostics_button.clicked.connect(self.show_diagnostics)
        self.diagnostics_button.setVisible(False)
        page, _, self.state_title, self.state_text = self._empty_page(
            "database", [self.start_button, self.open_button, self.create_button, self.diagnostics_button]
        )
        return page

    def _build_welcome(self) -> QWidget:
        search = button(tr("Search…"), icon="search", tooltip="Ctrl+K", colors=self.colors)
        search.clicked.connect(self.open_palette)
        query = button(tr("New query"), icon="sql", colors=self.colors)
        query.clicked.connect(self.new_query)
        page, _, title, self.welcome_text = self._empty_page("table", [search, query])
        title.setText(tr("Open a table"))
        return page

    def _build_footer(self) -> QWidget:
        foot = QFrame()
        foot.setProperty("pro", "rule-top")
        foot.setFixedHeight(30)
        row = QHBoxLayout(foot)
        row.setContentsMargins(16, 0, 16, 0)
        self.notice = label("", "muted")
        self.notice.setFont(style.ui_font(METRICS.font_small))
        self.notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.notice, 1)
        # E5: progreso del envío en el pie, con «Cancelar»; sin otra ventana
        self.progress = QProgressBar()
        self.progress.setProperty("pro", "thin")
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(140)
        self.progress.setVisible(False)
        row.addWidget(self.progress)
        self.progress_cancel = QPushButton(tr("Cancel"))
        self.progress_cancel.setProperty("pro", "ghost")
        self.progress_cancel.setVisible(False)
        self.progress_cancel.clicked.connect(self.quick_send.cancel)
        row.addWidget(self.progress_cancel)
        return foot

    # -- envío desde QGIS (E5) ---------------------------------------------------------------------------

    def show_progress(self, text: str, total: int) -> None:
        self.notify(text)
        self.progress.setRange(0, max(0, total))  # 0 = indeterminado: DuckDB copia sin informar entidades
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.progress_cancel.setVisible(True)

    def set_progress(self, rows: int) -> None:
        if self.progress.maximum() > 0:
            self.progress.setValue(min(self.progress.maximum(), rows))

    def hide_progress(self) -> None:
        self.progress.setVisible(False)
        self.progress_cancel.setVisible(False)

    def toast(self, text: str, actions: list[tuple[str, Callable[[], None]]], seconds: int) -> None:
        if self.last_toast is not None:
            with contextlib.suppress(RuntimeError):
                self.last_toast.dismiss()
        toast = Toast(self, text, kind="ok", seconds=seconds)
        for name, callback in actions:
            toast.add_action(name, callback)
        toast.show_at_corner(bottom=40)
        self.last_toast = toast

    def _loaded(self, report: Any) -> None:
        """Capa cargada: el aviso con «Ver en el mapa» (si el complemento sabe mostrarla)."""
        if self.on_view_map is None:
            return
        ids = [layer_id for layer_id, _ in report.layers] or [report.layer_id]
        self.toast(finished_title(report), [(tr("View on map"), lambda: self.view_map(ids))], 10)

    def view_map(self, layer_ids: list[str]) -> None:
        if self.on_view_map is not None:
            message = self.on_view_map(layer_ids)
            if message:
                self.notify(message)

    def open_table(self, table: Any) -> None:
        """«Abrir» del aviso: la tabla (o vista) recién enviada."""
        kind = ObjectKind.VIEW if table.view else ObjectKind.TABLE
        self.open_place(place_of(table.database, table.schema, table.name, kind))

    def send_layers(self, layer_ids_: list[str], destination: tuple[str, str] | None = None) -> None:
        """Capas de QGIS soltadas sobre una base (o, sin `destination`, sobre la base actual)."""
        self.quick_send.send(
            layer_ids_, destination if destination is not None else self.sidebar.current_target()
        )

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        """Capas soltadas en cualquier parte de GeoDuck (también en el panel): a la base actual."""
        if event.mimeData().hasFormat(LAYERS_MIME) and self._coordinator.state is SessionState.READY:
            event.acceptProposedAction()
            target = self.sidebar.current_target()
            where = target[0] if target else tr("the current database")
            count = len(layer_ids(event.mimeData()))
            self.notify(tr("Drop to send {0} layer(s) to «{1}»").format(count, where))
        else:
            event.ignore()

    def dropEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        ids = layer_ids(event.mimeData())
        if not ids:
            event.ignore()
            return
        event.acceptProposedAction()
        self.send_layers(ids)

    def _connect_sidebar(self) -> None:
        side = self.sidebar
        side.open_requested.connect(self.open_place)
        side.favorite_requested.connect(self.toggle_favorite)
        side.detach_requested.connect(self.detach)
        side.refresh_requested.connect(self.refresh)
        side.close_session_requested.connect(self.close_session)
        side.open_database_requested.connect(lambda: self.attach(OpenAction.OPEN_EXISTING))
        side.create_database_requested.connect(lambda: self.attach(OpenAction.CREATE_NEW))
        side.send_layers_requested.connect(self.send_layers_requested.emit)
        side.diagnostics_requested.connect(self.show_diagnostics)
        side.about_requested.connect(self.show_about)
        side.tree.layers_dropped.connect(self.send_layers)
        side.tree.drop_hint.connect(lambda text: self.notify(text) if text else None)

    def _shortcut(self, keys: str, slot: Callable[[], object]) -> None:
        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(slot)

    # -- presentación ---------------------------------------------------------------------------------

    def set_presentation(self, *, wide: bool) -> None:
        """Ventana (`wide`) o panel: en el panel no hay barra lateral ni «Acoplar»; la cabecera del panel
        lleva la sesión y la búsqueda."""
        self.wide = wide
        self.sidebar.setVisible(wide and self.sidebar_open)
        self.divider.setVisible(self.sidebar.isVisibleTo(self))
        for widget in (self.sidebar_button, self.dock_button, self.search_button, self.search_kbd):
            widget.setVisible(wide)  # en el panel, la búsqueda está en su cabecera
        self._render()

    def set_sidebar_open(self, open_: bool) -> None:
        self.sidebar_open = open_
        self.sidebar.setVisible(self.wide and open_)
        self.divider.setVisible(self.wide and open_)

    def toggle_sidebar(self) -> None:
        """Ctrl+B: pliega o abre la barra lateral (solo en la ventana)."""
        if not self.wide:
            return
        self.set_sidebar_open(not self.sidebar_open)
        self.sidebar_changed.emit(self.sidebar_open)

    def status(self) -> tuple[str, str]:
        """Punto y texto de la sesión, para la cabecera del panel."""
        return session_text(self._coordinator)

    def notify(self, text: str) -> None:
        """Aviso en el pie (§3: el último aviso)."""
        self.notice.setText(text)
        self.notice.setToolTip(text)

    def _render(self) -> None:
        state = self._coordinator.state
        dot, engine, status = session_parts(self._coordinator)
        _, text = session_text(self._coordinator)
        ready = state is SessionState.READY
        self.sidebar.set_session(dot, engine, status, ready=ready)
        self.status_changed.emit(dot, text)
        has_session = self._coordinator.engine_info is not None and state is not SessionState.DISCONNECTED
        for widget in (self.new_query_button, self.search_button):
            widget.setEnabled(has_session)
        self.tabs.bar.setVisible(len(self.tabs) > 0)
        if not has_session or state is SessionState.CLOSING:
            self._render_state(state)
            self.body.setCurrentIndex(STATE)
        elif len(self.tabs):
            self.body.setCurrentIndex(TABS)
        else:
            self.welcome_text.setText(
                tr("Double-click a table on the left, press Ctrl+K to search, or + for a new query.")
                if self.wide
                else tr("Press Ctrl+K to search, or + for a new query.")
            )
            self.body.setCurrentIndex(WELCOME)
        self._render_aborted()

    def transaction_aborted(self) -> bool:
        return (
            self._coordinator.state is SessionState.ERROR_RECOVERABLE
            and self._coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
        )

    def _render_aborted(self) -> None:
        """Transacción abortada (E6): un aviso que no se va solo, con «Revertir» (ROLLBACK). Sin él, la sesión
        no se puede volver a usar salvo cerrándola."""
        aborted = self.transaction_aborted()
        if aborted and self.aborted_toast is None:
            toast = Toast(
                self, tr("The transaction failed: roll it back to keep using DuckDB"), kind="error", seconds=0
            )
            toast.add_action(tr("Roll back"), self.rollback)
            toast.show_at_corner(bottom=40)
            self.aborted_toast = toast
        elif not aborted and self.aborted_toast is not None:
            with contextlib.suppress(RuntimeError):
                self.aborted_toast.dismiss()
            self.aborted_toast = None

    def rollback(self) -> None:
        self.aborted_toast = None  # el aviso se cierra con su botón
        self._guard(self._coordinator.rollback_transaction)

    def _render_state(self, state: SessionState) -> None:
        idle = state is SessionState.DISCONNECTED or (
            state is SessionState.ERROR_RECOVERABLE and self._coordinator.engine_info is None
        )
        if state is SessionState.CONNECTING:
            self.state_title.setText(tr("Starting DuckDB…"))
            self.state_text.setText(tr("It takes a moment the first time."))
        elif state is SessionState.CLOSING:
            self.state_title.setText(tr("Closing the session…"))
            self.state_text.setText("")
        elif not self.environment_ok:  # AT-BOOT-002: abre, explica y no deja iniciar
            checks = self._report.checks if self._report is not None else ()
            failing = [c.title for c in checks if c.status is CheckStatus.FAIL]
            self.state_title.setText(tr("The environment is not ready for GeoDuck"))
            self.state_text.setText(
                ", ".join(failing) + ". " + tr("Open «Environment diagnostics» to see what to do.")
            )
        else:
            self.state_title.setText(tr("DuckDB is not started"))
            self.state_text.setText(tr("Start DuckDB in memory, or open a database file."))
        for widget in (self.start_button, self.open_button, self.create_button):
            widget.setVisible(idle)
            widget.setEnabled(idle and self._coordinator.can_start and self.environment_ok)
        self.diagnostics_button.setVisible(idle and not self.environment_ok)

    # -- acciones -------------------------------------------------------------------------------------

    def start(self) -> None:
        self._guard(self._coordinator.start_memory_session)

    def attach(self, action: OpenAction) -> None:
        """«Abrir base…» o «Crear base…»: sin sesión, la inicia con esa base; con sesión, la adjunta."""
        ask = self._ask_attach
        if ask is None:
            from geoduck.ui.attach_dialog import AttachDialog  # noqa: PLC0415

            ask = AttachDialog.ask
        request = ask(action, self)
        if request is None:
            return
        if self._coordinator.can_start:
            self._guard(lambda: self._coordinator.start_file_session(request))
        else:
            self._guard(lambda: self._coordinator.attach_database(request))

    def detach(self, name: str) -> None:
        self._guard(lambda: self._coordinator.detach_database(name))

    def refresh(self) -> None:
        self._guard(self._coordinator.refresh_catalog)

    def close_session(self) -> None:
        self._guard(self._coordinator.request_close)

    def _guard(self, action: Callable[[], object]) -> None:
        try:
            action()
        except GeoDuckError as exc:
            self.notify(exc.message)

    def open_place(self, place: Place) -> None:
        """Doble clic, Intro o Ctrl+K: abre la tabla, vista o consulta en su pestaña (o trae la abierta)."""
        reason = missing_reason(place, self._coordinator.catalog)
        if reason is not None:
            self.notify(f"{place.name}: {reason}")
            return
        self.tabs.open_place(place)
        self.places.touch(place)
        self.sidebar.render(self._coordinator.catalog)
        self._render()

    def _make_page(self, place: Place) -> QWidget:
        """La página de cada pestaña: la de tabla para tablas y vistas (E3), la de consulta (E4)."""
        if place.kind == HISTORY:
            return HistoryPage(place, self.history, self.colors, self.open_sql)
        if not place.is_query:
            return TablePage(
                place,
                self._coordinator,
                self.colors,
                view_sql=self.open_sql,
                loader=self.loader.start,
                ask_path=self._ask_path,
                notify=self.notify,
            )
        sql, database = self._pending_query or ("", None)
        self._pending_query = None
        if place.path and not sql:
            sql, database = read_query(place.path)
        page = QueryPage(
            place,
            self._coordinator,
            self.colors,
            sql=sql,
            database=database,
            ask_path=self._ask_path,
            loader=self.loader.start,
        )
        page.changed.connect(lambda p=page: self._query_changed(p))
        page.renamed.connect(lambda old, p=page: self._query_renamed(p, old))
        page.open_requested.connect(self.open_query_file)
        page.notice.connect(self.notify)
        return page

    def _query_changed(self, page: QueryPage) -> None:
        self.tabs.retitle(page, modified=page.modified)
        self.recovery.schedule()

    def _query_renamed(self, page: QueryPage, old: Place) -> None:
        self.places.rename_query(old, page.place)
        self.places.touch(page.place)
        self.tabs.retitle(page, modified=page.modified)
        self.sidebar.render(self._coordinator.catalog)

    def open_query_file(self, path: str = "") -> None:
        """Ctrl+O: abre un `.sql` en una pestaña (un cuaderno de G7, como una sola consulta)."""
        if not path:
            path = self._ask_path(tr("Open query"), "", tr("SQL files (*.sql)"))
        if not path:
            return
        try:
            self._pending_query = read_query(path)
        except (OSError, UnicodeDecodeError) as exc:
            self.notify(
                tr("The query could not be opened: {}").format(getattr(exc, "strerror", "") or str(exc))
            )
            return
        place = Place(QUERY, Path(path).name, path=str(Path(path)))
        self.tabs.open_place(place)
        self._pending_query = None
        self.places.touch(place)
        self.sidebar.render(self._coordinator.catalog)
        self._render()

    def _ask_save(self, page: QWidget) -> bool:
        """Antes de cerrar una consulta con cambios sin archivo: guardar, no guardar o seguir editando."""
        if not isinstance(page, QueryPage):
            return True
        page.save_if_saved()
        if page.place.path or not page.modified:
            return True
        choice = self._confirm_close(page.place.name)
        if choice == "save":
            return page.save()
        return choice == "discard"

    def _confirm(self, name: str) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("GeoDuck"))
        box.setText(tr("Save the changes to «{}»?").format(name))
        box.setInformativeText(tr("If you do not save them, they are lost."))
        save = box.addButton(tr("Save…"), QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton(tr("Don't save"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is save else "discard" if clicked is discard else "cancel"

    def _file_dialog(self, title: str, name: str, pattern: str) -> str:
        if title == tr("Open query"):
            path, _ = QFileDialog.getOpenFileName(self, title, str(Path.home()), pattern)
        else:
            path, _ = QFileDialog.getSaveFileName(self, title, str(Path.home() / name), pattern)
        return path

    def open_recovered(self, name: str, sql: str, database: str | None, path: str | None) -> None:
        """Una consulta de la copia de recuperación, en una pestaña (con cambios sin guardar)."""
        place = Place(QUERY, name, path=path or "")
        if self.tabs.index_of(place) >= 0:
            place = Place(QUERY, tr("{} (recovered)").format(name), path="")
        self._pending_query = (sql, database)
        page = self.tabs.open_place(place)
        self._pending_query = None
        if isinstance(page, QueryPage):
            if path and Path(path).is_file():
                with contextlib.suppress(OSError, UnicodeDecodeError):
                    page.saved_text = read_query(path)[0]
            self.tabs.retitle(page, modified=page.modified)
        self._render()

    def query_pages(self) -> list[QueryPage]:
        return [p for p in (self.tabs.page(i) for i in range(len(self.tabs))) if isinstance(p, QueryPage)]

    def open_sql(self, text: str, database: str | None = None) -> None:
        """«Ver SQL» o una línea del historial: el SQL, en una pestaña de consulta nueva (sin ejecutarlo)."""
        self._pending_query = (text, database)
        self.tabs.new_query()
        self._pending_query = None
        self._render()

    def open_history(self) -> None:
        """Ctrl+K › «Historial de ejecución»: la pestaña con lo ejecutado en la sesión."""
        self.tabs.open_place(Place(HISTORY, tr("History")))
        self._render()

    def new_query(self) -> None:
        if self._coordinator.engine_info is None:
            return
        self.tabs.new_query()
        self._render()

    def toggle_favorite(self, place: Place) -> None:
        marked = self.places.toggle_favorite(place)
        self.sidebar.render(self._coordinator.catalog)
        self.notify(
            (tr("«{}» added to favorites") if marked else tr("«{}» removed from favorites")).format(
                place.name
            )
        )

    def _tabs_changed(self) -> None:
        save_tabs(self._settings, self.tabs.places(), self.tabs.bar.currentIndex())
        if self._coordinator.engine_info is not None:
            self._render()

    @property
    def environment_ok(self) -> bool:
        return self._report is None or self._report.ok

    def refresh_environment(self) -> DiagnosticReport:
        """Comprueba Python, QGIS, DuckDB y PyArrow (al abrir y en «Diagnóstico»)."""
        self._report = self._run_diagnostics()
        self._render()
        return self._report

    def show_diagnostics(self) -> None:
        from geoduck.ui.diagnostics_dialog import DiagnosticsDialog  # noqa: PLC0415

        DiagnosticsDialog(self.refresh_environment(), self).exec()

    def show_about(self) -> None:
        from geoduck.ui.about_dialog import AboutDialog  # noqa: PLC0415

        AboutDialog(self._report, self._coordinator.engine_info, self).exec()

    # -- Ctrl+K ---------------------------------------------------------------------------------------

    def open_palette(self) -> None:
        if self._coordinator.engine_info is not None:
            self.command_palette.open()

    def palette_entries(self) -> list[Entry]:
        """Pestañas abiertas, recientes, acciones y, al final, todas las tablas y vistas de la sesión."""
        entries: list[Entry] = []
        seen: set[tuple[str, ...]] = set()
        catalog = self._coordinator.catalog
        for index, place in enumerate(self.tabs.places()):
            seen.add(place.key)
            entries.append(
                Entry(
                    place.name,
                    tr("Open tab"),
                    icon_name(place),
                    lambda i=index: self.tabs.bar.setCurrentIndex(i),
                )
            )
        for place in self.places.recents:
            if place.key not in seen and missing_reason(place, catalog) is None:
                seen.add(place.key)
                entries.append(
                    Entry(place.name, place.location, icon_name(place), lambda p=place: self.open_place(p))
                )
        entries.extend(self._actions())
        if catalog is not None:
            for obj in catalog.objects:
                place = place_of(obj.database, obj.schema, obj.name, obj.kind)
                if place.key in seen:
                    continue
                kind = tr("view") if obj.kind is ObjectKind.VIEW else tr("table")
                meta = f"{tr('temporary')} · {kind}" if obj.temporary else f"{place.location} · {kind}"
                entries.append(Entry(obj.name, meta, icon_name(place), lambda p=place: self.open_place(p)))
        return entries

    def _actions(self) -> list[Entry]:
        action = tr("Action")
        ready = self._coordinator.state is SessionState.READY
        found = [
            Entry(tr("New query"), action, "plus", self.new_query),
            Entry(tr("Open query…"), "Ctrl+O", "sql", self.open_query_file),
            Entry(tr("Execution history"), action, "history", self.open_history),
        ]
        if self.transaction_aborted():
            found.append(Entry(tr("Roll back transaction"), action, "warning", self.rollback))
        if ready:
            found += [
                Entry(
                    tr("Open database…"), action, "database", lambda: self.attach(OpenAction.OPEN_EXISTING)
                ),
                Entry(tr("Create database…"), action, "database", lambda: self.attach(OpenAction.CREATE_NEW)),
                Entry(tr("Send QGIS layers to DuckDB…"), action, "layers", self.send_layers_requested.emit),
                Entry(tr("Refresh databases"), action, "refresh", self.refresh),
            ]
        if self.wide:
            found.append(Entry(tr("Show or hide the sidebar"), action, "sidebar", self.toggle_sidebar))
            found.append(
                Entry(tr("Dock to QGIS"), action, "dock", lambda: self.presentation_requested.emit(False))
            )
        else:
            found.append(
                Entry(
                    tr("Open in a window"), action, "window", lambda: self.presentation_requested.emit(True)
                )
            )
        found.append(Entry(tr("Environment diagnostics"), action, "info", self.show_diagnostics))
        return found

    # -- eventos del coordinador ----------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, (SessionStateChanged, SessionStarted)):
            self._render()
        elif isinstance(event, CatalogChanged):
            self.sidebar.render(event.catalog)
            self._render()
        elif isinstance(event, CatalogUnavailable):
            self.notify(tr("The catalog could not be read.") + f" {event.message}")
        elif isinstance(event, DatabaseAttached):
            self.notify(tr("Database «{}» open").format(event.database.name))
        elif isinstance(event, DatabaseDetached):
            self.notify(tr("Database «{}» closed").format(event.database.name))
        elif isinstance(event, AttachFailed):
            self.notify(tr("The database was not attached.") + f" {event.message}")
        elif isinstance(event, DetachFailed):
            self.notify(tr("The database was not detached.") + f" {event.message}")
        elif isinstance(event, CloseConfirmationRequired):
            ask = self._ask_close
            if ask is None:
                from geoduck.ui.close_dialog import CloseTransactionDialog  # noqa: PLC0415

                ask = CloseTransactionDialog.ask
            self._coordinator.resolve_close(ask(event, self))
        elif isinstance(event, SessionInvalidated):
            self.notify(
                tr("Session invalidated:")
                + f" {event.message} [{event.code.value}] "
                + tr("Start a new session or close.")
            )
        elif isinstance(event, TransactionFailed):
            self.notify(tr("The transaction operation did not complete.") + f" {event.message}")
        elif isinstance(event, SessionFailed):
            self.notify(tr("The operation could not be completed.") + f" {event.message}")

    def detach_coordinator(self) -> None:
        """Al descargar GeoDuck: deja de escuchar al coordinador."""
        with contextlib.suppress(Exception):
            self._unsubscribe()
        for index in range(len(self.tabs)):
            page = self.tabs.page(index)
            if hasattr(page, "close_page"):
                page.close_page()  # una consulta con archivo guarda lo pendiente
        self.recovery.stop()
        self.loader.detach()
        self.history.detach()
        self.quick_send.detach()
        if self.project_copies is not None:
            self.project_copies.detach()
