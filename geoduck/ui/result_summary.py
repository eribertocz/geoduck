# SPDX-License-Identifier: GPL-2.0-or-later
"""Resumen del resultado de la celda activa (G7 · E3, GD-NB-004; ui-ux-spec §10).

«N filas · M columnas» y cada columna con su tipo, sacados de la vista previa que ya se mostró: **ninguna
consulta nueva**. En la ventana va en la columna derecha (plegable); en el panel, como ayuda (ⓘ) del rótulo
del resultado de la celda (`summary_text`).
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.i18n import tr
from geoduck.domain.sql import Preview

_NUMBERS = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "UHUGEINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "REAL",
)


def type_marker(kind: str) -> str:
    """«#» números, «Aa» texto, «◈» geometría (maqueta G7, como las cabeceras del resultado)."""
    upper = kind.strip().upper()
    if is_geometry_type(kind):
        return "◈"
    if upper.startswith(_NUMBERS):
        return "#"
    if upper.startswith(("VARCHAR", "TEXT", "STRING")):
        return "Aa"
    return ""


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
        title = QLabel(tr("Result").upper())
        title.setProperty("geoduck", "muted")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        box.addWidget(title)
        self.line = QLabel("")  # «3 filas · 3 columnas»
        line_font = self.line.font()
        line_font.setBold(True)
        self.line.setFont(line_font)
        self.line.setWordWrap(True)
        box.addWidget(self.line)
        self.origin = QLabel("")  # «Celda 1 · db»
        self.origin.setProperty("geoduck", "muted")
        box.addWidget(self.origin)
        self.columns = QTreeWidget()  # «# Consumidor   BIGINT», como la maqueta
        self.columns.setObjectName("geoduckResultColumns")
        self.columns.setAccessibleName(tr("Columns of the result"))
        self.columns.setColumnCount(2)
        self.columns.setHeaderHidden(True)
        self.columns.setRootIsDecorated(False)
        self.columns.setFrameShape(QFrame.Shape.NoFrame)
        self.columns.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.columns.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        header = self.columns.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        box.addWidget(self.columns, 1)
        self.show_preview(None)

    def show_preview(self, preview: Preview | None, origin: str = "") -> None:
        """`origin`: de dónde sale el resultado («Celda 1 · db»)."""
        self.columns.clear()
        if preview is None:
            self.line.setText(tr("Run a cell to see its columns here."))
            self.origin.setText("")
            return
        self.line.setText(summary_line(preview))
        self.origin.setText(origin)
        for name, kind in zip(preview.columns, preview.types, strict=True):
            item = QTreeWidgetItem([f"{type_marker(kind)} {name}".strip(), kind])
            item.setToolTip(0, f"{name}\n{kind}")
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.columns.addTopLevelItem(item)

    def items(self) -> list[tuple[str, str]]:
        """(columna con su marca, tipo) de cada fila, como se ven."""
        rows = []
        for i in range(self.columns.topLevelItemCount()):
            item = self.columns.topLevelItem(i)
            rows.append((item.text(0), item.text(1)))
        return rows
