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
from qgis.PyQt.QtGui import QFont, QMouseEvent
from qgis.PyQt.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.bridge_types import GeometryFormat, LoadPlan
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.ui import theme
from geoduck.ui.i18n import tr

SETTING = "geoduck/load_mode"

#: Modalidades: nombre y para qué sirve (textos de la maqueta; los mismos en «Cargar en QGIS ▾»).
OPTIONS = {
    LoadMode.MEMORY: (
        tr("Copia en memoria"),
        tr("Capa temporal de QGIS. Para resultados pequeños o medianos."),
    ),
    LoadMode.SNAPSHOT: (tr("Copia rápida"), tr("GeoPackage en memoria. Ideal para resultados grandes.")),
    LoadMode.CONNECTED: (tr("Conectada"), tr("Lee DuckDB bajo demanda. Editable si viene de una tabla.")),
}


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


class ModeCard(QFrame):
    """Una modalidad como tarjeta: el botón de opción con su nombre y, debajo, la descripción o el motivo
    por el que no está disponible. Un clic en cualquier parte de la tarjeta la elige."""

    def __init__(self, label: str, description: str) -> None:
        super().__init__()
        self.setProperty("geoduck", "option-card")
        self.button = QRadioButton(label)
        font = QFont(self.button.font())
        font.setBold(True)
        self.button.setFont(font)
        self.description = QLabel(description)
        self.description.setProperty("geoduck", "muted")
        # Una línea: el diálogo toma el ancho necesario y el texto nunca queda cortado
        self.description.setWordWrap(False)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 8, 12, 8)
        box.setSpacing(2)
        box.addWidget(self.button)
        box.addWidget(self.description)
        self.description.setContentsMargins(2, 0, 0, 0)

    def set_selected(self, selected: bool) -> None:
        if self.property("selected") != selected:
            self.setProperty("selected", selected)
            self.style().unpolish(self)
            self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - API de Qt
        if self.button.isEnabled():
            self.button.setChecked(True)
        event.accept()


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
        self.setMinimumWidth(520)
        self.setStyleSheet(theme.stylesheet(theme.palette_for(self)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        # 1. Capa
        self.name_edit = QLineEdit(title)
        self.name_edit.setAccessibleName(tr("Nombre de la capa"))
        layout.addWidget(_heading(tr("Nombre de la capa")))
        layout.addWidget(self.name_edit)

        # 2. Modalidad: tarjetas de dos líneas, los mismos textos que «Cargar en QGIS ▾» (inventario V30)
        layout.addSpacing(6)
        layout.addWidget(_heading(tr("Modalidad")))
        self.mode_group = QButtonGroup(self)
        self.mode_buttons: dict[LoadMode, QRadioButton] = {}
        self._mode_cards: dict[LoadMode, ModeCard] = {}
        last = QgsSettings().value(SETTING, LoadMode.SNAPSHOT.value)
        for mode, (label, help_text) in OPTIONS.items():
            reason = modes.get(mode)
            card = ModeCard(label, help_text if reason is None else reason)
            card.button.setEnabled(reason is None)
            self.mode_group.addButton(card.button)
            self.mode_buttons[mode] = card.button
            self._mode_cards[mode] = card
            layout.addWidget(card)
        preferred = LoadMode(last) if last in {m.value for m in LoadMode} else LoadMode.SNAPSHOT
        available = [m for m in OPTIONS if modes.get(m) is None]
        choice = preferred if preferred in available else (available[0] if available else None)
        if choice is not None:
            self.mode_buttons[choice].setChecked(True)

        # 3. Geometría: una casilla por columna (una capa por columna marcada); SRC si falta
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
        self.geometry_heading = _heading(tr("Geometría"))
        layout.addSpacing(6)
        layout.addWidget(self.geometry_heading)
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

        # 4. Opciones de la modalidad elegida (solo con geometría): copias, «Reproyectar a…» y tipos mixtos;
        # Conectada, «Separar por tipo» y la nota de que QGIS reproyecta al vuelo (spatial-spec §4, §6)
        self.reproject_check = QCheckBox(tr("Reproyectar a…"))
        self.reproject_check.setToolTip(tr("Transforma las coordenadas al copiar, con QGIS/PROJ."))
        self.reproject_widget = QgsProjectionSelectionWidget()
        self.reproject_widget.setEnabled(False)
        self.reproject_row = QWidget()
        reproject_layout = QHBoxLayout(self.reproject_row)
        reproject_layout.setContentsMargins(0, 0, 0, 0)
        reproject_layout.addWidget(self.reproject_check)
        reproject_layout.addWidget(self.reproject_widget, 1)
        self.reproject_note = QLabel(tr("Se puede reproyectar cuando cada geometría tiene SRC."))
        self.reproject_note.setProperty("geoduck", "muted")
        self.on_the_fly_note = QLabel(tr("QGIS la reproyecta al vuelo en el mapa."))
        self.on_the_fly_note.setProperty("geoduck", "muted")
        self.split_check = QCheckBox(tr("Tipos mixtos: una capa por tipo"))
        self.split_check.setChecked(True)
        self.split_check.setToolTip(tr("Si se desactiva y hay varios tipos de geometría, no se carga nada."))
        self.separate_check = QCheckBox(tr("Separar por tipo"))
        self.separate_check.setToolTip(
            tr("Una capa Conectada por tipo de geometría, filtrada en DuckDB. Sin marcar: una sola capa.")
        )
        self.options_heading = _heading(tr("Opciones"))
        layout.addSpacing(6)
        layout.addWidget(self.options_heading)
        for widget in (self.reproject_row, self.reproject_note, self.split_check, self.separate_check):
            layout.addWidget(widget)
        layout.addWidget(self.on_the_fly_note)

        self.warnings_label = QLabel("")
        self.warnings_label.setProperty("geoduck", "notice")
        self.warnings_label.setWordWrap(True)
        layout.addSpacing(4)
        layout.addWidget(self.warnings_label)
        if replay_notice:
            notice = QLabel(tr("Se vuelve a ejecutar la consulta: puede diferir de la vista previa."))
            notice.setProperty("geoduck", "muted")
            notice.setWordWrap(True)
            layout.addWidget(notice)

        self._ok = QPushButton(tr("Cargar"))
        self._ok.setProperty("geoduck", "primary")
        self._ok.setDefault(True)
        cancel = QPushButton(tr("Cancelar"))
        cancel.setProperty("geoduck", "secondary")
        self._has_mode = choice is not None
        self._ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self._ok)
        layout.addSpacing(6)
        layout.addLayout(buttons)
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
        connected = self.mode() is LoadMode.CONNECTED
        self.split_check.setVisible(bool(checked) and copy)
        self.separate_check.setVisible(bool(checked) and connected)
        can_reproject = self._can_reproject(checked)
        self.reproject_check.setEnabled(can_reproject)
        self.reproject_widget.setEnabled(can_reproject and self.reproject_check.isChecked())
        # Sin geometría no hay nada que reproyectar; en la Conectada, QGIS lo hace al vuelo: se dice, no se
        # deja un control gris sin explicación
        self.reproject_row.setVisible(bool(checked) and copy and can_reproject)
        self.reproject_note.setVisible(bool(checked) and copy and not can_reproject)
        self.on_the_fly_note.setVisible(bool(checked) and connected)
        has_geometry = bool(self.geometry_checks) or bool(self._candidates)
        self.geometry_heading.setVisible(has_geometry)
        self.options_heading.setVisible(bool(checked))
        for mode, card in self._mode_cards.items():
            card.set_selected(self.mode_buttons[mode].isChecked())
        self.warnings_label.setText("\n".join(f"• {w}" for w in warnings))  # recuadro suave
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
