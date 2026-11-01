# SPDX-License-Identifier: GPL-2.0-or-later
"""Diálogo con el informe de diagnóstico, copiable para adjuntarlo a un issue."""

from __future__ import annotations

from qgis.PyQt.QtGui import QFontDatabase, QGuiApplication
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.diagnostics import DiagnosticReport
from geoduck.ui.i18n import tr


class DiagnosticsDialog(QDialog):
    def __init__(self, report: DiagnosticReport, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("GeoDuck — Diagnóstico del entorno"))
        self.setMinimumSize(560, 380)
        self._report = report

        summary = QLabel(
            tr("El entorno permite usar GeoDuck.")
            if report.ok
            else tr("El entorno no permite usar GeoDuck. Revise las acciones indicadas.")
        )
        summary.setWordWrap(True)

        self.text = QPlainTextEdit(report.to_text())
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setAccessibleName(tr("Informe de diagnóstico"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.copy_button = QPushButton(tr("Copiar"))
        self.copy_button.setToolTip(tr("Copia el informe para adjuntarlo a un reporte"))
        buttons.addButton(self.copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.text, 1)
        layout.addWidget(buttons)

    def copy_to_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._report.to_text())
