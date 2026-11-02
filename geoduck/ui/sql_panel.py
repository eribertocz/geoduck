# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL, resultados y registro (G2; sql-editor-spec §1, §3, §4, §7 P0; GD-SQL-001..005).

Tres zonas en un divisor vertical que el usuario redimensiona: editor, resultados y registro. Controles
nativos de QGIS (iconos del tema, `QgsCodeEditorSQL`), iguales en QGIS 3 y 4.

Editor: `QgsCodeEditorSQL` (spike G0-B, F-40). Las posiciones se traducen siempre con (línea, índice en
caracteres), nunca con posiciones absolutas de QScintilla, que son bytes (F-41).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsApplication
from qgis.gui import QgsCodeEditorSQL
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QKeySequence
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QShortcut,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    AppEvent,
    PreviewsInvalidated,
    ScriptFinished,
    ScriptRejected,
    SessionStateChanged,
    StatementFinished,
)
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.session import SessionState
from geoduck.domain.sql import (
    DEFAULT_PREVIEW_LIMIT,
    PREVIEW_LIMITS,
    OutputKind,
    Preview,
    RunScope,
    SqlStatement,
    StatementStatus,
    result_title,
)
from geoduck.ui.i18n import tr
from geoduck.ui.widgets import secondary, secondary_color

_STATUS_TEXT = {
    StatementStatus.OK: "OK",
    StatementStatus.FAILED: "Error",
    StatementStatus.CANCELLED: "Cancelada",
    StatementStatus.SKIPPED: "No ejecutada",
}
_MAX_COLUMN_WIDTH = 260


def offset_from(text: str, line: int, index: int) -> int:
    lines = text.split("\n")
    return sum(len(t) + 1 for t in lines[:line]) + index


def line_index_from(text: str, offset: int) -> tuple[int, int]:
    before = text[:offset]
    line = before.count("\n")
    return line, offset - (before.rfind("\n") + 1)


def _section(title: str, body: QWidget, trailing: QWidget | None = None) -> QWidget:
    """Zona del divisor con un encabezado discreto: separa editor, resultados y registro."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 6, 0, 0)
    layout.setSpacing(4)
    header = QHBoxLayout()
    label = QLabel(title)
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    header.addWidget(label)
    header.addStretch(1)
    if trailing is not None:
        header.addWidget(trailing)
    layout.addLayout(header)
    layout.addWidget(body, 1)
    return box


def _tool_button(icon: str, text: str, tip: str) -> QToolButton:
    button = QToolButton()
    button.setIcon(QgsApplication.getThemeIcon(icon))
    button.setText(text)
    button.setToolTip(tip)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setAutoRaise(True)
    return button


class ResultView(QWidget):
    """Una pestaña de resultado: siempre etiquetada como vista previa (sql-editor-spec §4)."""

    def __init__(self, event: StatementFinished, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.epoch = event.epoch
        self.title = title
        result = event.result
        preview = result.preview
        assert preview is not None
        self.statement = result.statement
        self.table = self._build_table(preview)

        parts = [tr("Vista previa"), f"{len(preview.rows)} " + tr("filas")]
        if preview.truncated:
            parts.append(tr("hay más"))
        if result.output is OutputKind.MUTATION_ROWS:
            parts.append(tr("resultado de escritura: no se repite al cargar"))
        elif result.output is OutputKind.PLAN:
            parts.append(tr("plan de ejecución"))
        self.caption = secondary(QLabel(" · ".join(parts)))
        self.caption.setWordWrap(False)
        self.stale_label = QLabel(tr("Posiblemente obsoleta"))
        italic = QFont(self.stale_label.font())
        italic.setItalic(True)
        self.stale_label.setFont(italic)
        self.stale_label.setToolTip(
            tr(
                "Después de esta vista previa se ejecutó algo que pudo cambiar estructura o datos. "
                "GeoDuck no detecta cambios hechos fuera de la sesión."
            )
        )
        self.stale_label.hide()
        self.load_button = _tool_button(
            "mActionAddLayer.svg", tr("Cargar en QGIS"), tr("Carga el resultado completo como capa de QGIS")
        )
        self.load_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.loadable = self.statement.replayable
        if not self.loadable:
            self.load_button.setToolTip(
                tr("Solo se pueden cargar consultas de lectura: esta sentencia no se repite")
            )
        caption_row = QHBoxLayout()
        caption_row.addWidget(self.caption)
        caption_row.addStretch(1)
        caption_row.addWidget(self.stale_label)
        caption_row.addWidget(self.load_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(caption_row)
        layout.addWidget(self.table, 1)

    def _build_table(self, preview: Preview) -> QTableWidget:
        table = QTableWidget(len(preview.rows), len(preview.columns))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(table.fontMetrics().height() + 8)
        table.setHorizontalHeaderLabels(list(preview.columns))
        for c, kind in enumerate(preview.types):
            header = table.horizontalHeaderItem(c)
            if header is not None:
                header.setToolTip(kind)
        null_font = QFont(table.font())
        null_font.setItalic(True)
        numeric = {i for i, kind in enumerate(preview.types) if _is_numeric(kind)}
        for r, row in enumerate(preview.rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem("NULL" if value is None else str(value))
                if value is None:
                    item.setFont(null_font)
                    item.setForeground(secondary_color(self))
                if c in numeric:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        for c in range(table.columnCount()):
            table.setColumnWidth(c, min(table.columnWidth(c), _MAX_COLUMN_WIDTH))
        return table

    @property
    def stale(self) -> bool:
        return not self.stale_label.isHidden()

    def mark_stale(self) -> None:
        self.stale_label.show()


def _is_numeric(kind: str) -> bool:
    base = kind.split("(", maxsplit=1)[0].upper()
    return base in {
        "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
        "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL",
    }  # fmt: skip


class SqlPanel(QWidget):
    def __init__(
        self,
        coordinator: SessionCoordinator,
        parent: QWidget | None = None,
        *,
        on_message: Callable[[str], None] | None = None,
        load_flow: Any = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._load_flow = load_flow
        self._on_message = on_message or (lambda _m: None)
        self._running = False
        self._run_text = ""
        self._statements: dict[tuple[int, int], SqlStatement] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(self._build_actions())
        self.editor = QgsCodeEditorSQL()
        self.editor.setAccessibleName(tr("Editor SQL"))
        self.editor.setMinimumHeight(60)
        self._build_results()
        self._build_log()
        # Divisor: editor | resultados | registro, redimensionable por el usuario.
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(_section(tr("Editor"), self.editor))
        self.splitter.addWidget(_section(tr("Resultados"), self.results_stack))
        self.splitter.addWidget(_section(tr("Registro"), self.log))
        for index, stretch in enumerate((3, 5, 2)):
            self.splitter.setStretchFactor(index, stretch)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        layout.addWidget(self.splitter, 1)

        self.run_current_button.clicked.connect(lambda: self.execute(RunScope.CURRENT))
        self.run_selection_button.clicked.connect(lambda: self.execute(RunScope.SELECTION))
        self.run_all_button.clicked.connect(lambda: self.execute(RunScope.ALL))
        self.cancel_button.clicked.connect(self._coordinator.cancel_current_operation)
        self.log.cellDoubleClicked.connect(self._select_logged_statement)
        QShortcut(QKeySequence("Ctrl+Return"), self.editor, lambda: self.execute(RunScope.CURRENT))
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self.editor, lambda: self.execute(RunScope.ALL))
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._render(coordinator.state)

    # -- construcción ------------------------------------------------------------------------------

    def _build_actions(self) -> QHBoxLayout:
        self.run_current_button = _tool_button(
            "mActionStart.svg", tr("Sentencia"), tr("Ejecuta la sentencia bajo el cursor (Ctrl+Intro)")
        )
        self.run_selection_button = _tool_button(
            "mActionRunSelected.svg", tr("Selección"), tr("Ejecuta solo el texto seleccionado")
        )
        self.run_all_button = _tool_button(
            "mActionPlay.svg", tr("Todo"), tr("Ejecuta todo el script, en orden (Ctrl+Mayús+Intro)")
        )
        self.cancel_button = _tool_button(
            "mActionStop.svg", tr("Cancelar"), tr("Cancela la ejecución en curso")
        )
        self.limit_combo = QComboBox()
        for limit in PREVIEW_LIMITS:
            self.limit_combo.addItem(str(limit), limit)
        self.limit_combo.setCurrentIndex(PREVIEW_LIMITS.index(DEFAULT_PREVIEW_LIMIT))
        self.limit_combo.setToolTip(tr("Filas de cada vista previa"))
        actions = QHBoxLayout()
        actions.setSpacing(2)
        for widget in (self.run_current_button, self.run_selection_button, self.run_all_button):
            actions.addWidget(widget)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        actions.addWidget(separator)
        actions.addWidget(self.cancel_button)
        actions.addStretch(1)
        actions.addWidget(secondary(QLabel(tr("Filas"))))
        actions.addWidget(self.limit_combo)
        return actions

    def _build_results(self) -> None:
        self.results = QTabWidget()
        self.results.setDocumentMode(True)
        self.results.setUsesScrollButtons(True)
        self.results.setElideMode(Qt.TextElideMode.ElideRight)
        self.empty_results = secondary(
            QLabel(tr("Sin resultados todavía. Ejecute una consulta (Ctrl+Intro)."))
        )
        self.empty_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.empty_results)
        self.results_stack.addWidget(self.results)
        self.results_stack.setMinimumHeight(60)

    def _build_log(self) -> None:
        self.log = QTableWidget(0, 6)
        self.log.setHorizontalHeaderLabels(
            [tr("Ejec."), tr("#"), tr("Resultado"), tr("Estado"), tr("Duración"), tr("Mensaje")]
        )
        self.log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.log.setAlternatingRowColors(True)
        self.log.verticalHeader().hide()
        self.log.verticalHeader().setDefaultSectionSize(self.log.fontMetrics().height() + 6)
        header = self.log.horizontalHeader()
        header.setStretchLastSection(True)
        for col in range(5):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.log.setToolTip(tr("Doble clic para seleccionar la sentencia en el editor"))
        self.log.setMinimumHeight(48)

    # -- acciones ----------------------------------------------------------------------------------

    def execute(self, scope: RunScope) -> None:
        if self._coordinator.state is not SessionState.READY:
            return
        full_text = self.editor.text()
        text, base, cursor = full_text, 0, 0
        if scope is RunScope.SELECTION:
            if not self.editor.hasSelectedText():
                return
            line_from, index_from, _l, _i = self.editor.getSelection()
            base = offset_from(full_text, line_from, index_from)
            text = self.editor.selectedText()
        elif scope is RunScope.CURRENT:
            line, index = self.editor.getCursorPosition()
            cursor = offset_from(full_text, line, index)
        if not text.strip():
            return
        self.editor.clearWarnings()
        self._clear_results()
        self._run_text = full_text
        self._running = True
        try:
            self._coordinator.execute_sql(
                text, scope, cursor=cursor, base=base, preview_limit=int(self.limit_combo.currentData())
            )
        except GeoDuckError as exc:  # p. ej. DETACH con capas Conectadas sin guardar (§5.5)
            self._running = False
            self._on_message(exc.message)

    def detach(self) -> None:
        self._unsubscribe()

    # -- eventos -----------------------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, SessionStateChanged):
            if event.current is not SessionState.BUSY:
                self._running = False
            self._render(event.current)
        elif isinstance(event, StatementFinished):
            self._on_statement(event)
        elif isinstance(event, PreviewsInvalidated):
            for view in self.result_views():
                if self._coordinator.is_stale(view.epoch):
                    view.mark_stale()
        elif isinstance(event, ScriptFinished):
            self._on_script(event)
        elif isinstance(event, ScriptRejected):
            self._on_message(f"[{event.code.value}] {event.message}")

    def _on_statement(self, event: StatementFinished) -> None:
        result = event.result
        title = result_title(self._run_text, result.statement)
        self._statements[(event.run_id, result.statement.index)] = result.statement
        self._add_log(event, title)
        if result.preview is not None:
            view = ResultView(event, title)
            view.load_button.clicked.connect(lambda _c=False, v=view: self._load(v))
            view.load_button.setEnabled(view.loadable and self._coordinator.state is SessionState.READY)
            index = self.results.addTab(view, f"{result.statement.index + 1} · {title}")
            self.results.setTabToolTip(index, result.statement.text.strip()[:500])
            self.results_stack.setCurrentWidget(self.results)
        if result.status is StatementStatus.FAILED and result.error_offset is not None:
            self._point_error(result.error_offset, result.message)

    def _on_script(self, event: ScriptFinished) -> None:
        run = event.run
        if run.parse_error:
            self._on_message(tr("Error de sintaxis: no se ejecutó nada.") + f" {run.parse_error}")
            if run.parse_error_offset is not None:
                self._point_error(run.parse_error_offset, run.parse_error)
        elif run.failed:
            failed = next(r for r in run.results if r.status is not StatementStatus.OK)
            code = failed.error_code.value if failed.error_code else ""
            self._on_message(f"[{code}] {failed.message}")
        if self.results.count():
            self.results.setCurrentIndex(self.results.count() - 1)

    def _add_log(self, event: StatementFinished, title: str) -> None:
        r = event.result
        row = self.log.rowCount()
        self.log.insertRow(row)
        duration = (
            f"{r.duration_ms:.0f} ms" if r.status in (StatementStatus.OK, StatementStatus.FAILED) else ""
        )
        values = (
            str(event.run_id),
            str(r.statement.index + 1),
            title,
            tr(_STATUS_TEXT[r.status]),
            duration,
            r.message,
        )
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 5:
                item.setToolTip(value)
            if col in (0, 1, 4):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if r.status is StatementStatus.FAILED:
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
            item.setData(Qt.ItemDataRole.UserRole, (event.run_id, r.statement.index))
            self.log.setItem(row, col, item)
        self.log.scrollToBottom()

    def _select_logged_statement(self, row: int, _column: int) -> None:
        """Navegación: doble clic en el registro selecciona la sentencia en el editor."""
        item = self.log.item(row, 0)
        key = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        statement = self._statements.get(tuple(key)) if key else None
        text = self.editor.text()
        if statement is None or statement.end > len(text):
            return
        start = statement.start + len(statement.text) - len(statement.text.lstrip())
        self.editor.setSelection(*line_index_from(text, start), *line_index_from(text, statement.end))
        self.editor.setFocus()

    def _point_error(self, offset: int, message: str) -> None:
        line, index = line_index_from(self.editor.text(), offset)
        self.editor.addWarning(line, message)
        self.editor.setCursorPosition(line, index)

    def _clear_results(self) -> None:
        while self.results.count():
            widget = self.results.widget(0)
            self.results.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self.results_stack.setCurrentWidget(self.empty_results)

    def _load(self, view: ResultView) -> None:
        if self._load_flow is not None and view.loadable:
            self._load_flow.start(view.statement.text, view.title)

    def result_views(self) -> list[ResultView]:
        views = [self.results.widget(i) for i in range(self.results.count())]
        return [v for v in views if isinstance(v, ResultView)]

    def _render(self, state: SessionState) -> None:
        ready = state is SessionState.READY
        for button in (self.run_current_button, self.run_selection_button, self.run_all_button):
            button.setEnabled(ready)
        loading = self._load_flow is not None and self._load_flow.loading
        self.cancel_button.setEnabled(state is SessionState.BUSY and (self._running or loading))
        for view in self.result_views():
            view.load_button.setEnabled(view.loadable and ready and self._load_flow is not None)
