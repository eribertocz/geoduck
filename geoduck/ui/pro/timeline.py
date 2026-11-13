# SPDX-License-Identifier: GPL-2.0-or-later
"""Progreso y trazabilidad en una línea de tiempo vertical (#148, punto 19; maqueta `progreso-traza`).

Un solo diseño para importar capas, importar archivos, exportar y cargar en QGIS: arriba el **total** (título,
subtítulo, tiempo y una barra fina) y una **fila plegable por capa**; dentro, sus **pasos** de arriba abajo
(de dónde viene y su filtro → cómo se lee: ⚡ directo con DuckDB o por QGIS y por qué → la copia → el
destino), cada uno con su tiempo. Círculos con icono: ✓ verde = hecho, girando turquesa = ahora, punteado gris
= en espera o saltado; un paso que falla se pone rojo con la tarjeta de error (#145). Reemplaza la
trazabilidad horizontal (`trace.py`).

La vista no sabe de capas ni de DuckDB: quien la usa le da `Step` ya escritos (ver `add_layers`, `transfer`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from qgis.PyQt.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import LOGO, Lake, label, reduced_motion

WAITING, RUNNING, DONE, FAILED, SKIPPED = "waiting", "running", "done", "failed", "skipped"
#: Tamaño del círculo de un paso y del espacio entre pasos.
NODE = 26


@dataclass
class Step:
    """Un paso: icono, qué (título) y dónde (detalle), su estado, cuánto tardó y su avance (0–1, o None si no
    se sabe). `card`: la tarjeta de error del paso que falló (un widget)."""

    icon: str
    title: str
    detail: str = ""
    state: str = WAITING
    seconds: float | None = None
    progress: float | None = None
    card: QWidget | None = field(default=None, compare=False)


def seconds_text(seconds: float | None) -> str:
    """«0,4 s», «1 min 12 s»."""
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds:.1f} s".replace(".", ",")
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} min {rest} s"


def count_text(n: int) -> str:
    return f"{n:,}".replace(",", " ")


class _Node(QWidget):
    """El círculo de un paso y la línea que baja al siguiente."""

    def __init__(self, colors: Colors) -> None:
        super().__init__()
        self.colors = colors
        self.icon = "file"
        self.state = WAITING
        self.last = False
        self.angle = 0
        self._spin = QTimer(self)
        self._spin.setInterval(50)
        self._spin.timeout.connect(self._turn)
        self.setFixedWidth(NODE + 6)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def set(self, icon: str, state: str, last: bool) -> None:
        self.icon, self.state, self.last = icon, state, last
        if state == RUNNING and not reduced_motion(self):
            self._spin.start()
        else:
            self._spin.stop()
        self.update()

    def _turn(self) -> None:
        self.angle = (self.angle + 18) % 360
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - API de Qt
        c = self.colors
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tone = {DONE: c.ok, RUNNING: c.accent, FAILED: c.error}.get(self.state, c.null)
        x, y = 3.0, 2.0
        box = QRectF(x, y, NODE, NODE)
        if not self.last:  # la línea al siguiente paso: verde si este terminó, gris si no
            pen = QPen(QColor(c.ok if self.state == DONE else c.border))
            pen.setWidthF(2)
            p.setPen(pen)
            p.drawLine(int(box.center().x()), int(box.bottom()) + 2, int(box.center().x()), self.height())
        pen = QPen(QColor(tone))
        pen.setWidthF(1.8)
        if self.state in (WAITING, SKIPPED):
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(QColor(c.bg))
        if self.state == RUNNING:  # el anillo gira: un arco más fuerte sobre uno suave
            soft = QColor(tone)
            soft.setAlpha(70)
            ring = QPen(soft)
            ring.setWidthF(1.8)
            p.setPen(ring)
            p.drawEllipse(box)
            p.setPen(pen)
            p.drawArc(box.adjusted(-1.5, -1.5, 1.5, 1.5), -self.angle * 16, 110 * 16)
        else:
            p.drawEllipse(box)
        size = 14
        p.drawPixmap(
            int(box.center().x() - size / 2),
            int(box.center().y() - size / 2),
            icons.pixmap(self.icon, tone if self.state != WAITING else c.faint, size),
        )
        if self.state in (DONE, FAILED):  # la marca abajo a la derecha: ✓ verde o ✕ rojo
            badge = QRectF(box.right() - 9, box.bottom() - 9, 12, 12)
            p.setPen(QPen(QColor(c.bg), 1.5))
            p.setBrush(QColor(tone))
            p.drawEllipse(badge)
            p.drawPixmap(
                int(badge.x() + 2),
                int(badge.y() + 2),
                icons.pixmap("check" if self.state == DONE else "close", c.bg, 8),
            )
        p.end()


class StepView(QWidget):
    """Un paso: el círculo a la izquierda; título (y tiempo a la derecha), detalle, barra y tarjeta."""

    def __init__(self, colors: Colors) -> None:
        super().__init__()
        self.colors = colors
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.node = _Node(colors)
        row.addWidget(self.node)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 4, 0, 10)
        texts.setSpacing(2)
        row.addLayout(texts, 1)  # antes de sus widgets: sin padre, uno visible sería una ventana suelta
        head = QHBoxLayout()
        head.setSpacing(8)
        texts.addLayout(head)
        self.title = label("")
        self.title.setFont(ui_font(bold=True))
        self.title.setMinimumWidth(1)
        head.addWidget(self.title, 1)
        self.time = label("", "muted")
        head.addWidget(self.time)
        self.detail = label("", "muted")
        self.detail.setWordWrap(True)
        self.detail.setMinimumWidth(1)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        texts.addWidget(self.detail)
        self.bar = QProgressBar()
        self.bar.setProperty("pro", "thin")
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(4)
        self.bar.hide()
        texts.addWidget(self.bar)
        self.card_box = QVBoxLayout()
        self.card_box.setContentsMargins(0, 4, 0, 0)
        texts.addLayout(self.card_box)
        self._card: QWidget | None = None

    def set(self, step: Step, last: bool) -> None:
        self.node.set(step.icon, step.state, last)
        self.title.setText(step.title)
        tone = {FAILED: "error", WAITING: "muted", SKIPPED: "muted"}.get(step.state)
        self.title.setProperty("pro", tone)
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)
        self.detail.setText(step.detail)
        self.detail.setVisible(bool(step.detail))
        self.time.setText(seconds_text(step.seconds))
        running = step.state == RUNNING and step.progress is not None
        self.bar.setVisible(running)
        if running:
            self.bar.setValue(round(1000 * min(1.0, max(0.0, step.progress or 0.0))))
        if step.card is not self._card:
            if self._card is not None:
                self._card.hide()
                self._card.setParent(None)
            self._card = step.card
            if step.card is not None:
                self.card_box.addWidget(step.card)
                step.card.show()
        self.setAccessibleName(f"{step.title}. {step.detail}")


class TimelineRow(QFrame):
    """Una capa: su cabecera plegable (›/⌄, nombre y estado a la derecha) y sus pasos debajo."""

    toggled = pyqtSignal(bool)

    def __init__(self, colors: Colors, name: str, *, on_remove: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.colors = colors
        self.setProperty("pro", "timeline-row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        box.addLayout(head)
        self.chevron = QLabel()
        head.addWidget(self.chevron)
        self.name = label(name)
        self.name.setFont(ui_font(bold=True))
        self.name.setMinimumWidth(1)
        head.addWidget(self.name, 1)
        self.status = label("", "muted")
        self.status.setMinimumWidth(1)
        head.addWidget(self.status)
        self.remove: QWidget | None = None
        if on_remove is not None:
            from geoduck.ui.pro.widgets import icon_button  # noqa: PLC0415

            self.remove = icon_button("close", tr("Remove this layer"), colors, size=12)
            self.remove.clicked.connect(on_remove)
            head.addWidget(self.remove)
        self.body = QWidget()
        self.steps_box = QVBoxLayout(self.body)
        self.steps_box.setContentsMargins(4, 4, 0, 0)
        self.steps_box.setSpacing(0)
        box.addWidget(self.body)
        self.views: list[StepView] = []
        self.open = False
        self.user_set = False  # el usuario la abrió o cerró: ya no se pliega sola
        self._apply_open()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        """Clic en la cabecera: abre o pliega (el usuario manda: ya no se pliega sola)."""
        y = event.position().y() if hasattr(event, "position") else event.pos().y()
        if event.button() == Qt.MouseButton.LeftButton and y < 36:
            self.user_set = True
            self.set_open(not self.open)
            self.toggled.emit(self.open)

    def set_open(self, open_: bool) -> None:
        if open_ != self.open:
            self.open = open_
            self._apply_open()

    def _apply_open(self) -> None:
        self.body.setVisible(self.open)
        name = "chevron-down" if self.open else "chevron-right"
        self.chevron.setPixmap(icons.pixmap(name, self.colors.muted, 14))
        self.setAccessibleDescription(tr("Expanded") if self.open else tr("Collapsed"))

    def set_status(self, text: str, tone: str | None = None) -> None:
        self.status.setText(text)
        color = {"ok": self.colors.ok, "accent": self.colors.accent, "error": self.colors.error}.get(
            tone or ""
        )
        self.status.setStyleSheet(f"color: {color}; font-weight: 600;" if color else "")

    def set_steps(self, steps: list[Step]) -> None:
        while len(self.views) < len(steps):
            view = StepView(self.colors)
            self.steps_box.addWidget(view)
            self.views.append(view)
        for index, view in enumerate(self.views):
            view.setVisible(index < len(steps))
            if index < len(steps):
                view.set(steps[index], index == len(steps) - 1)


class TimelineView(QWidget):
    """El total arriba y las filas. `add_row(nombre)` devuelve la fila para darle estado y pasos."""

    def __init__(self, colors: Colors) -> None:
        super().__init__()
        self.colors = colors
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        box.addLayout(head)
        duck = QLabel()
        duck.setPixmap(_logo(26))
        head.addWidget(duck, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        head.addLayout(titles, 1)
        self.title = label("", "title")
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(1)
        titles.addWidget(self.title)
        self.subtitle = label("", "muted")
        self.subtitle.setWordWrap(True)
        self.subtitle.setMinimumWidth(1)
        titles.addWidget(self.subtitle)
        self.time = label("")
        self.time.setFont(ui_font(METRICS.font_title - 1, bold=True))
        self.time.setStyleSheet(f"color: {colors.accent};")
        head.addWidget(self.time, 0, Qt.AlignmentFlag.AlignTop)
        self.pill = label("", "pill")
        self.pill.setProperty("pro", "timeline-pill")
        self.pill.hide()
        head.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        # el total: el lago con el pato que nada hasta la punta (#143), el progreso de GeoDuck
        self.total = Lake(colors, accessible_name=tr("Total progress"))
        box.addWidget(self.total)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.rows_box = QVBoxLayout(inner)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(8)
        self.rows_box.addStretch(1)
        self.scroll.setWidget(inner)
        self.scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        box.addWidget(self.scroll, 1)
        self.rows: list[TimelineRow] = []

    def sizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        return QSize(560, 420)

    def clear(self) -> None:
        for row in self.rows:
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.rows = []

    def add_row(self, name: str, *, on_remove: Callable[[], None] | None = None) -> TimelineRow:
        row = TimelineRow(self.colors, name, on_remove=on_remove)
        self.rows_box.insertWidget(self.rows_box.count() - 1, row)
        self.rows.append(row)
        return row

    def set_header(self, title: str, subtitle: str, seconds: float | None = None, pill: str = "") -> None:
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.time.setText(seconds_text(seconds))
        self.time.setVisible(not pill and seconds is not None)
        self.pill.setText(pill)
        self.pill.setVisible(bool(pill))

    def set_total(self, progress: float | None) -> None:
        """El lago del total (None: se oculta, al terminar)."""
        self.total.setVisible(progress is not None)
        if progress is not None:
            self.total.set_progress(progress)

    def follow(self, current: TimelineRow | None) -> None:
        """La fila que avanza se abre sola; las terminadas se pliegan (salvo que el usuario las tocara)."""
        for row in self.rows:
            if not row.user_set:
                row.set_open(row is current)
        if current is not None:
            self.scroll.ensureWidgetVisible(current, 0, 40)


def _logo(size: int) -> Any:
    from qgis.PyQt.QtGui import QIcon  # noqa: PLC0415

    return QIcon(LOGO).pixmap(size, size)


class TimelineWindow(QDialog):
    """Una ventana con la línea de tiempo y su pie (exportar; #148). Esc llama a `on_escape` (Cancelar
    mientras corre) o cierra."""

    def __init__(self, parent: QWidget | None, title: str) -> None:
        from geoduck.ui.pro import style  # noqa: PLC0415

        super().__init__(parent)
        self.setModal(False)
        self.colors = style.apply(self)
        self.setWindowTitle(title)
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 18)
        box.setSpacing(12)
        self.view = TimelineView(self.colors)
        box.addWidget(self.view, 1)
        self.footer = QHBoxLayout()
        box.addLayout(self.footer)
        self.on_escape: Callable[[], None] | None = None
        self.resize(560, 420)

    def set_footer(self, left: list[QWidget], right: list[QWidget]) -> None:
        set_footer(self.footer, left, right)

    def reject(self) -> None:  # Esc
        if self.on_escape is not None:
            self.on_escape()
            return
        super().reject()


def set_footer(footer: QHBoxLayout, left: list[QWidget], right: list[QWidget]) -> None:
    """Cambia los botones de un pie: los de antes se borran."""
    while footer.count():
        item = footer.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
    for widget in left:
        footer.addWidget(widget)
    footer.addStretch(1)
    for widget in right:
        footer.addWidget(widget)
