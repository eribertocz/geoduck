# SPDX-License-Identifier: GPL-2.0-or-later
"""Pestaña de consulta de Workspace Pro (workspace-pro-spec §5; GD-WSP-004; AT-WSP-005).

Una sola barra fina: «▶ Ejecutar» (la sentencia bajo el cursor o la selección, Ctrl+Intro), «Todo»
(Ctrl+Mayús+Intro), «Cancelar», la base de la consulta y «⋯» (abrir, guardar, guardar como). Debajo, el
editor SQL de QGIS (con el autocompletado de G6 y los colores de GeoDuck) y el resultado, con un divisor que
se arrastra: **Resultado** (la grilla de E3; una pestaña por sentencia con tabla, sin pestañas si es una) y
**Mensajes** (✓ o ✕ por sentencia, con la línea y la columna del error e «Ir»). «Exportar ▾» exporta la
consulta completa del resultado elegido.

El SQL se ejecuta por el coordinador (`execute_sql`, con la base de la consulta); esta página solo muestra.
Guardar escribe el SQL tal cual en un `.sql`; una consulta con archivo se autoguarda tras cada cambio.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qgis.PyQt.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QKeySequence
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
from geoduck.domain.sql import RunScope, StatementResult, StatementStatus, result_title
from geoduck.domain.sql_text import load_sql
from geoduck.domain.statements import current_span, statement_spans
from geoduck.ui.i18n import tr
from geoduck.ui.pro import editor as pro_editor
from geoduck.ui.pro.load import export_menu, export_query, load_menu, popup_under
from geoduck.ui.pro.places import QUERY, Place
from geoduck.ui.pro.table_page import DetailPanel, PageModel, TypeHeader, fit_columns, tighten
from geoduck.ui.pro.tokens import DARK, METRICS, Colors
from geoduck.ui.pro.widgets import Segmented, button, icon_button, label, spacer
from geoduck.ui.widgets import line_index_from, offset_from

#: Espera tras el último cambio antes de autoguardar en el archivo de la consulta.
AUTOSAVE_MS = 1500
#: Resultado o mensajes.
RESULT, MESSAGES = 0, 1
#: Espera tras mover el cursor o escribir antes de volver a marcar la sentencia que correrá.
MARK_MS = 60


def _seconds(ms: float) -> str:
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.2f} s".replace(".", ",")


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
        self.saved_text = sql if place.path else None  # lo que hay en el archivo
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self._build_bar())
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setHandleWidth(1)
        self.split.setChildrenCollapsible(False)
        self.editor = pro_editor.make(colors, dark=colors is DARK)
        self.editor.setAccessibleName(tr("SQL editor"))
        self.editor.setText(sql)
        self.editor.textChanged.connect(self._text_changed)
        self.editor.layer_drops.on_files = self.drop_files
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
        for keys, slot in (
            ("Ctrl+Return", lambda: self.execute(RunScope.CURRENT)),
            ("Ctrl+Enter", lambda: self.execute(RunScope.CURRENT)),
            ("Ctrl+Shift+Return", lambda: self.execute(RunScope.ALL)),
            ("Ctrl+Shift+Enter", lambda: self.execute(RunScope.ALL)),
            ("Ctrl+S", self.save),
        ):  # Ctrl+O es del workspace (abre en una pestaña nueva)
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        self.show_databases(coordinator.catalog, database)
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._render_state()
        self.mark_statement()
        self._show_results()

    # -- construcción ---------------------------------------------------------------------------------

    def _build_bar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("pro", "rule-bottom")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(6)
        # Un solo «Ejecutar» (propietario, 2026-11-06): la selección o la sentencia marcada; «Ejecutar todo»
        # un paso atrás (Ctrl+Mayús+Intro y el menú «⋯»). El texto y la marca dicen qué correrá.
        self.run_button = button(tr("Run"), "primary", icon="play")
        self.run_button.setIcon(self._icon("play", self.colors.on_accent))
        self.run_button.clicked.connect(lambda: self.execute(RunScope.CURRENT))
        row.addWidget(self.run_button)
        self.kbd_label = label("Ctrl+Intro", "kbd")
        row.addWidget(self.kbd_label, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(6)
        self.cancel_button = button(tr("Cancel"), "ghost", icon="stop", colors=self.colors)
        self.cancel_button.setToolTip(tr("Stops the running SQL"))
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        row.addWidget(spacer(), 1)
        self.runs_in_label = label(tr("Runs in"), "muted")
        row.addWidget(self.runs_in_label)
        self.base = QComboBox()
        self.base.setAccessibleName(tr("Database of the query"))
        self.base.setToolTip(tr("«Run» runs the SQL in this database"))
        self.base.setMinimumWidth(110)
        self.base.currentIndexChanged.connect(lambda _i: self.changed.emit())
        row.addWidget(self.base)
        # «Ejecutar todo»: Ctrl+Mayús+Intro y el clic derecho del editor (abrir y guardar están junto a las
        # pestañas: el archivo arriba, la ejecución aquí; propietario, 2026-11-06)
        self.run_all_action = QAction(tr("Run all") + "\tCtrl+Shift+Enter", self)
        self.run_all_action.triggered.connect(lambda: self.execute(RunScope.ALL))
        return bar

    def _icon(self, name: str, color: str) -> Any:
        from geoduck.ui.pro import icons  # noqa: PLC0415

        return icons.icon(name, color)

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
        row.addWidget(spacer(), 1)
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
        """El pie del resultado, igual que el de la pestaña de tabla: «Filas 1–100 de N · tiempo», ‹ ›,
        «Exportar» y «Cargar en QGIS» (propietario, 2026-11-06)."""
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
        self.export_button = button(tr("Export"), "ghost", icon="export", colors=self.colors)
        self.export_button.setToolTip(tr("Exports the full query of this result"))
        self.export_menu = export_menu(self, self.export)
        self.export_button.clicked.connect(lambda: popup_under(self.export_menu, self.export_button))
        row.addWidget(self.export_button)
        self.load_button = button(tr("Load in QGIS"), "primary", icon="layers", colors=self.colors)
        self.load_button.setToolTip(tr("Loads the full result as a QGIS layer"))
        self.load_menu = load_menu(self, self.colors, self.load_in_qgis, more=True)
        self.load_button.clicked.connect(lambda: popup_under(self.load_menu, self.load_button))
        row.addWidget(self.load_button)
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
        if self._coordinator.state is not SessionState.READY or self.run is not None:
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
        self.summary.setText(tr("Running…"))
        self._render_state()

    def set_compact(self, compact: bool) -> None:
        """Modo compacto (panel acoplado o ventana angosta; propietario, 2026-11-07): ▶ sin texto, ■, la base
        sin «Se ejecuta en»; «Exportar» y «Cargar en QGIS» como íconos; el detalle de la fila, cerrado. Todo
        sigue ahí, con su tooltip."""
        self.compact = compact
        self.kbd_label.setVisible(not compact)
        self.runs_in_label.setVisible(not compact)
        self.base.setMinimumWidth(80 if compact else 110)
        for widget, text in (
            (self.cancel_button, tr("Cancel")),
            (self.export_button, tr("Export")),
            (self.load_button, tr("Load in QGIS")),
        ):
            widget.setText("" if compact else text)
            widget.setAccessibleName(text)
        self.detail_button.setChecked(not compact)
        tighten(self.range_label.parentWidget().layout(), compact, (16, 0, 16, 0), 10)
        tighten(self.run_button.parentWidget().layout(), compact, (12, 8, 12, 8), 6)
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
        self._context = _EditorMenu(self)
        editor.viewport().installEventFilter(self._context)

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
        # en el modo compacto, solo el ícono ▶ (propietario, 2026-11-07); el texto va al tooltip
        self.run_button.setText("" if self.compact else what)
        self.run_button.setAccessibleName(what)
        tips = [
            tr("Ctrl+Enter: runs the selection or, without one, the marked statement"),
            tr("Ctrl+Shift+Enter: runs all ({} statements)").format(count),
        ]
        self.run_button.setToolTip("\n".join([what, *tips] if self.compact else tips))
        self.run_all_action.setText(tr("Run all ({} statements)").format(count) + "\tCtrl+Shift+Enter")

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
            self._messages(run.text, self.results, event.run.parse_error, event.run.parse_error_offset)
        else:
            self.results = []
            self._messages(run.text, [], event.message, None)
        self.run = None
        self.run_text = run.text
        self._show_results(run.text)
        self._render_state()

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
        failed = any(r.status in (StatementStatus.FAILED, StatementStatus.CANCELLED) for r in self.results)
        if tabular and not failed:
            self.result_tabs.setCurrentIndex(len(tabular) - 1)
            self.view.set_current(RESULT)
        elif self.results or failed:
            self.view.set_current(MESSAGES if (failed or not tabular) else RESULT)
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
        skipped = sum(r.status is StatementStatus.SKIPPED for r in results)
        if skipped:
            text_skipped = (
                tr("1 statement was not run after the error")
                if skipped == 1
                else tr("{} statements were not run after the error").format(skipped)
            )
            box.addWidget(label(text_skipped, "muted"))
        box.addStretch(1)
        self.messages.setWidget(body)

    def _line(self, ok: bool, message: str, text: str, offset: int | None) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        mark = label("✓" if ok else "✕", None if ok else "error")
        mark.setStyleSheet(f"color: {self.colors.ok}; font-weight: 600;" if ok else "font-weight: 600;")
        row.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
        body = label(message, None if ok else "error")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(body, 1)
        self._log.append((ok, message))
        if offset is not None and 0 <= offset <= len(text):
            line, index = line_index_from(text, offset)
            where = tr("line {}, column {}").format(line + 1, index + 1)
            link = f'<a href="#" style="color: {self.colors.accent}; text-decoration: none;">{tr("Go")}</a>'
            go = label(f'<span style="color: {self.colors.muted};">{where}</span> · {link}', "link")
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
            self.summary.setText(tr("{} OK · {} with error").format(len(log) - errors, errors))
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

    def load_in_qgis(self, kind: str) -> None:
        """«Cargar en QGIS ▾»: el resultado elegido como «Copia» o «Conectada» (repite la consulta)."""
        result = self.current_result
        if result is None or not result.statement.replayable or self._loader is None:
            return
        name = result_title(self.run_text, result.statement) if self.run_text else self.place.name
        self._loader(result.statement.text, name, kind, database=result.database)

    # -- archivo --------------------------------------------------------------------------------------

    def set_sql(self, text: str) -> None:
        """El SQL de «Ver SQL» (pestaña de tabla) en una consulta nueva."""
        self.editor.setText(text)

    @property
    def modified(self) -> bool:
        return self.editor.text() != (self.saved_text or "") if self.place.path else bool(self.editor.text())

    def _text_changed(self) -> None:
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
        self.cancel_button.setEnabled(self.run is not None and state is SessionState.BUSY)
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
        run = QAction(page.run_button.text() + "\tCtrl+Enter", menu)
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
