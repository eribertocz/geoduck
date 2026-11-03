# SPDX-License-Identifier: GPL-2.0-or-later
"""Diálogo «Cargar en QGIS» (ui-ux-spec §3, qgis-bridge-spec §1, GD-BRD-012).

Tres opciones con una línea de ayuda cada una, sin términos técnicos. Las no disponibles se muestran
desactivadas con el motivo. Recuerda la última modalidad elegida. Pregunta el CRS si es desconocido
(decisión 3 de G3).

G4 (spatial-spec §2.2, §7): una casilla por columna geométrica (una capa por columna marcada) y «Usar como
geometría» para columnas `BLOB` (WKB) o `VARCHAR` (WKT), que nunca se marcan solas.
"""

from __future__ import annotations

from qgis.core import QgsCoordinateReferenceSystem, QgsSettings
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
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

from geoduck.domain.bridge_types import GeometryFormat, LoadPlan
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
        layout.addLayout(form)

        # Geometrías: una casilla por columna (una capa por columna marcada)
        self._declared = {g.name: g.declared_crs for g in plan.geometries}
        self._formats: dict[str, GeometryFormat] = {}
        self.geometry_box = QWidget()
        self._geometry_layout = QVBoxLayout(self.geometry_box)
        self._geometry_layout.setContentsMargins(0, 0, 0, 0)
        self.geometry_checks: dict[str, QCheckBox] = {}
        for g in plan.geometries:
            self._add_geometry(g.name, checked=plan.geometry is not None and g.name == plan.geometry.name)
        self.candidate_combo = QComboBox()
        self.candidate_combo.addItem(tr("—"), None)
        self._candidates = dict(plan.candidates)
        for name, fmt in plan.candidates:
            self.candidate_combo.addItem(f"{name} ({fmt.value.upper()})", name)
        geo_form = QFormLayout()
        self.geometry_label = QLabel(tr("Geometrías"))
        geo_form.addRow(self.geometry_label, self.geometry_box)
        self.candidate_label = QLabel(tr("Usar como geometría"))
        geo_form.addRow(self.candidate_label, self.candidate_combo)
        self.candidate_label.setVisible(bool(plan.candidates))
        self.candidate_combo.setVisible(bool(plan.candidates))
        self.crs_form = QFormLayout()
        self.crs_widgets: dict[str, QgsProjectionSelectionWidget] = {}
        layout.addLayout(geo_form)
        layout.addLayout(self.crs_form)
        # «Reproyectar a…»: solo copias y con SRC conocido; QGIS/PROJ (spatial-spec §4)
        self.reproject_check = QCheckBox(tr("Reproyectar a…"))
        self.reproject_check.setToolTip(
            tr(
                "Transforma las coordenadas al copiar. La capa Conectada no se reproyecta: "
                "QGIS lo hace al vuelo."
            )
        )
        self.reproject_widget = QgsProjectionSelectionWidget()
        self.reproject_widget.setEnabled(False)
        reproject_form = QFormLayout()
        reproject_form.addRow(self.reproject_check, self.reproject_widget)
        layout.addLayout(reproject_form)
        # Tipos mixtos (spatial-spec §6): copias, una capa por tipo (activada); Conectada, «Separar por tipo»
        self.split_check = QCheckBox(tr("Tipos mixtos: una capa por tipo"))
        self.split_check.setChecked(True)
        self.split_check.setToolTip(tr("Si se desactiva y hay varios tipos de geometría, no se carga nada."))
        self.separate_check = QCheckBox(tr("Separar por tipo"))
        self.separate_check.setToolTip(
            tr("Una capa Conectada por tipo de geometría, filtrada en DuckDB. Sin marcar: una sola capa.")
        )
        layout.addWidget(self.split_check)
        layout.addWidget(self.separate_check)

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
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._has_mode = choice is not None
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.candidate_combo.currentIndexChanged.connect(self._mark_candidate)
        self.reproject_check.toggled.connect(self._refresh)
        for button in self.mode_buttons.values():
            button.toggled.connect(lambda _checked: self._refresh())
        self._refresh()

    def select_mode(self, mode: LoadMode) -> bool:
        """Marca la modalidad elegida en «Cargar en QGIS ▾» (ui-ux-spec §8). False si no está disponible."""
        button = self.mode_buttons.get(mode)
        if button is None or not button.isEnabled():
            return False
        button.setChecked(True)
        return True

    # -- geometrías ----------------------------------------------------------------------------

    def _add_geometry(self, name: str, *, checked: bool, fmt: GeometryFormat | None = None) -> None:
        label = name if fmt is None else f"{name} ({fmt.value.upper()})"
        box = QCheckBox(label)
        box.setChecked(checked)
        box.toggled.connect(self._refresh)
        self._geometry_layout.addWidget(box)
        self.geometry_checks[name] = box
        if fmt is not None:
            self._formats[name] = fmt

    def _mark_candidate(self) -> None:
        name = self.candidate_combo.currentData()
        if not name:
            return
        fmt = self._candidates[name]
        self.candidate_combo.blockSignals(True)
        self.candidate_combo.removeItem(self.candidate_combo.currentIndex())
        self.candidate_combo.setCurrentIndex(0)
        self.candidate_combo.blockSignals(False)
        self._add_geometry(name, checked=True, fmt=GeometryFormat(fmt))
        self._refresh()

    def checked_geometries(self) -> list[str]:
        return [name for name, box in self.geometry_checks.items() if box.isChecked()]

    def _unknown_crs(self) -> list[str]:
        """Columnas marcadas sin CRS declarado (WKB/WKT nunca lo declaran, spatial-spec §4)."""
        return [
            n
            for n in self.checked_geometries()
            if n in self._formats
            or not self._declared.get(n)
            or not QgsCoordinateReferenceSystem(self._declared[n]).isValid()  # p. ej. «FOO:123» (AX-4b)
        ]

    def _refresh(self) -> None:
        self.geometry_label.setVisible(len(self.geometry_checks) > 1 or bool(self._formats))
        self.geometry_box.setVisible(len(self.geometry_checks) > 1 or bool(self._formats))
        checked = self.checked_geometries()
        unknown = self._unknown_crs()
        self._crs_unknown = bool(unknown)
        for name in list(self.crs_widgets):
            if name not in unknown:
                widget = self.crs_widgets.pop(name)
                self.crs_form.removeRow(widget)
        for name in unknown:
            if name not in self.crs_widgets:
                widget = QgsProjectionSelectionWidget()
                widget.setOptionVisible(QgsProjectionSelectionWidget.CrsOption.CrsNotSet, True)
                widget.setCrs(QgsCoordinateReferenceSystem())
                widget.crsChanged.connect(lambda _crs: self._refresh())
                self.crs_widgets[name] = widget
                self.crs_form.addRow(
                    tr("SRC de «{}»").format(name) if len(checked) > 1 else tr("SRC"), widget
                )
        warnings = [w for w in self._plan.warnings if "geometría secundaria" not in w]
        others = [n for n in self.geometry_checks if n not in checked]
        if others:
            warnings.append(tr("Geometrías que no se cargan: ") + ", ".join(others))
        if len(checked) > 1:
            warnings.append(tr("Se crea una capa por geometría: {} capas").format(len(checked)))
        unrecognized = [
            self._declared[n] for n in unknown if self._declared.get(n) and n not in self._formats
        ]
        if unrecognized:
            warnings.append(
                tr("QGIS no reconoce el SRC declarado ({}). Elija uno o continúe sin SRC.").format(
                    ", ".join(f"«{c}»" for c in unrecognized)
                )
            )
        elif unknown:
            warnings.append(tr("Los datos no declaran SRC. Elija uno o continúe sin SRC."))
        if self.geometry_checks and not checked:
            warnings.append(tr("Marque al menos una geometría."))
        copy = self.mode() in (LoadMode.MEMORY, LoadMode.SNAPSHOT)
        self.split_check.setVisible(bool(checked) and copy)
        self.separate_check.setVisible(bool(checked) and self.mode() is LoadMode.CONNECTED)
        can_reproject = self._can_reproject(checked)
        self.reproject_check.setEnabled(can_reproject)
        self.reproject_widget.setEnabled(can_reproject and self.reproject_check.isChecked())
        if checked and not can_reproject and self.mode() in (LoadMode.MEMORY, LoadMode.SNAPSHOT):
            self.reproject_check.setToolTip(tr("Para reproyectar, cada geometría necesita un SRC."))
        self.warnings_label.setText("\n".join(f"• {w}" for w in warnings))
        self.warnings_label.setVisible(bool(warnings))
        self._ok.setEnabled(self._has_mode and (not self.geometry_checks or bool(checked)))

    def _can_reproject(self, checked: list[str]) -> bool:
        """Solo en copias, con al menos una geometría y SRC conocido (declarado o elegido) en todas."""
        if self.mode() not in (LoadMode.MEMORY, LoadMode.SNAPSHOT) or not checked:
            return False
        for name in checked:
            widget = self.crs_widgets.get(name)
            if widget is not None and not widget.crs().isValid():
                return False
        return True

    def mode(self) -> LoadMode | None:
        return next((m for m, b in self.mode_buttons.items() if b.isChecked()), None)

    def request(self) -> LoadRequest:
        mode = self.mode()
        if mode is None:
            raise ValueError("Ninguna modalidad disponible")
        QgsSettings().setValue(SETTING, mode.value)
        overrides = []
        for column, widget in self.crs_widgets.items():  # sin CRS en los datos: el elegido, o "" = sin CRS
            crs = widget.crs()
            overrides.append((column, (crs.authid() or crs.toWkt()) if crs.isValid() else ""))
        checked = self.checked_geometries()
        geometry = checked[0] if checked else None
        crs_override = dict(overrides).get(geometry) if geometry is not None else None
        name = self.name_edit.text().strip() or tr("Resultado")
        return LoadRequest(
            sql=self._sql,
            mode=mode,
            layer_name=name,
            geometry=geometry,
            crs_override=crs_override,
            geometries=tuple(checked) if len(checked) > 1 else (),
            formats=tuple((n, f.value) for n, f in self._formats.items() if n in checked),
            crs_overrides=tuple(overrides),
            reproject_to=self._reproject_target(),
            split_families=self.split_check.isChecked(),
            separate_types=mode is LoadMode.CONNECTED and self.separate_check.isChecked(),
        )

    def _reproject_target(self) -> str | None:
        if not (self.reproject_widget.isEnabled() and self.reproject_check.isChecked()):
            return None
        crs = self.reproject_widget.crs()
        return (crs.authid() or crs.toWkt()) if crs.isValid() else None
