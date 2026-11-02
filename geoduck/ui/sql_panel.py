# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL y resultados (G2; sql-editor-spec §1, §3, §4, §7 P0; GD-SQL-001..005).

Editor: `QgsCodeEditorSQL`, igual en QGIS 3 y 4 (spike G0-B, F-40). Las posiciones se traducen siempre con
(línea, índice en caracteres), nunca con posiciones absolutas de QScintilla, que son bytes (F-41).
"""

from __future__ import annotations

from collections.abc import Callable

from qgis.gui import QgsCodeEditorSQL
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QShortcut,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
from geoduck.domain.session import SessionState
from geoduck.domain.sql import DEFAULT_PREVIEW_LIMIT, PREVIEW_LIMITS, OutputKind, RunScope, StatementStatus
from geoduck.ui.i18n import tr

_STATUS_TEXT = {
    StatementStatus.OK: "OK",
    StatementStatus.FAILED: "Error",
    StatementStatus.CANCELLED: "Cancelada",
    StatementStatus.SKIPPED: "No ejecutada",
}


def offset_from(text: str, line: int, index: int) -> int:
    lines = text.split("\n")
    return sum(len(t) + 1 for t in lines[:line]) + index


def line_index_from(text: str, offset: int) -> tuple[int, int]:
    before = text[:offset]
    line = before.count("\n")
    return line, offset - (before.rfind("\n") + 1)


class ResultView(QWidget):
    """Una pestaña de resultado: siempre etiquetada como vista previa (sql-editor-spec §4)."""

    def __init__(self, event: StatementFinished, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.epoch = event.epoch
        result = event.result
        preview = result.preview
        assert preview is not None
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.table = QTableWidget(len(preview.rows), len(preview.columns))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalHeaderLabels(list(preview.columns))
        for r, row in enumerate(preview.rows):
            for c, value in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem("NULL" if value is None else str(value)))
        more = tr(" (hay más filas)") if preview.truncated else ""
        kind = {
            OutputKind.MUTATION_ROWS: tr(" · resultado de escritura: no se repite al cargar"),
            OutputKind.PLAN: tr(" · plan"),
        }.get(result.output, "")
        self._base_caption = tr("Vista previa") + f" · {len(preview.rows)} " + tr("filas") + more + kind
        self.stale = False
        self._render_caption()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(self.caption)
        layout.addWidget(self.table)

    def mark_stale(self) -> None:
        self.stale = True
        self._render_caption()

    def _render_caption(self) -> None:
        prefix = tr("Posiblemente obsoleta · ") if self.stale else ""
        self.caption.setText(prefix + self._base_caption)


class SqlPanel(QWidget):
    def __init__(
        self,
        coordinator: SessionCoordinator,
        parent: QWidget | None = None,
        *,
        on_message: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._on_message = on_message or (lambda _m: None)
        self._running = False

        self.editor = QgsCodeEditorSQL()
        self.editor.setAccessibleName(tr("Editor SQL"))
        self.run_current_button = QPushButton(tr("Ejecutar sentencia"))
        self.run_current_button.setToolTip(tr("Ejecuta la sentencia bajo el cursor (Ctrl+Intro)"))
        self.run_selection_button = QPushButton(tr("Ejecutar selección"))
        self.run_all_button = QPushButton(tr("Ejecutar todo"))
        self.run_all_button.setToolTip(tr("Ejecuta todo el script, en orden (Ctrl+Mayús+Intro)"))
        self.cancel_button = QPushButton(tr("Cancelar"))
        self.limit_combo = QComboBox()
        for limit in PREVIEW_LIMITS:
            self.limit_combo.addItem(str(limit), limit)
        self.limit_combo.setCurrentIndex(PREVIEW_LIMITS.index(DEFAULT_PREVIEW_LIMIT))
        self.limit_combo.setToolTip(tr("Filas de la vista previa"))

        actions = QHBoxLayout()
        for widget in (self.run_current_button, self.run_selection_button, self.run_all_button):
            actions.addWidget(widget)
        actions.addStretch(1)
        actions.addWidget(QLabel(tr("Vista previa")))
        actions.addWidget(self.limit_combo)
        actions.addWidget(self.cancel_button)

        self.results = QTabWidget()
        self.results.setDocumentMode(True)
        self.log = QTableWidget(0, 5)
        self.log.setHorizontalHeaderLabels(
            [tr("Ejecución"), tr("Sentencia"), tr("Tipo"), tr("Estado"), tr("Detalle")]
        )
        self.log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log.horizontalHeader().setStretchLastSection(True)
        self.results.addTab(self.log, tr("Registro"))

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.editor)
        split.addWidget(self.results)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(actions)
        layout.addWidget(split, 1)

        self.run_current_button.clicked.connect(lambda: self.execute(RunScope.CURRENT))
        self.run_selection_button.clicked.connect(lambda: self.execute(RunScope.SELECTION))
        self.run_all_button.clicked.connect(lambda: self.execute(RunScope.ALL))
        self.cancel_button.clicked.connect(self._coordinator.cancel_current_operation)
        QShortcut(QKeySequence("Ctrl+Return"), self.editor, lambda: self.execute(RunScope.CURRENT))
        QShortcut(QKeySequence("Ctrl+Shift+Return"), self.editor, lambda: self.execute(RunScope.ALL))
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._render(coordinator.state)

    # -- acciones ----------------------------------------------------------------------------------

    def execute(self, scope: RunScope) -> None:
        if self._coordinator.state is not SessionState.READY:
            return
        text = self.editor.text()
        base, cursor = 0, 0
        if scope is RunScope.SELECTION:
            if not self.editor.hasSelectedText():
                return
            line_from, index_from, _l, _i = self.editor.getSelection()
            base = offset_from(text, line_from, index_from)
            text = self.editor.selectedText()
        elif scope is RunScope.CURRENT:
            line, index = self.editor.getCursorPosition()
            cursor = offset_from(text, line, index)
        if not text.strip():
            return
        self.editor.clearWarnings()
        self._clear_results()
        self._running = True
        self._coordinator.execute_sql(
            text, scope, cursor=cursor, base=base, preview_limit=int(self.limit_combo.currentData())
        )

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
            for view in self._result_views():
                if self._coordinator.is_stale(view.epoch):
                    view.mark_stale()
        elif isinstance(event, ScriptFinished):
            self._on_script(event)
        elif isinstance(event, ScriptRejected):
            self._on_message(f"[{event.code.value}] {event.message}")

    def _on_statement(self, event: StatementFinished) -> None:
        self._add_log(event)
        result = event.result
        if result.preview is not None:
            label = f"{result.statement.index + 1} · {result.statement.type}"
            self.results.addTab(ResultView(event), label)
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
        if self.results.count() > 1:
            self.results.setCurrentIndex(self.results.count() - 1)

    def _add_log(self, event: StatementFinished) -> None:
        r = event.result
        row = self.log.rowCount()
        self.log.insertRow(row)
        detail = r.message or (f"{r.duration_ms:.1f} ms" if r.status is StatementStatus.OK else "")
        for col, value in enumerate(
            (
                str(event.run_id),
                str(r.statement.index + 1),
                r.statement.type,
                tr(_STATUS_TEXT[r.status]),
                detail,
            )
        ):
            self.log.setItem(row, col, QTableWidgetItem(value))
        self.log.scrollToBottom()

    def _point_error(self, offset: int, message: str) -> None:
        line, index = line_index_from(self.editor.text(), offset)
        self.editor.addWarning(line, message)
        self.editor.setCursorPosition(line, index)

    def _clear_results(self) -> None:
        while self.results.count() > 1:
            widget = self.results.widget(1)
            self.results.removeTab(1)
            if widget is not None:
                widget.deleteLater()

    def _result_views(self) -> list[ResultView]:
        views = [self.results.widget(i) for i in range(1, self.results.count())]
        return [v for v in views if isinstance(v, ResultView)]

    def _render(self, state: SessionState) -> None:
        ready = state is SessionState.READY
        for button in (self.run_current_button, self.run_selection_button, self.run_all_button):
            button.setEnabled(ready)
        self.cancel_button.setEnabled(state is SessionState.BUSY and self._running)
