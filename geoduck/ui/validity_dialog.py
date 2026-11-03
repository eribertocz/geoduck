# SPDX-License-Identifier: GPL-2.0-or-later
"""Resultado de «Diagnosticar geometrías…» (spatial-spec §9, ui-ux-spec §2).

Muestra los contadores por estado y los primeros motivos de GEOS. Las inválidas e ilegibles ya están
seleccionadas en la capa. «Reparar en una copia…» pide confirmación y no toca la capa ni el origen.
"""

from __future__ import annotations

from collections.abc import Callable

from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.validity import GeometryDiagnosis
from geoduck.ui.i18n import tr
from geoduck.ui.widgets import secondary


def _confirm(parent: QWidget, title: str, text: str) -> bool:
    answer = QMessageBox.question(
        parent,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


class ValidityDialog(QDialog):
    def __init__(
        self,
        diagnosis: GeometryDiagnosis,
        parent: QWidget | None = None,
        *,
        on_repair: Callable[[], None] | None = None,
        confirm: Callable[[QWidget, str, str], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Geometry diagnosis — «{}»").format(diagnosis.layer_name))
        self._on_repair = on_repair
        self._confirm = confirm or _confirm
        self._diagnosis = diagnosis
        layout = QVBoxLayout(self)
        self.summary_label = QLabel("\n".join(diagnosis.lines()))
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        selected = len(diagnosis.selected)
        note = (
            tr("{} invalid or unreadable features were selected in the layer.").format(selected)
            if selected
            else tr("There are no invalid or unreadable geometries.")
        )
        layout.addWidget(
            secondary(QLabel(note + " " + tr("The diagnosis does not change the layer or its source.")))
        )
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.repair_button = QPushButton(tr("Repair in a copy…"))
        self.repair_button.setEnabled(diagnosis.invalid > 0 and on_repair is not None)
        buttons.addButton(self.repair_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        self.repair_button.clicked.connect(self._repair)
        layout.addWidget(buttons)

    def _repair(self) -> None:
        if self._on_repair is None:
            return
        if not self._confirm(
            self,
            tr("Repair in a copy"),
            tr(
                "A new in-memory layer will be created with the {} invalid geometries repaired (QGIS "
                "«makeValid»). The original layer and its source do not change.\n\nThe repair may "
                "change the type, the dimension or the number of parts of a geometry; every change "
                "will be reported."
            ).format(self._diagnosis.invalid),
        ):
            return
        self._on_repair()
        self.accept()
