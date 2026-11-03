# SPDX-License-Identifier: GPL-2.0-or-later
"""Resumen del resultado de la celda activa (G7 · E3, GD-NB-004; ui-ux-spec §10).

«N filas · M columnas» y cada columna con su tipo, sacados de la vista previa que ya se mostró: **ninguna
consulta nueva**. En la ventana va en la columna derecha (plegable); en el panel, como ayuda (ⓘ) del rótulo
del resultado de la celda (`summary_text`).
"""

from __future__ import annotations

from qgis.core import QgsApplication
from qgis.PyQt.QtWidgets import QFrame, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.i18n import tr
from geoduck.domain.sql import Preview


def rows_text(preview: Preview) -> str:
    """«3 filas», o «200+ filas» si había más (no se cuentan: sin `COUNT(*)` automático, §4)."""
    count = len(preview.rows)
    shown = f"{count}+" if preview.truncated else str(count)
    return (tr("{0} row") if shown == "1" else tr("{0} rows")).format(shown)


def summary_line(preview: Preview) -> str:
    columns = len(preview.columns)
    return " · ".join(
        (rows_text(preview), (tr("{0} column") if columns == 1 else tr("{0} columns")).format(columns))
    )


def summary_text(preview: Preview) -> str:
    """El resumen en texto, para la ayuda del rótulo del resultado en el panel."""
    lines = [summary_line(preview)]
    lines += [f"{name} · {kind}" for name, kind in zip(preview.columns, preview.types, strict=True)]
    return "\n".join(lines)


class ResultSummary(QFrame):
    """Columna derecha de la ventana: resumen del resultado de la celda activa."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("geoduck", "card")
        self.setObjectName("geoduckResultSummary")
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 8)
        box.setSpacing(6)
        title = QLabel(tr("Result"))
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        box.addWidget(title)
        self.line = QLabel("")
        self.line.setProperty("geoduck", "muted")
        self.line.setWordWrap(True)
        box.addWidget(self.line)
        self.columns = QListWidget()
        self.columns.setObjectName("geoduckResultColumns")
        self.columns.setAccessibleName(tr("Columns of the result"))
        box.addWidget(self.columns, 1)
        self.show_preview(None)

    def show_preview(self, preview: Preview | None) -> None:
        self.columns.clear()
        if preview is None:
            self.line.setText(tr("Run a cell to see its columns here."))
            return
        self.line.setText(summary_line(preview))
        geometry = QgsApplication.getThemeIcon("mIconFieldGeometry.svg")
        for name, kind in zip(preview.columns, preview.types, strict=True):
            item = QListWidgetItem(f"{name} · {kind}")
            item.setToolTip(f"{name}\n{kind}")
            if is_geometry_type(kind):
                item.setIcon(geometry)
            self.columns.addItem(item)
