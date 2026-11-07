# SPDX-License-Identifier: GPL-2.0-or-later
"""Piezas de Workspace Pro (workspace-pro-spec §10): botones, chips, control segmentado, campo de búsqueda,
insignias, punto de estado y aviso. Su aspecto lo da `style` por la propiedad `pro`; aquí solo la estructura,
el comportamiento y la accesibilidad (nombre accesible y ayuda en cada acción).
"""

from __future__ import annotations

from collections.abc import Callable

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QPropertyAnimation, QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPalette, QTextDocument
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons
from geoduck.ui.pro.style import colors_for
from geoduck.ui.pro.tokens import METRICS, Colors


def label(text: str, kind: str | None = None) -> QLabel:
    """Texto con su papel: `muted`, `faint`, `title`, `section`, `mono`, `null`, `error`, `link`, `kbd`…"""
    widget = QLabel(text)
    if kind:
        widget.setProperty("pro", kind)
    return widget


class ElidedLabel(QLabel):
    """Texto de una línea que se recorta con «…» si no cabe, sin ensanchar su contenedor (la cabecera del
    panel acoplado, el estado de la sesión). El texto completo queda en la ayuda."""

    def __init__(self, text: str = "", kind: str | None = None) -> None:
        super().__init__(text)
        if kind:
            self.setProperty("pro", kind)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:  # noqa: N802 - API de Qt
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        self.style().drawItemText(
            painter,
            rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.palette(),
            self.isEnabled(),
            text,
            QPalette.ColorRole.WindowText,
        )
        painter.end()


def button(
    text: str,
    kind: str | None = None,
    *,
    icon: str | None = None,
    tooltip: str = "",
    colors: Colors | None = None,
) -> QPushButton:
    """Botón: sin `kind`, secundario; `primary`, `danger`, `ghost`. `icon`: del color de su texto."""
    widget = QPushButton(text)
    if kind:
        widget.setProperty("pro", kind)
    if icon and colors is not None:
        color = colors.on_accent if kind == "primary" else colors.muted if kind == "ghost" else colors.text
        widget.setIcon(icons.icon(icon, color))
    widget.setToolTip(tooltip or text)
    widget.setAccessibleName(text or tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


def icon_button(icon: str, tooltip: str, colors: Colors, *, size: int = 16) -> QPushButton:
    """Botón cuadrado solo con icono; su nombre accesible y su ayuda son `tooltip` (nunca un botón mudo)."""
    widget = QPushButton()
    widget.setProperty("pro", "icon")
    widget.setIcon(icons.icon(icon, colors.muted, size))
    widget.setToolTip(tooltip)
    widget.setAccessibleName(tooltip)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class Chip(QFrame):
    """Un filtro: «columna operador valor ×». Emite `removed` al quitarlo (clic en × o Supr con el foco)."""

    removed = pyqtSignal()

    def __init__(self, column: str, operator: str, value: str, colors: Colors, *, remove_tip: str) -> None:
        super().__init__()
        self.setProperty("pro", "chip")
        self.setFixedHeight(METRICS.control)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{column} {operator} {value}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 3, 0)
        row.setSpacing(6)
        row.addWidget(label(column, "muted"))
        row.addWidget(label(operator))
        row.addWidget(label(value, "mono"))
        self.close_button = icon_button("close", remove_tip, colors, size=12)
        self.close_button.setFixedSize(22, 22)
        self.close_button.clicked.connect(self.removed.emit)
        row.addWidget(self.close_button)

    def keyPressEvent(self, event: object) -> None:  # noqa: N802 - API de Qt
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):  # type: ignore[attr-defined]
            self.removed.emit()
            return
        super().keyPressEvent(event)  # type: ignore[arg-type]


def add_chip_button(text: str, tooltip: str) -> QPushButton:
    """«+ Filtro»: borde punteado, como un hueco para el siguiente chip."""
    widget = button(f"+ {text}", "add-chip", tooltip=tooltip)
    widget.setFixedHeight(METRICS.control)
    return widget


class Segmented(QFrame):
    """Control segmentado («Datos | Estructura»): una opción a la vez. Emite `changed(índice)`."""

    changed = pyqtSignal(int)

    def __init__(self, options: list[str], *, accessible_name: str) -> None:
        super().__init__()
        self.setProperty("pro", "segmented")
        self.setAccessibleName(accessible_name)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        for index, text in enumerate(options):
            item = button(text, "segment")
            item.setCheckable(True)
            self.group.addButton(item, index)
            self.buttons.append(item)
            row.addWidget(item)
        self.buttons[0].setChecked(True)
        for index, item in enumerate(self.buttons):
            item.clicked.connect(lambda _checked=False, i=index: self.changed.emit(i))

    @property
    def current(self) -> int:
        return self.group.checkedId()

    def set_current(self, index: int) -> None:
        self.buttons[index].setChecked(True)


class SearchField(QFrame):
    """Campo de búsqueda con lupa y, si se da, el atajo a la derecha («Ctrl K»). `edit` es el `QLineEdit`."""

    def __init__(
        self, placeholder: str, colors: Colors, *, shortcut: str = "", accessible_name: str = ""
    ) -> None:
        super().__init__()
        self.setProperty("pro", "field")
        self.setFixedHeight(METRICS.control + 2)
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 0, 6, 0)
        row.setSpacing(7)
        glass = QLabel()
        glass.setPixmap(icons.pixmap("search", colors.muted, 14))
        row.addWidget(glass)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setAccessibleName(accessible_name or placeholder)
        self.edit.setClearButtonEnabled(True)
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, 1)
        if shortcut:
            row.addWidget(label(shortcut, "kbd"))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - API de Qt
        if watched is self.edit and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.setProperty("focused", event.type() == QEvent.Type.FocusIn)  # «focus» es de Qt (hasFocus)
            self.style().unpolish(self)
            self.style().polish(self)
        return False


class StatusDot(QWidget):
    """Punto de estado de la sesión: `ok` (lista), `busy` (ocupada), `error`, `off` (sin sesión)."""

    def __init__(self, colors: Colors, state: str = "off") -> None:
        super().__init__()
        self.colors = colors
        self.state = state
        self.setFixedSize(10, 10)

    def set_state(self, state: str) -> None:
        self.state = state
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - API de Qt
        color = {
            "ok": self.colors.ok,
            "busy": self.colors.warn,
            "error": self.colors.error,
        }.get(self.state, self.colors.null)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(1, 1, 8, 8)
        painter.end()


class Toast(QFrame):
    """Aviso flotante abajo a la derecha: punto de color, texto y acciones («Abrir», «Deshacer»). Aparece y se
    va con un fundido breve; se cierra solo tras `seconds` (0 = no) y nunca roba el foco."""

    def __init__(self, parent: QWidget, text: str, *, kind: str = "ok", seconds: int = 8) -> None:
        super().__init__(parent)
        self.setProperty("pro", "toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName(text)
        colors = colors_for(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 9, 10, 9)
        row.setSpacing(10)
        dot = StatusDot(colors, kind)
        row.addWidget(dot)
        self.text = QLabel(text)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        # un aviso corto, en una línea; uno largo (origen, acceso, advertencias) baja de línea a los 520 px
        self.text.setWordWrap(True)
        plain = QTextDocument()
        plain.setHtml(text)
        width = self.text.fontMetrics().horizontalAdvance(plain.toPlainText()) + 4
        self.text.setMinimumWidth(min(width, 520))
        self.text.setMaximumWidth(520)
        row.addWidget(self.text)
        self.actions: list[QPushButton] = []
        self.seconds = seconds
        #: F-132: «×» para cerrar el aviso sin hacer nada más; va siempre al final, después de las acciones.
        self.close_button = icon_button("close", tr("Close"), colors, size=14)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.close_button.clicked.connect(self.dismiss)
        #: Se llama al cerrarlo con «×» (p. ej., recordar que no se decidió).
        self.on_closed: Callable[[], None] | None = None
        self.close_button.clicked.connect(lambda: self.on_closed() if self.on_closed else None)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(METRICS.motion)
        self.hide()

    def add_action(self, text: str, callback: Callable[[], None]) -> QPushButton:
        action = button(text)
        action.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        action.clicked.connect(callback)
        action.clicked.connect(self.dismiss)
        self.layout().addWidget(action)  # type: ignore[union-attr]
        self.actions.append(action)
        return action

    def show_at_corner(self, margin: int = METRICS.space_lg, bottom: int = 64) -> None:
        parent = self.parentWidget()
        self.layout().addWidget(self.close_button)  # type: ignore[union-attr]
        self.adjustSize()
        if parent is not None:
            self.move(
                QPoint(parent.width() - self.width() - margin, parent.height() - self.height() - bottom)
            )
        self.raise_()
        self.show()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        if self.seconds:
            QTimer.singleShot(self.seconds * 1000, self.dismiss)

    def dismiss(self) -> None:
        self.hide()
        self.deleteLater()


def spacer() -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return widget
