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
import dataclasses
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QEvent, QObject, QPoint, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QKeySequence
from qgis.PyQt.QtWidgets import (
    QApplication,
    QBoxLayout,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QStackedWidget,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from geoduck.app.events import (
    ActivationFailed,
    AppEvent,
    AttachFailed,
    CatalogChanged,
    CatalogUnavailable,
    CloseConfirmationRequired,
    ColumnsListed,
    ColumnsUnavailable,
    DatabaseAttached,
    DatabaseDetached,
    DatabaseSaved,
    DetachFailed,
    ExportFailed,
    ExportFinished,
    ExportStarted,
    SaveDatabaseFailed,
    SendFinished,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
    SpatialActivated,
    SpatialActivationFailed,
    TransactionFailed,
    VocabularyChanged,
)
from geoduck.domain.catalog import (
    MEMORY_ALIAS,
    AccessMode,
    AttachRequest,
    ObjectKind,
    OpenAction,
    catalog_key,
)
from geoduck.domain.diagnostics import CheckStatus, DiagnosticReport
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.files import OTHER, file_filters, format_for, gdal_readable, unsupported_lines
from geoduck.domain.resources import size_text
from geoduck.domain.session import ErrorCause, SessionState
from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons, style
from geoduck.ui.pro.add_layers import AddLayers
from geoduck.ui.pro.drag import accepts, drop_hint, file_paths, layer_ids, menu_title, place_job
from geoduck.ui.pro.export_progress import ExportProgress
from geoduck.ui.pro.history import History, HistoryPage
from geoduck.ui.pro.load import (
    SPATIAL_MISSING,
    QuickLoad,
    finished_lines,
    is_temporary,
    layer_name,
    load_menu,
)
from geoduck.ui.pro.load_window import LoadWindow
from geoduck.ui.pro.open_files import open_in_qgis
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
from geoduck.ui.pro.sidebar import Sidebar
from geoduck.ui.pro.table_page import TablePage
from geoduck.ui.pro.tabs import TabArea
from geoduck.ui.pro.tokens import METRICS
from geoduck.ui.pro.widgets import LOGO, Toast, button, icon_button, label, lines_html, relayout

#: Páginas del cuerpo: estado de la sesión, pestañas, o «abre una tabla» (sesión lista sin pestañas).
STATE, TABS, WELCOME = 0, 1, 2
#: Por debajo de este ancho (o en el panel acoplado), las páginas pasan al modo compacto.
COMPACT_WIDTH = 640
#: Segundos del aviso de archivos no compatibles (tiene una acción: «Abrir en QGIS»).
UNSUPPORTED_SECONDS = 20
#: Ancho del explorador abierto encima del contenido en el panel.
OVERLAY_WIDTH = 272
#: El explorador fijado en el panel acoplado (#147): más angosto que en la ventana.
PINNED_WIDTH = 240
#: Fijado o flotando en el panel acoplado (#147); se recuerda entre sesiones.
PINNED_KEY = "geoduck/pro/explorer_pinned"
#: Arrastrando algo sobre ☰, cuánto esperar para abrir el explorador (#147).
HOLD_MS = 500
#: Un aviso de información del pie se borra solo a los 6 s (#177).
NOTICE_MS = 6000
#: El nombre en la cabecera de la sesión: la marca, sin la versión del motor (#149).
NAME = "GeoDuck"


def session_parts(coordinator: Any) -> tuple[str, str, str]:
    """Punto de estado (`ok`, `busy`, `error`, `off`), nombre («GeoDuck») y estado («Activo») de la sesión
    (§3). Sin la base: la base activa se ve en el explorador; la versión de DuckDB
    solo va en «Acerca de» (#149)."""
    state: SessionState = coordinator.state
    info = coordinator.engine_info
    if state is SessionState.DISCONNECTED or info is None:
        if state is SessionState.CONNECTING:
            return "busy", NAME, tr("Starting…")
        return "off", NAME, tr("Stopped")
    known = {
        SessionState.READY: ("ok", tr("Active")),
        SessionState.BUSY: ("busy", tr("Busy")),
        SessionState.ERROR_RECOVERABLE: ("error", tr("With error")),
        SessionState.DETACHING: ("busy", tr("Closing database…")),
    }
    dot, text = known.get(state, ("busy", tr("Closing the session…")))
    return dot, NAME, text


def session_text(coordinator: Any) -> tuple[str, str]:
    """Punto de estado y texto de la sesión: «Activo»."""
    dot, _name, status = session_parts(coordinator)
    return dot, status


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
        ask_load_options: Any = None,
        ask_save_copies: Any = None,
        copies_bridge: Any = None,
        ask_files: Callable[[str, list[str]], list[str]] | None = None,
        ask_alias: Callable[[str], str | None] | None = None,
        ask_lose: Callable[[str, int], bool] | None = None,
        ask_save_memory: Callable[[str, list[str], int, bool], str | None] | None = None,
        tell_blocked: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__()
        #: #183: guardar una base en memoria que leen capas Conectadas, y «No se puede cerrar…».
        self._ask_save_memory = ask_save_memory or self._save_memory_dialog
        self._tell_blocked = tell_blocked or self._blocked_dialog
        #: Barra de mensajes de QGIS (texto, nivel, [(botón, acción)]); la pone el complemento.
        self.push_bar: Callable[[str, str, list[tuple[str, Callable[[], None]]]], None] | None = None
        self._close_after_save = False
        self._closing = False
        #: Capas no disponibles tras el último catálogo, y la base que se está cerrando desde el menú.
        self._unavailable: set[str] = set()
        self._bases: dict[str, Any] = {}
        self._detaching: str | None = None
        self._retrying_spatial = False
        #: El archivo de `spatial` para «Instalar desde un archivo…» (las pruebas lo reemplazan).
        self._ask_spatial_file: Callable[[], str] = self._spatial_file_dialog
        self._resave_project: Callable[[], None] | None = None
        #: #168: el alias de una base nueva en memoria y confirmar cerrar una base en memoria con tablas.
        self._ask_alias = ask_alias
        self._ask_lose = ask_lose
        self._ask_files = ask_files or self._files_dialog
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
        #: Modo compacto (panel acoplado o ventana angosta): íconos con tooltip donde no cabe el texto.
        self.compact = False
        #: En el panel, el explorador se abre encima del contenido y se cierra al elegir algo.
        self.overlay_open = False
        #: Ancho de la ventana que pedía la página sin compactar (ver `decide_compact`).
        self._wide_need = 0
        #: En el panel acoplado, el explorador fijado al lado (True) o flotando encima (#147).
        self.pinned = False
        self._action_rows: list[QBoxLayout] = []
        self.colors = style.apply(self)
        self.places = Places(self._settings)

        self.sidebar = Sidebar(self.colors, self.places)
        self.pinned = str(self._settings.value(PINNED_KEY, False)).lower() in ("true", "1")
        self.recovery = QueryRecovery(self, recovery)
        self.loader = QuickLoad(coordinator, self, self.notify, ask_crs, ask_load_options)
        #: Lo ejecutado en la sesión (E6): la pestaña «Historial» lo muestra.
        self.history = History(coordinator, self)
        #: «Ver en el mapa» (E6): selecciona las capas y hace zoom; lo pone el complemento (necesita `iface`).
        self.on_view_map: Callable[[list[str]], str | None] | None = None
        self.loader.on_loaded = self._loaded
        #: Capas de QGIS soltadas sobre GeoDuck (E5): sin diálogo si no hay nada que decidir.
        self.to_duckdb = AddLayers(coordinator, self)
        #: GeoDuck → QGIS con nombres y línea de tiempo (#148): «Cambiar nombres…» con varias tablas.
        self.to_qgis = LoadWindow(self, coordinator, self.loader)
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
        factory = page_factory or self._make_page
        self.tabs = TabArea(self.colors, lambda place: self._with_mode(factory(place)), self)
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
        # el ancho mínimo lo decide `decide_compact`, no la página: así la ventana puede angostarse hasta que
        # la página pase al modo compacto (#147, punto 28)
        policy = self.body.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.body.setSizePolicy(policy)
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
        #: Avisos de «Exportar ▾» en curso, por id (con su trazabilidad).
        self._exports: dict[int, Any] = {}
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._unsubscribe_exports = coordinator.subscribe(
            lambda e: (
                self._export_trace(e)
                if isinstance(e, (ExportStarted, ExportFinished, ExportFailed))
                else None
            )
        )
        self.sidebar.render(coordinator.catalog)  # una sesión ya abierta (p. ej. al cambiar de interfaz)
        self.refresh_environment()
        self.recovery.offer()

    # -- construcción ---------------------------------------------------------------------------------

    def _build_head(self) -> QWidget:
        head = QFrame()
        head.setProperty("pro", "head")
        head.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        head.setFixedHeight(METRICS.bar)
        policy = head.sizePolicy()  # como el cuerpo: su ancho lo cuenta `decide_compact` (#147)
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        head.setSizePolicy(policy)
        self.head = head
        row = QHBoxLayout(head)
        row.setContentsMargins(8, 0, 12, 0)
        row.setSpacing(4)
        self.sidebar_button = icon_button("sidebar", tr("Show or hide the sidebar (Ctrl+B)"), self.colors)
        self.sidebar_button.clicked.connect(self.toggle_sidebar)
        # arrastrando capas o archivos: mantener sobre ☰ medio segundo abre el explorador (#147)
        self.hold_to_open = HoldToOpen(self.sidebar_button, self._open_for_drop, self.dropEvent)
        row.addWidget(self.sidebar_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.tabs.bar, 0, Qt.AlignmentFlag.AlignBottom)
        self.new_query_button = icon_button("plus", tr("New query"), self.colors)
        self.new_query_button.clicked.connect(self.new_query)
        row.addWidget(self.new_query_button, 0, Qt.AlignmentFlag.AlignVCenter)
        # Al final de las pestañas, «Cerrar todas las pestañas»; el archivo de cada
        # pestaña, en su clic derecho
        self.close_all_button = icon_button("close", tr("Close all tabs"), self.colors)
        self.close_all_button.clicked.connect(self.tabs.close_all)
        row.addWidget(self.close_all_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.tabs.bar.customContextMenuRequested.connect(self._tab_menu)
        self.tabs.rename_requested.connect(self._rename_tab)
        row.addStretch(1)
        # Solo iconos, en la ventana y en el panel; la ayuda dice qué hacen
        self.search_button = icon_button("search", tr("Go to a table or run an action (Ctrl+K)"), self.colors)
        self.search_button.clicked.connect(self.open_palette)
        row.addWidget(self.search_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.dock_button = icon_button(
            "dock", tr("Shows GeoDuck as a QGIS panel, with the same session"), self.colors
        )
        self.dock_button.clicked.connect(lambda: self.presentation_requested.emit(False))
        row.addWidget(self.dock_button, 0, Qt.AlignmentFlag.AlignVCenter)
        return head

    def _load_menu_for(self, parent: QWidget, places: list[Any]) -> QMenu:
        """Clic derecho en una o varias tablas › «Cargar en QGIS ▸»: el mismo menú que al soltarlas en el
        mapa; con una sola, también «Más opciones…»."""
        jobs = [place_job(place) for place in places]
        single = len(places) == 1
        menu = load_menu(
            parent,
            self.colors,
            lambda kind: self.to_qgis.quick(
                [dict(jobs[0], name=layer_name(menu, jobs[0]["name"]))] if single else jobs, kind
            ),
            title="" if single else menu_title(len(places)),
            more=single,
            name=(lambda: jobs[0]["name"]) if single else None,
            rename=None if single else lambda: self.to_qgis.open(jobs),
            temporary=is_temporary([place.database for place in places]),
        )
        return menu

    def _rename_tab(self, page: QWidget, name: str) -> None:
        """Doble clic en el nombre de una consulta y Enter (#143, punto 6): renombra la pestaña y su archivo,
        sin sobrescribir nunca; si no se puede, el pie dice por qué."""
        if not isinstance(page, QueryPage):
            return
        if not page.place.path:
            twin = self.tabs.index_of(Place(QUERY, name.strip()))
            if twin >= 0 and self.tabs.page(twin) is not page:
                self.notify(tr("A tab named «{}» is already open").format(name.strip()))
                return
        reason = page.rename(name)
        if reason:
            self.notify(reason)

    def _tab_menu(self, pos: Any) -> None:
        """Clic derecho en una pestaña (#143, punto 4): Guardar, Guardar como…, Abrir consulta… y Cerrar.
        Guardar y Guardar como, solo en una consulta; «Abrir consulta…» abre otra pestaña."""
        index = self.tabs.bar.tabAt(pos)
        if index < 0:
            return
        page = self.tabs.page(index)
        query = page if isinstance(page, QueryPage) else None
        menu = QMenu(self)
        if query is not None:
            menu.addAction(tr("Save") + "\tCtrl+S", query.save)
            menu.addAction(tr("Save as…"), query.save_as)
        menu.addAction(tr("Open query…") + "\tCtrl+O", self.open_query_file)
        menu.addSeparator()
        menu.addAction(tr("Close") + "\tCtrl+W", lambda: self.tabs.close_tab(self.tabs.index_of_page(page)))
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(self.tabs.bar.mapToGlobal(pos))
        self._last_tab_menu = menu

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self.decide_compact()
        if self.floating:
            self._place_overlay()
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
        if icon == "logo":  # sin sesión: el logo grande en gris (marca, 2026-11-07)
            glyph.setPixmap(QIcon(LOGO).pixmap(64, 64, QIcon.Mode.Disabled))
        else:
            glyph.setPixmap(icons.pixmap(icon, self.colors.faint, 36))
        title = label("", "title")
        text = label("", "muted")
        text.setWordWrap(True)
        title.setWordWrap(True)
        for wrapped in (title, text):
            wrapped.setMinimumWidth(160)  # bajan de línea: en el panel angosto no fijan el ancho
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
        self._action_rows.append(actions)  # en el modo compacto, los botones uno debajo de otro
        box.addLayout(actions)
        row.addWidget(column, 1)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        return page, glyph, title, text

    def _build_state_page(self) -> QWidget:
        self.start_button = button(
            tr("Start GeoDuck"),
            "primary",
            tooltip=tr("Starts GeoDuck with a database in memory, in its own thread"),
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
            "logo", [self.start_button, self.open_button, self.create_button, self.diagnostics_button]
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
        # #177: ✕ cierra un error del pie; los avisos de información se borran solos a los `NOTICE_MS`
        self.notice_close = icon_button("close", tr("Close the message"), self.colors, size=12)
        self.notice_close.clicked.connect(lambda: self.notify(""))
        self.notice_close.hide()
        row.addWidget(self.notice_close)
        self._notice_timer = QTimer(self)
        self._notice_timer.setSingleShot(True)
        self._notice_timer.timeout.connect(lambda: self.notify(""))
        # E5: progreso del envío en el pie, con «Cancelar»; sin otra ventana
        self.progress = QProgressBar()
        self.progress.setProperty("pro", "thin")
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(140)
        self.progress.setVisible(False)
        row.addWidget(self.progress)
        # la línea de progreso: un clic vuelve al paso 3 de «Capas de QGIS → DuckDB» (F-131)
        self.progress_button = QPushButton()
        self.progress_button.setProperty("pro", "ghost")
        self.progress_button.setToolTip(tr("Show the progress"))
        self.progress_button.setAccessibleName(tr("Show the progress"))
        self.progress_button.setVisible(False)
        self.progress_button.clicked.connect(self.to_duckdb.show_window)
        row.addWidget(self.progress_button)
        return foot

    # -- envío desde QGIS (E5) ---------------------------------------------------------------------------

    def show_progress(self, text: str, _total: int = 0) -> None:
        self.progress.setRange(0, 0)  # en marcha; el detalle de cada capa, en el paso 3
        self.progress.setVisible(True)
        self.set_progress(text)
        self.progress_button.setVisible(True)

    def set_progress(self, text: str) -> None:
        self.progress_button.setText(text)

    def hide_progress(self) -> None:
        self.progress.setVisible(False)
        self.progress_button.setVisible(False)

    def toast(
        self, text: str, actions: list[tuple[str, Callable[[], None]]], seconds: int, *, kind: str = "ok"
    ) -> None:
        if self.last_toast is not None:
            with contextlib.suppress(RuntimeError):
                self.last_toast.dismiss()
        toast = Toast(self, text, kind=kind, seconds=seconds)
        for name, callback in actions:
            toast.add_action(name, callback)
        toast.show_at_corner(bottom=40)
        self.last_toast = toast

    def _loaded(self, report: Any) -> bool:
        """Capa cargada: un solo aviso, con «Ver en el mapa» (si el complemento sabe mostrarla), el origen, el
        acceso y las advertencias. Devuelve si lo mostró."""
        if self.to_qgis.showing():  # la línea de tiempo ya lo dice, con su «Ver en el mapa»
            return True
        if self.on_view_map is None:
            return False
        ids = [layer_id for layer_id, _ in report.layers] or [report.layer_id]
        self.toast(lines_html(finished_lines(report)), [(tr("View on map"), lambda: self.view_map(ids))], 12)
        return True

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
        """Capas de QGIS arrastradas (o del clic derecho): «Capas de QGIS → DuckDB», paso 1 con esas capas;
        en el paso 2, la base donde se soltaron o, sin `destination`, la base actual (F-131)."""
        self.to_duckdb.open(
            layer_ids_, destination if destination is not None else self.sidebar.current_target()
        )

    def import_files(
        self, destination: tuple[str, str] | None = None, paths: list[str] | None = None
    ) -> None:
        """«Importar archivos…» (qgis-import-spec §10): el selector con los formatos compatibles y, con los
        archivos elegidos (o soltados: `paths`), «Archivos → DuckDB» en la base donde, o en la actual."""
        if self._coordinator.state is not SessionState.READY:
            self.notify(tr("Start GeoDuck to import files."))
            return
        if paths is None:
            paths = self._ask_files(tr("Import files"), file_filters())
        if not paths:
            return
        # Un formato que no está en la lista no entra al diálogo: un aviso claro y «Abrir en QGIS»;
        # los compatibles siguen a los tres pasos.
        unsupported = [p for p in paths if format_for(p) is OTHER]
        supported = [p for p in paths if p not in unsupported]
        if unsupported:
            readable = [p for p in unsupported if gdal_readable(p)]
            actions: list[tuple[str, Callable[[], None]]] = []
            if readable:  # el GDAL de DuckDB lo lee: SQL para quien lo sabe, QGIS para el resto
                actions = [
                    (tr("Write query"), lambda: self.write_query(readable)),
                    (tr("Open in QGIS"), lambda: self.open_in_qgis(readable)),
                ]
            self.toast(
                lines_html(unsupported_lines(unsupported, len(supported))),
                actions,
                UNSUPPORTED_SECONDS,
                kind="busy",  # ámbar: un aviso, no un error
            )
        if supported:
            self.to_duckdb.open_files(
                supported, destination if destination is not None else self.sidebar.current_target()
            )

    def write_query(self, paths: list[str]) -> None:
        """«Escribir consulta»: una pestaña nueva con un `FROM ST_Read('ruta');` por archivo, sin ejecutar
        (lo mismo que soltarlos en el editor)."""
        self.new_query()
        page = self.tabs.page(self.tabs.bar.currentIndex())
        if isinstance(page, QueryPage):
            page.drop_files(paths, any_format=True)

    def _export_trace(self, event: Any) -> None:
        """«Exportar ▾» con su línea de tiempo (#148, punto 19): Consulta → DuckDB escribe el archivo →
        Archivo, con «Cancelar · Esc» y, al terminar, «Abrir carpeta», «Cargar en QGIS» y «Cerrar»."""
        if isinstance(event, ExportStarted):
            self._exports[event.export_id] = ExportProgress(
                self,
                event,
                cancel=self._coordinator.cancel_current_operation,
                load=lambda path: self.open_in_qgis([path]),
                progress=self._coordinator.query_progress,
            )
            return
        progress = self._exports.pop(event.export_id, None)
        if progress is not None:
            with contextlib.suppress(RuntimeError):
                progress.finish(event)

    def open_in_qgis(self, paths: list[str]) -> None:
        """«Abrir en QGIS» para archivos que GeoDuck no importa: QGIS los abre (todas sus capas); después se
        añaden a DuckDB como capas de QGIS (clic derecho › «Añadir a DuckDB…» o arrastrándolas)."""
        opened, failed = open_in_qgis(paths)
        if failed:
            names = ", ".join(os.path.basename(p) for p in failed)
            self.notify(tr("QGIS could not open: {0}").format(names))
        elif opened:
            self.notify(
                tr("{0} layer(s) opened in QGIS: now add them to GeoDuck from the layers panel").format(
                    opened
                )
            )

    def add_layers(self, checked: list[str] | None = None) -> None:
        """«+» o Ctrl+K › «Añadir capas de QGIS a DuckDB…»: paso 1 con todas las capas del proyecto."""
        self.to_duckdb.open(None, self.sidebar.current_target(), checked=checked)

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        """Capas o archivos soltados en cualquier parte de GeoDuck (también en el panel): a la base actual."""
        if accepts(event.mimeData()) and self._coordinator.state is SessionState.READY:
            event.setDropAction(Qt.DropAction.CopyAction)  # nunca «mover»: QGIS borraría la capa
            event.accept()
            target = self.sidebar.current_target()
            where = target[0] if target else tr("the current database")
            self.notify(drop_hint(event.mimeData(), where))
        else:
            event.ignore()

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if accepts(event.mimeData()) and self._coordinator.state is SessionState.READY:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        ids = layer_ids(event.mimeData())
        files = file_paths(event.mimeData())
        if not ids and not files:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if files:
            self.import_files(paths=files)
        else:
            self.send_layers(ids)

    def _connect_sidebar(self) -> None:
        side = self.sidebar
        side.open_requested.connect(self.open_place)
        side.open_requested.connect(
            lambda _p: self.set_overlay_open(False)
        )  # en el panel: elegido, se cierra
        side.make_load_menu = self._load_menu_for
        side.favorite_requested.connect(self.toggle_favorite)
        side.detach_requested.connect(self.detach)
        side.refresh_requested.connect(self.refresh)
        side.close_session_requested.connect(self.close_session)
        side.open_database_requested.connect(lambda: self.attach(OpenAction.OPEN_EXISTING))
        side.create_database_requested.connect(lambda: self.attach(OpenAction.CREATE_NEW))
        side.memory_database_requested.connect(self.new_memory_database)
        side.activate_requested.connect(self.activate_database)
        side.close_reason = self._coordinator.close_reason
        side.send_layers_requested.connect(self.send_layers_requested.emit)
        side.diagnostics_requested.connect(self.show_diagnostics)
        side.about_requested.connect(self.show_about)
        side.start_requested.connect(self.start)
        side.tree.layers_dropped.connect(self.send_layers)
        side.tree.files_dropped.connect(lambda paths, target: self.import_files(target, paths))
        side.import_files_requested.connect(self.import_files)
        side.tree.drop_hint.connect(lambda text: self.notify(text) if text else None)
        side.pin_toggled.connect(self.set_pinned)
        side.columns_wanted.connect(self._list_columns)
        side.columns_requested.connect(self.write_columns)

    def _shortcut(self, keys: str, slot: Callable[[], object]) -> None:
        shortcut = QShortcut(QKeySequence(keys), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(slot)

    # -- presentación ---------------------------------------------------------------------------------

    def set_presentation(self, *, wide: bool) -> None:
        """Ventana (`wide`) o panel. En el panel: la sesión y la búsqueda van en su
        cabecera; el explorador se abre **encima** del contenido con el botón de la barra lateral (Ctrl+B) y
        se cierra al elegir algo, con Esc o con un clic fuera; las páginas pasan al modo compacto."""
        self.wide = wide
        layout = self.layout()
        beside = wide or self.pinned
        self.sidebar.setFixedWidth(
            METRICS.sidebar if wide else PINNED_WIDTH if self.pinned else OVERLAY_WIDTH
        )
        self.sidebar.set_docked(not wide, pinned=self.pinned)
        if beside and layout.indexOf(self.sidebar) < 0:
            layout.insertWidget(0, self.sidebar)
            self.sidebar.setGraphicsEffect(None)
        elif not beside and layout.indexOf(self.sidebar) >= 0:
            layout.removeWidget(self.sidebar)
            shadow = QGraphicsDropShadowEffect(self.sidebar)
            shadow.setBlurRadius(24)
            shadow.setOffset(4, 0)
            shadow.setColor(QColor(0, 0, 0, 70))
            self.sidebar.setGraphicsEffect(shadow)
        for widget in (self.dock_button, self.search_button):
            widget.setVisible(wide)  # en el panel, la búsqueda está en su cabecera
        self.overlay_open = False
        self._apply_sidebar()
        self._wide_need = 0
        self.decide_compact()
        self._render()

    def decide_compact(self) -> None:
        """Modo compacto (#147, punto 28): siempre en el panel; en la ventana, por debajo de `COMPACT_WIDTH` o
        cuando la página no cabe con sus textos. El ancho que pedía la página sin compactar se recuerda: no
        sale del modo compacto hasta que vuelva a caber (ni se queda atascado ni salta de un modo a otro)."""
        if not self.wide:
            self.set_compact(True)
            return
        if self.compact:
            if self.width() >= max(COMPACT_WIDTH, self._wide_need):
                self.set_compact(False)
            else:
                return
        side = self.sidebar.width() + 1 if self.sidebar.isVisibleTo(self) else 0
        relayout(self.head)
        need = max(self._page_need(), self.head.minimumSizeHint().width()) + side
        if self.width() < COMPACT_WIDTH or need > self.width():
            self._wide_need = need
            self.set_compact(True)

    def _page_need(self) -> int:
        """El ancho mínimo de lo que se ve en el cuerpo (la página de la pestaña, o la de estado)."""
        page = self.body.currentWidget()
        if page is self.tabs.stack and self.tabs.stack.currentWidget() is not None:
            page = self.tabs.stack.currentWidget()
        if page is None:
            return 0
        relayout(page)
        return int(page.minimumSizeHint().width())

    def set_compact(self, compact: bool) -> None:
        if compact == self.compact:
            return
        self.compact = compact
        direction = QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
        for actions in self._action_rows:
            actions.setDirection(direction)
            actions.invalidate()
        for index in range(len(self.tabs)):
            self._with_mode(self.tabs.page(index))
        relayout(self)

    def _with_mode(self, page: QWidget) -> QWidget:
        """Cada página nueva entra en el modo de ahora (compacto o no)."""
        if hasattr(page, "set_compact"):
            page.set_compact(self.compact)
            relayout(page)
        return page

    @property
    def floating(self) -> bool:
        """El explorador flota encima del contenido (panel acoplado, sin fijar; #147)."""
        return not self.wide and not self.pinned

    def set_pinned(self, pinned: bool) -> None:
        """El 📌 del explorador en el panel (#147): fijado queda al lado y no se cierra solo; flotando, se
        cierra con un clic fuera o Esc. Se recuerda entre sesiones; en la ventana no cambia nada."""
        self.pinned = pinned
        self._settings.setValue(PINNED_KEY, pinned)
        if self.wide:
            self.sidebar.set_docked(False, pinned=pinned)
            return
        self.sidebar_open = True
        self.set_presentation(wide=False)
        if not pinned:
            self.set_overlay_open(True)

    def _apply_sidebar(self) -> None:
        if not self.floating:
            self.sidebar.setVisible(self.sidebar_open)
            self.divider.setVisible(self.sidebar_open)
            QApplication.instance().removeEventFilter(self)
            return
        self.divider.setVisible(False)
        self.sidebar.setVisible(self.overlay_open)
        if self.overlay_open:
            self._place_overlay()
            self.sidebar.raise_()
            self.sidebar.search.edit.setFocus()
            QApplication.instance().installEventFilter(self)
        else:
            QApplication.instance().removeEventFilter(self)

    def _place_overlay(self) -> None:
        if self.overlay_open:
            self.sidebar.setGeometry(0, 0, min(OVERLAY_WIDTH, max(self.width() - 48, 200)), self.height())

    def set_sidebar_open(self, open_: bool) -> None:
        self.sidebar_open = open_
        self._apply_sidebar()

    def set_overlay_open(self, open_: bool) -> None:
        if open_ != self.overlay_open:
            self.overlay_open = open_
            self._apply_sidebar()

    def reveal(self, source: tuple[str, str, str]) -> None:
        """Una tabla o vista en el explorador (#146: Ctrl+clic en el SQL), abriéndolo si estaba cerrado."""
        self.open_explorer()
        self.sidebar.reveal(*source)

    def open_explorer(self) -> None:
        """Abre el explorador (al lado o encima, según cómo esté)."""
        if not self.floating and not self.sidebar_open:
            self.set_sidebar_open(True)
            if self.wide:
                self.sidebar_changed.emit(True)
        elif self.floating and not self.overlay_open:
            self.set_overlay_open(True)

    def _open_for_drop(self) -> None:
        """Arrastrando sobre ☰ (#147): el explorador se abre con la guía «Suelta sobre una base…»."""
        self.open_explorer()
        self.sidebar.show_drop_guide(True)

    def toggle_sidebar(self) -> None:
        """Ctrl+B o el botón: en la ventana pliega o abre la barra lateral; en el panel, abre o cierra el
        explorador encima del contenido."""
        if self.floating:
            self.set_overlay_open(not self.overlay_open)
            return
        self.set_sidebar_open(not self.sidebar_open)
        if self.wide:
            self.sidebar_changed.emit(self.sidebar_open)

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        """Con el explorador abierto en el panel: un clic fuera o Esc lo cierran (sin tragarse el clic)."""
        if not self.overlay_open or not self.floating:
            return False
        kind = event.type()
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.set_overlay_open(False)
            return True
        if kind == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            inside = self.sidebar.isAncestorOf(watched) or watched is self.sidebar
            toggle = watched is self.sidebar_button or self.sidebar_button.isAncestorOf(watched)
            popup = watched.window() is not self.window()  # menús del propio explorador
            if not inside and not toggle and not popup:
                self.set_overlay_open(False)
        return False

    def status(self) -> tuple[str, str]:
        """Punto y texto de la sesión, para la cabecera del panel."""
        return session_text(self._coordinator)

    def notify(self, text: str, *, error: bool = False) -> None:
        """Aviso de la aplicación en el pie (§3; #177): la información se borra sola a los `NOTICE_MS`; un
        error se queda hasta el siguiente aviso o hasta cerrarlo con ✕. Lo de una consulta va a su pestaña."""
        self.notice.setText(text)
        self.notice.setToolTip(text)
        self.notice.setProperty("pro", "error" if error and text else "muted")
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice_close.setVisible(error and bool(text))
        self._notice_timer.stop()
        if text and not error:
            self._notice_timer.start(NOTICE_MS)

    def _render(self) -> None:
        state = self._coordinator.state
        dot, engine, status = session_parts(self._coordinator)
        _, text = session_text(self._coordinator)
        ready = state is SessionState.READY
        self.sidebar.set_session(dot, engine, status, ready=ready)
        self.status_changed.emit(dot, text)
        has_session = self._coordinator.engine_info is not None and state is not SessionState.DISCONNECTED
        self.close_all_button.setVisible(len(self.tabs) > 0)
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
                self,
                tr("The transaction failed. «Roll back» discards its changes and GeoDuck is ready again."),
                kind="error",
                seconds=0,
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
            self.state_title.setText(tr("Starting GeoDuck…"))
            self.state_text.setText(tr("It takes a moment the first time."))
        elif state is SessionState.CLOSING:
            self.state_title.setText(tr("Closing the session…"))
            self.state_text.setText("")
        elif not self.environment_ok:  # AT-BOOT-002: abre, explica y no deja iniciar
            checks = self._report.checks if self._report is not None else ()
            failing = [c.title for c in checks if c.status is CheckStatus.FAIL]
            self.state_title.setText(tr("The environment is not ready for GeoDuck"))
            self.state_text.setText(
                tr("Missing: {}. Press «Diagnostics» to see how to install it.").format(", ".join(failing))
            )
        else:
            self.state_title.setText(tr("GeoDuck is not started"))
            self.state_text.setText(tr("Start GeoDuck in memory, or open a database file."))
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
        """«Cerrar base» (#168, #183). Con cambios sin guardar, no se cierra. Una base en memoria que leen
        capas Conectadas se guarda como archivo; con tablas y sin capas, pide confirmar: se pierden."""
        unsaved = self._coordinator.unsaved_layers(name)
        if unsaved:
            self._tell_blocked(tr("The database «{0}» cannot be closed").format(name), _unsaved_text(unsaved))
            return
        catalog = self._coordinator.catalog
        db = catalog.get(name) if catalog is not None else None
        if db is not None and db.in_memory and catalog is not None:
            layers = self._coordinator.layers_reading(db.name)
            if layers:
                self.save_memory(db.name)
                return
            count = self._table_count(db.name)
            if count and not self._confirm_lose(db.name, count):
                return
        self._detaching = name
        self._guard(lambda: self._coordinator.detach_database(name))
        if self._coordinator.state is not SessionState.DETACHING:
            self._detaching = None  # no empezó: el motivo ya se avisó

    def _table_count(self, name: str) -> int:
        catalog = self._coordinator.catalog
        if catalog is None:
            return 0
        key = catalog_key(name)
        return sum(1 for o in catalog.objects if not o.temporary and catalog_key(o.database) == key)

    def save_memory(
        self,
        name: str,
        *,
        confirm: bool = True,
        then_close: bool = False,
        then: Callable[[], None] | None = None,
    ) -> None:
        """Ventana 3 de #183: la base en memoria `name` se guarda como archivo, con el mismo alias, y sus
        capas siguen funcionando. `confirm=False` va directo a elegir el archivo; `then_close`: después
        sigue «Cerrar sesión»; `then`: otra acción al terminar."""
        layers = self._coordinator.layers_reading(name)
        path = self._ask_save_memory(name, layers, self._table_count(name), confirm)
        if not path:
            self._close_after_save = False
            return
        self._close_after_save = then_close
        self._resave_project = then
        self._guard(lambda: self._coordinator.save_database_as(name, path))

    def _save_memory_dialog(self, name: str, layers: list[str], tables: int, confirm: bool) -> str | None:
        if confirm and not self._confirm_save_memory(name, layers, tables):
            return None
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("Save the database «{0}» as").format(name),
            f"{name}.duckdb",
            tr("Database") + " (*.duckdb)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if path and not path.lower().endswith((".duckdb", ".ddb", ".db")):
            path += ".duckdb"
        return path or None

    def _confirm_save_memory(self, name: str, layers: list[str], tables: int) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("GeoDuck"))
        box.setText(tr("Save the database «{0}» before closing it").format(name))
        box.setInformativeText(_save_memory_text(layers, tables))
        box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        go = box.addButton(tr("Save as file and close…"), QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(go)
        box.exec()
        return box.clickedButton() is go

    def _blocked_dialog(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("GeoDuck"))
        box.setText(title)
        box.setInformativeText(text)
        box.addButton(tr("Understood"), QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def _bar(
        self, text: str, level: str = "info", actions: list[tuple[str, Callable[[], None]]] | None = None
    ) -> None:
        """Aviso en la barra de mensajes de QGIS (no bloquea); sin ella, en el pie."""
        if self.push_bar is not None:
            self.push_bar(text, level, actions or [])
        else:
            self.notify(text)

    def _detached(self, database: Any) -> None:
        """Situación 1 de #183: la base se cerró; si la leían capas Conectadas, quedaron no disponibles y
        «Abrir de nuevo» la vuelve a abrir igual (ruta, alias y acceso)."""
        layers = self._coordinator.layers_reading(database.name)
        if not layers:
            self.notify(tr("Database «{}» closed").format(database.name))
            return
        text = tr("Database «{0}» closed. {1}").format(database.name, _left_unavailable(layers))
        actions: list[tuple[str, Callable[[], None]]] = []
        if database.path:
            request = AttachRequest(
                database.path, database.access, OpenAction.OPEN_EXISTING, alias=database.name
            )
            actions.append((tr("Open again"), lambda: self.reopen(request)))
        self._bar(text, "info", actions)

    def reopen(self, request: AttachRequest) -> None:
        """Vuelve a abrir una base (o inicia GeoDuck con ella)."""
        if self._coordinator.can_start:
            self._guard(lambda: self._coordinator.start_file_session(request))
        else:
            self._guard(lambda: self._coordinator.attach_database(request))

    def _track_unavailable(self, catalog: Any) -> None:
        """Una base cerrada con `DETACH` en el editor: el mismo aviso que «Cerrar base», con «Abrir de
        nuevo». Otras capas que quedaron no disponibles se dicen en el pie."""
        bases = {d.name: d for d in catalog.databases} if catalog is not None else {}
        closed = [d for name, d in self._bases.items() if name not in bases]
        self._bases = bases
        now = set(self._coordinator.unavailable_layers())
        lost = now - self._unavailable
        self._unavailable = now
        if not lost or self._detaching is not None or self._closing:
            return
        for database in closed:
            told = set(self._coordinator.layers_reading(database.name))
            if told & lost:
                self._detached(database)
                lost -= told
        if lost:
            self.notify(_left_unavailable(sorted(lost)))

    def _spatial_missing(self, message: str) -> None:
        """#193: GeoDuck carga `spatial` al iniciar; si no pudo (sin internet), lo dice con «Reintentar».
        Todo lo demás funciona como siempre."""
        self._bar(
            f"{SPATIAL_MISSING()} {message}",
            "warning",
            [(tr("Retry"), self.retry_spatial), (tr("Install from a file…"), self.install_spatial_from_file)],
        )

    def install_spatial_from_file(self) -> None:
        """Una red sin salida a internet: el archivo de `spatial` descargado en otro equipo («Diagnóstico»
        dice cuál)."""
        path = self._ask_spatial_file()
        if not path:
            return
        self._retrying_spatial = True
        self._guard(lambda: self._coordinator.install_spatial_from(path))

    def _spatial_file_dialog(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Install the «spatial» extension"),
            "",
            tr("«spatial» extension") + " (*.duckdb_extension *.duckdb_extension.gz)",
        )
        return path

    def retry_spatial(self) -> None:
        self._retrying_spatial = True
        self._guard(lambda: self._coordinator.activate_spatial(install=True))

    def _session_closed(self) -> None:
        """Situación 5 de #183: las capas Conectadas vuelven al iniciar GeoDuck y abrir sus bases."""
        layers = self._coordinator.unavailable_layers()
        if layers:
            count = len(layers)
            text = (
                tr(
                    "GeoDuck session closed. 1 layer is now unavailable; it comes back when you start "
                    "GeoDuck and open its database."
                )
                if count == 1
                else tr(
                    "GeoDuck session closed. {0} layers are now unavailable; they come back when you "
                    "start GeoDuck and open their databases."
                ).format(count)
            )
            self._bar(text)

    def _confirm_lose(self, name: str, count: int) -> bool:
        """«¿Cerrar la base «memory»?»: sus tablas solo existen en memoria (maqueta `bases`)."""
        if self._ask_lose is not None:
            return self._ask_lose(name, count)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("GeoDuck"))
        box.setText(tr("Close the database «{0}»?").format(name))
        tables = tr("1 table") if count == 1 else tr("{0} tables").format(count)
        box.setInformativeText(tr("It has {0} that only exist in memory: they will be lost.").format(tables))
        lose = box.addButton(tr("Close and lose {0}").format(tables), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is lose

    def activate_database(self, name: str) -> None:
        """«Usar como base activa» (#168): una sola para toda la sesión (explorador, editor y lo nuevo)."""
        self._guard(lambda: self._coordinator.activate_database(name))

    def new_memory_database(self) -> None:
        """«Nueva base en memoria…» (#168): con el alias que se elija («memory» o el siguiente libre). Sin
        sesión, la inicia en memoria."""
        if self._coordinator.can_start:
            self.start()
            return
        catalog = self._coordinator.catalog
        proposed = catalog.next_alias() if catalog is not None else MEMORY_ALIAS
        if self._ask_alias is not None:
            alias = self._ask_alias(proposed)
        else:
            text, ok = QInputDialog.getText(
                self, tr("New database in memory"), tr("Alias of the database:"), text=proposed
            )
            alias = text.strip() if ok else None
        if not alias:
            return
        self._guard(
            lambda: self._coordinator.attach_database(
                AttachRequest(path="", access=AccessMode.READ_WRITE, action=OpenAction.IN_MEMORY, alias=alias)
            )
        )

    def refresh(self) -> None:
        self._guard(self._coordinator.refresh_catalog)

    def close_session(self) -> None:
        """«Cerrar sesión» (#183): todo o nada. Con cambios sin guardar no se cierra; cada base en memoria
        que leen capas Conectadas se guarda antes como archivo (cancelar no cierra nada)."""
        unsaved = self._coordinator.unsaved_layers()
        if unsaved:
            self._tell_blocked(tr("The session cannot be closed"), _unsaved_text(unsaved))
            return
        catalog = self._coordinator.catalog
        for db in catalog.databases if catalog is not None else ():
            if db.in_memory and self._coordinator.layers_reading(db.name):
                self.save_memory(db.name, then_close=True)
                return
        self._closing = True
        self._guard(self._coordinator.request_close)

    def _guard(self, action: Callable[[], object]) -> None:
        try:
            action()
        except GeoDuckError as exc:
            self.notify(exc.message, error=True)

    def open_place(self, place: Place) -> None:
        """Doble clic, Intro o Ctrl+K: abre la tabla, vista o consulta en su pestaña (o trae la abierta)."""
        reason = missing_reason(place, self._coordinator.catalog)
        if reason is not None:
            self.notify(f"{place.name}: {reason}")
            return
        self.tabs.open_place(place)
        self.places.touch(place)  # el explorador no muestra recientes: no hace falta rehacerlo
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
                loader=self.to_qgis.quick_one,
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
            loader=self.to_qgis.quick_one,
        )
        page.changed.connect(lambda p=page: self._query_changed(p))
        page.renamed.connect(lambda old, p=page: self._query_renamed(p, old))
        page.open_requested.connect(self.open_query_file)
        page.notice.connect(self.notify)
        page.activate_requested.connect(self.activate_database)
        if page.saved_database:  # #168: la consulta se guardó con otra base; se ofrece, no se cambia
            other = page.saved_database
            self.toast(
                tr("This query was saved with «{0}»; the active database is «{1}».").format(
                    other, self._coordinator.catalog.default if self._coordinator.catalog else ""
                ),
                [(tr("Activate «{0}»").format(other), lambda: self.activate_database(other))],
                12,
            )
        page.import_files_requested.connect(lambda paths: self.import_files(paths=paths))
        page.view_sql_requested.connect(self.open_sql)  # «Ver SQL» del resultado filtrado (#144)
        page.reveal_requested.connect(self.reveal)  # Ctrl+clic en una tabla del SQL (#146)
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

    def _files_dialog(self, title: str, filters: list[str]) -> list[str]:
        paths, _ = QFileDialog.getOpenFileNames(self, title, str(Path.home()), ";;".join(filters))
        return list(paths)

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
        self._wide_need = 0  # otra página: se vuelve a medir
        self.decide_compact()
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

        report = self.refresh_environment()
        info = self._coordinator.engine_info
        if info is not None and info.temp_directory:  # #172: dónde usa disco DuckDB y hasta cuánto
            facts = dict(report.facts)
            facts[tr("Session temporary files")] = tr("{0} · up to {1}").format(
                info.temp_directory, size_text(info.temp_limit)
            )
            report = dataclasses.replace(report, facts=facts)
        DiagnosticsDialog(report, self).exec()

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
        if self.to_duckdb.running:
            found.append(
                Entry(
                    tr("Show progress: QGIS layers → GeoDuck"), action, "layers", self.to_duckdb.show_window
                )
            )
        if ready:
            found += [
                Entry(
                    tr("Open database…"), action, "database", lambda: self.attach(OpenAction.OPEN_EXISTING)
                ),
                Entry(tr("Create database…"), action, "database", lambda: self.attach(OpenAction.CREATE_NEW)),
                Entry(tr("New database in memory…"), action, "memory", self.new_memory_database),
                Entry(tr("Import files…"), action, "layers", self.import_files),
                Entry(tr("Add QGIS layers to GeoDuck…"), action, "layers", self.send_layers_requested.emit),
                Entry(tr("Refresh databases"), action, "refresh", self.refresh),
            ]
            catalog = self._coordinator.catalog
            for db in catalog.databases if catalog is not None else ():
                if catalog is not None and db.key != catalog_key(catalog.default):  # #168
                    found.append(
                        Entry(
                            tr("Use «{0}» as active database").format(db.name),
                            action,
                            "database",
                            lambda name=db.name: self.activate_database(name),
                        )
                    )
        found.append(Entry(tr("Show or hide the sidebar"), action, "sidebar", self.toggle_sidebar))
        if self.wide:
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

    def _on_event(self, event: AppEvent) -> None:  # noqa: PLR0912, PLR0915 - un caso por evento
        if isinstance(event, (SessionStateChanged, SessionStarted)):
            self._render()
            if self._closing and self._coordinator.state is SessionState.DISCONNECTED:
                self._closing = False
                self._session_closed()
            if isinstance(event, SessionStarted) and event.info.spatial_error:
                self._spatial_missing(event.info.spatial_error)
        elif isinstance(event, SpatialActivated) and self._retrying_spatial:
            self._retrying_spatial = False
            self._bar(tr("The «spatial» extension is loaded: spatial analysis is available."), "success")
        elif isinstance(event, SpatialActivationFailed) and self._retrying_spatial:
            self._retrying_spatial = False
            self._spatial_missing(event.message)
        elif isinstance(event, CatalogChanged):
            self.sidebar.render(event.catalog)
            self._render()
            self._track_unavailable(event.catalog)
        elif isinstance(event, ColumnsListed):
            self.sidebar.set_columns(event.source, event.columns)
        elif isinstance(event, ColumnsUnavailable):
            self.sidebar.set_columns(event.source, None)
        elif isinstance(event, VocabularyChanged):
            vocabulary = self._coordinator.vocabulary()
            self.sidebar.reserved = vocabulary.reserved if vocabulary is not None else None
        elif isinstance(event, SendFinished):  # lo nuevo, resaltado en el explorador (#147)
            self.sidebar.mark_new([(t.database, t.schema, t.name) for t in event.report.tables if t.name])
        elif isinstance(event, CatalogUnavailable):
            self.notify(tr("The catalog could not be read.") + f" {event.message}")
        elif isinstance(event, DatabaseAttached):
            self.notify(tr("Database «{}» open").format(event.database.name))
        elif isinstance(event, DatabaseDetached):
            self._detaching = None
            self._detached(event.database)
        elif isinstance(event, DatabaseSaved):
            self.notify(tr("Database «{0}» saved as {1}").format(event.database.name, event.database.path))
            again, self._resave_project = self._resave_project, None
            if again is not None:
                again()
            if self._close_after_save:
                self._close_after_save = False
                self.close_session()
        elif isinstance(event, SaveDatabaseFailed):
            self._close_after_save = False
            self._resave_project = None
            self.notify(tr("The database was not saved.") + f" {event.message}", error=True)
        elif isinstance(event, AttachFailed):
            self.notify(tr("The database was not opened.") + f" {event.message}", error=True)
        elif isinstance(event, DetachFailed):
            self._detaching = None
            self.notify(tr("The database was not closed.") + f" {event.message}", error=True)
        elif isinstance(event, ActivationFailed):
            self.notify(tr("The active database did not change.") + f" {event.message}", error=True)
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

    def _list_columns(self, source: tuple[str, str, str]) -> None:
        """Las columnas de una tabla del explorador (#147): `duckdb_columns()`, sin leer datos."""
        try:
            self._coordinator.list_columns(source)
        except GeoDuckError:
            self.sidebar.set_columns(source, None)

    def write_columns(self, text: str) -> None:
        """Doble clic en columnas del explorador (#147): sus nombres donde está el cursor de la consulta
        actual (o de una nueva). Nunca se ejecuta nada."""
        if not text:
            return
        page = self.tabs.stack.currentWidget() if len(self.tabs) else None
        if not isinstance(page, QueryPage):
            self.new_query()
            page = self.tabs.stack.currentWidget()
        if not isinstance(page, QueryPage):
            return
        page.editor.insert(text)
        line, index = page.editor.getCursorPosition()
        page.editor.setCursorPosition(line, index + len(text))
        page.editor.setFocus()
        if self.floating:
            self.set_overlay_open(False)

    def detach_coordinator(self) -> None:
        """Al descargar GeoDuck: deja de escuchar al coordinador."""
        with contextlib.suppress(Exception):
            self._unsubscribe()
        with contextlib.suppress(Exception):
            self._unsubscribe_exports()
        for index in range(len(self.tabs)):
            page = self.tabs.page(index)
            if hasattr(page, "close_page"):
                page.close_page()  # una consulta con archivo guarda lo pendiente
        self.recovery.stop()
        self.loader.detach()
        self.to_qgis.detach()
        self.history.detach()
        self.to_duckdb.detach()
        if self.project_copies is not None:
            self.project_copies.detach()


class HoldToOpen(QObject):
    """☰ con algo arrastrado encima (#147, maqueta `explorador-lago`): el botón se ilumina, dice «Mantén para
    abrir el explorador» y a los `HOLD_MS` lo abre. Soltar sobre el botón es como soltar en GeoDuck."""

    def __init__(
        self, button: QPushButton, opened: Callable[[], None], dropped: Callable[[Any], None]
    ) -> None:
        super().__init__(button)
        self.button = button
        self._opened = opened
        self._dropped = dropped
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(HOLD_MS)
        self.timer.timeout.connect(self._hold)
        button.setAcceptDrops(True)
        button.installEventFilter(self)

    def _light(self, on: bool) -> None:
        self.button.setProperty("drop", on)
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)

    def _hold(self) -> None:
        self._light(False)
        QToolTip.hideText()
        self._opened()

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        kind = event.type()
        if kind == QEvent.Type.DragEnter:
            if not accepts(event.mimeData()):
                return False
            event.acceptProposedAction()
            self._light(True)
            QToolTip.showText(
                self.button.mapToGlobal(QPoint(0, self.button.height())),
                tr("Hold to open the explorer"),
                self.button,
            )
            self.timer.start()
            return True
        if kind == QEvent.Type.DragMove:
            event.acceptProposedAction()
            return True
        if kind == QEvent.Type.DragLeave:
            self.timer.stop()
            self._light(False)
            QToolTip.hideText()
            return True
        if kind == QEvent.Type.Drop:
            self.timer.stop()
            self._light(False)
            QToolTip.hideText()
            self._dropped(event)
            return True
        return False


def _names(layers: list[str], limit: int = 5) -> str:
    shown = ", ".join(layers[:limit])
    return shown + (tr(" and {0} more").format(len(layers) - limit) if len(layers) > limit else "")


def _left_unavailable(layers: list[str]) -> str:
    if len(layers) == 1:
        return tr("1 layer is now unavailable: {0}.").format(layers[0])
    return tr("{0} layers are now unavailable: {1}.").format(len(layers), _names(layers))


def _unsaved_text(layers: list[str]) -> str:
    if len(layers) == 1:
        return tr("The layer {0} has unsaved changes. Save or discard them in QGIS and try again.").format(
            layers[0]
        )
    return tr("The layers {0} have unsaved changes. Save or discard them in QGIS and try again.").format(
        _names(layers)
    )


def _save_memory_text(layers: list[str], tables: int) -> str:
    used = (
        tr("It only exists in memory and the layer {0} uses it.").format(layers[0])
        if len(layers) == 1
        else tr("It only exists in memory and the layers {0} use it.").format(_names(layers))
    )
    kept = tr("the layer keeps working") if len(layers) == 1 else tr("the layers keep working")
    if tables == 1:
        saved = tr("It will be saved as a file, with its table, and {0}.").format(kept)
    else:
        saved = tr("It will be saved as a file, with its {0} tables, and {1}.").format(tables, kept)
    return f"{used} {saved}"
