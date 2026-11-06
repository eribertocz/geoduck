# SPDX-License-Identifier: GPL-2.0-or-later
"""Ctrl+K de Workspace Pro (workspace-pro-spec §6; GD-WSP-005; AT-WSP-006).

Una sola paleta para ir a cualquier sitio y hacer cualquier cosa sin el ratón: tablas y vistas de todas las
bases, pestañas abiertas, recientes y acciones. La búsqueda es tolerante (letras en orden, sin acentos ni
mayúsculas, `fuzzy`) y se hace en el hilo de la interfaz sobre una lista ya plegada: < 50 ms por tecla con
1 000 objetos. ↑ ↓ eligen, Intro abre, Esc cierra; un clic fuera también la cierra.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from qgis.PyQt.QtCore import QEvent, QModelIndex, QObject, QRect, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath
from qgis.PyQt.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from geoduck.ui.i18n import tr
from geoduck.ui.pro import fuzzy, icons
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import label

ROW = 36
VISIBLE_ROWS = 9
#: Resultados que se muestran como máximo (los mejores).
LIMIT = 50
ENTRY = Qt.ItemDataRole.UserRole


@dataclass
class Entry:
    """Un resultado: título, dónde o qué es (`meta`, en gris), icono y qué hace al elegirlo."""

    title: str
    meta: str
    icon: str
    run: Callable[[], object]
    #: Texto en que se busca, ya plegado (título y meta).
    folded: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not self.folded:
            self.folded = fuzzy.fold(self.title)


class _Delegate(QStyledItemDelegate):
    """Fila: icono, título y, a la derecha, `meta` en gris; la elegida con fondo de acento suave."""

    def __init__(self, colors: Colors, parent: QObject) -> None:
        super().__init__(parent)
        self.colors = colors
        self.font = ui_font()
        self.small = ui_font(METRICS.font_small)
        self._icons: dict[str, object] = {}

    def sizeHint(self, _option: QStyleOptionViewItem, _index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(100, ROW)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        entry: Entry = index.data(ENTRY)
        c = self.colors
        rect = option.rect.adjusted(6, 1, -6, -1)  # type: ignore[attr-defined]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_Selected:  # type: ignore[attr-defined]
            path = QPainterPath()
            path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), 6, 6)
            painter.fillPath(path, QColor(c.accent_soft))
        pixmap = self._icons.get(entry.icon)
        if pixmap is None:
            pixmap = self._icons[entry.icon] = icons.pixmap(entry.icon, c.muted, 16)
        painter.drawPixmap(rect.x() + 10, rect.y() + (rect.height() - 16) // 2, pixmap)  # type: ignore[arg-type]
        painter.setFont(self.small)
        meta_width = painter.fontMetrics().horizontalAdvance(entry.meta) + 12
        painter.setPen(QColor(c.faint))
        meta_rect = QRect(rect.right() - meta_width - 6, rect.y(), meta_width, rect.height())
        painter.drawText(
            meta_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight), entry.meta
        )
        painter.setFont(self.font)
        painter.setPen(QColor(c.text))
        title_rect = QRect(rect.x() + 36, rect.y(), meta_rect.x() - rect.x() - 44, rect.height())
        title = painter.fontMetrics().elidedText(entry.title, Qt.TextElideMode.ElideRight, title_rect.width())
        painter.drawText(title_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), title)
        painter.restore()


class CommandPalette(QFrame):
    """La paleta, flotando arriba al centro de `parent`. `source()` da las entradas al abrirla."""

    def __init__(self, parent: QWidget, colors: Colors, source: Callable[[], list[Entry]]) -> None:
        super().__init__(parent)
        self.colors = colors
        self.source = source
        self.entries: list[Entry] = []
        self.shown: list[Entry] = []
        self.setProperty("pro", "palette")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName(tr("Go to or run"))
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 60))
        self.setGraphicsEffect(shadow)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 6)
        box.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(16, 0, 14, 0)
        row.setSpacing(10)
        glass = label("")
        glass.setPixmap(icons.pixmap("search", colors.muted, 16))
        row.addWidget(glass)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(tr("Search tables, tabs and actions…"))
        self.edit.setAccessibleName(tr("Search tables, tabs and actions"))
        self.edit.textChanged.connect(self.refresh)
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, 1)
        row.addWidget(label("Esc", "kbd"), 0, Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(row)
        self.list = QListWidget()
        self.list.setProperty("pro", "palette-list")
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # el foco se queda en la búsqueda
        self.list.setUniformItemSizes(True)
        self.delegate = _Delegate(colors, self.list)  # la vista no se queda con él: se guarda aquí
        self.list.setItemDelegate(self.delegate)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setAccessibleName(tr("Results"))
        self.list.itemClicked.connect(lambda item: self._run(item.data(ENTRY)))
        box.addWidget(self.list)
        self.empty = label(tr("Nothing found"), "muted")
        self.empty.setContentsMargins(16, 10, 16, 6)
        box.addWidget(self.empty)
        self.hide()

    def open(self) -> None:
        self.entries = self.source()
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self.refresh("")
        self.show()
        self.raise_()
        self.edit.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def close_palette(self) -> None:
        if self.isVisible():
            self.hide()
            parent = self.parentWidget()
            if parent is not None:
                parent.setFocus(Qt.FocusReason.OtherFocusReason)

    def refresh(self, text: str) -> None:
        """Filtra las entradas con `text` y muestra las mejores (sin texto, las primeras: pestañas, recientes
        y acciones, en ese orden)."""
        self.shown = (
            fuzzy.rank(text, self.entries, lambda e: e.folded, LIMIT)
            if text.strip()
            else self.entries[:LIMIT]
        )
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for entry in self.shown:
            item = QListWidgetItem()
            item.setData(ENTRY, entry)
            item.setText(entry.title)  # nombre accesible de la fila
            self.list.addItem(item)
        if self.shown:
            self.list.setCurrentRow(0)
        self.list.setUpdatesEnabled(True)
        self.list.setVisible(bool(self.shown))
        self.empty.setVisible(not self.shown)
        self._place()

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        width = min(620, parent.width() - 32)
        rows = min(len(self.shown), VISIBLE_ROWS)
        self.list.setFixedHeight(rows * ROW + 8 if rows else 0)
        height = 46 + (self.list.height() if rows else 40) + 6
        self.setGeometry((parent.width() - width) // 2, 64, width, height)

    def _move(self, step: int) -> None:
        count = self.list.count()
        if count:
            self.list.setCurrentRow((self.list.currentRow() + step) % count)

    def _run(self, entry: Entry | None) -> None:
        if entry is None:
            return
        self.close_palette()
        entry.run()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - API de Qt
        if watched is self.edit:
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()  # type: ignore[attr-defined]
                if key == Qt.Key.Key_Escape:
                    self.close_palette()
                    return True
                if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    self._move(1 if key == Qt.Key.Key_Down else -1)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    item = self.list.currentItem()
                    self._run(item.data(ENTRY) if item is not None else None)
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, self._close_if_unfocused)
        return False

    def _close_if_unfocused(self) -> None:
        if self.isVisible() and not self.edit.hasFocus():
            self.close_palette()
