# SPDX-License-Identifier: GPL-2.0-or-later
"""La grilla de datos de Workspace Pro: la de la pestaña de tabla y la del resultado de una consulta
(workspace-pro-spec §4, §5; #144).

Páginas de 100 filas que DuckDB lee bajo demanda (nunca todo), con el tipo bajo cada columna, el número de
fila, el detalle de la fila a la derecha y, desde #144, filtros (fila de casillas, chips, clic derecho y
barra `WHERE`), selección como en una hoja de cálculo, Ctrl+C con DuckDB, orden con ⇅ y el resumen de la
columna elegida. El SQL lo construye `domain.browse` (y `domain.filters`); aquí solo se pide y se muestra.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from qgis.PyQt.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    QStringListModel,
    Qt,
    QTimer,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QColor, QGuiApplication, QKeySequence, QPainter
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QScrollArea,
    QShortcut,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from geoduck.domain.browse import PAGE, Browse, Filter, geometry_summary
from geoduck.domain.catalog import ColumnInfo
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.filters import (
    EXCLUDE,
    FILTER,
    GREATER,
    LESS,
    NO_EMPTY,
    ONLY_EMPTY,
    FilterError,
    box_condition,
    cell_filters,
    comparable,
    preview,
    where_condition,
)
from geoduck.domain.i18n import get_language
from geoduck.domain.i18n import number as number_text
from geoduck.domain.i18n import rows as rows_text
from geoduck.domain.sql_text import quote_identifier
from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import Chip, button, icon_button, label, spacer

#: Ctrl+C de columnas enteras: hasta cuántos valores copia DuckDB; más, avisa y ofrece Exportar (#144).
COPY_LIMIT = 100_000
#: Pausa tras dejar de escribir en una casilla de filtro o en la barra `WHERE` antes de validarla.
TYPING_MS = 600
#: Pausa antes de pedir el resumen de la columna elegida (no uno por cada clic seguido).
SUMMARY_MS = 250
#: Alto de la fila de casillas de filtro bajo los encabezados.
FILTER_ROW = 30
GRID, MESSAGE = 0, 1
#: Palabras de la barra `WHERE` además de las columnas (autocompletado).
WHERE_WORDS = (
    "AND",
    "OR",
    "NOT",
    "IN",
    "LIKE",
    "ILIKE",
    "BETWEEN",
    "IS NULL",
    "IS NOT NULL",
    "TRUE",
    "FALSE",
    "lower",
    "upper",
    "length",
    "contains",
    "starts_with",
    "regexp_matches",
    "coalesce",
    "abs",
    "round",
    "year",
    "month",
    "date_trunc",
    "ST_Area",
    "ST_Length",
    "ST_Intersects",
    "ST_Contains",
    "ST_Within",
    "ST_DWithin",
    "ST_IsValid",
    "ST_X",
    "ST_Y",
    "ST_GeomFromText",
    "ST_Point",
)


def filter_help() -> str:
    """Lo que acepta una casilla de filtro (su ayuda)."""
    return tr(
        "Text: contains · >50, 10..50, =Sur · empty / not empty · /regex/ or /regex/i · "
        "SQL that starts with an operator: > 50 AND < 100, IN (1, 5), LIKE 'a%', BETWEEN, IS NULL"
    )


_NUMERIC = re.compile(
    r"^(U?(TINY|SMALL|BIG|HUGE)?INT|INTEGER|DOUBLE|FLOAT|REAL|DECIMAL|NUMERIC)", re.IGNORECASE
)
#: Caracteres de una celda en la grilla (el valor completo está en el detalle).
CELL = 300
#: Filas que se miden para el ancho de las columnas.
FIT_ROWS = 25


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
    # Medir solo las primeras filas (performance-spec §5: medir las 100 filas de cada columna era la mayor
    # parte de la pausa al mostrar una página); el ancho tiene tope de 360 px y la celda se puede ensanchar
    grid.horizontalHeader().setResizeContentsPrecision(FIT_ROWS)
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
        # Por columna, calculado una vez por página (data() se llama miles de veces al pintar)
        self._numeric: tuple[bool, ...] = ()
        self._align: tuple[int, ...] = ()
        self._texts: dict[tuple[int, int], str] = {}
        self._null = QColor(colors.null)
        self._muted = QColor(colors.muted)

    def set_page(
        self, columns: tuple[ColumnInfo, ...], rows: tuple[tuple[object, ...], ...], offset: int
    ) -> None:
        self.beginResetModel()
        self.columns, self.rows, self.offset = columns, rows, offset
        self._numeric = tuple(is_numeric(c.data_type) for c in columns)
        right = int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        left = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._align = tuple(right if n else left for n in self._numeric)
        self._texts = {}
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
        row, col = index.row(), index.column()
        value = self.rows[row][col]
        column = self.columns[col]
        numeric = self._numeric[col]
        answer: Any = None
        if role == Qt.ItemDataRole.DisplayRole:
            key = (row, col)
            answer = self._texts.get(key)
            if answer is None:
                answer = self._texts[key] = cell_text(value)
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            answer = self._align[col]
        elif role == Qt.ItemDataRole.ForegroundRole and (value is None or column.is_geometry):
            answer = self._null if value is None else self._muted
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
    """Encabezado de la grilla: nombre en negrita y tipo en gris. Al pasar el ratón, ⇅ a la derecha ordena
    (#144: ordenar pasa al icono; el clic en el nombre elige la columna entera); la columna ordenada lleva su
    flecha turquesa. Con `set_filters_visible(True)`, debajo de cada nombre su casilla de filtro (#144,
    punto 36): `box_edited(columna, texto)` al pulsar Intro o al dejar de escribir."""

    sort_requested = pyqtSignal(int)
    box_edited = pyqtSignal(str, str)

    def __init__(self, model: PageModel, colors: Colors) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.page_model = model
        self.colors = colors
        self.order: tuple[str, bool] | None = None
        self.sortable = True
        self.filters_visible = False
        self.boxes: dict[str, QLineEdit] = {}
        self._hover = -1
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.setDefaultSectionSize(160)
        self.setMinimumSectionSize(60)
        self.setMouseTracking(True)
        self.bold = ui_font(bold=True)
        self.mono = ui_font(METRICS.font_tiny, mono=True)
        self._arrows = {
            True: icons.pixmap("arrow-up", colors.accent, 12),
            False: icons.pixmap("arrow-down", colors.accent, 12),
        }
        self._sort_icon = icons.pixmap("sort", colors.faint, 13)
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(TYPING_MS)
        self._typing.timeout.connect(self._typed)
        self._typed_box: QLineEdit | None = None
        for signal in (self.sectionResized, self.sectionMoved, self.geometriesChanged):
            signal.connect(lambda *_a: self.place_boxes())

    # -- casillas de filtro -----------------------------------------------------------------------------

    def set_filters_visible(self, visible: bool) -> None:
        self.filters_visible = visible
        self.updateGeometries()
        self.place_boxes()
        self.viewport().update()

    def set_columns(self, texts: dict[str, str]) -> None:
        """Una casilla por columna del modelo, con el texto de su filtro (las de otras columnas se van)."""
        names = [c.name for c in self.page_model.columns]
        for name in [n for n in self.boxes if n not in names]:
            self.boxes.pop(name).deleteLater()
        for name in names:
            box = self.boxes.get(name)
            if box is None:
                box = QLineEdit(self.viewport())
                box.setProperty("pro", "filter-box")
                box.setPlaceholderText(tr("filter…"))
                box.setAccessibleName(tr("Filter of {}").format(name))
                box.returnPressed.connect(lambda b=box, n=name: self._commit(n, b))
                box.textEdited.connect(lambda _t, b=box: self._edited(b))
                self.boxes[name] = box
            self.set_box(name, texts.get(name, ""))
        self.place_boxes()

    def set_box(self, name: str, text: str | None, *, error: str = "") -> None:
        """El texto de la casilla de `name` (`None`: lo deja) y su estado: turquesa si filtra, rojo con
        `error` (el último filtro válido sigue aplicado)."""
        box = self.boxes.get(name)
        if box is None:
            return
        if text is not None and box.text() != text:
            box.setText(text)
        _set_state(box, active=bool(box.text().strip()) and not error, invalid=bool(error))
        box.setToolTip(("✕ " + error + "\n\n" if error else "") + filter_help())

    def _edited(self, box: QLineEdit) -> None:
        self._typed_box = box
        self._typing.start()

    def _typed(self) -> None:
        box = self._typed_box
        name = next((n for n, b in self.boxes.items() if b is box), None)
        if box is not None and name is not None:
            self._commit(name, box)

    def _commit(self, name: str, box: QLineEdit) -> None:
        self._typing.stop()
        self.box_edited.emit(name, box.text())

    def place_boxes(self) -> None:
        """Cada casilla bajo su columna, con su ancho; ocultas si la fila de filtros está apagada."""
        for index, column in enumerate(self.page_model.columns):
            box = self.boxes.get(column.name)
            if box is None:
                continue
            if not self.filters_visible or self.isSectionHidden(index):
                box.hide()
                continue
            x = self.sectionViewportPosition(index)
            width = max(20, self.sectionSize(index) - 8)
            box.setGeometry(x + 4, METRICS.header + 3, width, FILTER_ROW - 7)
            box.show()

    # -- dibujo y ratón ---------------------------------------------------------------------------------

    def _sort_rect(self, index: int) -> QRect:
        x = self.sectionViewportPosition(index)
        return QRect(x + self.sectionSize(index) - 26, 0, 22, METRICS.header)

    def section_at_sort(self, pos: QPoint) -> int:
        """La columna cuyo ⇅ está bajo `pos`, o -1."""
        if not self.sortable or pos.y() >= METRICS.header:
            return -1
        index = self.logicalIndexAt(pos)
        return index if index >= 0 and self._sort_rect(index).contains(pos) else -1

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        index = self.logicalIndexAt(event.pos()) if event.pos().y() < METRICS.header else -1
        if index != self._hover:
            self._hover = index
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        self._hover = -1
        self.viewport().update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if event.pos().y() >= METRICS.header:
            return  # la fila de filtros: solo sus casillas
        sort = self.section_at_sort(event.pos())
        if sort >= 0 and event.button() == Qt.MouseButton.LeftButton:
            self.sort_requested.emit(sort)  # ⇅ ordena y no elige la columna
            return
        super().mousePressEvent(event)

    def paintSection(self, painter: QPainter, rect: QRect, index: int) -> None:  # noqa: N802
        if index >= len(self.page_model.columns):
            return
        c = self.colors
        column = self.page_model.columns[index]
        chosen = self._column_selected(index)
        painter.save()
        painter.fillRect(rect, QColor(c.head))
        top = QRect(rect.left(), rect.top(), rect.width(), METRICS.header)
        if chosen:
            painter.fillRect(top, QColor(c.accent_soft))
        painter.setPen(QColor(c.border))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setPen(QColor(c.line))
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        inner = top.adjusted(10, 0, -8, 0)
        if self.order is not None and self.order[0] == column.name:
            arrow = self._arrows[self.order[1]]
            painter.drawPixmap(inner.right() - 12, inner.center().y() - 6, arrow)
            inner.setRight(inner.right() - 16)
        elif self.sortable and index == self._hover:
            painter.drawPixmap(inner.right() - 13, inner.center().y() - 6, self._sort_icon)
            inner.setRight(inner.right() - 16)
        painter.setFont(self.bold)
        painter.setPen(QColor(c.accent if chosen else c.text))
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

    def _column_selected(self, index: int) -> bool:
        view = self.parent()
        selection = view.selectionModel() if hasattr(view, "selectionModel") else None
        return bool(selection is not None and self.page_model.rows and selection.isColumnSelected(index))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), METRICS.header + (FILTER_ROW if self.filters_visible else 0))


def _set_state(widget: QWidget, **flags: bool) -> None:
    """Propiedades de estilo (`active`, `invalid`) y que la hoja de estilos las vuelva a leer."""
    for name, value in flags.items():
        widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class DetailPanel(QFrame):
    """Panel derecho: cada campo con su tipo y su valor completo; la geometría, resumida; copiar. Sigue a la
    celda elegida (clic o ↑ ↓) y se abre o cierra solo con el icono ◫ de su barra (#144, punto 8)."""

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
        row.addWidget(self.title, 1)  # sin ✕: se muestra u oculta con su icono ◫ (#144, punto 8)
        box.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setProperty("pro", "plain")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        box.addWidget(self.scroll, 1)
        self.fields: list[tuple[str, str]] = []
        self._shown: tuple[Any, ...] | None = None
        self._pending: tuple[Any, ...] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._build)

    def show_row(self, number: int, columns: tuple[ColumnInfo, ...], values: tuple[object, ...]) -> None:
        """Muestra la fila en la siguiente vuelta del bucle de eventos (performance-spec §5): primero se pinta
        la grilla y después el detalle, en dos pausas cortas y no una larga. Si llegan varias filas seguidas,
        solo se construye la última, y la misma fila no se reconstruye."""
        self.title.setText(tr("Row {}").format(number_text(number)))
        key = (number, columns, values)
        if key == self._shown:
            return
        self._pending = key
        if not self._timer.isActive():
            self._timer.start()

    def _build(self) -> None:
        if self._pending is None:
            return
        number, columns, values = self._pending
        self._pending = None
        self._shown = (number, columns, values)
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
            count = tr("1 vertex") if vertices == 1 else tr("{} vertices").format(number_text(vertices))
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


# -- la grilla con filtros, selección y detalle (#144) ---------------------------------------------------


class _MenuRow(QFrame):
    """Una opción del clic derecho en celdas: lo que hace y, debajo, la condición exacta que aplicará."""

    picked = pyqtSignal()

    def __init__(self, title: str, detail: str, *, enabled: bool = True) -> None:
        super().__init__()
        self.setProperty("pro", "menu-row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setEnabled(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.setAccessibleName(f"{title}: {detail}" if detail else title)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 6, 14, 6)
        box.setSpacing(1)
        name = label(title, None if enabled else "faint")
        box.addWidget(name)
        if detail:
            short = detail if len(detail) <= 70 else detail[:69] + "…"
            text = label(short, "mono" if enabled else "faint")
            text.setFont(ui_font(METRICS.font_tiny, mono=enabled))
            text.setToolTip(detail)
            box.addWidget(text)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit()


class WhereEdit(QLineEdit):
    """La barra `WHERE` (#144, punto 36): SQL libre con autocompletado de columnas, palabras y funciones
    (Ctrl+Espacio, o al escribir)."""

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("pro", "where")
        self.setPlaceholderText(tr("SQL condition… (Ctrl+Space: columns and functions)"))
        self.setAccessibleName(tr("WHERE condition"))
        self.words = QStringListModel(list(WHERE_WORDS), self)
        self.completer = QCompleter(self.words, self)
        self.completer.setWidget(self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.activated.connect(self._insert)

    def set_columns(self, names: list[str]) -> None:
        quoted = [n if re.match(r"^[a-z_][a-z0-9_]*$", n) else quote_identifier(n) for n in names]
        self.words.setStringList(quoted + list(WHERE_WORDS))

    def _word(self) -> tuple[int, str]:
        text = self.text()[: self.cursorPosition()]
        found = re.search(r'[\w"]+$', text)
        return (found.start(), found.group(0)) if found else (len(text), "")

    def _insert(self, word: str) -> None:
        start, current = self._word()
        text = self.text()
        end = start + len(current)
        self.setText(text[:start] + word + text[end:])
        self.setCursorPosition(start + len(word))

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        popup = self.completer.popup()
        if popup.isVisible() and event.key() in (
            Qt.Key.Key_Enter,
            Qt.Key.Key_Return,
            Qt.Key.Key_Escape,
            Qt.Key.Key_Tab,
        ):
            event.ignore()  # la lista las usa
            return
        forced = event.key() == Qt.Key.Key_Space and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if not forced:
            super().keyPressEvent(event)
        _start, word = self._word()
        if forced or len(word) >= 2:
            self.completer.setCompletionPrefix(word)
            if self.completer.completionCount():
                rect = self.cursorRect()
                rect.setWidth(260)
                self.completer.complete(rect)
                return
        popup.hide()


class DataGrid(QWidget):
    """La grilla de datos de la pestaña de tabla y del resultado de una consulta (#144): páginas de 100 filas
    que DuckDB lee bajo demanda, y sobre ellas

    - **filtros** (punto 36): la fila de casillas bajo los encabezados (embudo para mostrarla), los chips, el
      clic derecho en las celdas y la barra `WHERE`; todo se une con Y, lo valida DuckDB antes de aplicarlo
      (un error queda en rojo y sigue el último filtro válido) y lo ejecuta DuckDB por páginas;
    - **selección como en una hoja de cálculo** (punto 9): celda, columna (clic en su nombre), fila (clic en
      su número), Mayús/Ctrl y Ctrl+A; la selección de columnas enteras es lógica (no trae los datos); Ctrl+C
      copia lo elegido y, con columnas enteras, lo lee DuckDB (más de `COPY_LIMIT` valores: avisa y ofrece
      Exportar); ordenar, con el ⇅ del encabezado;
    - **detalle de la fila** (punto 8): sigue a la celda elegida (clic o ↑ ↓), sin ✕;
    - **resumen de la columna elegida** (punto 11): suma, promedio, mínimo, máximo y nulos, de DuckDB sobre
      todas las filas filtradas (`summary`).

    `read(sql, filas, hecho)` pide una lectura al motor y devuelve `False` si está ocupado; `hecho` recibe el
    resultado o la excepción. `changed()` avisa al anfitrión (pie, botones) de una página, total o filtro
    nuevos."""

    changed = pyqtSignal()

    def __init__(
        self,
        colors: Colors,
        read: Callable[[str, int, Callable[[Any], None]], bool],
        *,
        name: str = "",
        notify: Callable[[str], None] | None = None,
        offer_export: Callable[[], None] | None = None,
        view_sql: Callable[[str], object] | None = None,
        always_show_bar: bool = True,
    ) -> None:
        super().__init__()
        self.colors = colors
        self._read_fn = read
        self._notify = notify or (lambda _text: None)
        self._offer_export = offer_export
        self._view_sql = view_sql
        self.always_show_bar = always_show_bar
        self.browse: Browse | None = None
        self.offset = 0
        self.total: int | None = None
        self.base_total: int | None = None
        self.replayable = True
        self.detail_open = True
        self.filters_open = always_show_bar
        self.pending = False
        self.closed = False
        self.compact = False
        self.summary = ""
        self.empty_text = tr("This table has no rows.")
        self.error_text = tr("The table could not be read.")
        self.busy_text = tr("The session is busy; the table will load when it finishes.")
        self._generation = 0
        self._where_typing = QTimer(self)
        self._where_typing.setSingleShot(True)
        self._where_typing.setInterval(TYPING_MS)
        self._where_typing.timeout.connect(self.apply_where)
        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.setInterval(SUMMARY_MS)
        self._summary_timer.timeout.connect(self._read_summary)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self._build_bar())
        middle = QWidget()
        side = QHBoxLayout(middle)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        self.body = QStackedWidget()
        self.body.addWidget(self._build_grid(name))
        self.body.addWidget(self._build_message())
        side.addWidget(self.body, 1)
        self.detail = DetailPanel(colors)
        self.detail.hide()
        side.addWidget(self.detail)
        box.addWidget(middle, 1)
        self.set_filters_open(self.filters_open)

    # -- construcción ---------------------------------------------------------------------------------

    def _build_bar(self) -> QWidget:
        self.filter_bar = QFrame()
        self.filter_bar.setProperty("pro", "rule-bottom")
        outer = QVBoxLayout(self.filter_bar)
        outer.setContentsMargins(16, 8, 12, 8)
        outer.setSpacing(6)
        self.where_row = QWidget()
        where = QHBoxLayout(self.where_row)
        where.setContentsMargins(0, 0, 0, 0)
        where.setSpacing(8)
        keyword = label("WHERE", "accent")
        keyword.setFont(ui_font(METRICS.font_small, mono=True, bold=True))
        where.addWidget(keyword)
        self.where_edit = WhereEdit()
        self.where_edit.textEdited.connect(lambda _t: self._where_typing.start())
        self.where_edit.returnPressed.connect(self.apply_where)
        where.addWidget(self.where_edit, 1)
        outer.addWidget(self.where_row)
        self.where_error = label("", "error")
        self.where_error.setWordWrap(True)
        self.where_error.hide()
        outer.addWidget(self.where_error)
        row = QHBoxLayout()
        row.setSpacing(8)
        outer.addLayout(row)  # antes de sus widgets: sin padre, uno visible sería una ventana suelta
        self.chips = QHBoxLayout()
        self.chips.setSpacing(8)
        row.addLayout(self.chips)
        self.count_label = label("", "muted")
        row.addWidget(self.count_label)
        self.funnel_button = icon_button(
            "filter", tr("Show or hide the filters under each column"), self.colors
        )
        self.funnel_button.setIcon(icons.toggle("filter", self.colors.muted, self.colors.accent))
        self.funnel_button.setCheckable(True)
        self.funnel_button.toggled.connect(self.set_filters_open)
        row.addWidget(self.funnel_button)
        self.sql_button = icon_button(  # solo icono, también en la ventana (propietario, 2026-11-13)
            "sql", tr("Opens the full query, with its filters and order, in a new query tab"), self.colors
        )
        self.sql_button.clicked.connect(self.view_sql)
        row.addWidget(self.sql_button)
        self.sql_button.setVisible(self._view_sql is not None)
        row.addWidget(spacer(), 1)
        self.tools = QHBoxLayout()
        self.tools.setSpacing(8)
        row.addLayout(self.tools)
        return self.filter_bar

    def add_tool(self, widget: QWidget) -> None:
        """Un control del anfitrión a la derecha de la fila de chips (búsqueda, estructura, detalle)."""
        self.tools.addWidget(widget)

    def _build_grid(self, name: str) -> QWidget:
        self.model = PageModel(self.colors)
        self.grid = QTableView()
        self.grid.setProperty("pro", "grid")
        self.grid.setModel(self.model)
        self.header = TypeHeader(self.model, self.colors)
        self.grid.setHorizontalHeader(self.header)
        self.header.sort_requested.connect(self.sort_by)
        self.header.box_edited.connect(self.apply_box)
        self.grid.horizontalScrollBar().valueChanged.connect(lambda _v: QTimer.singleShot(0, self._place))
        self.grid.setShowGrid(False)
        self.grid.setWordWrap(False)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self.cell_menu)
        if name:
            self.grid.setAccessibleName(tr("Rows of {}").format(name))
        vertical = self.grid.verticalHeader()
        vertical.setDefaultSectionSize(METRICS.row)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vertical.setMinimumWidth(48)
        vertical.setHighlightSections(True)
        selection = self.grid.selectionModel()
        selection.currentRowChanged.connect(lambda current, _prev: self._row_changed(current.row()))
        selection.selectionChanged.connect(lambda *_a: self._selection_changed())
        copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.grid)
        copy.setContext(Qt.ShortcutContext.WidgetShortcut)
        copy.activated.connect(self.copy_selection)
        return self.grid

    def _build_message(self) -> QWidget:
        message = QWidget()
        box = QVBoxLayout(message)
        box.addStretch(1)
        self.message = label("", "muted")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        box.addWidget(self.message)
        actions = QHBoxLayout()
        box.addLayout(actions)
        actions.addStretch(1)
        self.retry_button = button(tr("Try again"))
        self.retry_button.clicked.connect(lambda: self.reload(keep_offset=True))
        self.clear_button = button(tr("Clear filters"))
        self.clear_button.clicked.connect(self.clear_filters)
        actions.addWidget(self.retry_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        box.addStretch(1)
        return message

    # -- lecturas -------------------------------------------------------------------------------------

    def _read(
        self,
        sql: str,
        max_rows: int,
        done: Callable[[Any], None],
        fresh: Callable[[], bool] | None = None,
        *,
        quiet: bool = False,
    ) -> bool:
        """Pide una lectura; `done` solo la recibe si sigue valiendo (`fresh`; por defecto, si no hubo otra
        página, filtro u orden después). Un error de una lectura de página se muestra en la grilla; con
        `quiet`, `done` recibe también la excepción."""
        generation = self._generation
        still = fresh or (lambda: generation == self._generation)

        def answer(result: Any) -> None:
            if self.closed or not still():
                return
            if isinstance(result, BaseException) and not quiet:
                text = result.message if isinstance(result, GeoDuckError) else str(result)
                self.show_message(self.error_text + f"\n{text}", retry=True)
                return
            done(result)

        try:
            return bool(self._read_fn(sql, max_rows, answer))
        except GeoDuckError:
            return False

    def set_browse(
        self,
        browse: Browse,
        *,
        rows: tuple[tuple[object, ...], ...] | None = None,
        total: int | None = None,
        replayable: bool = True,
    ) -> None:
        """Muestra `browse`. Con `rows` (la primera página que trajo la ejecución de una consulta), sin leer
        nada; el total, si no se sabe, lo cuenta DuckDB aparte."""
        self.replayable = replayable
        self.browse = browse
        self.header.sortable = replayable
        self.funnel_button.setEnabled(replayable)
        self.where_edit.set_columns([c.name for c in browse.columns])
        if rows is None or browse.filtered or browse.order is not None:
            self.reload()
            return
        self.offset = 0
        self.total = total
        self.base_total = total
        self._generation += 1
        self._render_filters()
        self._show_page(browse, rows)
        if total is None and replayable:
            self._read(browse.count_sql(), 1, self._counted, fresh=lambda: self.browse is browse, quiet=True)
        self.changed.emit()

    def reload(self, *, keep_offset: bool = False) -> None:
        """Vuelve a leer la página (y el total) con los filtros y el orden actuales."""
        browse = self.browse
        if browse is None or self.closed:
            return
        if not keep_offset:
            self.offset = 0
        self._generation += 1
        self.total = None
        self._render_filters()
        if not self.replayable:
            return
        if self._read(browse.page_sql(self.offset), PAGE, lambda r: self._page_read(browse, r)):
            fresh = lambda: self.browse is browse  # noqa: E731 - el total vale mientras no cambie el filtro
            self._read(browse.count_sql(), 1, self._counted, fresh, quiet=True)
            if browse.filtered and self.base_total is None:
                self._read(browse.total_sql(), 1, self._base_counted, quiet=True, fresh=lambda: True)
            self.pending = False
        else:
            self.pending = True
            self.show_message(self.busy_text)
        self.changed.emit()

    def go(self, offset: int) -> None:
        browse = self.browse
        if browse is None or not self.replayable:
            return
        offset = max(0, offset)
        if self.total is not None and offset >= self.total:
            return
        self.offset = offset
        self._generation += 1
        self._read(browse.page_sql(offset), PAGE, lambda r: self._page_read(browse, r))

    def _page_read(self, browse: Browse, result: Any) -> None:
        if not result.rows and self.offset > 0:
            self.go(self.offset - PAGE)  # la última página quedó vacía (filas borradas)
            return
        self._show_page(browse, result.rows)
        self.changed.emit()

    def _show_page(self, browse: Browse, rows: tuple[tuple[object, ...], ...]) -> None:
        self.model.set_page(browse.columns, rows, self.offset)
        fit_columns(self.grid, self.model)
        self.header.set_columns(dict(browse.boxes))
        self._place()
        if rows:
            self.body.setCurrentIndex(GRID)
            self.grid.setCurrentIndex(self.model.index(0, 0))  # el detalle muestra la primera fila
            self.grid.clearSelection()
        elif browse.filtered:
            self.show_message(tr("No rows match these filters."), clear=True)
        else:
            self.show_message(self.empty_text)
        self._row_changed(0 if rows else -1)

    def _counted(self, result: Any) -> None:
        if isinstance(result, BaseException):
            return  # sin total: el pie sigue con «de …»
        self.total = int(result.rows[0][0]) if result.rows else 0
        if self.browse is not None and not self.browse.filtered:
            self.base_total = self.total
        self._update_count()
        self.changed.emit()

    def _base_counted(self, result: Any) -> None:
        if not isinstance(result, BaseException):
            self.base_total = int(result.rows[0][0]) if result.rows else 0
            self._update_count()

    def show_message(self, text: str, *, retry: bool = False, clear: bool = False) -> None:
        self.message.setText(text)
        self.retry_button.setVisible(retry)
        self.clear_button.setVisible(clear)
        self.body.setCurrentIndex(MESSAGE)
        self.detail.hide()

    def clear(self, text: str = "") -> None:
        """Sin datos (otra sesión, una consulta sin tabla): la grilla vacía y el mensaje."""
        self._generation += 1
        self.browse = None
        self.total = self.base_total = None
        self.offset = 0
        self.model.set_page((), (), 0)
        self.header.set_columns({})
        self._render_filters()
        self.show_message(text)

    # -- filtros --------------------------------------------------------------------------------------

    def set_filters_open(self, open_: bool) -> None:
        """El embudo: la fila de casillas bajo los encabezados y la barra `WHERE`."""
        self.filters_open = open_ and self.replayable
        if self.funnel_button.isChecked() != self.filters_open:
            self.funnel_button.blockSignals(True)
            self.funnel_button.setChecked(self.filters_open)
            self.funnel_button.blockSignals(False)
        self.header.set_filters_visible(self.filters_open)
        self.where_row.setVisible(self.filters_open)
        self.where_error.setVisible(self.filters_open and bool(self.where_error.text()))
        self._update_bar()
        QTimer.singleShot(0, self._place)

    def _place(self) -> None:
        if not self.closed:
            self.header.place_boxes()

    def apply_box(self, name: str, text: str) -> None:
        """La casilla de `name`: si DuckDB la entiende, filtra; si no, queda en rojo con el motivo y sigue
        el último filtro válido."""
        browse = self.browse
        column = next((c for c in browse.columns if c.name == name), None) if browse else None
        if browse is None or column is None:
            return
        text = text.strip()
        if text == browse.box(name):
            self.header.set_box(name, None)
            return
        try:
            condition = box_condition(column, text)
        except FilterError as exc:
            self.header.set_box(name, None, error=exc.message)
            return

        def apply() -> None:
            if self.browse is not None:
                self.header.set_box(name, None)
                self.browse = self.browse.with_box(name, text)
                self.reload()

        if condition is None:
            apply()
        else:
            self._validate(condition.sql, apply, lambda error: self.header.set_box(name, None, error=error))

    def apply_where(self) -> None:
        """La barra `WHERE`: la valida DuckDB; con error, en rojo y con el último filtro válido."""
        self._where_typing.stop()
        browse = self.browse
        if browse is None:
            return
        text = self.where_edit.text().strip()
        if text == browse.where:
            self._where_state("")
            return
        try:
            condition = where_condition(text)
        except FilterError as exc:
            self._where_state(exc.message)
            return

        def apply() -> None:
            if self.browse is not None:
                self._where_state("")
                self.browse = self.browse.with_where(text)
                self.reload()

        if condition is None:
            apply()
        else:
            self._validate(condition.sql, apply, self._where_state)

    def _where_state(self, error: str) -> None:
        _set_state(self.where_edit, invalid=bool(error))
        text = "✕ " + error + " · " + tr("the rows keep the last valid filter") if error else ""
        self.where_error.setText(text)
        self.where_error.setVisible(bool(error) and self.filters_open)

    def _validate(self, condition: str, ok: Callable[[], None], fail: Callable[[str], None]) -> None:
        """DuckDB dice si la condición vale aquí (sin leer filas)."""
        browse = self.browse
        if browse is None:
            return

        def done(result: Any) -> None:
            if isinstance(result, BaseException):
                text = result.message if isinstance(result, GeoDuckError) else str(result)
                fail(text.strip().splitlines()[0] if text.strip() else text)
            else:
                ok()

        if not self._read(browse.check_sql(condition), 1, done, fresh=lambda: True, quiet=True):
            fail(tr("GeoDuck is busy: try again when it finishes"))

    def apply_cells(self, cells: list[tuple[ColumnInfo, object]], action: str) -> None:
        """Clic derecho en celdas (#144): sus casillas toman la condición; excluir de varias columnas es una
        condición aparte."""
        if self.browse is None:
            return
        try:
            boxes, extra = cell_filters(cells, action)
        except FilterError as exc:
            self._notify(exc.message)
            return
        browse = self.browse
        for name, text in boxes.items():
            browse = browse.with_box(name, text)
        if extra is not None:
            browse = browse.with_extra(extra)
        self.browse = browse
        self.reload()

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
            self.where_edit.clear()
            self._where_state("")
            self.browse = self.browse.cleared()
            self.reload()

    def sort_by(self, section: int) -> None:
        if self.browse is not None and self.replayable and 0 <= section < len(self.browse.columns):
            self.browse = self.browse.next_order(self.browse.columns[section].name)
            self.reload()

    def view_sql(self) -> None:
        if self.browse is not None and self._view_sql is not None:
            self._view_sql(self.browse.display_sql())

    def _render_filters(self) -> None:
        """Los chips (uno por casilla, por exclusión y por la barra `WHERE`), el orden y el contador."""
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()  # hasta borrarse sigue siendo hija de la barra: que no se vea
                item.widget().deleteLater()
        browse = self.browse
        self.header.order = browse.order if browse else None
        self.header.viewport().update()
        if browse is None:
            self._update_bar()
            return
        tip = tr("Remove this filter")
        for index, item in enumerate(browse.filters):
            column, op, value = item.label
            chip = Chip(column, op, value, self.colors, remove_tip=tip)
            chip.removed.connect(lambda i=index: self.remove_filter(i))
            self.chips.addWidget(chip)
        for condition in browse.box_conditions():
            chip = Chip("", "", "", self.colors, remove_tip=tip, text=condition.label)
            chip.removed.connect(lambda n=condition.column: self._remove_box(n))
            self.chips.addWidget(chip)
        for index, condition in enumerate(browse.extra):
            chip = Chip("", "", "", self.colors, remove_tip=tip, text=condition.label)
            chip.removed.connect(lambda i=index: self._remove_extra(i))
            self.chips.addWidget(chip)
        where = where_condition(browse.where) if browse.where else None
        if where is not None:
            chip = Chip("", "", "", self.colors, remove_tip=tip, text=where.label)
            chip.removed.connect(self._remove_where)
            self.chips.addWidget(chip)
        if self.where_edit.text().strip() != browse.where and not self.where_edit.hasFocus():
            self.where_edit.setText(browse.where)
        self._update_count()
        self._update_bar()

    def _remove_box(self, name: str) -> None:
        if self.browse is not None:
            self.header.set_box(name, "")
            self.browse = self.browse.with_box(name, "")
            self.reload()

    def _remove_extra(self, index: int) -> None:
        if self.browse is not None:
            self.browse = self.browse.without_extra(index)
            self.reload()

    def _remove_where(self) -> None:
        if self.browse is not None:
            self.where_edit.clear()
            self._where_state("")
            self.browse = self.browse.with_where("")
            self.reload()

    def _update_count(self) -> None:
        """«1 234 de 1 000 000 filas», solo con filtros (sin ellos, el pie lo dice)."""
        browse = self.browse
        if browse is None or not browse.filtered or self.total is None:
            self.count_label.setText("")
            self.count_label.hide()
            return
        shown = number_text(self.total)
        if self.base_total is None:
            text = rows_text(self.total)
        else:
            text = tr("{0} of {1} rows").format(shown, number_text(self.base_total))
        self.count_label.setText(text)
        self.count_label.show()

    def _update_bar(self) -> None:
        filtered = self.browse is not None and self.browse.filtered
        self.filter_bar.setVisible(self.always_show_bar or self.filters_open or filtered)

    # -- selección, copia y resumen ---------------------------------------------------------------------

    def whole_columns(self) -> list[int]:
        """Columnas elegidas enteras (clic en el nombre, Ctrl+A): una selección lógica de todas las filas."""
        selection = self.grid.selectionModel()
        if not self.model.rows:
            return []
        return [c for c in range(self.model.columnCount()) if selection.isColumnSelected(c, QModelIndex())]

    def selected_cells(self) -> list[tuple[ColumnInfo, object]]:
        indexes = sorted(self.grid.selectedIndexes(), key=lambda i: (i.row(), i.column()))
        return [(self.model.columns[i.column()], self.model.rows[i.row()][i.column()]) for i in indexes]

    def copy_selection(self) -> None:
        """Ctrl+C: lo elegido, separado por tabuladores (como una hoja de cálculo). Columnas enteras de un
        resultado más largo que la página: las lee DuckDB; más de `COPY_LIMIT` valores, avisa y ofrece
        Exportar. Sin nada elegido, la página con los nombres de las columnas."""
        browse = self.browse
        whole = self.whole_columns()
        longer = self.total is None or self.total > len(self.model.rows) or self.offset > 0
        if browse is not None and whole and self.replayable and longer:
            names = tuple(self.model.columns[c].name for c in whole)
            limit = COPY_LIMIT // len(names)

            def copied(result: Any) -> None:
                if isinstance(result, BaseException):
                    self._notify(result.message if isinstance(result, GeoDuckError) else str(result))
                elif len(result.rows) > limit:
                    self._too_many()
                else:
                    _clipboard(list(result.rows))
                    self._notify(_copied_text(len(result.rows)))

            if self.total is not None and self.total * len(names) > COPY_LIMIT:
                self._too_many()
            elif not self._read(browse.values_sql(names, limit + 1), limit + 1, copied, quiet=True):
                self._notify(tr("GeoDuck is busy: try again when it finishes"))
            return
        indexes = sorted(self.grid.selectedIndexes(), key=lambda i: (i.row(), i.column()))
        if not indexes:
            if self.model.rows:
                _clipboard([tuple(c.name for c in self.model.columns), *self.model.rows])
                self._notify(_copied_text(len(self.model.rows)))
            return
        rows: dict[int, list[object]] = {}
        for index in indexes:
            rows.setdefault(index.row(), []).append(self.model.rows[index.row()][index.column()])
        _clipboard([tuple(values) for values in rows.values()])

    def _too_many(self) -> None:
        self._notify(
            tr("More than {} values: too many to copy. Export them instead.").format(number_text(COPY_LIMIT))
        )
        if self._offer_export is not None:
            self._offer_export()

    def _selection_changed(self) -> None:
        self.header.viewport().update()  # el nombre de la columna elegida, en turquesa
        whole = self.whole_columns()
        if len(whole) == 1 and self.replayable and self.browse is not None:
            self._summary_timer.start()
        elif self.summary:
            self.summary = ""
            self.changed.emit()

    def _read_summary(self) -> None:
        """Resumen de la columna elegida (#144, punto 11), sobre todas las filas filtradas."""
        whole = self.whole_columns()
        browse = self.browse
        if len(whole) != 1 or browse is None:
            return
        column = self.model.columns[whole[0]]

        def done(result: Any) -> None:
            if isinstance(result, BaseException) or not result.rows or self.whole_columns() != whole:
                return
            self.summary = summary_text(column, result.rows[0])
            self.changed.emit()

        self._read(browse.summary_sql(column), 1, done, quiet=True)

    # -- clic derecho ---------------------------------------------------------------------------------

    def cell_menu(self, pos: QPoint) -> QMenu | None:
        """Filtrar o excluir estos valores, mayor o menor, vacíos y copiar; cada opción muestra la condición
        exacta antes de aplicarla. Sobre una celda fuera de la selección, solo esa celda."""
        index = self.grid.indexAt(pos)
        if not index.isValid():
            return None
        if not self.grid.selectionModel().isSelected(index):
            self.grid.setCurrentIndex(index)
            self.grid.selectionModel().select(index, self.grid.selectionModel().SelectionFlag.ClearAndSelect)
        cells = self.selected_cells() or [
            (self.model.columns[index.column()], self.model.rows[index.row()][index.column()])
        ]
        names = list(dict.fromkeys(column.name for column, _v in cells))
        menu = QMenu(self)
        menu.setProperty("pro", "load-menu")
        count = tr("1 cell") if len(cells) == 1 else tr("{} cells").format(len(cells))
        head = QWidgetAction(menu)
        caption = label(f"{count} · {', '.join(names)}", "faint")
        caption.setContentsMargins(12, 6, 12, 4)
        head.setDefaultWidget(caption)
        head.setEnabled(False)
        menu.addAction(head)
        one = len(names) == 1
        compare = one and comparable(cells[0][0]) and any(v is not None for _c, v in cells)
        options = [
            (FILTER, tr("Filter by these values") if len(cells) > 1 else tr("Filter by this value"), True),
            (EXCLUDE, tr("Exclude these values") if len(cells) > 1 else tr("Exclude this value"), True),
            None,
            (GREATER, tr("Greater than this value"), compare),
            (LESS, tr("Less than this value"), compare),
            (ONLY_EMPTY, tr("Only empty"), True),
            (NO_EMPTY, tr("Without empty"), True),
        ]
        for option in options:
            if option is None:
                menu.addSeparator()
                continue
            action_name, title, enabled = option
            enabled = enabled and self.replayable
            detail = preview(cells, action_name) if enabled else ""
            self._menu_row(menu, title, detail, enabled, lambda a=action_name: self.apply_cells(cells, a))
        menu.addSeparator()
        copy = menu.addAction(tr("Copy") + "\tCtrl+C")
        copy.triggered.connect(lambda _c=False: self.copy_selection())
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(self.grid.viewport().mapToGlobal(pos))
        self.last_menu = menu
        return menu

    @staticmethod
    def _menu_row(menu: QMenu, title: str, detail: str, enabled: bool, run: Callable[[], None]) -> None:
        row = _MenuRow(title, detail, enabled=enabled)
        action = QWidgetAction(menu)
        action.setDefaultWidget(row)
        action.setText(title)
        action.setEnabled(enabled)
        action.triggered.connect(lambda _c=False: run())
        row.picked.connect(action.trigger)
        row.picked.connect(menu.close)
        menu.addAction(action)

    # -- detalle --------------------------------------------------------------------------------------

    def set_detail_open(self, open_: bool) -> None:
        self.detail_open = open_
        self._row_changed(self.grid.currentIndex().row())

    def _row_changed(self, row: int) -> None:
        browse = self.browse
        if not self.detail_open or row < 0 or row >= len(self.model.rows) or browse is None:
            self.detail.hide()
            return
        if self.body.currentIndex() != GRID:
            self.detail.hide()
            return
        self.detail.show()
        number = self.offset + row + 1
        self.detail.show_row(number, self.model.columns, self.model.rows[row])
        if self.replayable and any(c.is_geometry for c in self.model.columns):
            offset = self.offset

            def done(result: Any) -> None:  # la geometría completa, para resumirla bien
                current = self.grid.currentIndex().row() == row
                if not isinstance(result, BaseException) and result.rows and current:
                    self.detail.show_row(number, browse.columns, result.rows[0])

            if offset == self.offset:
                self._read(browse.row_sql(offset + row), 1, done, quiet=True)

    # -- modo compacto --------------------------------------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        self.compact = compact
        self.filter_bar.layout().setContentsMargins(8 if compact else 16, 8, 8 if compact else 12, 8)

    def close_grid(self) -> None:
        self.closed = True
        self._where_typing.stop()
        self._summary_timer.stop()


def _clipboard(lines: list[tuple[object, ...]]) -> None:
    QGuiApplication.clipboard().setText(
        "\n".join("\t".join("" if v is None else str(v) for v in values) for values in lines)
    )


def _copied_text(rows: int) -> str:
    return tr("1 row copied") if rows == 1 else tr("{} rows copied").format(number_text(rows))


def _number(value: object) -> str:
    if isinstance(value, float):
        text = format(value, ",.6g") if abs(value) >= 1e15 else f"{value:,.4f}".rstrip("0").rstrip(".")
    elif isinstance(value, int):
        text = f"{value:,}"
    else:
        text = str(value)
    if get_language() != "es":
        return text
    return text.replace(",", " ").replace(".", ",")  # «1 234,5» (#149)


def summary_text(column: ColumnInfo, row: tuple[object, ...]) -> str:
    """«kwh · Σ 1 234,5 · x̄ 61,7 · mín 1 · máx 99 · nulos 0» (#144, punto 11)."""
    total, mean, low, high, nulls = row
    parts = [column.name]
    if total is not None:
        parts.append("Σ " + _number(float(total) if not isinstance(total, int) else total))
    if mean is not None:
        parts.append("x̄ " + _number(float(mean)))  # type: ignore[arg-type]
    if low is not None:
        parts.append(tr("min {}").format(_number(low)))
    if high is not None:
        parts.append(tr("max {}").format(_number(high)))
    parts.append(tr("nulls {}").format(_number(nulls)))
    return " · ".join(parts)
