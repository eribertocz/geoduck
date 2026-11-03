# SPDX-License-Identifier: GPL-2.0-or-later
"""Ayudas visuales compartidas por el panel, nativas de QGIS 3 y 4 y válidas en temas claros y oscuros."""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QPainter, QPaintEvent, QPalette
from qgis.PyQt.QtWidgets import QLabel, QSizePolicy, QWidget


def secondary_color(widget: QWidget) -> QColor:
    """Color de texto secundario derivado del tema activo.

    No se usa `PlaceholderText`: en Qt5 puede ser transparente y ocultar el texto (visto en QGIS 3.44).
    """
    color = widget.palette().color(QPalette.ColorRole.WindowText)
    color.setAlpha(170)
    return color


def secondary(label: QLabel) -> QLabel:
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, secondary_color(label))
    label.setPalette(palette)
    label.setWordWrap(True)
    return label


class ElidedLabel(QLabel):
    """Etiqueta que, si `elide` está activo, se dibuja en una línea recortada con «…»; `text()` y la ayuda
    conservan el texto completo (inventario P3)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.elide = False

    def set_elide(self, elide: bool) -> None:
        self.elide = elide
        self.setWordWrap(not elide)
        width = QSizePolicy.Policy.Ignored if elide else QSizePolicy.Policy.Preferred
        self.setSizePolicy(width, QSizePolicy.Policy.Preferred)
        self.updateGeometry()
        self.update()

    def setText(self, text: str) -> None:  # noqa: N802 - API de Qt
        super().setText(text)
        self.setToolTip(text if text else "")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if not self.elide:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        first_line = self.text().split("\n")
        text = " · ".join(part for part in first_line if part)
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, rect.width()),
        )
