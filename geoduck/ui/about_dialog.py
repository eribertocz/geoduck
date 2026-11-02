# SPDX-License-Identifier: GPL-2.0-or-later
"""«Acerca de GeoDuck»: versión, principio de diseño, licencia, enlaces y componentes detectados."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QIcon
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from geoduck import __version__
from geoduck.domain.diagnostics import DiagnosticReport
from geoduck.domain.operations import EngineInfo
from geoduck.ui.i18n import tr
from geoduck.ui.widgets import secondary

REPOSITORY = "https://github.com/eribertocz/geoduck"
_ICON = Path(__file__).resolve().parent.parent / "resources" / "icon.svg"


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


class AboutDialog(QDialog):
    def __init__(
        self,
        report: DiagnosticReport | None,
        engine: EngineInfo | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Acerca de GeoDuck"))
        self.setMinimumWidth(420)

        icon = QLabel()
        icon.setPixmap(QIcon(str(_ICON)).pixmap(48, 48))
        name = QLabel("GeoDuck")
        font = QFont(name.font())
        font.setPointSizeF(font.pointSizeF() * 1.4)
        font.setBold(True)
        name.setFont(font)
        version = secondary(QLabel(tr("Versión") + f" {__version__} · Alpha"))
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(name)
        heading.addWidget(version)
        top = QHBoxLayout()
        top.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(heading, 1)

        summary = QLabel(
            tr("Sesión DuckDB dentro de QGIS. DuckDB procesa, GeoDuck transfiere y QGIS administra.")
        )
        summary.setWordWrap(True)

        self.links = QLabel(
            f'<a href="{REPOSITORY}">{tr("Repositorio")}</a> · '
            f'<a href="{REPOSITORY}/issues">{tr("Informar de un problema")}</a> · '
            f'<a href="{REPOSITORY}/blob/main/LICENSE">GPL-2.0-or-later</a>'
        )
        self.links.setTextFormat(Qt.TextFormat.RichText)
        self.links.setOpenExternalLinks(True)

        self.components = QFormLayout()
        self.components.setContentsMargins(0, 4, 0, 0)
        for label, value in components(report, engine):
            text = QLabel(value)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.components.addRow(secondary(QLabel(label)), text)

        note = secondary(
            QLabel(
                tr(
                    "Versión Alpha: puede cambiar sin aviso. La compatibilidad certificada en Windows está "
                    "pendiente; consulte «Diagnóstico del entorno» para su instalación."
                )
            )
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(top)
        layout.addWidget(summary)
        layout.addWidget(self.links)
        layout.addLayout(self.components)
        layout.addWidget(note)
        layout.addWidget(buttons)
