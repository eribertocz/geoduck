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
        self.setWindowTitle(tr("Diagnóstico de geometrías — «{}»").format(diagnosis.layer_name))
        self._on_repair = on_repair
        self._confirm = confirm or _confirm
        self._diagnosis = diagnosis
        layout = QVBoxLayout(self)
        self.summary_label = QLabel("\n".join(diagnosis.lines()))
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        selected = len(diagnosis.selected)
        note = (
            tr("Se seleccionaron en la capa {} entidades inválidas o ilegibles.").format(selected)
            if selected
            else tr("No hay geometrías inválidas ni ilegibles.")
        )
        layout.addWidget(secondary(QLabel(note + " " + tr("El diagnóstico no cambia la capa ni el origen."))))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.repair_button = QPushButton(tr("Reparar en una copia…"))
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
            tr("Reparar en una copia"),
            tr(
                "Se creará una capa nueva en memoria con las {} geometrías inválidas reparadas "
                "(QGIS «makeValid»). La capa original y el origen no cambian.\n\n"
                "La reparación puede cambiar el tipo, la dimensión o el número de partes de una geometría; "
                "se informará cada cambio."
            ).format(self._diagnosis.invalid),
        ):
            return
        self._on_repair()
        self.accept()
