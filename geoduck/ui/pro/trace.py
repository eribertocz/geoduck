# SPDX-License-Identifier: GPL-2.0-or-later
"""Trazabilidad de cada capa en el paso 3 de «→ DuckDB» (workspace-pro-spec §9; maqueta aprobada
`docs/g9/maqueta/trazabilidad.png`, propietario, 2026-11-07).

Tres nodos en círculo, de izquierda a derecha: **de dónde viene** (archivo, base, servicio web, capa
temporal o DuckDB, con su formato corto), **QGIS** (la pila de capas) y **el destino** (el logo y la
tabla).
Cuando DuckDB lee el archivo, un **puente** («⚡ DuckDB») salta por encima de QGIS, que queda punteado y
apagado («se saltó»); si no, la línea pasa por QGIS. El avance llena la línea (o el anillo del destino); al
terminar, el destino se pone verde con ✓. En «Archivos → DuckDB» no hay QGIS: dos nodos y el puente.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QSizePolicy, QWidget

from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons
from geoduck.ui.pro.tokens import Colors
from geoduck.ui.pro.widgets import LOGO

#: Ícono de cada origen.
SOURCE_ICONS = {"file": "file", "database": "database", "web": "globe", "memory": "memory", "duckdb": "logo"}
WAITING, RUNNING, DONE, CANCELLED, FAILED = "waiting", "running", "done", "cancelled", "failed"
_R = 14  # radio de un nodo
_AMBER = "#F2A33A"


class TraceView(QWidget):
    """El diagrama de una capa. `bridge`: DuckDB lee directo (salta QGIS); `qgis`: hay un nodo QGIS."""

    def __init__(
        self,
        colors: Colors,
        *,
        source_kind: str,
        source_label: str,
        dest_label: str,
        bridge: bool,
        qgis: bool = True,
        dest_kind: str = "duckdb",
    ) -> None:
        super().__init__()
        self.colors = colors
        self.source_kind = source_kind
        self.source_label = source_label
        self.dest_label = dest_label
        self.bridge = bridge
        self.qgis = qgis
        #: «duckdb» (importar: el logo) o «file» (exportar: el archivo).
        self.dest_kind = dest_kind
        self.state = WAITING
        #: 0..1, o None si no se sabe (DuckDB copia sin informar filas): el anillo gira.
        self.progress: float | None = None
        self._spin = 0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self.setMinimumSize(260, 78)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(tr("How this layer reaches GeoDuck"))

    def sizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        return QSize(400, 78)

    def set_state(self, state: str, progress: float | None = None) -> None:
        self.state = state
        self.progress = progress
        spinning = state == RUNNING and progress is None
        if spinning and not self._timer.isActive():
            self._timer.start()
        elif not spinning:
            self._timer.stop()
        self.setToolTip(self._describe())
        self.update()

    def set_bridge(self, bridge: bool) -> None:
        self.bridge = bridge
        self.setToolTip(self._describe())
        self.update()

    def _describe(self) -> str:
        how = tr("DuckDB reads it directly, skipping QGIS") if self.bridge else tr("QGIS reads it")
        return f"{self.source_label} → {how} → {self.dest_label}"

    def _tick(self) -> None:
        self._spin = (self._spin + 12) % 360
        self.update()

    # -- dibujo ---------------------------------------------------------------------------------------

    def _xs(self) -> list[float]:
        pad = 46.0
        w = max(self.width() - 2 * pad, 10.0)
        return [pad, pad + w / 2, pad + w] if self.qgis else [pad, pad + w]

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - API de Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = 40.0
        xs = self._xs()
        if self.bridge:
            self._paint_bridge(p, xs, y)
        else:
            self._paint_through(p, xs, y)
        self._paint_nodes(p, xs, y)
        self._paint_labels(p, xs, y)
        p.end()

    def _paint_bridge(self, p: QPainter, xs: list[float], y: float) -> None:
        line = QColor(self.colors.line)
        if self.qgis:  # la línea de QGIS, punteada: no hizo falta
            p.setPen(QPen(line, 1.5, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(xs[0] + _R, y), QPointF(xs[-1] - _R, y))
        arc = QPainterPath(QPointF(xs[0] + _R * 0.7, y - _R * 0.7))
        arc.cubicTo(
            QPointF(xs[0] + 60, y - 42),
            QPointF(xs[-1] - 60, y - 42),
            QPointF(xs[-1] - _R * 0.7, y - _R * 0.7),
        )
        active = self.state in (RUNNING, DONE)
        p.setPen(QPen(QColor(self.colors.accent) if active else line, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(arc)
        self._pill(p, (xs[0] + xs[-1]) / 2, y - 31, "⚡ DuckDB", active)

    def _paint_through(self, p: QPainter, xs: list[float], y: float) -> None:
        amber, done = QColor(_AMBER), self.state == DONE
        rest = QColor(self.colors.faint) if done else QColor(self.colors.line)
        p.setPen(QPen(amber if self.state == RUNNING else rest, 2.5))
        p.drawLine(QPointF(xs[0] + _R, y), QPointF(xs[1] - _R, y))
        p.setPen(QPen(rest, 2.5))
        p.drawLine(QPointF(xs[1] + _R, y), QPointF(xs[2] - _R, y))
        if self.state == RUNNING and self.progress:
            end = xs[1] + _R + (xs[2] - xs[1] - 2 * _R) * min(self.progress, 1.0)
            p.setPen(QPen(amber, 2.5))
            p.drawLine(QPointF(xs[1] + _R, y), QPointF(end, y))

    def _paint_nodes(self, p: QPainter, xs: list[float], y: float) -> None:
        c = self.colors
        blue = QColor(c.accent)
        done, failed = self.state == DONE, self.state in (FAILED, CANCELLED)
        src_color = blue if self.bridge and self.state != WAITING else QColor(c.muted)
        self._node(
            p, xs[0], y, SOURCE_ICONS.get(self.source_kind, "file"), color=src_color, fill=QColor(c.bg)
        )
        if self.qgis and self.bridge:
            grey = QColor(c.faint)
            self._node(p, xs[1], y, "qgis-layers", color=grey, fill=QColor(c.bg), dashed=True, faded=True)
        elif self.qgis:
            running = self.state == RUNNING
            self._node(
                p,
                xs[1],
                y,
                "qgis-layers",
                color=QColor(_AMBER) if running else QColor(c.muted),
                fill=QColor("#fff8ee") if running else QColor(c.bg),
                ring=QColor(_AMBER) if running else QColor(c.border),
            )
        if done:
            ring = QColor(c.ok)
        elif failed:
            ring = QColor(c.error)
        else:
            ring = blue if self.bridge else QColor(c.border)
        soft = self.state == RUNNING and self.bridge
        self._node(
            p,
            xs[-1],
            y,
            SOURCE_ICONS.get(self.dest_kind, "file"),
            color=blue,
            fill=QColor(c.accent_soft) if soft else QColor(c.bg),
            ring=ring,
            dashed=self.state == WAITING,
            faded=self.state in (WAITING, CANCELLED),
        )
        if self.state == RUNNING and self.bridge:
            self._ring(p, xs[-1], y, blue)
        if done or failed:
            self._badge(p, xs[-1] + 10, y - 10, QColor(c.ok) if done else QColor(c.error), done)

    def _paint_labels(self, p: QPainter, xs: list[float], y: float) -> None:
        c = self.colors
        small = QFont(self.font())
        small.setPointSizeF(max(small.pointSizeF() - 1.5, 7.0))
        p.setFont(small)
        p.setPen(QColor(c.muted))
        self._text(p, xs[0], y + 30, self.source_label)
        if self.qgis:
            self._text(
                p, xs[1], y + 30, tr("QGIS · skipped") if self.bridge else tr("QGIS"), faded=self.bridge
            )
        bold = QFont(small)
        bold.setBold(True)
        p.setFont(bold)
        p.setPen(QColor(c.text))
        self._text(p, xs[-1], y + 30, self.dest_label)

    def _text(self, p: QPainter, x: float, y: float, text: str, *, faded: bool = False) -> None:
        if faded:
            p.setPen(QColor(self.colors.faint))
        metrics = p.fontMetrics()
        room = int((self.width() / (3 if self.qgis else 2)) - 8)
        shown = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max(room, 40))
        width = metrics.horizontalAdvance(shown)
        p.drawText(QPointF(x - width / 2, y), shown)

    def _pill(self, p: QPainter, x: float, y: float, text: str, active: bool) -> None:
        font = QFont(self.font())
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 7.0))
        font.setBold(True)
        p.setFont(font)
        width = p.fontMetrics().horizontalAdvance(text) + 16
        rect = QRectF(x - width / 2, y - 9, width, 18)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.colors.accent_soft) if active else QColor(self.colors.line))
        p.drawRoundedRect(rect, 9, 9)
        p.setPen(QColor(self.colors.accent) if active else QColor(self.colors.faint))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _node(
        self,
        p: QPainter,
        x: float,
        y: float,
        icon: str,
        *,
        color: QColor,
        fill: QColor,
        ring: QColor | None = None,
        dashed: bool = False,
        faded: bool = False,
    ) -> None:
        p.save()
        if faded:
            p.setOpacity(0.45)
        pen = QPen(ring if ring is not None else color, 1.6)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(fill)
        p.drawEllipse(QPointF(x, y), _R, _R)
        size = 16
        pix = QIcon(LOGO).pixmap(size, size) if icon == "logo" else icons.pixmap(icon, color.name(), size)
        p.drawPixmap(int(x - size / 2), int(y - size / 2), pix)
        p.restore()

    def _ring(self, p: QPainter, x: float, y: float, color: QColor) -> None:
        """El avance del destino: un anillo que se llena (o gira si no se sabe cuánto falta)."""
        p.save()
        p.setPen(QPen(color, 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(x - _R - 3, y - _R - 3, 2 * _R + 6, 2 * _R + 6)
        if self.progress is None:
            p.drawArc(rect, int(-self._spin * 16), 100 * 16)
        else:
            p.drawArc(rect, 90 * 16, int(-360 * 16 * min(self.progress, 1.0)))
        p.restore()

    def _badge(self, p: QPainter, x: float, y: float, color: QColor, ok: bool) -> None:
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(x, y), 6, 6)
        pen = QPen(QColor("#ffffff"), 1.6)
        p.setPen(pen)
        if ok:
            p.drawLine(QPointF(x - 3, y), QPointF(x - 1, y + 2))
            p.drawLine(QPointF(x - 1, y + 2), QPointF(x + 3, y - 2.5))
        else:
            p.drawLine(QPointF(x - 2.5, y - 2.5), QPointF(x + 2.5, y + 2.5))
            p.drawLine(QPointF(x + 2.5, y - 2.5), QPointF(x - 2.5, y + 2.5))
        p.restore()
