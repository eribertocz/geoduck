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

from qgis.PyQt.QtCore import QPoint, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
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
    PreviewsInvalidated,
    ScriptFinished,
    ScriptRejected,
    SessionStateChanged,
    StatementFinished,
)
from geoduck.domain.catalog import CatalogSnapshot, ColumnInfo
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.export import ExportFormat
from geoduck.domain.session import SessionState
from geoduck.domain.sql import DEFAULT_PREVIEW_LIMIT, RunScope, StatementResult, StatementStatus, result_title
from geoduck.ui.i18n import tr
from geoduck.ui.pro import editor as pro_editor
from geoduck.ui.pro.load import export_query, load_menu, popup_under
from geoduck.ui.pro.places import QUERY, Place
from geoduck.ui.pro.table_page import PageModel, TypeHeader, fit_columns
from geoduck.ui.pro.tokens import DARK, METRICS, Colors
from geoduck.ui.pro.widgets import Segmented, button, icon_button, label, spacer
from geoduck.ui.widgets import line_index_from, offset_from

#: Espera tras el último cambio antes de autoguardar en el archivo de la consulta.
AUTOSAVE_MS = 1500
#: Resultado o mensajes.
RESULT, MESSAGES = 0, 1


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
        self.split.addWidget(self.editor)
        self.split.addWidget(self._build_results())
        self.split.setSizes([360, 400])
        box.addWidget(self.split, 1)
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
        self._show_results()

    # -- construcción ---------------------------------------------------------------------------------

    def _build_bar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("pro", "rule-bottom")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(6)
        self.run_button = button(
            tr("Run"),
            "primary",
            icon="play",
            tooltip=tr("Runs the statement under the cursor or the selection"),
        )
        self.run_button.setIcon(self._icon("play", self.colors.on_accent))
        self.run_button.clicked.connect(lambda: self.execute(RunScope.CURRENT))
        row.addWidget(self.run_button)
        row.addWidget(label("Ctrl+Intro", "kbd"), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(6)
        self.all_button = button(tr("All"), tooltip=tr("Runs all the SQL (Ctrl+Shift+Enter)"))
        self.all_button.clicked.connect(lambda: self.execute(RunScope.ALL))
        row.addWidget(self.all_button)
        self.cancel_button = button(tr("Cancel"), "ghost", icon="stop", colors=self.colors)
        self.cancel_button.setToolTip(tr("Stops the running SQL"))
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        row.addWidget(spacer(), 1)
        row.addWidget(label(tr("Database"), "muted"))
        self.base = QComboBox()
        self.base.setAccessibleName(tr("Database of the query"))
        self.base.setToolTip(tr("The query runs in this database"))
        self.base.setMinimumWidth(110)
        self.base.currentIndexChanged.connect(lambda _i: self.changed.emit())
        row.addWidget(self.base)
        self.file_button = icon_button("more", tr("Open, save, save as…"), self.colors)
        self.file_menu = QMenu(self)
        self.file_menu.addAction(tr("Open…") + "\tCtrl+O", self.open_requested.emit)
        self.file_menu.addAction(tr("Save") + "\tCtrl+S", self.save)
        self.file_menu.addAction(tr("Save as…"), self.save_as)
        self.file_button.clicked.connect(
            lambda: self.file_menu.popup(self.file_button.mapToGlobal(QPoint(0, self.file_button.height())))
        )
        row.addWidget(self.file_button)
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
        self.export_button = button(tr("Export"), "ghost", icon="export", colors=self.colors)
        self.export_button.setToolTip(tr("Exports the full query of this result"))
        self.export_menu = QMenu(self)
        self.export_menu.addAction(tr("CSV…"), lambda: self.export(ExportFormat.CSV))
        self.export_menu.addAction(tr("Parquet…"), lambda: self.export(ExportFormat.PARQUET))
        self.export_button.clicked.connect(
            lambda: self.export_menu.popup(
                self.export_button.mapToGlobal(QPoint(0, self.export_button.height()))
            )
        )
        row.addWidget(self.export_button)
        self.load_button = button(tr("Load in QGIS"), "primary", icon="layers", colors=self.colors)
        self.load_button.setToolTip(tr("Loads the full result as a QGIS layer"))
        self.load_menu = load_menu(self, self.colors, self.load_in_qgis)
        self.load_button.clicked.connect(lambda: popup_under(self.load_menu, self.load_button))
        row.addWidget(self.load_button)
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
        box.addWidget(self.stack, 1)
        return panel

    # -- base de la consulta --------------------------------------------------------------------------

    @property
    def database(self) -> str | None:
        return self.base.currentData()

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
        """«Ejecutar» (la sentencia bajo el cursor, o la selección si la hay) o «Todo»."""
        if self._coordinator.state is not SessionState.READY or self.run is not None:
            return
        text = self.editor.text()
        if not text.strip():
            self.notice.emit(tr("There is no SQL to run"))
            return
        cursor, base = 0, 0
        if scope is RunScope.CURRENT and self.editor.hasSelectedText():
            scope = RunScope.SELECTION
            line_from, index_from, _l, _i = self.editor.getSelection()
            base = offset_from(text, line_from, index_from)
            sql = self.editor.selectedText()
        else:
            line, index = self.editor.getCursorPosition()
            cursor = offset_from(text, line, index)
            sql = text
        try:
            run_id = self._coordinator.execute_sql(
                sql,
                scope,
                cursor=cursor,
                base=base,
                preview_limit=DEFAULT_PREVIEW_LIMIT,
                database=self.database,
            )
        except GeoDuckError as exc:
            self.notice.emit(exc.message)
            return
        self.run = Run(run_id, text)
        self.summary.setText(tr("Running…"))
        self._render_state()

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
            self._summarize_messages()
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
            return
        result = tabular[index]
        preview = result.preview
        assert preview is not None
        columns = tuple(ColumnInfo(n, t, None) for n, t in zip(preview.columns, preview.types, strict=False))
        self.model.set_page(columns, preview.rows, 0)
        fit_columns(self.grid, self.model)
        rows = _count(len(preview.rows))
        text = (tr("first {} rows") if preview.truncated else tr("{} rows")).format(rows)
        if self._coordinator.is_stale(self._epochs.get(id(result), 0)):
            text += " · " + tr("may be out of date")
        self.summary.setText(f"{text} · {_seconds(result.duration_ms)}")
        self.stack.setCurrentWidget(self.grid if preview.rows else self.empty)
        if not preview.rows:
            self.empty.setText(tr("The query returned no rows."))
        usable = result.statement.replayable and self._coordinator.state is SessionState.READY
        self.export_button.setEnabled(usable)
        self.load_button.setEnabled(usable and self._loader is not None)

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
        for widget in (self.run_button, self.all_button, self.base):
            widget.setEnabled(ready and self.run is None)
        self.cancel_button.setEnabled(self.run is not None and state is SessionState.BUSY)
        usable = (
            self.current_result is not None
            and self.view.current == RESULT
            and ready
            and self.current_result.statement.replayable
        )
        self.export_button.setEnabled(usable)
        self.load_button.setEnabled(usable and self._loader is not None)

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
        elif isinstance(event, CatalogChanged):
            self.show_databases(event.catalog)
        elif isinstance(event, PreviewsInvalidated) and self.view.current == RESULT:
            self._show_grid()

    def close_page(self) -> None:
        """La pestaña se cierra: deja de escuchar; lo pendiente se guarda en su archivo."""
        self._closed = True
        self._autosave.stop()
        self.save_if_saved()
        self._unsubscribe()


def _file_name(title: str) -> str:
    """Nombre de archivo a partir de un título («Consumo por municipio» → «Consumo por municipio»), sin
    caracteres que no admiten los sistemas de archivos."""
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in title).strip(" .")
    return Path(cleaned or "consulta").stem
