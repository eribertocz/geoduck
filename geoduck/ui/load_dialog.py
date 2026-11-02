# SPDX-License-Identifier: GPL-2.0-or-later
"""Diálogo «Cargar en QGIS» (ui-ux-spec §3, qgis-bridge-spec §1, GD-BRD-012).

Tres opciones con una línea de ayuda cada una, sin términos técnicos. Las no disponibles se muestran
desactivadas con el motivo. Recuerda la última modalidad elegida. Pregunta la geometría si hay varias y el
CRS si es desconocido (decisión 3 de G3).
"""

from __future__ import annotations

from qgis.core import QgsCoordinateReferenceSystem, QgsSettings
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.bridge_types import LoadPlan
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.ui.i18n import tr
from geoduck.ui.widgets import secondary

SETTING = "geoduck/load_mode"

OPTIONS = {
    LoadMode.MEMORY: (
        tr("Copia en memoria"),
        tr("Compatible con todo; para resultados pequeños o medianos."),
    ),
    LoadMode.SNAPSHOT: (tr("Copia rápida"), tr("Rápida y con poca memoria; ideal para resultados grandes.")),
    LoadMode.CONNECTED: (tr("Conectada a DuckDB"), tr("Sin copiar: siempre al día con la sesión.")),
}


class LoadDialog(QDialog):
    def __init__(  # noqa: PLR0915 - un formulario pequeño construido en un solo lugar
        self,
        sql: str,
        title: str,
        plan: LoadPlan,
        modes: dict[LoadMode, str | None],
        parent: QWidget | None = None,
        *,
        replay_notice: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Cargar en QGIS"))
        self._sql = sql
        self._plan = plan
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(title)
        form.addRow(tr("Nombre de la capa"), self.name_edit)
        self.geometry_combo = QComboBox()
        for g in plan.geometries:
            self.geometry_combo.addItem(g.name, g.name)
        if plan.geometry is not None:
            self.geometry_combo.setCurrentIndex(self.geometry_combo.findData(plan.geometry.name))
        if len(plan.geometries) > 1:
            form.addRow(tr("Geometría"), self.geometry_combo)
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setOptionVisible(QgsProjectionSelectionWidget.CrsOption.CrsNotSet, True)
        self.crs_label = QLabel(tr("SRC"))
        form.addRow(self.crs_label, self.crs_widget)
        layout.addLayout(form)

        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[LoadMode, QRadioButton] = {}
        last = QgsSettings().value(SETTING, LoadMode.SNAPSHOT.value)
        for mode, (label, help_text) in OPTIONS.items():
            reason = modes.get(mode)
            button = QRadioButton(label)
            button.setEnabled(reason is None)
            note = secondary(QLabel(help_text if reason is None else reason))
            note.setWordWrap(True)
            note.setContentsMargins(22, 0, 0, 4)
            self.mode_group.addButton(button)
            self.mode_buttons[mode] = button
            layout.addWidget(button)
            layout.addWidget(note)
        preferred = LoadMode(last) if last in {m.value for m in LoadMode} else LoadMode.SNAPSHOT
        available = [m for m in OPTIONS if modes.get(m) is None]
        choice = preferred if preferred in available else (available[0] if available else None)
        if choice is not None:
            self.mode_buttons[choice].setChecked(True)

        if replay_notice:
            notice = secondary(
                QLabel(
                    tr(
                        "Se vuelve a ejecutar la consulta sobre el estado actual de la sesión; "
                        "puede diferir de la vista previa."
                    )
                )
            )
            notice.setWordWrap(True)
            layout.addWidget(notice)
        self.warnings_label = secondary(QLabel(""))
        self.warnings_label.setWordWrap(True)
        layout.addWidget(self.warnings_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Cargar"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(choice is not None)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.geometry_combo.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        name = self.geometry_combo.currentData()
        geom = next((g for g in self._plan.geometries if g.name == name), None)
        unknown = geom is not None and not geom.declared_crs
        self._crs_unknown = unknown
        self.crs_label.setVisible(unknown)
        self.crs_widget.setVisible(unknown)
        if unknown:
            self.crs_widget.setCrs(QgsCoordinateReferenceSystem())
        warnings = [w for w in self._plan.warnings if "geometría secundaria" not in w]
        others = [g.name for g in self._plan.geometries if g.name != name]
        if others:
            warnings.append(tr("Geometrías secundarias que no se cargan: ") + ", ".join(others))
        if unknown:
            warnings.append(tr("Los datos no declaran SRC. Elija uno o continúe sin SRC."))
        self.warnings_label.setText("\n".join(f"• {w}" for w in warnings))
        self.warnings_label.setVisible(bool(warnings))

    def mode(self) -> LoadMode | None:
        return next((m for m, b in self.mode_buttons.items() if b.isChecked()), None)

    def request(self) -> LoadRequest:
        mode = self.mode()
        if mode is None:
            raise ValueError("Ninguna modalidad disponible")
        QgsSettings().setValue(SETTING, mode.value)
        crs_override = None
        if self._crs_unknown:  # sin CRS en los datos: el elegido, o "" para continuar sin CRS
            crs = self.crs_widget.crs()
            crs_override = (crs.authid() or crs.toWkt()) if crs.isValid() else ""
        geometry = self.geometry_combo.currentData() if self._plan.geometries else None
        name = self.name_edit.text().strip() or tr("Resultado")
        return LoadRequest(
            sql=self._sql, mode=mode, layer_name=name, geometry=geometry, crs_override=crs_override
        )
