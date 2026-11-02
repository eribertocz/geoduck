# SPDX-License-Identifier: GPL-2.0-or-later
"""Ayudas visuales compartidas por el panel, nativas de QGIS 3 y 4 y válidas en temas claros y oscuros."""

from __future__ import annotations

from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QLabel, QWidget


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
