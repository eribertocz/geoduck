# SPDX-License-Identifier: GPL-2.0-or-later
"""Pestaña de tabla de Workspace Pro (workspace-pro-spec §4; GD-WSP-003; AT-WSP-003, 004).

Solo lectura. **Datos:** grilla por páginas de 100 filas que DuckDB lee bajo demanda (nunca la tabla entera),
con el tipo bajo cada columna y el número de fila; orden con clic en el encabezado; filtros en chips
(«+ Filtro»); búsqueda en las columnas de texto; «1–100 de 48 312» con el total contado aparte; detalle de la
fila a la derecha (valor completo, geometría resumida, copiar); «Ver SQL»; Ctrl+C copia lo elegido.
**Estructura:** columnas (nombre, tipo, nulos, clave), filas, tamaño aproximado y la sentencia `CREATE`.

Toda lectura va al worker por `SessionCoordinator.read_rows` (SQL de `domain.browse`) y vuelve en el hilo de
la interfaz; una respuesta vieja (de antes de otro filtro u orden) se descarta.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from typing import Any

from qgis.PyQt.QtCore import QAbstractTableModel, QModelIndex, QPoint, QRect, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QGuiApplication, QKeySequence, QPainter
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QShortcut,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from geoduck.app.events import (
    AppEvent,
    CatalogChanged,
    ColumnsListed,
    ColumnsUnavailable,
    PreviewsInvalidated,
    SessionStateChanged,
)
from geoduck.domain.browse import (
    OPERATORS,
    PAGE,
    UNARY,
    Browse,
    Filter,
    geometry_summary,
    page_label,
    size_sql,
    structure_sql,
)
from geoduck.domain.catalog import ColumnInfo
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.operations import StatementOutcome
from geoduck.domain.session import SessionState
from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons
from geoduck.ui.pro.places import VIEW, Place
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import (
    Chip,
    SearchField,
    Segmented,
    add_chip_button,
    button,
    icon_button,
    label,
    spacer,
)

_NUMERIC = re.compile(
    r"^(U?(TINY|SMALL|BIG|HUGE)?INT|INTEGER|DOUBLE|FLOAT|REAL|DECIMAL|NUMERIC)", re.IGNORECASE
)
#: Caracteres de una celda en la grilla (el valor completo está en el detalle).
CELL = 300


def is_numeric(data_type: str) -> bool:
    return bool(_NUMERIC.match(data_type.strip()))


def short_type(data_type: str) -> str:
    """El tipo en el encabezado, en minúsculas y sin parámetros largos («geometry», «decimal(10,2)»)."""
    text = data_type.strip().lower()
    return text if len(text) <= 18 else text.split("(", 1)[0]


def fit_columns(grid: QTableView, model: PageModel) -> None:
    """Ancho de cada columna: el de su contenido o el de su encabezado (nombre y tipo), entre 90 y 360 px."""
    if not model.columns:
        return
    grid.resizeColumnsToContents()
    metrics = grid.horizontalHeader().fontMetrics()
    for i, column in enumerate(model.columns):
        title = metrics.horizontalAdvance(column.name + short_type(column.data_type)) + 48
        grid.setColumnWidth(i, min(max(grid.columnWidth(i), title, 90), 360))


def cell_text(value: object) -> str:
    """El valor en la grilla: NULL, binarios en hexadecimal, números reales con 15 cifras significativas
    (159.232 y no 159.23199999999972) y el texto, abreviado."""
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return format(value, ".15g")
    text = value.hex() if isinstance(value, (bytes, bytearray)) else str(value)
    return text if len(text) <= CELL else text[:CELL] + "…"


# -- grilla ----------------------------------------------------------------------------------------------


class PageModel(QAbstractTableModel):
    """Una página de filas ya leídas; nunca pide nada a DuckDB."""

    def __init__(self, colors: Colors) -> None:
        super().__init__()
        self.colors = colors
        self.columns: tuple[ColumnInfo, ...] = ()
        self.rows: tuple[tuple[object, ...], ...] = ()
        self.offset = 0
        self.mono = ui_font(METRICS.font_small, mono=True)
        self.italic = ui_font()
        self.italic.setItalic(True)

    def set_page(
        self, columns: tuple[ColumnInfo, ...], rows: tuple[tuple[object, ...], ...], offset: int
    ) -> None:
        self.beginResetModel()
        self.columns, self.rows, self.offset = columns, rows, offset
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008 - API de Qt
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Texto, alineación (números a la derecha), color (NULL y geometrías en gris) y fuente (NULL en
        cursiva; números y geometrías en monoespaciada)."""
        if not index.isValid():
            return None
        value = self.rows[index.row()][index.column()]
        column = self.columns[index.column()]
        numeric = is_numeric(column.data_type)
        answer: Any = None
        if role == Qt.ItemDataRole.DisplayRole:
            answer = cell_text(value)
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            side = Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft
            answer = int(side | Qt.AlignmentFlag.AlignVCenter)
        elif role == Qt.ItemDataRole.ForegroundRole and (value is None or column.is_geometry):
            answer = QColor(self.colors.null if value is None else self.colors.muted)
        elif role == Qt.ItemDataRole.FontRole and (value is None or numeric or column.is_geometry):
            answer = self.italic if value is None else self.mono
        return answer

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.columns[section].name if section < len(self.columns) else None
        return str(self.offset + section + 1)


class TypeHeader(QHeaderView):
    """Encabezado de la grilla: nombre en negrita, tipo en gris y monoespaciado, y la flecha del orden."""

    def __init__(self, model: PageModel, colors: Colors) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.page_model = model
        self.colors = colors
        self.order: tuple[str, bool] | None = None
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setDefaultSectionSize(160)
        self.setMinimumSectionSize(60)
        self.bold = ui_font(bold=True)
        self.mono = ui_font(METRICS.font_tiny, mono=True)
        self._arrows = {
            True: icons.pixmap("arrow-up", colors.accent, 12),
            False: icons.pixmap("arrow-down", colors.accent, 12),
        }

    def paintSection(self, painter: QPainter, rect: QRect, index: int) -> None:  # noqa: N802
        if index >= len(self.page_model.columns):
            return
        c = self.colors
        column = self.page_model.columns[index]
        painter.save()
        painter.fillRect(rect, QColor(c.head))
        painter.setPen(QColor(c.border))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setPen(QColor(c.line))
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        inner = rect.adjusted(10, 0, -8, 0)
        if self.order is not None and self.order[0] == column.name:
            arrow = self._arrows[self.order[1]]
            painter.drawPixmap(inner.right() - 12, inner.center().y() - 6, arrow)
            inner.setRight(inner.right() - 16)
        painter.setFont(self.bold)
        painter.setPen(QColor(c.text))
        metrics = painter.fontMetrics()
        name = metrics.elidedText(column.name, Qt.TextElideMode.ElideRight, inner.width())
        painter.drawText(inner, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), name)
        used = metrics.horizontalAdvance(name) + 6
        if used < inner.width():
            painter.setFont(self.mono)
            painter.setPen(QColor(c.faint))
            kind = painter.fontMetrics().elidedText(
                short_type(column.data_type), Qt.TextElideMode.ElideRight, inner.width() - used
            )
            painter.drawText(
                inner.adjusted(used, 1, 0, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                kind,
            )
        painter.restore()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), METRICS.header)


# -- filtro nuevo ----------------------------------------------------------------------------------------


class FilterPopup(QFrame):
    """«+ Filtro»: columna, operador y valor; Intro o «Añadir». El valor se esconde con «es nulo»."""

    added = pyqtSignal(object)  # Filter

    def __init__(self, parent: QWidget, columns: tuple[ColumnInfo, ...]) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setProperty("pro", "popup")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        box.addWidget(label(tr("New filter"), "section"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.column = QComboBox()
        self.column.setAccessibleName(tr("Column"))
        for column in columns:
            self.column.addItem(column.name)
        self.operator = QComboBox()
        self.operator.setAccessibleName(tr("Operator"))
        for op, text in OPERATORS:
            self.operator.addItem(tr(text), op)
        self.value = QLineEdit()
        self.value.setPlaceholderText(tr("Value"))
        self.value.setAccessibleName(tr("Value"))
        self.value.returnPressed.connect(self._add)
        self.operator.currentIndexChanged.connect(self._operator_changed)
        for widget in (self.column, self.operator):
            row.addWidget(widget)
        row.addWidget(self.value, 1)
        box.addLayout(row)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.add_button = button(tr("Add"), "primary")
        self.add_button.clicked.connect(self._add)
        actions.addWidget(self.add_button)
        box.addLayout(actions)
        self.setMinimumWidth(460)

    def _operator_changed(self) -> None:
        self.value.setVisible(self.operator.currentData() not in UNARY)

    def _add(self) -> None:
        op = self.operator.currentData()
        if op not in UNARY and not self.value.text().strip():
            self.value.setFocus()
            return
        self.added.emit(Filter(self.column.currentText(), op, self.value.text().strip()))
        self.close()

    def show_under(self, anchor: QWidget) -> None:
        self.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        self.show()
        self.value.setFocus()


# -- detalle de fila -------------------------------------------------------------------------------------


class DetailPanel(QFrame):
    """Panel derecho: cada campo con su tipo y su valor completo; la geometría, resumida; copiar."""

    closed = pyqtSignal()

    def __init__(self, colors: Colors) -> None:
        super().__init__()
        self.colors = colors
        self.setProperty("pro", "rule-left")
        self.setFixedWidth(METRICS.detail)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        head = QFrame()
        head.setProperty("pro", "rule-bottom")
        row = QHBoxLayout(head)
        row.setContentsMargins(14, 8, 8, 8)
        self.title = label("", "title")
        row.addWidget(self.title, 1)
        close = icon_button("close", tr("Hide the row detail"), colors)
        close.clicked.connect(self.closed.emit)
        row.addWidget(close)
        box.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setProperty("pro", "plain")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        box.addWidget(self.scroll, 1)
        self.fields: list[tuple[str, str]] = []

    def show_row(self, number: int, columns: tuple[ColumnInfo, ...], values: tuple[object, ...]) -> None:
        self.title.setText(tr("Row {}").format(f"{number:,}".replace(",", " ")))
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(14, 6, 10, 10)
        box.setSpacing(0)
        self.fields = []
        for column, value in zip(columns, values, strict=False):
            box.addWidget(self._field(column, value))
        box.addStretch(1)
        self.scroll.setWidget(body)

    def _field(self, column: ColumnInfo, value: object) -> QWidget:
        cell = QFrame()
        cell.setProperty("pro", "rule-bottom")
        box = QVBoxLayout(cell)
        box.setContentsMargins(0, 8, 0, 8)
        box.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        name = label(column.name, "muted")
        name.setFont(ui_font(METRICS.font_small))
        top.addWidget(name)
        kind = label(short_type(column.data_type), "faint")
        kind.setFont(ui_font(METRICS.font_tiny, mono=True))
        top.addWidget(kind)
        top.addStretch(1)
        text = "" if value is None else (value.hex() if isinstance(value, (bytes, bytearray)) else str(value))
        copy = icon_button("copy", tr("Copy value"), self.colors, size=14)
        copy.setFixedSize(22, 22)
        copy.setEnabled(value is not None)
        copy.clicked.connect(lambda _=False, t=text: QGuiApplication.clipboard().setText(t))
        top.addWidget(copy)
        box.addLayout(top)
        if value is None:
            shown = label("NULL", "null")
        elif column.is_geometry:
            kind_name, crs, vertices = geometry_summary(text, column.data_type)
            count = (
                tr("1 vertex")
                if vertices == 1
                else tr("{} vertices").format(f"{vertices:,}".replace(",", " "))
            )
            summary = " · ".join([kind_name, crs or tr("no CRS"), count])
            shown = label(
                summary + (f"\n{text}" if len(text) <= 120 else ""), "mono"
            )  # una geometría corta, entera
            shown.setToolTip(text[:500])
        else:
            shown = label(text[:5000], "mono" if is_numeric(column.data_type) else None)
        shown.setWordWrap(True)
        shown.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(shown)
        self.fields.append((column.name, shown.text().split("\n", 1)[0]))
        return cell


# -- estructura ------------------------------------------------------------------------------------------


class StructureView(QWidget):
    """«Estructura»: columnas (nombre, tipo, nulos, clave), filas, tamaño aproximado y `CREATE`."""

    def __init__(self, colors: Colors) -> None:
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)
        self.summary = label("", "muted")
        box.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setProperty("pro", "list")
        self.table.setHorizontalHeaderLabels([tr("Column"), tr("Type"), tr("Nulls"), tr("Key")])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.table.verticalHeader().setDefaultSectionSize(METRICS.row)
        box.addWidget(self.table, 3)
        row = QHBoxLayout()
        row.addWidget(label(tr("Definition"), "section"))
        row.addStretch(1)
        self.copy_button = button(tr("Copy"), "ghost", icon="copy", colors=colors)
        self.copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.create.toPlainText())
        )
        row.addWidget(self.copy_button)
        box.addLayout(row)
        self.create = QPlainTextEdit()
        self.create.setProperty("pro", "code")
        self.create.setReadOnly(True)
        self.create.setAccessibleName(tr("Definition"))
        box.addWidget(self.create, 2)

    def show_structure(
        self,
        columns: tuple[ColumnInfo, ...],
        keys: dict[str, str],
        rows: int | None,
        size: int | None,
        sql: str,
    ) -> None:
        self.table.setRowCount(len(columns))
        for i, column in enumerate(columns):
            nulls = "" if column.nullable is None else (tr("yes") if column.nullable else tr("no"))
            for j, text in enumerate((column.name, column.data_type, nulls, keys.get(column.name, ""))):
                self.table.setItem(i, j, QTableWidgetItem(text))
        parts = [tr("{} columns").format(len(columns))]
        if rows is not None:
            parts.append(tr("{} rows").format(f"{rows:,}".replace(",", " ")))
        if size:
            parts.append(tr("about {}").format(_size(size)))
        self.summary.setText(" · ".join(parts))
        self.create.setPlainText(sql)


def _size(rows_bytes: int) -> str:
    value = float(rows_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return ""


# -- la pestaña ------------------------------------------------------------------------------------------

#: Páginas del cuerpo: la grilla o un mensaje (cargando, ocupada, error, sin filas).
GRID, MESSAGE = 0, 1


class TablePage(QWidget):
    """La pestaña de una tabla o vista. `view_sql(texto)` abre «Ver SQL» en una consulta nueva."""

    def __init__(
        self, place: Place, coordinator: Any, colors: Colors, view_sql: Callable[[str], object] | None = None
    ) -> None:
        super().__init__()
        self.place = place
        self.colors = colors
        self._coordinator = coordinator
        self._view_sql = view_sql
        self.source = (place.database, place.schema, place.name)
        self.is_view = place.kind == VIEW
        self.browse: Browse | None = None
        self.total: int | None = None
        self.offset = 0
        self._generation = 0
        self._pending = True
        self._closed = False
        self._structure_loaded = False
        self.detail_open = True
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self._build_filters())
        self.views = QStackedWidget()
        self.views.addWidget(self._build_data())
        self.structure = StructureView(colors)
        self.views.addWidget(self.structure)
        box.addWidget(self.views, 1)
        box.addWidget(self._build_footer())
        copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.grid)
        copy.setContext(Qt.ShortcutContext.WidgetShortcut)
        copy.activated.connect(self.copy_selection)
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._show_message(tr("Loading…"))
        self.load()

    # -- construcción ---------------------------------------------------------------------------------

    def _build_filters(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("pro", "rule-bottom")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 12, 10)
        row.setSpacing(8)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(8)
        row.addLayout(self.chips)
        self.add_filter_button = add_chip_button(tr("Filter"), tr("Add a filter: column, operator and value"))
        self.add_filter_button.clicked.connect(self.open_filter_popup)
        row.addWidget(self.add_filter_button)
        self.search = SearchField(
            tr("Search in text columns…"), self.colors, accessible_name=tr("Search in the table")
        )
        self.search.setFixedWidth(260)
        self.search.edit.returnPressed.connect(self._search_changed)
        self.search.edit.textChanged.connect(lambda text: self._search_changed() if not text else None)
        row.addSpacing(4)
        row.addWidget(self.search)
        row.addWidget(spacer(), 1)
        self.sql_button = button(tr("View SQL"), "ghost", icon="sql", colors=self.colors)
        self.sql_button.setToolTip(tr("Opens the equivalent query in a new query tab"))
        self.sql_button.clicked.connect(self.view_sql)
        row.addWidget(self.sql_button)
        self.detail_button = icon_button("dock", tr("Show or hide the row detail"), self.colors)
        self.detail_button.setCheckable(True)
        self.detail_button.setChecked(True)
        self.detail_button.toggled.connect(self.set_detail_open)
        row.addWidget(self.detail_button)
        return bar

    def _build_data(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.body = QStackedWidget()
        self.model = PageModel(self.colors)
        self.grid = QTableView()
        self.grid.setProperty("pro", "grid")
        self.grid.setModel(self.model)
        self.header = TypeHeader(self.model, self.colors)
        self.grid.setHorizontalHeader(self.header)
        self.header.sectionClicked.connect(self._sort)
        self.grid.setShowGrid(False)
        self.grid.setWordWrap(False)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.grid.setAccessibleName(tr("Rows of {}").format(self.place.name))
        vertical = self.grid.verticalHeader()
        vertical.setDefaultSectionSize(METRICS.row)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vertical.setMinimumWidth(48)
        self.grid.selectionModel().currentRowChanged.connect(
            lambda current, _prev: self._row_changed(current.row())
        )
        self.body.addWidget(self.grid)
        message = QWidget()
        mbox = QVBoxLayout(message)
        mbox.addStretch(1)
        self.message = label("", "muted")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        mbox.addWidget(self.message)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.retry_button = button(tr("Try again"))
        self.retry_button.clicked.connect(self.load)
        self.clear_button = button(tr("Clear filters"))
        self.clear_button.clicked.connect(self.clear_filters)
        actions.addWidget(self.retry_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        mbox.addLayout(actions)
        mbox.addStretch(1)
        self.body.addWidget(message)
        row.addWidget(self.body, 1)
        self.detail = DetailPanel(self.colors)
        self.detail.closed.connect(lambda: self.detail_button.setChecked(False))
        self.detail.hide()
        row.addWidget(self.detail)
        return page

    def _build_footer(self) -> QWidget:
        foot = QFrame()
        foot.setProperty("pro", "rule-top")
        foot.setFixedHeight(METRICS.bar - 4)
        row = QHBoxLayout(foot)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)
        self.mode = Segmented([tr("Data"), tr("Structure")], accessible_name=tr("Data or structure"))
        self.mode.changed.connect(self.show_mode)
        row.addWidget(self.mode)
        self.range_label = label("", "muted")
        row.addWidget(self.range_label)
        self.prev_button = icon_button("chevron-left", tr("Previous page"), self.colors)
        self.prev_button.clicked.connect(lambda: self.go(self.offset - PAGE))
        self.next_button = icon_button("chevron-right", tr("Next page"), self.colors)
        self.next_button.clicked.connect(lambda: self.go(self.offset + PAGE))
        row.addWidget(self.prev_button)
        row.addWidget(self.next_button)
        row.addStretch(1)
        return foot

    # -- lecturas -------------------------------------------------------------------------------------

    def _read(
        self,
        sql: str,
        max_rows: int,
        done: Callable[[StatementOutcome], None],
        fresh: Callable[[], bool] | None = None,
    ) -> bool:
        """Pide una lectura; `done` solo recibe la respuesta si sigue valiendo (`fresh`; por defecto, si no
        hubo otra página, filtro u orden después). Devuelve si se pidió."""
        generation = self._generation
        still = fresh or (lambda: generation == self._generation)

        def answer(result: StatementOutcome | BaseException) -> None:
            if self._closed or not still():
                return  # pestaña cerrada, u otro filtro, orden o página después
            if isinstance(result, BaseException):
                text = result.message if isinstance(result, GeoDuckError) else str(result)
                self._show_message(tr("The table could not be read.") + f"\n{text}", retry=True)
                return
            done(result)

        try:
            self._coordinator.read_rows(sql, max_rows, answer)
        except GeoDuckError:
            self._pending = True
            self._show_busy()
            return False
        return True

    def load(self) -> None:
        """Columnas (si aún no se tienen) y la página actual."""
        if self._closed:
            return
        self._pending = True
        state = self._coordinator.state
        if self._coordinator.engine_info is None or state is SessionState.DISCONNECTED:
            self._show_message(tr("Start DuckDB to see this table."))
            return
        if state is not SessionState.READY:
            self._show_busy()
            return
        known = self._coordinator.known_columns().get(self.source)
        if known is not None:
            self._columns_ready(known)
            return
        self._show_message(tr("Loading…"))
        try:
            self._coordinator.list_columns(self.source)
        except GeoDuckError:
            self._show_busy()

    def _columns_ready(self, columns: tuple[ColumnInfo, ...]) -> None:
        if self.browse is None or self.browse.columns != columns:
            names = {c.name for c in columns}
            old = self.browse
            filters = tuple(f for f in old.filters if f.column in names) if old else ()
            order = old.order if old and old.order and old.order[0] in names else None
            self.browse = Browse(
                *self.source, columns, filters, old.search if old else "", order, has_rowid=not self.is_view
            )
        self.reload(keep_offset=True)

    def reload(self, *, keep_offset: bool = False) -> None:
        """Vuelve a leer la página (y el total) con los filtros, la búsqueda y el orden actuales."""
        if self.browse is None:
            self.load()
            return
        if not keep_offset:
            self.offset = 0
        self._generation += 1
        self.total = None
        browse = self.browse
        self._render_chips()
        self.header.order = browse.order
        self.header.viewport().update()
        if self._read(browse.page_sql(self.offset), PAGE, lambda r: self._page_read(browse, r)):
            # el total vale mientras no cambien los filtros, la búsqueda ni el orden (pasar de página, sí)
            self._read(browse.count_sql(), 1, self._counted, fresh=lambda: self.browse is browse)
            self._pending = False
        if self._structure_loaded:
            self._structure_loaded = False
            if self.mode.current == 1:
                self._load_structure()

    def go(self, offset: int) -> None:
        if self.browse is None:
            return
        offset = max(0, offset)
        if self.total is not None and offset >= self.total:
            return
        self.offset = offset
        self._generation += 1
        browse = self.browse
        self._read(browse.page_sql(offset), PAGE, lambda r: self._page_read(browse, r))

    def _page_read(self, browse: Browse, result: StatementOutcome) -> None:
        if not result.rows and self.offset > 0:
            self.go(self.offset - PAGE)  # la última página quedó vacía (filas borradas)
            return
        self.model.set_page(browse.columns, result.rows, self.offset)
        self._fit_columns()
        if result.rows:
            self.body.setCurrentIndex(GRID)
            self.grid.selectRow(0)
        elif browse.filters or browse.search:
            self._show_message(tr("No rows match these filters."), clear=True)
        else:
            self._show_message(tr("This table has no rows."))
        self._update_range()

    def _counted(self, result: StatementOutcome) -> None:
        self.total = int(result.rows[0][0]) if result.rows else 0
        self._update_range()

    def _update_range(self) -> None:
        shown = self.model.rowCount()
        self.range_label.setText(page_label(self.offset, shown, self.total))
        self.prev_button.setEnabled(self.offset > 0)
        more = shown == PAGE and (self.total is None or self.offset + shown < self.total)
        self.next_button.setEnabled(more)

    def _fit_columns(self) -> None:
        fit_columns(self.grid, self.model)

    # -- acciones -------------------------------------------------------------------------------------

    def open_filter_popup(self) -> None:
        if self.browse is None:
            return
        popup = FilterPopup(self, self.browse.columns)
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        popup.added.connect(self.add_filter)
        popup.show_under(self.add_filter_button)
        self.popup = popup  # para las pruebas

    def add_filter(self, item: Filter) -> None:
        if self.browse is not None:
            self.browse = self.browse.with_filter(item)
            self.reload()

    def remove_filter(self, index: int) -> None:
        if self.browse is not None:
            self.browse = self.browse.without_filter(index)
            self.reload()

    def clear_filters(self) -> None:
        if self.browse is not None:
            self.search.edit.blockSignals(True)
            self.search.edit.clear()
            self.search.edit.blockSignals(False)
            self.browse = Browse(
                *self.source, self.browse.columns, order=self.browse.order, has_rowid=not self.is_view
            )
            self.reload()

    def _search_changed(self) -> None:
        if self.browse is not None and self.browse.search != self.search.edit.text().strip():
            self.browse = self.browse.with_search(self.search.edit.text())
            self.reload()

    def _sort(self, section: int) -> None:
        if self.browse is not None and 0 <= section < len(self.browse.columns):
            self.browse = self.browse.next_order(self.browse.columns[section].name)
            self.reload()

    def view_sql(self) -> None:
        if self.browse is not None and self._view_sql is not None:
            self._view_sql(self.browse.display_sql())

    def set_detail_open(self, open_: bool) -> None:
        self.detail_open = open_
        self.detail.setVisible(open_ and self.model.rowCount() > 0 and self.body.currentIndex() == GRID)
        if open_:
            self._row_changed(self.grid.currentIndex().row())

    def _row_changed(self, row: int) -> None:
        if not self.detail_open or row < 0 or self.browse is None:
            self.detail.hide()
            return
        self.detail.show()
        values = self.model.rows[row]
        number = self.offset + row + 1
        self.detail.show_row(number, self.model.columns, values)
        if any(c.is_geometry for c in self.model.columns):  # la geometría completa, para resumirla bien
            browse = self.browse
            self._read_detail(browse, row, number)

    def _read_detail(self, browse: Browse, row: int, number: int) -> None:
        def done(result: StatementOutcome) -> None:
            if result.rows and self.grid.currentIndex().row() == row:
                self.detail.show_row(number, browse.columns, result.rows[0])

        with contextlib.suppress(GeoDuckError):  # sesión ocupada: el detalle queda con la geometría abreviada
            self._coordinator.read_rows(
                browse.row_sql(self.offset + row),
                1,
                lambda r: done(r) if not self._closed and not isinstance(r, BaseException) else None,
            )

    def copy_selection(self) -> None:
        """Ctrl+C: las celdas elegidas como texto separado por tabuladores (filas enteras si se eligieron)."""
        indexes = sorted(self.grid.selectedIndexes(), key=lambda i: (i.row(), i.column()))
        if not indexes:
            return
        rows: dict[int, list[str]] = {}
        for index in indexes:
            value = self.model.rows[index.row()][index.column()]
            rows.setdefault(index.row(), []).append("" if value is None else str(value))
        QGuiApplication.clipboard().setText("\n".join("\t".join(cells) for cells in rows.values()))

    def show_mode(self, index: int) -> None:
        """«Datos» o «Estructura»."""
        self.views.setCurrentIndex(index)
        for widget in (self.add_filter_button, self.search, self.sql_button, self.detail_button):
            widget.setVisible(index == 0)
        for i in range(self.chips.count()):
            item = self.chips.itemAt(i).widget()
            if item is not None:
                item.setVisible(index == 0)
        for widget in (self.range_label, self.prev_button, self.next_button):
            widget.setVisible(index == 0)
        if index == 1 and not self._structure_loaded:
            self._load_structure()

    def _load_structure(self) -> None:
        browse = self.browse
        if browse is None:
            return
        self._structure_loaded = True
        found: dict[str, Any] = {"keys": {}, "definition": "", "rows": None, "size": None}

        def show() -> None:
            self.structure.show_structure(
                browse.columns, found["keys"], found["rows"], found["size"], found["definition"]
            )

        def described(result: StatementOutcome) -> None:
            for kind, text, _value, columns in result.rows:
                if kind == "definition":
                    found["definition"] = str(text or "")
                elif columns:
                    for name in columns:  # type: ignore[attr-defined]
                        keys = found["keys"]
                        keys[str(name)] = (keys.get(str(name), "") + " " + _key_text(str(text))).strip()
            show()

        def counted(result: StatementOutcome) -> None:
            found["rows"] = int(result.rows[0][0]) if result.rows else None
            show()

        def measured(result: StatementOutcome | BaseException) -> None:
            if (
                not self._closed
                and not isinstance(result, BaseException)
                and result.rows
                and result.rows[0][0]
            ):
                found["size"] = int(result.rows[0][0])
                show()

        fresh = lambda: self.browse is browse  # noqa: E731 - misma tabla, filtros y orden
        self._read(structure_sql(*self.source), 200, described, fresh)
        self._read(Browse(*self.source, browse.columns).count_sql(), 1, counted, fresh)  # filas de la tabla
        if not self.is_view:  # tamaño en disco; en memoria o sin guardar aún, no se muestra
            with contextlib.suppress(GeoDuckError):
                self._coordinator.read_rows(size_sql(*self.source), 1, measured)

    def _render_chips(self) -> None:
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()  # hasta borrarse sigue siendo hija de la barra: que no se vea
                item.widget().deleteLater()
        if self.browse is None:
            return
        for index, item in enumerate(self.browse.filters):
            column, op, value = item.label
            chip = Chip(column, op, value, self.colors, remove_tip=tr("Remove this filter"))
            chip.removed.connect(lambda i=index: self.remove_filter(i))
            chip.setVisible(self.mode.current == 0)
            self.chips.addWidget(chip)

    def _show_message(self, text: str, *, retry: bool = False, clear: bool = False) -> None:
        self.message.setText(text)
        self.retry_button.setVisible(retry)
        self.clear_button.setVisible(clear)
        self.body.setCurrentIndex(MESSAGE)
        self.detail.hide()
        if not clear:
            self.range_label.setText("")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)

    def _show_busy(self) -> None:
        self._show_message(tr("The session is busy; the table will load when it finishes."))

    # -- eventos --------------------------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if self._closed:
            return
        if isinstance(event, ColumnsListed) and event.source == self.source:
            self._columns_ready(event.columns)
        elif isinstance(event, ColumnsUnavailable) and event.source == self.source:
            self._show_message(tr("The table could not be read.") + f"\n{event.message}", retry=True)
        elif isinstance(event, PreviewsInvalidated) and self.browse is not None:
            self.reload(keep_offset=True)  # SQL del usuario cambió datos
        elif isinstance(event, CatalogChanged):
            self._pending = True  # las columnas pueden haber cambiado: se releen
            if event.catalog is not None and self._coordinator.state is SessionState.READY:
                self.load()
        elif isinstance(event, SessionStateChanged):
            if event.current is SessionState.READY and self._pending:
                self.load()
            elif event.current is SessionState.DISCONNECTED:
                self.browse = None
                self._show_message(tr("Start DuckDB to see this table."))

    def close_page(self) -> None:
        """La pestaña se cierra: deja de escuchar y descarta las respuestas que lleguen después."""
        self._closed = True
        self._unsubscribe()


def _key_text(kind: str) -> str:
    return {"PRIMARY KEY": tr("primary"), "UNIQUE": tr("unique")}.get(kind, kind.lower())
