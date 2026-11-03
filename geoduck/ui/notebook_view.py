# SPDX-License-Identifier: GPL-2.0-or-later
"""Vista de un cuaderno: sus celdas, una debajo de otra (G7 · E2, GD-NB-001..003; ui-ux-spec §10).

Cada `CellWidget` tiene su editor SQL, su selector de base, su resultado (pestañas por sentencia, como G2)
y sus botones «Cargar en QGIS ▾» y «Copiar». La vista no ejecuta nada: emite lo que pide el usuario y
`SqlPanel` lo ejecuta en la sesión única. El modelo (orden, SQL y base) es `geoduck.domain.notebook.Notebook`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QEvent, QMimeData, QObject, Qt, pyqtSignal
from qgis.PyQt.QtGui import QDrag, QKeySequence
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.catalog import CatalogSnapshot
from geoduck.domain.notebook import Cell, Notebook
from geoduck.ui.i18n import tr

#: Tipo MIME del arrastre de una celda (su id).
CELL_MIME = "application/x-geoduck-cell"
#: Altura del editor de una celda: entre estas líneas, según su texto.
EDITOR_LINES = (3, 18)
#: Altura máxima del resultado de una celda (con desplazamiento propio).
RESULT_MAX_HEIGHT = 320
#: Altura mínima de un resultado con tabla: cabecera, pestañas y unas filas a la vista.
RESULT_MIN_HEIGHT = 200


def _tool(text: str, tip: str, name: str = "") -> QToolButton:
    button = QToolButton()
    button.setText(text)
    button.setAutoRaise(True)
    button.setToolTip(tip)
    button.setAccessibleName(name or tip)
    button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return button


class _DragHandle(QLabel):
    """Asa «⠿»: arrastrar la celda a otra posición (ui-ux-spec §10)."""

    def __init__(self, cell: CellWidget) -> None:
        super().__init__("⠿")
        self._cell = cell
        self.setToolTip(tr("Drag to move the cell (Ctrl+↑/↓ with the keyboard)"))
        self.setAccessibleName(tr("Move the cell"))
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt
        if event.button() != Qt.MouseButton.LeftButton:
            return
        data = QMimeData()
        data.setData(CELL_MIME, str(self._cell.cell.id).encode())
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.setPixmap(self._cell.grab().scaledToWidth(min(360, max(1, self._cell.width()))))
        drag.exec(Qt.DropAction.MoveAction)


class CellWidget(QFrame):
    """Una celda: margen izquierdo (⠿ y pliegues), cabecera (▶ y base), editor, resultado y margen derecho."""

    run_requested = pyqtSignal(object)  # CellWidget
    activated = pyqtSignal(object)
    action_requested = pyqtSignal(object, str)  # CellWidget, «up», «down», «duplicate», «delete», «sheet»

    def __init__(self, cell: Cell, make_editor: Callable[[], Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cell = cell
        self.setObjectName("geoduckCell")
        self.setProperty("geoduck", "cell")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.editor = make_editor()
        self.editor.setText(cell.sql)
        self.editor.textChanged.connect(self._text_changed)
        self.editor.installEventFilter(self)
        self.sheet = False
        #: «Cargar en QGIS ▾» de la celda y su menú (los pone el panel, `SqlPanel._setup_cell`).
        self.load_button: Any = None
        self.load_menu: Any = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(2, 4, 2, 4)
        outer.setSpacing(4)
        outer.addLayout(self._build_gutter())
        body = QVBoxLayout()
        body.setSpacing(4)
        body.addLayout(self._build_header())
        self.splitter = QSplitter(
            Qt.Orientation.Vertical
        )  # editor | resultado (en la vista de hoja, ajustable)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self._build_result())
        body.addWidget(self.splitter, 1)
        outer.addLayout(body, 1)
        outer.addLayout(self._build_side())
        self._fit_editor()
        self.set_active(False)

    # -- construcción ---------------------------------------------------------------------------------

    def _build_gutter(self) -> QVBoxLayout:
        gutter = QVBoxLayout()
        gutter.setSpacing(2)
        gutter.addWidget(_DragHandle(self))
        self.fold_cell = _tool("˅", tr("Fold the cell"))
        self.fold_editor = _tool("˅", tr("Fold the editor"))
        self.fold_result = _tool("˅", tr("Fold the result"))
        for button, part in (
            (self.fold_cell, "cell"),
            (self.fold_editor, "editor"),
            (self.fold_result, "result"),
        ):
            button.setCheckable(True)
            button.toggled.connect(lambda folded, p=part: self.fold(p, folded))
            gutter.addWidget(button)
        gutter.addStretch(1)
        return gutter

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(6)
        self.run_button = _tool("▶", tr("Run the cell (Ctrl+Enter)"), tr("Run the cell"))
        self.run_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.run_menu = QMenu(self.run_button)
        self.run_button.setMenu(self.run_menu)
        self.run_button.clicked.connect(lambda _c=False: self.run_requested.emit(self))
        header.addWidget(self.run_button)
        self.title = QLabel("")
        self.title.setProperty("geoduck", "muted")
        header.addWidget(self.title, 1)
        self.database_combo = QComboBox()
        self.database_combo.setToolTip(
            tr("Database of the cell: names without a database are looked up here; other databases are")
            + " "
            + tr("still available with their name (database.schema.table)")
        )
        self.database_combo.setAccessibleName(tr("Database of the cell"))
        self.database_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.database_combo.activated.connect(self._database_chosen)
        header.addWidget(self.database_combo)
        return header

    def _build_result(self) -> QWidget:
        self.result_box = QWidget()
        box = QVBoxLayout(self.result_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setProperty("geoduck", "muted")
        row.addWidget(self.status_label, 1)
        self.copy_button = _tool(tr("Copy"), tr("Copies the shown rows as text separated by tabs"))
        self.copy_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.copy_button.setIcon(QgsApplication.getThemeIcon("mActionEditCopy.svg"))
        row.addWidget(self.copy_button)
        self.load_slot = QHBoxLayout()  # «Cargar en QGIS ▾» de la celda (lo pone el panel)
        row.addLayout(self.load_slot)
        box.addLayout(row)
        self.results = QTabWidget()
        self.results.setProperty("geoduck", "results")
        self.results.setDocumentMode(True)
        self.results.setUsesScrollButtons(True)
        self.results.setElideMode(Qt.TextElideMode.ElideRight)
        self.empty_results = QLabel(tr("No results yet. Run the cell (Ctrl+Enter)."))
        self.empty_results.setProperty("geoduck", "muted")
        self.empty_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.empty_results)
        self.results_stack.addWidget(self.results)
        self.results_stack.setMaximumHeight(RESULT_MAX_HEIGHT)
        box.addWidget(self.results_stack, 1)
        self.result_box.hide()  # hasta que haya resultado
        return self.result_box

    def _build_side(self) -> QVBoxLayout:
        side = QVBoxLayout()
        side.setSpacing(2)
        self.sheet_button = _tool(
            "⛶", tr("Sheet view: the cell takes the whole area (Ctrl+E)"), tr("Sheet view")
        )
        self.sheet_button.setCheckable(True)
        self.sheet_button.toggled.connect(lambda _on: self.action_requested.emit(self, "sheet"))
        side.addWidget(self.sheet_button)
        self.more_button = _tool("⋯", tr("More actions"))
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # Como la DuckDB UI: mover (con su atajo a la vista), duplicar y eliminar
        menu = QMenu(self.more_button)
        for key, text, keys, icon in (
            ("up", tr("Move cell up"), "Ctrl+Up", ""),
            ("down", tr("Move cell down"), "Ctrl+Down", ""),
            ("-", "", "", ""),
            ("duplicate", tr("Duplicate cell"), "", "mActionEditCopy.svg"),
            ("delete", tr("Delete"), "", "mActionDeleteSelected.svg"),
        ):
            if key == "-":
                menu.addSeparator()
                continue
            action = menu.addAction(text)
            action.setObjectName(f"geoduckCell_{key}")
            if icon:
                action.setIcon(QgsApplication.getThemeIcon(icon))
            if keys:  # solo se muestra en el menú: el atajo real es de la vista (NotebookView)
                action.setShortcut(QKeySequence(keys))
                action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            action.triggered.connect(lambda _c=False, k=key: self.action_requested.emit(self, k))
        self.more_button.setMenu(menu)
        side.addWidget(self.more_button)
        side.addStretch(1)
        return side

    # -- estado -------------------------------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt
        if watched is self.editor and event.type() == QEvent.Type.FocusIn:
            self.activated.emit(self)
        return False

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt
        self.activated.emit(self)
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _text_changed(self) -> None:
        self.cell.sql = self.editor.text()
        self._fit_editor()

    def _fit_editor(self) -> None:
        if self.sheet:
            self.editor.setMinimumHeight(60)
            self.editor.setMaximumHeight(16777215)
            return
        lines = min(max(self.editor.lines(), EDITOR_LINES[0]), EDITOR_LINES[1])
        # + la barra horizontal, para que una línea larga no tape la última línea
        bar = self.editor.horizontalScrollBar().sizeHint().height()
        height = lines * max(14, self.editor.textHeight(0)) + 12 + bar
        self.editor.setFixedHeight(height)

    def show_databases(self, catalog: CatalogSnapshot | None, in_use: str | None) -> None:
        """Rellena el selector con las bases del catálogo; una celda sin base toma la base en uso."""
        if self.cell.database is None and in_use is not None:
            self.cell.database = in_use
        self.database_combo.blockSignals(True)
        self.database_combo.clear()
        names = [db.name for db in catalog.databases] if catalog is not None else []
        for name in names:
            self.database_combo.addItem(name, name)
        current = self.cell.database
        if current is not None and current not in names:  # desadjuntada: se ve, y avisa
            self.database_combo.addItem(tr("{0} (not attached)").format(current), current)
        if current is not None:
            self.database_combo.setCurrentIndex(self.database_combo.findData(current))
        self.database_combo.blockSignals(False)
        problem = self.cell.database_problem(catalog)
        self.database_combo.setProperty("geoduck", "error" if problem else "")
        self.database_combo.setToolTip(problem or self.database_combo.toolTip())

    def _database_chosen(self, index: int) -> None:
        value = self.database_combo.itemData(index)
        if value:
            self.cell.database = str(value)

    def fold(self, part: str, folded: bool) -> None:
        """Plegar la celda entera, el editor o el resultado (ui-ux-spec §10)."""
        if part == "cell":
            self.splitter.setVisible(not folded)
            self.title.setText(
                self.cell.sql.strip().splitlines()[0][:80] if folded and self.cell.sql.strip() else ""
            )
        elif part == "editor":
            self.editor.setVisible(not folded)
        elif part == "result":
            self.results_stack.setVisible(not folded)

    def show_result_area(self) -> None:
        """Tras ejecutar: la fila de estado siempre; la tabla, si hay resultados (un `CREATE` no tiene)."""
        self.result_box.show()
        has_tabs = self.results.count() > 0
        self.results_stack.setCurrentWidget(self.results if has_tabs else self.empty_results)
        self.results_stack.setVisible(has_tabs and not self.fold_result.isChecked())
        self.results_stack.setMinimumHeight(RESULT_MIN_HEIGHT if has_tabs and not self.sheet else 0)

    def set_sheet(self, sheet: bool) -> None:
        self.sheet = sheet
        self.results_stack.setMaximumHeight(16777215 if sheet else RESULT_MAX_HEIGHT)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding if sheet else QSizePolicy.Policy.Maximum,
        )
        self.sheet_button.blockSignals(True)
        self.sheet_button.setChecked(sheet)
        self.sheet_button.blockSignals(False)
        self._fit_editor()


class _Cells(QWidget):
    """Columna de celdas que acepta soltar una celda arrastrada."""

    dropped = pyqtSignal(int, int)  # id de la celda, posición de destino

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(4, 4, 4, 4)
        self.column.setSpacing(8)

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802 - Qt
        if event.mimeData().hasFormat(CELL_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt
        if event.mimeData().hasFormat(CELL_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:  # noqa: N802 - Qt
        if not event.mimeData().hasFormat(CELL_MIME):
            return
        cell_id = int(bytes(event.mimeData().data(CELL_MIME)).decode())
        y = event.position().y() if hasattr(event, "position") else event.pos().y()
        self.dropped.emit(cell_id, self.index_at(y))
        event.acceptProposedAction()

    def index_at(self, y: float) -> int:
        """Posición entre celdas para una altura `y` (antes de la primera celda cuyo centro queda debajo)."""
        index = 0
        for i in range(self.column.count()):
            widget = self.column.itemAt(i).widget()
            if isinstance(widget, CellWidget):
                if y < widget.geometry().center().y():
                    return index
                index += 1
        return index


class NotebookView(QScrollArea):
    """Las celdas de un cuaderno, con «+ Añadir celda» al final.

    La celda activa recibe Ctrl+E y Ctrl+↑/↓."""

    run_requested = pyqtSignal(object)  # CellWidget
    active_changed = pyqtSignal(object)  # CellWidget
    #: Celda nueva (añadida o duplicada), para que el panel le ponga sus botones.
    cell_created = pyqtSignal(object)  # CellWidget

    def __init__(
        self, notebook: Notebook, make_editor: Callable[[], Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.notebook = notebook
        self._make_editor = make_editor
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("geoduckNotebook")
        self._cells = _Cells()
        self._cells.dropped.connect(self.move_cell)
        self.add_button = QToolButton()
        self.add_button.setText("＋ " + tr("Add cell"))
        self.add_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.add_button.setAccessibleName(tr("Add cell"))
        self.add_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.add_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.add_button.clicked.connect(lambda _c=False: self.add_cell(len(self.notebook.cells)))
        self._widgets: dict[int, CellWidget] = {}
        self.active: CellWidget | None = None
        self.sheet: CellWidget | None = None
        #: Pregunta antes de borrar una celda con SQL; las pruebas la sustituyen.
        self.confirm_delete: Callable[[CellWidget], bool] = lambda _w: True
        self.setWidget(self._cells)
        for cell in notebook.cells:
            self._widgets[cell.id] = self._new_widget(cell)
        self._relayout()
        self.set_active(self._widgets[notebook.cells[0].id])
        self.shortcuts: list[QShortcut] = []
        for keys, slot in (
            ("Ctrl+E", lambda: self.active is not None and self.toggle_sheet(self.active)),
            ("Ctrl+Up", lambda: self._step(-1)),
            ("Ctrl+Down", lambda: self._step(1)),
            ("Alt+Up", lambda: self._focus_step(-1)),
            ("Alt+Down", lambda: self._focus_step(1)),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
            self.shortcuts.append(shortcut)

    # -- celdas -------------------------------------------------------------------------------------------

    def _new_widget(self, cell: Cell) -> CellWidget:
        widget = CellWidget(cell, self._make_editor)
        widget.run_requested.connect(self.run_requested)
        widget.activated.connect(self.set_active)
        widget.action_requested.connect(self._action)
        self.cell_created.emit(widget)
        return widget

    def cell_widgets(self) -> list[CellWidget]:
        return [self._widgets[c.id] for c in self.notebook.cells]

    def widget_for(self, cell: Cell) -> CellWidget | None:
        return self._widgets.get(cell.id)

    def _relayout(self) -> None:
        column = self._cells.column
        while column.count():
            item = column.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        for i, cell in enumerate(self.notebook.cells):
            insert = _tool("＋", tr("Insert a cell here"))
            insert.clicked.connect(lambda _c=False, at=i: self.add_cell(at))
            insert.setObjectName("geoduckInsertCell")
            column.addWidget(insert, 0, Qt.AlignmentFlag.AlignLeft)
            widget = self._widgets[cell.id]
            widget.setParent(self._cells)
            widget.setVisible(self.sheet is None or widget is self.sheet)
            insert.setVisible(self.sheet is None)
            column.addWidget(widget, 1 if widget is self.sheet else 0)
        column.addWidget(self.add_button)
        self.add_button.setVisible(self.sheet is None)
        if self.sheet is None:
            column.addStretch(1)

    def add_cell(self, index: int, sql: str = "") -> CellWidget:
        database = self.active.cell.database if self.active is not None else None
        cell = self.notebook.insert(index, database, sql)
        self._widgets[cell.id] = self._new_widget(cell)
        self._relayout()
        widget = self._widgets[cell.id]
        self.set_active(widget)
        widget.editor.setFocus()
        return widget

    def move_cell(self, cell_id: int, target: int) -> None:
        """Arrastrar o subir/bajar: el texto, la base y el resultado viajan con la celda; nada se ejecuta."""
        current = self.notebook.index_of(cell_id)
        if target > current:
            target -= 1  # `target` cuenta la celda que se mueve
        self.notebook.move(cell_id, target)
        self._relayout()

    def _step(self, delta: int) -> None:
        if self.active is None:
            return
        index = self.notebook.index_of(self.active.cell.id)
        target = max(0, min(len(self.notebook.cells) - 1, index + delta))
        self.notebook.move(self.active.cell.id, target)
        self._relayout()
        self.active.editor.setFocus()

    def _focus_step(self, delta: int) -> None:
        if self.active is None:
            return
        cells = self.cell_widgets()
        index = cells.index(self.active)
        target = cells[max(0, min(len(cells) - 1, index + delta))]
        self.set_active(target)
        target.editor.setFocus()

    def delete_cell(self, widget: CellWidget) -> bool:
        if widget.cell.sql.strip() and not self.confirm_delete(widget):
            return False
        if self.sheet is widget:
            self.toggle_sheet(widget)
        index = self.notebook.index_of(widget.cell.id)
        self.notebook.remove(widget.cell.id)
        self._widgets.pop(widget.cell.id, None)
        widget.deleteLater()
        for cell in self.notebook.cells:  # si era la última, el modelo creó una vacía
            if cell.id not in self._widgets:
                self._widgets[cell.id] = self._new_widget(cell)
        self._relayout()
        cells = self.cell_widgets()
        self.set_active(cells[min(index, len(cells) - 1)])
        return True

    def _action(self, widget: CellWidget, key: str) -> None:
        if key == "sheet":
            self.toggle_sheet(widget)
        elif key in ("up", "down"):
            self.set_active(widget)
            self._step(-1 if key == "up" else 1)
        elif key == "duplicate":
            copy = self.notebook.duplicate(widget.cell.id)
            self._widgets[copy.id] = self._new_widget(copy)
            self._relayout()
            self.set_active(self._widgets[copy.id])
        elif key == "delete":
            self.delete_cell(widget)

    def toggle_sheet(self, widget: CellWidget) -> None:
        """Vista de hoja (⛶, Ctrl+E): la celda ocupa todo; otra vez, vuelve a la lista de celdas."""
        self.sheet = None if self.sheet is widget else widget
        for w in self._widgets.values():
            w.set_sheet(w is self.sheet)
        self._relayout()
        if self.sheet is not None:
            self.sheet.splitter.setSizes([2, 3])
        self.set_active(widget)

    def set_active(self, widget: CellWidget) -> None:
        if self.active is widget:
            return
        if self.active is not None and self.active in self._widgets.values():
            self.active.set_active(False)
        self.active = widget
        widget.set_active(True)
        self.ensureWidgetVisible(widget)
        self.active_changed.emit(widget)

    def show_databases(self, catalog: CatalogSnapshot | None, in_use: str | None) -> None:
        for widget in self._widgets.values():
            widget.show_databases(catalog, in_use)
