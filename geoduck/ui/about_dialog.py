# SPDX-License-Identifier: GPL-2.0-or-later
"""«Acerca de GeoDuck»: versión, principio de diseño, licencia, enlaces y componentes detectados."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from geoduck import __version__
from geoduck.domain.diagnostics import DiagnosticReport
from geoduck.domain.operations import EngineInfo
from geoduck.domain.versions import release_stage
from geoduck.ui import theme
from geoduck.ui.i18n import tr

REPOSITORY = "https://github.com/eribertocz/geoduck"
_ICON = Path(__file__).resolve().parent.parent / "resources" / "icon.svg"


def version_text() -> str:
    """Versión real del paquete (`geoduck.__version__`, igual a `metadata.txt`) y su etapa."""
    stage = release_stage(__version__)
    return tr("Version") + f" {__version__}" + (f" · {stage}" if stage else "")


def components(report: DiagnosticReport | None, engine: EngineInfo | None) -> list[tuple[str, str]]:
    """Versiones detectadas, sin rutas ni datos personales."""
    rows: list[tuple[str, str]] = []
    facts = report.facts if report is not None else {}
    for key in ("QGIS", "Qt", "Python"):
        if facts.get(key):
            rows.append((key, facts[key]))
    if engine is not None:
        rows.append(("DuckDB", engine.duckdb_version))
    elif report is not None:
        rows.append(("DuckDB", report.by_id("duckdb").detail.removeprefix("DuckDB ")))
    if report is not None:
        rows.append(("PyArrow", report.by_id("pyarrow").detail.removeprefix("PyArrow ")))
    return rows


class _Band(QWidget):
    """La franja de la marca arriba de «Acerca de» (azul lago → azul profundo)."""

    def __init__(self, start: QColor, end: QColor) -> None:
        super().__init__()
        self._colors = (start, end)

    def paintEvent(self, _event: object) -> None:  # noqa: N802 - API de Qt
        gradient = QLinearGradient(0, 0, self.width(), 0)
        gradient.setColorAt(0, self._colors[0])
        gradient.setColorAt(1, self._colors[1])
        QPainter(self).fillRect(self.rect(), gradient)


class AboutDialog(QDialog):
    def __init__(
        self,
        report: DiagnosticReport | None,
        engine: EngineInfo | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("About GeoDuck"))
        self.setMinimumWidth(460)
        palette = theme.palette_for(self)
        self.setStyleSheet(theme.stylesheet(palette))

        top = self._build_header(palette)

        # Componentes detectados, en una tarjeta (sin rutas ni datos personales)
        box = QFrame()
        box.setProperty("geoduck", "card")
        self.components = QFormLayout(box)
        self.components.setContentsMargins(14, 10, 14, 10)
        self.components.setHorizontalSpacing(24)
        self.components.setVerticalSpacing(6)
        for label, value in components(report, engine):
            text = QLabel(value)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            key = QLabel(label)
            key.setProperty("geoduck", "muted")
            self.components.addRow(key, text)

        link = f"color: {palette.action};"
        self.links = QLabel(
            f'<a style="{link}" href="{REPOSITORY}">{tr("Repository")}</a> &nbsp;·&nbsp; '
            f'<a style="{link}" href="{REPOSITORY}/issues">{tr("Report a problem")}</a> &nbsp;·&nbsp; '
            f'<a style="{link}" href="{REPOSITORY}/blob/main/LICENSE">GPL-2.0-or-later</a>'
        )
        self.links.setTextFormat(Qt.TextFormat.RichText)
        self.links.setOpenExternalLinks(True)

        note = QLabel(
            tr(
                "Alpha version: it may change without notice. Certified compatibility on Windows is "
                "pending; see «Environment diagnostics» for your installation."
            )
        )
        note.setProperty("geoduck", "note")  # la raya ámbar de la marca
        note.setWordWrap(True)

        close = QPushButton(tr("Close"))
        close.setProperty("geoduck", "primary")
        close.setDefault(True)
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.links, 1)
        buttons.addWidget(close)

        # una franja azul arriba: solo aquí, el diálogo de presentación (marca, 2026-11-07)
        band = _Band(QColor(palette.primary), QColor("#1D3F99"))
        band.setFixedHeight(5)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(band)
        layout = QVBoxLayout()
        outer.addLayout(layout)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        layout.addLayout(top)
        layout.addWidget(box)
        layout.addWidget(note)
        layout.addLayout(buttons)

    def _build_header(self, palette: theme.Palette) -> QHBoxLayout:
        """Icono, nombre, versión en una etiqueta y resumen."""
        icon = QLabel()
        icon.setPixmap(QIcon(str(_ICON)).pixmap(56, 56))
        name = QLabel(f'Geo<span style="color: {palette.action};">Duck</span>')  # «Geo» + «Duck» en azul
        name.setTextFormat(Qt.TextFormat.RichText)
        font = QFont(name.font())
        font.setPointSizeF(font.pointSizeF() * 1.6)
        font.setBold(True)
        name.setFont(font)
        self.version = QLabel(version_text())
        self.version.setStyleSheet(
            f"background: {palette.chip}; color: {palette.brand_text}; border: none;"
            "border-radius: 10px; padding: 2px 10px; font-weight: 600;"
        )
        name_row = QHBoxLayout()
        name_row.setSpacing(10)
        name_row.addWidget(name)
        name_row.addWidget(self.version, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addStretch(1)
        summary = QLabel(
            tr("DuckDB session inside QGIS. DuckDB processes, GeoDuck transfers and QGIS manages.")
        )
        summary.setProperty("geoduck", "muted")
        summary.setWordWrap(True)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        heading.addLayout(name_row)
        heading.addWidget(summary)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(heading, 1)
        return top
