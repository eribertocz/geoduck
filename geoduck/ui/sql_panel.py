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
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont, QKeySequence, QResizeEvent
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
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
from geoduck.domain.load import LoadMode
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
from geoduck.ui.load_dialog import OPTIONS
from geoduck.ui.widgets import secondary, secondary_color

_STATUS_TEXT = {
    StatementStatus.OK: "OK",
    StatementStatus.FAILED: "Error",
    StatementStatus.CANCELLED: "Cancelada",
    StatementStatus.SKIPPED: "No ejecutada",
}
_MAX_COLUMN_WIDTH = 260
_STATUS_ROLE = int(Qt.ItemDataRole.UserRole) + 1
#: Filtros del registro: todas las filas, solo OK, solo Error (ui-ux-spec §8).
LOG_FILTERS = ("all", "ok", "error")


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
        # «Cargar en QGIS ▾» (ui-ux-spec §8): clic = diálogo de G4; flecha = las tres modalidades
        self.load_button = _tool_button(
            "mActionAddLayer.svg", tr("Cargar en QGIS"), tr("Carga el resultado completo como capa de QGIS")
        )
        self.load_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.load_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.load_menu = QMenu(self.load_button)
        self.load_menu.setToolTipsVisible(True)
        self.load_button.setMenu(self.load_menu)
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
        # Tipo por columna (ui-ux-spec §8, AT-UX-007): «#» numérica, «Aa» texto; el tipo exacto, en la ayuda
        table.setHorizontalHeaderLabels(
            [column_header(name, kind) for name, kind in zip(preview.columns, preview.types, strict=True)]
        )
        for c, kind in enumerate(preview.types):
            header = table.horizontalHeaderItem(c)
            if header is not None:
                header.setToolTip(kind)
                header.setData(Qt.ItemDataRole.AccessibleTextRole, f"{preview.columns[c]}, {kind}")
        null_font = QFont(table.font())
        null_font.setItalic(True)
        numeric = {i for i, kind in enumerate(preview.types) if _is_numeric(kind)}
        for r, row in enumerate(preview.rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem("NULL" if value is None else str(value))
                if value is None:  # NULL ≠ "" y ≠ el texto 'NULL': cursiva atenuada y su propia ayuda
                    item.setFont(null_font)
                    item.setForeground(secondary_color(self))
                    item.setToolTip(tr("NULL: sin valor"))
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, tr("NULL, sin valor"))
                elif value == "":
                    item.setToolTip(tr("Cadena vacía"))
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, tr("cadena vacía"))
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


def column_header(name: str, kind: str) -> str:
    if _is_numeric(kind):
        return f"# {name}"
    if _is_text(kind):
        return f"Aa {name}"
    return name


def _is_text(kind: str) -> bool:
    return kind.split("(", maxsplit=1)[0].upper() in {"VARCHAR", "TEXT", "STRING", "CHAR", "BPCHAR"}


def _is_numeric(kind: str) -> bool:
    base = kind.split("(", maxsplit=1)[0].upper()
    return base in {
        "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
        "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL",
    }  # fmt: skip


class SqlPanel(QWidget):
    #: (todas, OK, Error) del registro, al cambiar.
    log_counts_changed = pyqtSignal(int, int, int)
    #: Filtro del registro elegido («all», «ok», «error»).
    log_filter_changed = pyqtSignal(str)

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
        # La fila de acciones no impone su ancho con texto: si no cabe, se compacta (resizeEvent)
        self.actions_bar = QWidget()
        self.actions_bar.setLayout(self._build_actions())
        self.actions_bar.layout().setContentsMargins(0, 0, 0, 0)
        self._wide_width = self.actions_bar.sizeHint().width()  # con texto
        self.set_compact(True)
        self.actions_bar.setMinimumWidth(self.actions_bar.sizeHint().width())  # el mínimo: solo iconos
        self.set_compact(False)
        layout.addWidget(self.actions_bar)
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
        self.log_section = _section(tr("Registro"), self.log, self._build_log_filters())
        self.splitter.addWidget(self.log_section)
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
        # Atajos solo con el foco dentro del panel SQL, nunca en el resto de QGIS (§8, AT-UX-013)
        self.shortcuts = []
        for keys, scope in (("Ctrl+Return", RunScope.CURRENT), ("Ctrl+Shift+Return", RunScope.ALL)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda s=scope: self.execute(s))
            self.shortcuts.append(shortcut)
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._render(coordinator.state)

    # -- construcción ------------------------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self.set_compact(event.size().width() < self._wide_width)

    def set_compact(self, compact: bool) -> None:
        """Panel estrecho: los botones quedan solo con icono (con su ayuda y nombre accesible); nunca se
        quita una acción (ui-ux-spec §8)."""
        style = (
            Qt.ToolButtonStyle.ToolButtonIconOnly if compact else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        for button in self.action_buttons:
            button.setToolButtonStyle(style)
        self.limit_label.setVisible(not compact)
        self.compact = compact

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
        self.action_buttons = (
            self.run_current_button,
            self.run_selection_button,
            self.run_all_button,
            self.cancel_button,
        )
        for button in self.action_buttons:
            button.setAccessibleName(button.text())
        self.compact = False
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
        self.limit_label = secondary(QLabel(tr("Filas")))
        actions.addWidget(self.limit_label)
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

    def _build_log_filters(self) -> QWidget:
        """Todo / OK / Error con su número (ui-ux-spec §8, AT-UX-009). Filtrar oculta filas, no las borra."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.log_filter_group = QButtonGroup(box)
        self.log_filter_group.setExclusive(True)
        self.log_filter_buttons: dict[str, QToolButton] = {}
        for key in LOG_FILTERS:
            button = QToolButton()
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setObjectName(f"geoduckLogFilter_{key}")
            self.log_filter_group.addButton(button)
            self.log_filter_buttons[key] = button
            button.clicked.connect(lambda _c=False, k=key: self.set_log_filter(k))
            row.addWidget(button)
        self.log_filter = "all"
        self.log_filter_buttons["all"].setChecked(True)
        self._update_log_counts()
        return box

    def dock_log(self, tabs: QTabWidget | None) -> None:
        """Dónde va el registro: con `tabs` (panel acoplado), en su propia pestaña; sin ellas (ventana), como
        tercera zona del divisor, debajo del editor y los resultados (plegable). El mismo widget."""
        if tabs is None:
            self.splitter.addWidget(self.log_section)  # addWidget lo saca de la pestaña
            self.splitter.setStretchFactor(2, 2)
            self.splitter.setCollapsible(2, True)
        else:
            tabs.insertTab(2, self.log_section, tr("Registro"))

    def log_counts(self) -> tuple[int, int, int]:
        """(todas, OK, Error) del registro."""
        statuses = [self._row_status(r) for r in range(self.log.rowCount())]
        return len(statuses), statuses.count("ok"), statuses.count("error")

    def _row_status(self, row: int) -> str:
        item = self.log.item(row, 3)
        if item is None:
            return "other"
        status = item.data(_STATUS_ROLE)
        if status is StatementStatus.OK:
            return "ok"
        if status is StatementStatus.FAILED:
            return "error"
        return "other"  # cancelada o no ejecutada: solo en «Todo»

    def set_log_filter(self, key: str) -> None:
        if key not in LOG_FILTERS:
            key = "all"
        self.log_filter = key
        self.log_filter_buttons[key].setChecked(True)
        for row in range(self.log.rowCount()):
            self.log.setRowHidden(row, key != "all" and self._row_status(row) != key)
        self.log_filter_changed.emit(key)

    def _update_log_counts(self) -> None:
        total, ok, errors = self.log_counts()
        for key, text, number in (
            ("all", tr("Todo"), total),
            ("ok", tr("OK"), ok),
            ("error", tr("Error"), errors),
        ):
            button = self.log_filter_buttons[key]
            button.setText(f"{text} ({number})")
            button.setAccessibleName(f"{text}: {number}")
        self.log_counts_changed.emit(total, ok, errors)

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
            view.load_menu.aboutToShow.connect(lambda v=view: self._fill_load_menu(v))
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
            if col == 5:  # mensaje completo: ayuda y nombre accesible (AT-UX-009)
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.AccessibleTextRole, value)
            if col in (0, 1, 4):
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if r.status is StatementStatus.FAILED:
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
            item.setData(Qt.ItemDataRole.UserRole, (event.run_id, r.statement.index))
            item.setData(_STATUS_ROLE, r.status)
            self.log.setItem(row, col, item)
        self.log.setRowHidden(row, self.log_filter != "all" and self._row_status(row) != self.log_filter)
        self._update_log_counts()
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

    def _load(self, view: ResultView, mode: LoadMode | None = None) -> None:
        if self._load_flow is not None and view.loadable:
            self._load_flow.start(view.statement.text, view.title, mode=mode)

    def _fill_load_menu(self, view: ResultView) -> None:
        """Las tres modalidades con su descripción; las no disponibles, desactivadas con el motivo."""
        menu = view.load_menu
        menu.clear()
        reasons = self._coordinator.load_modes()
        for mode, (label, help_text) in OPTIONS.items():
            reason = reasons.get(mode)
            action = menu.addAction(f"{label} — {help_text if reason is None else reason}")
            action.setObjectName(f"geoduckLoad_{mode.value}")
            action.setToolTip(help_text if reason is None else reason)
            action.setEnabled(
                reason is None and view.loadable and self._coordinator.state is SessionState.READY
            )
            action.triggered.connect(lambda _c=False, m=mode, v=view: self._load(v, m))

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
