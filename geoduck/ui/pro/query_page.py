# SPDX-License-Identifier: GPL-2.0-or-later
"""Pestaña de consulta de Workspace Pro (workspace-pro-spec §5; GD-WSP-004; AT-WSP-005).

Una sola barra fina: «▶ Ejecutar» (la sentencia bajo el cursor o la selección, Ctrl+Enter), «Todo»
(Ctrl+Shift+Enter), «Cancelar», la base de la consulta y «⋯» (abrir, guardar, guardar como). Debajo, el
editor SQL de QGIS (con el autocompletado de G6 y los colores de GeoDuck) y el resultado, con un divisor que
se arrastra: **Resultado** (la grilla de E3; una pestaña por sentencia con tabla, sin pestañas si es una) y
**Mensajes** (✓ o ✕ por sentencia, con la línea y la palabra del error e «Ir»; ante un error se abre solo y el
editor marca cada sentencia con ✓, ✕ o –, #139). «Exportar ▾» exporta la
consulta completa del resultado elegido.

El SQL se ejecuta por el coordinador (`execute_sql`, con la base de la consulta); esta página solo muestra.
Guardar escribe el SQL tal cual en un `.sql`; una consulta con archivo se autoguarda tras cada cambio.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qgis.PyQt.QtCore import QEvent, QObject, QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QGuiApplication, QKeySequence
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QAction,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QScrollArea,
    QShortcut,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from geoduck.app.events import (
    AppEvent,
    CatalogChanged,
    ColumnsListed,
    PreviewsInvalidated,
    ScriptFinished,
    ScriptRejected,
    SessionStateChanged,
    StatementFinished,
    VocabularyChanged,
)
from geoduck.domain.browse import PAGE, page_label
from geoduck.domain.catalog import AccessMode, CatalogSnapshot, ColumnInfo
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.export import ExportFormat
from geoduck.domain.files import create_sql, editor_readable, format_for, gdal_readable
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope, StatementResult, StatementStatus, error_token, result_title
from geoduck.domain.sql_text import load_sql
from geoduck.domain.statements import current_span, statement_spans
from geoduck.ui.i18n import tr
from geoduck.ui.pro import editor as pro_editor
from geoduck.ui.pro.load import export_menu, export_query, load_menu, popup_under
from geoduck.ui.pro.places import QUERY, Place
from geoduck.ui.pro.table_page import DetailPanel, PageModel, TypeHeader, fit_columns, tighten
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import Lake, Segmented, button, icon_button, label, spacer
from geoduck.ui.widgets import line_index_from, offset_from

#: Espera tras el último cambio antes de autoguardar en el archivo de la consulta.
AUTOSAVE_MS = 1500
#: Resultado o mensajes.
RESULT, MESSAGES = 0, 1
#: Espera tras mover el cursor o escribir antes de volver a marcar la sentencia que correrá.
MARK_MS = 60
#: La franja «Ejecutando…» aparece solo si la consulta tarda más que esto (#138: sin parpadeo).
RUNNING_MS = 300
#: El ▶ de la barra de la consulta: cuadrado y compacto (px).
RUN_SIZE = 28


def _seconds(ms: float) -> str:
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.2f} s".replace(".", ",")


def _html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _count(n: int) -> str:
    return f"{n:,}".replace(",", " ")


@dataclass
class Run:
    """Una ejecución: el texto del editor al pedirla y lo que va llegando."""

    run_id: int
    text: str
    results: list[StatementResult] = field(default_factory=list)


class QueryPage(QWidget):
    """La pestaña de una consulta. `changed()` al editar (para la copia de recuperación y el autoguardado);
    `renamed(Place)` al guardar con otro nombre; `open_requested()` con Ctrl+O."""

    changed = pyqtSignal()
    renamed = pyqtSignal(object)  # Place
    open_requested = pyqtSignal()
    #: Aviso para el pie del workspace.
    notice = pyqtSignal(str)
    #: Archivos soltados en el editor que no se leen con SQL (Arrow, no compatibles): al área de trabajo.
    import_files_requested = pyqtSignal(list)

    def __init__(
        self,
        place: Place,
        coordinator: Any,
        colors: Colors,
        *,
        sql: str = "",
        database: str | None = None,
        ask_path: Callable[[str, str, str], str] | None = None,
        loader: Callable[..., None] | None = None,
    ) -> None:
        super().__init__()
        self.place = place
        self.colors = colors
        self._coordinator = coordinator
        self._ask_path = ask_path or self._file_dialog
        self._loader = loader
        self.run_text = ""
        self._closed = False
        self.run: Run | None = None
        self.results: list[StatementResult] = []
        self._epochs: dict[int, int] = {}
        #: Página de cada resultado con tabla (por `id`): desplazamiento, filas y total (None: sin contar).
        self._pages: dict[int, dict[str, Any]] = {}
        self.detail_open = True
        self.compact = False
        self._started = 0.0  # consulta en curso (#138): cuándo empezó
        self._running_timer = QTimer(self, timeout=self._tick_running)
        self.saved_text = sql if place.path else None  # lo que hay en el archivo
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self._build_bar())
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setHandleWidth(1)
        self.split.setChildrenCollapsible(False)
        self.editor = pro_editor.make(colors, dark=colors.dark)
        self.editor.setAccessibleName(tr("SQL editor"))
        self.editor.setText(sql)
        self.editor.textChanged.connect(self._text_changed)
        self.editor.layer_drops.on_files = self.drop_files
        # Ctrl+Enter / Ctrl+Shift+Enter desde el editor, antes que cualquier atajo y con la lista de
        # autocompletado abierta (#139); los atajos de abajo cubren el resto de la página (resultado, barra)
        self._run_keys = pro_editor.RunKeys(
            self.editor,
            lambda every: self.execute(RunScope.ALL if every else RunScope.CURRENT),
            self._escape_cancels,
        )
        self.editor.installEventFilter(self._run_keys)
        self._wire_mark()
        self.split.addWidget(self.editor)
        self.split.addWidget(self._build_results())
        self.split.setSizes([360, 400])
        box.addWidget(self.split, 1)
        self.completer: Any = None
        with contextlib.suppress(Exception):  # G6: el mismo autocompletado que el editor de G6
            from geoduck.ui.completer import SqlCompleter  # noqa: PLC0415

            self.completer = SqlCompleter(self.editor, coordinator)
        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(AUTOSAVE_MS)
        self._autosave.timeout.connect(self.save_if_saved)
        self._shortcuts()
        self.show_databases(coordinator.catalog, database)
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._render_state()
        self.mark_statement()
        self._show_results()

    def _shortcuts(self) -> None:
        for keys, slot in (
            ("Ctrl+Return", lambda: self.execute(RunScope.CURRENT)),
            ("Ctrl+Enter", lambda: self.execute(RunScope.CURRENT)),
            ("Ctrl+Shift+Return", lambda: self.execute(RunScope.ALL)),
            ("Ctrl+Shift+Enter", lambda: self.execute(RunScope.ALL)),
            ("Ctrl+S", self.save),
            ("Escape", self.cancel),
        ):  # Ctrl+O es del workspace (abre en una pestaña nueva)
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        # Esc cancela solo mientras corre (#143): el resto del tiempo es del editor (autocompletado…)
        self._escape = shortcut
        self._escape.setEnabled(False)

    # -- construcción ---------------------------------------------------------------------------------

    def _build_bar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("pro", "rule-bottom")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(6)
        # Una sola idea por zona (propietario, 2026-11-12): esta barra es «correr el SQL»: ▶ (solo ícono; la
        # ayuda dice qué corre y su atajo) y la base. El archivo va en la pestaña; las filas, en el resultado.
        self.run_button = button("", "primary", icon="play")
        # ▶ lleno, cuadrado y compacto (propietario, 2026-11-13, opción 1): 28 × 28, icono de 12
        self.run_button.setProperty("square", True)
        self.run_button.setFixedSize(RUN_SIZE, RUN_SIZE)
        self.run_button.setIcon(self._icon("play", self.colors.on_accent, 12))
        self.run_button.setIconSize(QSize(12, 12))
        self.run_button.clicked.connect(lambda: self.execute(RunScope.CURRENT))
        row.addWidget(self.run_button)
        row.addSpacing(6)
        self.runs_in_label = label(tr("Runs in"), "muted")
        row.addWidget(self.runs_in_label)
        self.base = QComboBox()
        self.base.setAccessibleName(tr("Database of the query"))
        self.base.setToolTip(tr("«Run» runs the SQL in this database"))
        self.base.setMinimumWidth(110)
        self.base.currentIndexChanged.connect(lambda _i: self.changed.emit())
        row.addWidget(self.base)
        row.addWidget(spacer(), 1)
        # «Ejecutar todo»: Ctrl+Shift+Enter y el clic derecho del editor (abrir y guardar están junto a las
        # pestañas: el archivo arriba, la ejecución aquí; propietario, 2026-11-06)
        self.run_all_action = QAction(tr("Run all") + "\tCtrl+Shift+Enter", self)
        self.run_all_action.triggered.connect(lambda: self.execute(RunScope.ALL))
        return bar

    def _icon(self, name: str, color: str, size: int = 16) -> Any:
        from geoduck.ui.pro import icons  # noqa: PLC0415

        return icons.icon(name, color, size)

    def _build_results(self) -> QWidget:  # noqa: PLR0915 - el panel de resultados, en un solo lugar
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        head = QFrame()
        head.setProperty("pro", "rule-bottom")
        row = QHBoxLayout(head)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(10)
        self.view = Segmented([tr("Result"), tr("Messages")], accessible_name=tr("Result or messages"))
        self.view.changed.connect(self._show_view)
        row.addWidget(self.view)
        self.summary = label("", "muted")
        row.addWidget(self.summary)
        # «✕ Error en la línea N, cerca de «palabra»»: un clic lleva el cursor ahí (#139)
        self.error_link = label("", "error")
        self.error_link.setTextFormat(Qt.TextFormat.RichText)
        self.error_link.linkActivated.connect(lambda _l: self._go_to_error())
        self.error_link.hide()
        row.addWidget(self.error_link)
        # Consulta en curso (#143, punto 1): el pato nadando en el lago, «Ejecutando… 12 s» y
        # ■ Cancelar · Esc, solo si tarda más de `RUNNING_MS` (sin parpadeo en las rápidas)
        self.running = QWidget()
        strip = QHBoxLayout(self.running)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(10)
        self.lake = Lake(self.colors, accessible_name=tr("Running"))
        self.lake.setMinimumWidth(120)
        self.lake.setMaximumWidth(220)
        strip.addWidget(self.lake, 1)
        self.elapsed_label = label("", "muted")
        strip.addWidget(self.elapsed_label)
        self.stop_button = button(tr("Cancel · Esc"), "ghost", icon="stop", colors=self.colors)
        self.stop_button.setToolTip(tr("Stops the running SQL (Esc)"))
        self.stop_button.clicked.connect(self.cancel)
        strip.addWidget(self.stop_button)
        self.running.hide()
        row.addWidget(self.running, 1)
        row.addWidget(spacer(), 1)
        # Las filas (#143, punto 3): solo íconos, con la ayuda que dice qué hace y sobre qué
        self.copy_button = icon_button("copy", tr("Copy the rows of this page"), self.colors)
        self.copy_button.clicked.connect(self.copy_result)
        row.addWidget(self.copy_button)
        self.export_button = icon_button("export", tr("Export the full result ▾"), self.colors)
        self.export_menu = export_menu(self, self.export)
        self.export_button.clicked.connect(lambda: popup_under(self.export_menu, self.export_button))
        row.addWidget(self.export_button)
        self.load_button = icon_button("layers", tr("Load the full result in QGIS ▾"), self.colors)
        self.load_menu = load_menu(self, self.colors, self.load_in_qgis, more=True)
        self.load_button.clicked.connect(lambda: popup_under(self.load_menu, self.load_button))
        row.addWidget(self.load_button)
        self.detail_button = icon_button("dock", tr("Show or hide the row detail"), self.colors)
        self.detail_button.setCheckable(True)
        self.detail_button.setChecked(True)
        self.detail_button.toggled.connect(self.set_detail_open)
        row.addWidget(self.detail_button)
        box.addWidget(head)
        self.result_tabs = QTabBar()
        self.result_tabs.setProperty("pro", "tabs")
        self.result_tabs.setDocumentMode(True)
        self.result_tabs.setDrawBase(False)
        self.result_tabs.setExpanding(False)
        self.result_tabs.setAccessibleName(tr("Results"))
        self.result_tabs.currentChanged.connect(lambda _i: self._show_grid())
        box.addWidget(self.result_tabs)
        self.stack = QStackedWidget()
        self.model = PageModel(self.colors)
        self.grid = QTableView()
        self.grid.setProperty("pro", "grid")
        self.grid.setModel(self.model)
        self.header = TypeHeader(self.model, self.colors)
        self.header.setSectionsClickable(False)
        self.grid.setHorizontalHeader(self.header)
        self.grid.setShowGrid(False)
        self.grid.setWordWrap(False)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        vertical = self.grid.verticalHeader()
        vertical.setDefaultSectionSize(METRICS.row)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vertical.setMinimumWidth(40)
        self.stack.addWidget(self.grid)
        self.empty = label("", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        self.stack.addWidget(self.empty)
        self.messages = QScrollArea()
        self.messages.setProperty("pro", "plain")
        self.messages.setWidgetResizable(True)
        self.stack.addWidget(self.messages)
        middle = QWidget()
        side = QHBoxLayout(middle)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        side.addWidget(self.stack, 1)
        # el detalle de la fila a la derecha, plegable, como en la pestaña de tabla (propietario, 2026-11-06)
        self.detail = DetailPanel(self.colors)
        self.detail.closed.connect(lambda: self.detail_button.setChecked(False))
        self.detail.hide()
        side.addWidget(self.detail)
        box.addWidget(middle, 1)
        self.grid.selectionModel().currentRowChanged.connect(
            lambda current, _p: self._row_changed(current.row())
        )
        box.addWidget(self._build_footer())
        return panel

    def _build_footer(self) -> QWidget:
        """El pie del resultado: «Filas 1–100 de N · tiempo» y ‹ ›. Exportar y cargar están en la barra del
        resultado, junto a las filas (propietario, 2026-11-12)."""
        foot = QFrame()
        foot.setProperty("pro", "rule-top")
        foot.setFixedHeight(METRICS.bar - 4)
        row = QHBoxLayout(foot)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)
        self.range_label = label("", "muted")
        row.addWidget(self.range_label)
        self.prev_button = icon_button("chevron-left", tr("Previous page"), self.colors)
        self.prev_button.clicked.connect(lambda: self.go(self._offset() - PAGE))
        self.next_button = icon_button("chevron-right", tr("Next page"), self.colors)
        self.next_button.clicked.connect(lambda: self.go(self._offset() + PAGE))
        row.addWidget(self.prev_button)
        row.addWidget(self.next_button)
        row.addStretch(1)
        return foot

    # -- base de la consulta --------------------------------------------------------------------------

    @property
    def database(self) -> str | None:
        return self.base.currentData()

    # -- archivos soltados en el editor (decisión del propietario, 2026-11-07) -------------------------

    def drop_target(self) -> tuple[str, str] | None:
        """Dónde crear las tablas: la base «Se ejecuta en» (si se escribe); `main` o su primer esquema."""
        catalog = self._coordinator.catalog
        if catalog is None:
            return None
        name = self.base.currentData() or catalog.default_database.name
        db = catalog.get(name)
        if db is None or db.access is not AccessMode.READ_WRITE:
            writable = [d for d in catalog.databases if d.access is AccessMode.READ_WRITE]
            if not writable:
                return None
            db = writable[0]
        schemas = catalog.schemas_of(db.name)
        return db.name, "main" if "main" in schemas or not schemas else schemas[0]

    def drop_files(self, paths: list[str], *, any_format: bool = False) -> bool:
        """Un `CREATE TABLE … AS SELECT *` por archivo, en el cursor y sin ejecutar; los que no se leen con
        SQL (Arrow, no compatibles) siguen a «Importar archivos». Con `spatial` sin cargar, la primera línea
        la carga (visible: lo decide el usuario al ejecutar, ADR-0011)."""
        readable = [p for p in paths if editor_readable(p) or (any_format and gdal_readable(p))]
        rest = [p for p in paths if p not in readable]
        if rest:
            self.import_files_requested.emit(rest)
        target = self.drop_target()
        if not readable or target is None:
            if readable:
                self.notice.emit(tr("There is no database in read and write mode to create the tables."))
            return bool(readable)
        database, schema = target
        catalog = self._coordinator.catalog
        taken = [o.name for o in catalog.objects_in(database, schema)] if catalog is not None else []
        vocabulary = self._coordinator.vocabulary()
        reserved = vocabulary.reserved if vocabulary is not None else None

        def write(spatial: str) -> None:
            text = create_sql(readable, database, schema, taken, spatial=spatial, reserved=reserved)
            pro_editor.insert_sql(self.editor, text)

        if not any(format_for(p).needs_spatial for p in readable):  # fuera de la lista: también GDAL
            write("")
            return True

        def checked(out: Any) -> None:
            row = out.rows[0] if not isinstance(out, BaseException) and out.rows else (False, False)
            write("" if row[1] else "load" if row[0] else "install")

        try:
            self._coordinator.read_rows(
                "SELECT installed, loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'",
                1,
                checked,
            )
        except GeoDuckError:
            write("install")
        return True

    def show_databases(self, catalog: CatalogSnapshot | None, chosen: str | None = None) -> None:
        """Las bases de la sesión en el desplegable; conserva la elegida si sigue adjunta."""
        keep = chosen if chosen is not None else self.database
        self.base.blockSignals(True)
        self.base.clear()
        if catalog is not None:
            for db in catalog.databases:
                self.base.addItem(db.name, db.name)
            index = self.base.findData(keep) if keep else -1
            if index < 0:
                index = self.base.findData(catalog.default)
            self.base.setCurrentIndex(max(index, 0))
        self.base.blockSignals(False)

    # -- ejecutar -------------------------------------------------------------------------------------

    def execute(self, scope: RunScope) -> None:
        """«Ejecutar» (la selección, o la sentencia marcada) o «Ejecutar todo». Lo marcado es exactamente lo
        que corre: la sentencia se calcula aquí (`domain.statements`), igual con DuckDB 1.5 y 2.0."""
        blocked = self._blocked()
        if blocked:
            self.notice.emit(blocked)  # nunca en silencio (#139)
            return
        text = self.editor.text()
        if not text.strip():
            self.notice.emit(tr("There is no SQL to run"))
            return
        cursor, base = 0, 0
        sql = text
        if scope is RunScope.CURRENT and self.editor.hasSelectedText():
            scope = RunScope.SELECTION
            line_from, index_from, _l, _i = self.editor.getSelection()
            base = offset_from(text, line_from, index_from)
            sql = self.editor.selectedText()
        elif scope is RunScope.CURRENT:
            span = self.current_span()
            if span is None:
                self.notice.emit(tr("There is no SQL to run"))
                return
            scope, base, sql = RunScope.SELECTION, span[0], text[span[0] : span[1]]
        try:
            run_id = self._coordinator.execute_sql(
                sql,
                scope,
                cursor=cursor,
                base=base,
                preview_limit=PAGE,  # la primera página llega con la ejecución
                database=self.database,
            )
        except GeoDuckError as exc:
            self.notice.emit(exc.message)
            return
        self.run = Run(run_id, text)
        self.editor.status.clear()  # las marcas son de la ejecución anterior (#139)
        self.error_link.hide()
        self.summary.setText("")
        self._started = time.monotonic()
        self._running_timer.start(RUNNING_MS)
        self._render_state()

    def _blocked(self) -> str:
        """Por qué «Ejecutar» no puede correr ahora, o vacío si puede."""
        if self.run is not None:
            return tr("A query is already running · «Cancel» stops it")
        state = self._coordinator.state
        if state is SessionState.READY:
            return ""
        if state is SessionState.BUSY:
            return tr(
                "GeoDuck is finishing another task (loading, exporting or importing): run it when it ends"
            )
        if state is SessionState.CONNECTING:
            return tr("GeoDuck is starting: run it in a moment")
        if state is SessionState.ERROR_RECOVERABLE:
            return tr("The transaction failed: run ROLLBACK (or close it) before running more SQL")
        return tr("GeoDuck is not started: start it to run SQL")

    def _tick_running(self) -> None:
        """Muestra o actualiza «Ejecutando… N s» mientras la consulta sigue (#143, punto 1)."""
        if self.run is None:
            self._stop_running()
            return
        seconds = int(time.monotonic() - self._started)
        self.elapsed_label.setText(
            tr("{} s").format(seconds) if self.compact else tr("Running… {} s").format(seconds)
        )
        if self.running.isHidden():
            self.running.show()
            for widget in (self.summary, self.error_link):
                widget.hide()
            self._running_timer.start(1000)

    def _stop_running(self) -> None:
        """Termina la franja «Ejecutando…»; el resumen del resultado vuelve a su lugar."""
        self._running_timer.stop()
        self.running.hide()
        self.summary.show()
        self._started = 0.0

    def copy_result(self) -> None:
        """Copiar (#143, punto 3): la página que se ve, con los nombres de las columnas, separadas por
        tabuladores (se pegan en una hoja de cálculo). Copiar una selección llega con #144."""
        model = self.model
        if not model.columns:
            return
        rows = range(len(model.rows))
        names = [column.name for column in model.columns]
        lines = ["\t".join(names)]
        lines += ["\t".join("" if v is None else str(v) for v in model.rows[r]) for r in rows]
        QGuiApplication.clipboard().setText("\n".join(lines))
        copied = len(lines) - 1
        self.notice.emit(tr("1 row copied") if copied == 1 else tr("{} rows copied").format(_count(copied)))

    def set_compact(self, compact: bool) -> None:
        """Modo compacto (panel acoplado o ventana angosta; propietario, 2026-11-07): la base sin «Se ejecuta
        en», «12 s» en vez de «Ejecutando… 12 s» y el detalle de la fila cerrado. Todo sigue ahí."""
        self.compact = compact
        self.runs_in_label.setVisible(not compact)
        self.base.setMinimumWidth(80 if compact else 110)
        self.detail_button.setChecked(not compact)
        self.stop_button.setText("" if compact else tr("Cancel · Esc"))  # compacto: solo ■, con su ayuda
        self.stop_button.setAccessibleName(tr("Cancel · Esc"))
        self.lake.setMinimumWidth(60 if compact else 120)
        self.lake.setMaximumWidth(120 if compact else 220)
        tighten(self.range_label.parentWidget().layout(), compact, (16, 0, 16, 0), 10)
        tighten(self.run_button.parentWidget().layout(), compact, (12, 8, 12, 8), 6)
        tighten(self.view.parentWidget().layout(), compact, (12, 6, 12, 6), 10)
        self.mark_statement()
        self._update_range(self.current_result if self.view.current == RESULT else None)

    def _wire_mark(self) -> None:
        """Cada movimiento del cursor, selección o cambio de texto vuelve a marcar (tras `MARK_MS`)."""
        self._mark_timer = QTimer(self)
        self._mark_timer.setSingleShot(True)
        self._mark_timer.setInterval(MARK_MS)
        self._mark_timer.timeout.connect(self.mark_statement)
        editor = self.editor
        for signal in (editor.cursorPositionChanged, editor.selectionChanged, editor.textChanged):
            signal.connect(lambda *_a: self._mark_timer.start())
        pro_editor.prepare_mark(editor, self.colors)
        pro_editor.prepare_play(editor, self.colors, self._play_line)
        self._context = _EditorMenu(self)
        editor.viewport().installEventFilter(self._context)

    def _play_line(self, line: int) -> None:
        """▶ del margen: ejecuta la sentencia de esa línea (el cursor va ahí; sin selección)."""
        self.editor.setCursorPosition(line, 0)
        self.mark_statement()
        self.execute(RunScope.CURRENT)

    def current_span(self) -> tuple[int, int] | None:
        """(inicio, fin) de la sentencia marcada en el texto del editor."""
        text = self.editor.text()
        line, index = self.editor.getCursorPosition()
        return current_span(text, offset_from(text, line, index))

    def mark_statement(self) -> None:
        """La barra a la izquierda de la sentencia que correrá «Ejecutar», y el botón que lo dice: «Ejecutar ·
        línea 5» o «Ejecutar selección». Con selección no hay barra (dos marcas confundirían)."""
        if self._closed:
            return
        text = self.editor.text()
        count = len(statement_spans(text))
        span = None if self.editor.hasSelectedText() else self.current_span()
        lines = None
        if span is not None:
            lines = (line_index_from(text, span[0])[0], line_index_from(text, span[1])[0])
        pro_editor.mark_lines(self.editor, lines)
        if self.editor.hasSelectedText():
            what = tr("Run selection")
        elif lines is not None:
            what = tr("Run · line {}").format(lines[0] + 1)
        else:
            what = tr("Run")
        # solo el ícono ▶ (propietario, 2026-11-12): la ayuda dice qué corre y sus atajos
        self.run_button.setAccessibleName(what)
        self.run_button.setToolTip(
            "\n".join(
                [what + " · Ctrl+Enter", tr("Run all ({} statements) · Ctrl+Shift+Enter").format(count)]
            )
        )
        pro_editor.mark_play(self.editor, lines[0] if lines is not None else None)
        self.run_all_action.setText(tr("Run all ({} statements)").format(count) + "\tCtrl+Shift+Enter")

    def _escape_cancels(self) -> bool:
        """Esc en el editor: cancela si hay una consulta en curso (#143); si no, la tecla sigue su camino."""
        if self.run is None:
            return False
        self.cancel()
        return True

    def cancel(self) -> None:
        if self.run is not None:
            self._coordinator.cancel_current_operation()

    def _statement(self, event: StatementFinished) -> None:
        if self.run is None or event.run_id != self.run.run_id:
            return
        self.run.results.append(event.result)
        self._epochs[id(event.result)] = event.epoch

    def _finished(self, event: ScriptFinished | ScriptRejected) -> None:
        run = self.run
        if run is None:
            return
        if isinstance(event, ScriptFinished):
            if event.run.run_id != run.run_id:
                return
            self.results = list(event.run.results) or run.results
            parse_error, parse_offset = event.run.parse_error, event.run.parse_error_offset
        else:
            self.results = []
            parse_error, parse_offset = event.message, None
        self._failed = bool(parse_error) or any(
            r.status in (StatementStatus.FAILED, StatementStatus.CANCELLED) for r in self.results
        )
        self._messages(run.text, self.results, parse_error, parse_offset)
        self.run = None
        self._stop_running()
        self.run_text = run.text
        self._mark_run(run.text, self.results, parse_error, parse_offset)
        self._show_results(run.text)
        self._render_state()

    def _mark_run(
        self, text: str, results: list[StatementResult], parse_error: str, parse_offset: int | None
    ) -> None:
        """Las marcas de la ejecución en el editor y el enlace al primer error (#139). Solo si el texto
        sigue siendo el que corrió: si cambió mientras corría, las posiciones ya no valdrían."""
        self._error_at: tuple[int, int] | None = None
        status = self.editor.status
        status.clear()
        self.error_link.hide()
        if self.editor.text() != text:
            return
        marks: list[tuple[int, int]] = []
        errors: list[tuple[int, int, str]] = []
        first: tuple[int, str, int | None] | None = None  # (línea, palabra, posición) del primer error
        if parse_error:
            first = self._error_place(text, parse_offset, parse_error, errors)
        for result in results:
            line = line_index_from(text, self._code_start(text, result.statement.start))[0]
            if result.status is StatementStatus.OK:
                marks.append((line, pro_editor.OK_MARK))
            elif result.status is StatementStatus.SKIPPED:
                marks.append((line, pro_editor.SKIPPED_MARK))
            elif result.status is StatementStatus.FAILED:
                marks.append((line, pro_editor.ERROR_MARK))
                offset = result.error_offset
                if offset is None:  # sin lugar: la sentencia entera es el error
                    errors.append(
                        (self._code_start(text, result.statement.start), result.statement.end, result.message)
                    )
                    place: tuple[int, str, int | None] = (line, "", None)
                else:
                    place = self._error_place(text, offset, result.message, errors)
                first = first or place
        if parse_error and first is not None:
            marks.append((first[0], pro_editor.ERROR_MARK))
        status.show(marks, errors)
        if first is None:
            return
        line, word, offset = first
        self._error_at = (line, line_index_from(text, offset)[1] if offset is not None else 0)
        where = (
            tr("Error on line {0}, near «{1}»").format(line + 1, word)
            if word
            else tr("Error on line {0}").format(line + 1)
        )
        self.error_link.setText(f'✕ <a href="#" style="color: {self.colors.error};">{_html(where)}</a>')
        self.error_link.setToolTip(tr("Goes to the error in the editor"))
        self.error_link.show()

    @staticmethod
    def _code_start(text: str, start: int) -> int:
        """El primer carácter de código de una sentencia (sin los espacios ni los comentarios de antes)."""
        for first, last in statement_spans(text):
            if first <= last and start <= first:
                return first
        return start

    @staticmethod
    def _error_place(
        text: str, offset: int | None, message: str, errors: list[tuple[int, int, str]]
    ) -> tuple[int, str, int | None]:
        if offset is None or not 0 <= offset < len(text):
            return (0, "", None) if not errors else (line_index_from(text, errors[-1][0])[0], "", None)
        word = error_token(text, offset, message)
        errors.append((offset, offset + max(1, len(word)), message.split("\n", 1)[0]))
        return line_index_from(text, offset)[0], word, offset

    def _go_to_error(self) -> None:
        if getattr(self, "_error_at", None) is not None:
            self.go_to(*self._error_at)

    def _show_results(self, text: str = "") -> None:
        """Una pestaña por sentencia con tabla (sin pestañas si es una); si ninguna tiene tabla, los
        mensajes."""
        tabular = [r for r in self.results if r.preview is not None]
        self._pages = {}
        self.result_tabs.blockSignals(True)
        while self.result_tabs.count():
            self.result_tabs.removeTab(0)
        for result in tabular:
            self.result_tabs.addTab(result_title(text, result.statement) if text else "")
        self.result_tabs.blockSignals(False)
        self.result_tabs.setVisible(len(tabular) > 1)
        self._tabular = tabular
        # ante cualquier error, también uno de sintaxis que no dejó correr nada, se abre «Mensajes» (#139)
        failed = getattr(self, "_failed", False) or any(
            r.status in (StatementStatus.FAILED, StatementStatus.CANCELLED) for r in self.results
        )
        if tabular and not failed:
            self.result_tabs.setCurrentIndex(len(tabular) - 1)
            self.view.set_current(RESULT)
        elif self.results or failed:
            self.view.set_current(MESSAGES)
        self._show_view(self.view.current)

    def _show_view(self, index: int) -> None:
        if index == MESSAGES:
            self.stack.setCurrentWidget(self.messages)
            self.result_tabs.hide()
            self.export_button.setEnabled(False)
            self.load_button.setEnabled(False)
            self.detail.hide()
            self._summarize_messages()
            self._update_range(None)
        else:
            self.result_tabs.setVisible(len(getattr(self, "_tabular", [])) > 1)
            self._show_grid()

    def _show_grid(self) -> None:
        tabular = getattr(self, "_tabular", [])
        index = self.result_tabs.currentIndex() if len(tabular) > 1 else len(tabular) - 1
        if not tabular or index < 0:
            self.model.set_page((), (), 0)
            self.empty.setText(tr("Run a query to see its result here."))
            self.stack.setCurrentWidget(self.empty)
            self.summary.setText("")
            self.export_button.setEnabled(False)
            self.load_button.setEnabled(False)
            self.detail.hide()
            self._update_range(None)
            return
        result = tabular[index]
        preview = result.preview
        assert preview is not None
        page = self._page_of(result)
        columns = tuple(ColumnInfo(n, t, None) for n, t in zip(preview.columns, preview.types, strict=False))
        self.model.set_page(columns, page["rows"], page["offset"])
        fit_columns(self.grid, self.model)
        self.summary.setText("")  # el resumen va en el pie, como en la pestaña de tabla
        self.stack.setCurrentWidget(self.grid if page["rows"] else self.empty)
        if not page["rows"]:
            self.empty.setText(tr("The query returned no rows."))
        else:
            self.grid.selectRow(0)
        self._row_changed(0 if page["rows"] else -1)
        usable = result.statement.replayable and self._coordinator.state is SessionState.READY
        self.export_button.setEnabled(usable)
        self.load_button.setEnabled(usable and self._loader is not None)
        self._update_range(result)

    # -- páginas y total (propietario, 2026-11-06: igual que la pestaña de tabla) ---------------------------

    def _page_of(self, result: StatementResult) -> dict[str, Any]:
        """La página que se muestra de `result`: la primera llega con la ejecución; el total se cuenta aparte
        (solo si había más filas que la página y la consulta se puede repetir)."""
        key = id(result)
        page = self._pages.get(key)
        if page is None:
            preview = result.preview
            assert preview is not None
            total = None if preview.truncated else len(preview.rows)
            page = {"offset": 0, "rows": preview.rows, "total": total}
            self._pages[key] = page
            if total is None and result.statement.replayable:
                self._count(result, page)
        return page

    def _count(self, result: StatementResult, page: dict[str, Any]) -> None:
        def counted(outcome: Any) -> None:
            if self._closed or isinstance(outcome, BaseException):
                return  # sin total: el pie sigue con «de …»
            page["total"] = int(outcome.rows[0][0]) if outcome.rows else 0
            if self.current_result is result:
                self._update_range(result)

        sql = f"SELECT count(*) FROM ({load_sql(result.statement.text)}) AS geoduck_q"
        with contextlib.suppress(GeoDuckError):  # DuckDB ocupado: el pie sigue con «de …»
            self._coordinator.read_rows(sql, 1, counted, database=result.database)

    def _offset(self) -> int:
        result = self.current_result
        page = self._pages.get(id(result)) if result is not None else None
        return page["offset"] if page else 0

    def go(self, offset: int) -> None:
        """‹ ›: otra página del resultado elegido. Repite la consulta con `LIMIT`/`OFFSET`."""
        result = self.current_result
        if result is None or not result.statement.replayable:
            return
        page = self._page_of(result)
        offset = max(0, offset)
        if page["total"] is not None and offset >= page["total"]:
            return

        def read(outcome: Any) -> None:
            if self._closed:
                return
            if isinstance(outcome, BaseException):
                self.notice.emit(getattr(outcome, "message", str(outcome)))
                return
            page["offset"], page["rows"] = offset, outcome.rows
            if self.current_result is result:
                self._show_grid()

        sql = f"SELECT * FROM ({load_sql(result.statement.text)}) AS geoduck_q LIMIT {PAGE} OFFSET {offset}"
        try:
            self._coordinator.read_rows(sql, PAGE, read, database=result.database)
        except GeoDuckError as exc:
            self.notice.emit(exc.message)

    def _update_range(self, result: StatementResult | None) -> None:
        """«Filas 1–100 de 1 000 000 · 0,4 s»; ‹ › solo si hay otra página y la consulta se puede repetir."""
        page = self._pages.get(id(result)) if result is not None else None
        if result is None or page is None:
            self.range_label.setText("")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            return
        shown = len(page["rows"])
        if page["total"] is None and not result.statement.replayable:
            # una escritura (`DELETE … RETURNING`) no se repite: ni se cuenta ni se pasa de página
            text = tr("Rows {} of more than {}").format(f"1–{shown}", _count(shown))
        else:
            text = page_label(page["offset"], shown, page["total"])
        if self._coordinator.is_stale(self._epochs.get(id(result), 0)):
            text += " · " + tr("may be out of date")
        full = f"{text} · {_seconds(result.duration_ms)}"
        self.range_label.setText(text if self.compact else full)
        self.range_label.setToolTip(full)
        ready = result.statement.replayable and self._coordinator.state is SessionState.READY
        self.prev_button.setEnabled(ready and page["offset"] > 0)
        more = shown == PAGE and (page["total"] is None or page["offset"] + shown < page["total"])
        self.next_button.setEnabled(ready and more)

    # -- detalle de la fila -----------------------------------------------------------------------------

    def set_detail_open(self, open_: bool) -> None:
        self.detail_open = open_
        self._row_changed(self.grid.currentIndex().row())

    def _row_changed(self, row: int) -> None:
        visible = (
            self.detail_open
            and 0 <= row < self.model.rowCount()
            and self.stack.currentWidget() is self.grid
            and self.view.current == RESULT
        )
        if not visible:
            self.detail.hide()
            return
        self.detail.show()
        self.detail.show_row(self.model.offset + row + 1, self.model.columns, self.model.rows[row])

    @property
    def current_result(self) -> StatementResult | None:
        tabular = getattr(self, "_tabular", [])
        if not tabular:
            return None
        index = self.result_tabs.currentIndex() if len(tabular) > 1 else len(tabular) - 1
        return tabular[index] if 0 <= index < len(tabular) else None

    def _messages(
        self, text: str, results: list[StatementResult], parse_error: str, parse_offset: int | None
    ) -> None:
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(16, 10, 28, 10)
        box.setSpacing(6)
        self._log: list[tuple[bool, str]] = []
        if parse_error:
            box.addLayout(self._line(False, parse_error, text, parse_offset))
        for result in results:
            if result.status is StatementStatus.SKIPPED:
                continue
            ok = result.status is StatementStatus.OK
            if ok:
                what = result_title(text, result.statement)
                if result.preview is not None:
                    what += " · " + tr("{} rows").format(_count(len(result.preview.rows)))
                message = f"{what} · {_seconds(result.duration_ms)}"
            elif result.status is StatementStatus.CANCELLED:
                message = tr("Cancelled")
            else:
                message = result.message
            box.addLayout(self._line(ok, message, text, None if ok else result.error_offset))
        box.addStretch(1)  # lo que no corrió ya lo dicen la marca «–» y el resumen (#139)
        self.messages.setWidget(body)

    def _line(self, ok: bool, message: str, text: str, offset: int | None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        mark = label("✓" if ok else "✕", None if ok else "error")
        mark.setStyleSheet(f"color: {self.colors.ok}; font-weight: 600;" if ok else "font-weight: 600;")
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        place = ""
        if not ok and offset is not None and 0 <= offset < len(text):
            line, _index = line_index_from(text, offset)
            word = error_token(text, offset, message)
            place = (
                tr("Line {0} · near «{1}»").format(line + 1, word)
                if word
                else tr("Line {0}").format(line + 1)
            )
        body = label(
            f"<b>{_html(place)}</b> · {_html(message)}" if place else message, None if ok else "error"
        )
        if place:
            body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(body, 1)
        self._log.append((ok, message))
        if not ok and offset is not None and 0 <= offset <= len(text):
            line, index = line_index_from(text, offset)
            link = f'<a href="#" style="color: {self.colors.accent}; text-decoration: none;">{tr("Go")}</a>'
            go = label(link, "link")
            go.setTextFormat(Qt.TextFormat.RichText)
            go.linkActivated.connect(lambda _l, ln=line, ix=index: self.go_to(ln, ix))
            row.addWidget(go, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _summarize_messages(self) -> None:
        log = getattr(self, "_log", [])
        errors = sum(not ok for ok, _ in log)
        if not log:
            self.summary.setText("")
        elif errors:
            skipped = sum(r.status is StatementStatus.SKIPPED for r in self.results)
            text = tr("{} OK · {} with error").format(len(log) - errors, errors)
            if skipped:
                text += " · " + tr("{} not run").format(skipped)
            self.summary.setText(text)
        else:
            self.summary.setText(tr("{} OK").format(len(log)))

    def go_to(self, line: int, index: int) -> None:
        """«Ir»: el cursor al lugar del error."""
        self.editor.setCursorPosition(line, index)
        self.editor.ensureLineVisible(line)
        self.editor.setFocus()

    # -- exportar -------------------------------------------------------------------------------------

    def export(self, fmt: ExportFormat) -> None:
        """«Exportar ▾»: la consulta completa del resultado elegido, a CSV o Parquet."""
        result = self.current_result
        if result is None or not result.statement.replayable:
            return
        export_query(
            self._coordinator,
            result.statement.text,
            result.database,
            self.place.name,
            fmt,
            self._ask_path,
            self.notice.emit,
        )
        self.editor.setFocus()  # el teclado vuelve al editor: Ctrl+Enter sigue funcionando (#139)

    def load_in_qgis(self, kind: str) -> None:
        """«Cargar en QGIS ▾»: el resultado elegido como «Copia» o «Conectada» (repite la consulta)."""
        result = self.current_result
        if result is None or not result.statement.replayable or self._loader is None:
            return
        name = result_title(self.run_text, result.statement) if self.run_text else self.place.name
        self._loader(result.statement.text, name, kind, database=result.database)
        self.editor.setFocus()  # el teclado vuelve al editor: Ctrl+Enter sigue funcionando (#139)

    # -- archivo --------------------------------------------------------------------------------------

    def set_sql(self, text: str) -> None:
        """El SQL de «Ver SQL» (pestaña de tabla) en una consulta nueva."""
        self.editor.setText(text)

    @property
    def modified(self) -> bool:
        return self.editor.text() != (self.saved_text or "") if self.place.path else bool(self.editor.text())

    def _text_changed(self) -> None:
        if self.editor.status.shown:  # las marcas eran de otro texto (#139)
            self.editor.status.clear()
            self.error_link.hide()
            self._error_at = None
        self.changed.emit()
        if self.place.path:
            self._autosave.start()

    def save_if_saved(self) -> None:
        if self.place.path and self.modified:
            self._write(self.place.path)

    def save(self) -> bool:
        """Ctrl+S: en su archivo, o «Guardar como…» si aún no tiene."""
        if not self.place.path:
            return self.save_as()
        return self._write(self.place.path)

    def save_as(self) -> bool:
        path = self._ask_path(tr("Save query"), _file_name(self.place.name) + ".sql", tr("SQL files (*.sql)"))
        if not path:
            return False
        if not path.lower().endswith(".sql"):
            path += ".sql"
        if not self._write(path):
            return False
        old = self.place
        self.place = Place(QUERY, Path(path).name, path=path)
        self.renamed.emit(old)
        return True

    def rename(self, name: str) -> str:
        """Doble clic en el nombre de la pestaña (#143, punto 6). Con archivo, el `.sql` se renombra en la
        misma carpeta; sin archivo, solo cambia el nombre (se propone al guardar). Nunca sobrescribe: si ya
        existe un archivo con ese nombre, no cambia nada. Devuelve el motivo si no se pudo, o vacío."""
        name = name.strip()
        if not name or name == self.place.name:
            return ""
        if any(ch in name for ch in '/\\:*?"<>|'):
            return tr("A file name cannot have / \\ : * ? < > | or quotes")
        old = self.place
        if old.path:
            source = Path(old.path)
            target = source.with_name(name if name.lower().endswith(".sql") else name + ".sql")
            same = target.exists() and target.resolve() == source.resolve()  # solo mayúsculas (Windows)
            if target.exists() and not same:
                return tr("«{}» already exists in that folder: the query keeps its name").format(target.name)
            self.save_if_saved()
            try:
                source.rename(target)
            except OSError as exc:
                return tr("The file could not be renamed: {}").format(exc.strerror or str(exc))
            self.place = Place(QUERY, target.name, path=str(target))
        else:
            self.place = Place(QUERY, name)
        self.renamed.emit(old)
        return ""

    def _write(self, path: str) -> bool:
        from geoduck.ui.notebook_store import write_text  # noqa: PLC0415 - escritura atómica (G7)

        text = self.editor.text()
        try:
            write_text(Path(path), text)
        except OSError as exc:
            self.notice.emit(tr("The query could not be saved: {}").format(exc.strerror or str(exc)))
            return False
        self.saved_text = text
        self.changed.emit()
        self.notice.emit(tr("Query saved in {}").format(Path(path).name))
        return True

    def _file_dialog(self, title: str, name: str, pattern: str) -> str:
        folder = str(Path(self.place.path).parent) if self.place.path else str(Path.home())
        if title == tr("Save query") or title == tr("Export"):
            path, _ = QFileDialog.getSaveFileName(self, title, str(Path(folder) / name), pattern)
        else:
            path, _ = QFileDialog.getOpenFileName(self, title, folder, pattern)
        return path

    # -- estado y eventos -----------------------------------------------------------------------------

    def _render_state(self) -> None:
        state = self._coordinator.state
        ready = state is SessionState.READY
        for widget in (self.run_button, self.base):
            widget.setEnabled(ready and self.run is None)
        self.run_all_action.setEnabled(ready and self.run is None)
        running = self.run is not None
        self._escape.setEnabled(running)
        self.stop_button.setEnabled(running and state is SessionState.BUSY)
        for widget in (self.copy_button, self.export_button, self.load_button, self.detail_button):
            widget.setVisible(not running)  # mientras corre no hay filas que copiar ni exportar (#143)
        self.copy_button.setEnabled(self.current_result is not None and self.view.current == RESULT)
        usable = (
            self.current_result is not None
            and self.view.current == RESULT
            and ready
            and self.current_result.statement.replayable
        )
        self.export_button.setEnabled(usable)
        self.load_button.setEnabled(usable and self._loader is not None)
        if hasattr(self, "range_label"):
            self._update_range(self.current_result if self.view.current == RESULT else None)

    def _on_event(self, event: AppEvent) -> None:
        if self._closed:
            return
        if isinstance(event, StatementFinished):
            self._statement(event)
        elif isinstance(event, (ScriptFinished, ScriptRejected)):
            self._finished(event)
        elif isinstance(event, SessionStateChanged):
            if event.current is SessionState.DISCONNECTED:
                self.run = None  # la sesión se cerró: la ejecución no terminará
                self._stop_running()
            self._render_state()
        elif isinstance(event, (ColumnsListed, VocabularyChanged)):
            if self.completer is not None:
                self.completer.refresh()  # llegaron las columnas o las palabras que esperaba la lista
        elif isinstance(event, CatalogChanged):
            with contextlib.suppress(Exception):
                self._coordinator.vocabulary()  # se pide ya, para que el autocompletado lo tenga a tiempo
            self.show_databases(event.catalog)
        elif isinstance(event, PreviewsInvalidated) and self.view.current == RESULT:
            self._show_grid()

    def close_page(self) -> None:
        """La pestaña se cierra: deja de escuchar; lo pendiente se guarda en su archivo."""
        self._closed = True
        self._autosave.stop()
        self.save_if_saved()
        self._unsubscribe()


class _EditorMenu(QObject):
    """Clic derecho en el editor: arriba «▶ Ejecutar · línea N» y «Ejecutar todo (N sentencias)»; debajo, el
    menú de siempre del editor (deshacer, cortar, copiar, pegar…)."""

    def __init__(self, page: QueryPage) -> None:
        super().__init__(page)
        self._page = page
        #: El último menú mostrado (para las pruebas).
        self.menu: QMenu | None = None

    def build(self) -> QMenu:
        page = self._page
        editor = page.editor
        standard = getattr(editor, "createStandardContextMenu", None)
        menu = standard() if standard is not None else None
        if menu is None:
            menu = QMenu(editor)
        first = menu.actions()[0] if menu.actions() else None
        run = QAction(page.run_button.accessibleName() + "\tCtrl+Enter", menu)
        run.setEnabled(page.run_button.isEnabled())
        run.triggered.connect(lambda: page.execute(RunScope.CURRENT))
        menu.insertAction(first, run)
        menu.insertAction(first, page.run_all_action)
        if first is not None:
            menu.insertSeparator(first)
        self.menu = menu
        return menu

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        if event.type() == QEvent.Type.ContextMenu:
            self.build().popup(event.globalPos())
            return True
        return False


def _file_name(title: str) -> str:
    """Nombre de archivo a partir de un título («Consumo por municipio» → «Consumo por municipio»), sin
    caracteres que no admiten los sistemas de archivos."""
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in title).strip(" .")
    return Path(cleaned or "consulta").stem
