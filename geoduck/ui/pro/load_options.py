# SPDX-License-Identifier: GPL-2.0-or-later
"""«Cargar en QGIS ▾» › «Más opciones…» (G9 · E6b; workspace-pro-spec §7).

Lo que la carga de un clic no pregunta, para quien lo necesita: elegir qué
geometrías cargar, usar una columna WKB o de texto (WKT) como geometría, «Reproyectar a…» en una Copia y
«Separar por tipo» en una Conectada. Lo demás es igual que la carga de un clic: el SRC que falte se pregunta
después, una sola vez.
"""

from __future__ import annotations

from typing import Any

from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.bridge_types import GeometryFormat, LoadPlan
from geoduck.ui.i18n import tr
from geoduck.ui.pro import style
from geoduck.ui.pro.widgets import Segmented, button, label

COPY_INDEX, CONNECTED_INDEX = 0, 1
#: Con más columnas, «Buscar columna…» y «Todas · Ninguna» (#148, punto 25).
SEARCH_FROM = 8
#: Filas que se ven de la lista de geometrías; el resto, con desplazamiento.
VISIBLE_ROWS = 6
ROW_HEIGHT = 28


def _columns(plan: LoadPlan) -> list[Any]:
    return list(plan.geometries or ((plan.geometry,) if plan.geometry is not None else ()))


def _option(box: QVBoxLayout, check: QWidget, help_text: str) -> QWidget:
    """Una opción: la casilla y, debajo, una línea que dice en simple qué pasará."""
    holder = QWidget()
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(1)
    column.addWidget(check)
    hint = label(help_text, "faint")
    hint.setWordWrap(True)
    hint.setContentsMargins(24, 0, 0, 0)
    column.addWidget(hint)
    box.addWidget(holder)
    return holder


class LoadOptionsDialog(QDialog):
    """Las opciones de una carga. `choice()` devuelve lo elegido para `QuickLoad`."""

    def __init__(
        self, plan: LoadPlan, name: str, kind_index: int = COPY_INDEX, parent: QWidget | None = None
    ):
        super().__init__(parent)
        style.apply(self)
        self.setWindowTitle(tr("GeoDuck"))
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 18)
        box.setSpacing(10)
        box.addWidget(label(tr("Load in QGIS with options"), "title"))
        self.mode = Segmented([tr("Copy (mode)"), tr("Connected")], accessible_name=tr("How to load"))
        self.mode.set_current(kind_index)
        self.mode.changed.connect(lambda _i: self._refresh())
        box.addWidget(self.mode, 0, Qt.AlignmentFlag.AlignLeft)
        # el nombre de la capa (#148, punto 25), ya relleno
        box.addWidget(label(tr("Layer name"), "section"))
        self.name_edit = QLineEdit(name)
        self.name_edit.setAccessibleName(tr("Layer name in QGIS"))
        self.name_edit.setToolTip(
            tr("With several geometries, the name is the prefix: «{0} · geom»").format(name)
        )
        box.addWidget(self.name_edit)

        self._build_geometries(box, plan)
        self._build_options(box)
        self.summary = label("", "muted")
        self.summary.setWordWrap(True)
        box.addWidget(self.summary)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = button(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.load_button = button(tr("Load"), "primary")
        self.load_button.setDefault(True)
        self.load_button.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(self.load_button)
        box.addLayout(actions)
        self.setMinimumWidth(520)
        self._refresh()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:  # nunca más alto que la pantalla: nombre, opciones y botones a la vista
            self.setMaximumHeight(max(360, screen.availableGeometry().height() - 60))

    def _build_geometries(self, box: QVBoxLayout, plan: LoadPlan) -> None:  # noqa: PLR0915 - una lista
        """«Qué geometrías»: solo si hay algo que elegir (varias geometrías o una columna WKB/WKT), en una
        lista de alto fijo con desplazamiento (#148, punto 25); con más de `SEARCH_FROM`, «Buscar columna…» y
        «Todas · Ninguna»."""
        columns = _columns(plan)
        self.geometry_checks: dict[str, QCheckBox] = {}
        self._single = [c.name for c in columns] if len(columns) == 1 else []
        self.candidate_checks: dict[str, tuple[QCheckBox, GeometryFormat]] = {}
        checks: list[QCheckBox] = []
        for column in columns if len(columns) > 1 else ():
            crs = column.declared_crs or tr("no CRS")
            check = QCheckBox(f"{column.name}  ·  {crs}")
            check.setChecked(True)
            self.geometry_checks[column.name] = check
            checks.append(check)
        for name_, fmt in plan.candidates:
            text = tr("Use «{0}» as geometry ({1})").format(
                name_, "WKB" if fmt is GeometryFormat.WKB else "WKT"
            )
            check = QCheckBox(text)
            check.setToolTip(tr("The column has coordinates written as text or bytes: QGIS will draw them."))
            self.candidate_checks[name_] = (check, fmt)
            checks.append(check)
        self.checks = checks
        self.search: QLineEdit | None = None
        self.count = label("", "faint")
        if not checks:
            return
        head = QHBoxLayout()
        box.addLayout(head)
        head.addWidget(label(tr("Which geometries · {0} columns").format(len(checks)), "section"), 1)
        many = len(checks) > SEARCH_FROM
        if many:
            every = button(tr("All"), "link")
            every.clicked.connect(lambda: self._check_all(True))
            none = button(tr("None"), "link")
            none.clicked.connect(lambda: self._check_all(False))
            head.addWidget(every)
            head.addWidget(label("·", "faint"))
            head.addWidget(none)
            self.search = QLineEdit()
            self.search.setPlaceholderText(tr("Search column…"))
            self.search.setAccessibleName(tr("Search column"))
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(self._filter)
            box.addWidget(self.search)
        holder = QWidget()
        column_box = QVBoxLayout(holder)
        column_box.setContentsMargins(8, 4, 8, 4)
        column_box.setSpacing(0)
        for check in checks:
            check.setMinimumHeight(ROW_HEIGHT)
            check.toggled.connect(lambda _c: self._refresh())
            column_box.addWidget(check)
        column_box.addStretch(1)
        self.list = QScrollArea()
        self.list.setWidgetResizable(True)
        self.list.setFrameShape(QFrame.Shape.StyledPanel)
        self.list.setWidget(holder)
        self.list.setFixedHeight(min(len(checks), VISIBLE_ROWS) * ROW_HEIGHT + 10)
        self.list.setAccessibleName(tr("Which geometries"))
        box.addWidget(self.list)
        box.addWidget(self.count)

    def _check_all(self, on: bool) -> None:
        for check in self.checks:
            if not check.isHidden():
                check.setChecked(on)

    def _filter(self, text: str) -> None:
        wanted = text.strip().lower()
        for check in self.checks:
            check.setHidden(bool(wanted) and wanted not in check.text().lower())

    def _build_options(self, box: QVBoxLayout) -> None:
        """«Reproyectar a…» (Copia) y «Separar por tipo» (Conectada): solo la que aplica se ve."""
        from qgis.gui import QgsProjectionSelectionWidget  # noqa: PLC0415

        self.reproject = QCheckBox(tr("Reproject to…"))
        self.reproject.setToolTip(tr("Transforms the coordinates while copying, with QGIS/PROJ."))
        self.reproject_crs = QgsProjectionSelectionWidget()
        self.reproject_crs.setEnabled(False)
        project_crs = QgsProject.instance().crs()
        self.reproject_crs.setCrs(
            project_crs if project_crs.isValid() else QgsCoordinateReferenceSystem("EPSG:4326")
        )
        self.reproject.toggled.connect(self.reproject_crs.setEnabled)
        self.reproject.toggled.connect(lambda _c: self._refresh())
        line = QWidget()
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.reproject)
        row.addWidget(self.reproject_crs, 1)
        box.addWidget(label(tr("Options"), "section"))
        self.reproject_row = _option(
            box,
            line,
            tr(
                "The copy keeps its coordinates in this CRS. Not needed to see it on the map: QGIS does that."
            ),
        )
        self.separate = QCheckBox(tr("Separate by geometry type"))
        self.separate_row = _option(
            box, self.separate, tr("If the column mixes points, lines and polygons: one layer for each.")
        )

    @property
    def connected(self) -> bool:
        return self.mode.group.checkedId() == CONNECTED_INDEX

    def chosen_geometries(self) -> list[str]:
        found = self._single + [name for name, check in self.geometry_checks.items() if check.isChecked()]
        return found + [name for name, (check, _f) in self.candidate_checks.items() if check.isChecked()]

    def _refresh(self) -> None:
        chosen = self.chosen_geometries()
        self.reproject_row.setVisible(not self.connected and bool(chosen))
        self.separate_row.setVisible(self.connected and bool(chosen))
        how = tr("Connected") if self.connected else tr("Copy (mode)")
        if not chosen:
            text = tr("It will load as a table without geometry · {}").format(how)
        elif len(chosen) == 1:
            text = tr("It will load 1 layer · {}").format(how)
        else:
            text = tr("It will load {} layers, one per geometry · {}").format(len(chosen), how)
        self.summary.setText(text)
        if self.checks:
            picked = sum(1 for check in self.checks if check.isChecked())
            count = tr("{0} of {1} chosen").format(picked, len(self.checks))
            if len(self.checks) > VISIBLE_ROWS:
                count += " · " + tr("scroll to see them all")
            self.count.setText(count)

    def choice(self) -> dict[str, Any]:
        """Modo («copy» o «connected»), geometrías, formatos de las columnas marcadas, SRC de destino y
        «Separar por tipo»."""
        crs = self.reproject_crs.crs()
        reproject = (crs.authid() or crs.toWkt()) if (self.reproject.isChecked() and crs.isValid()) else None
        return {
            "kind": "connected" if self.connected else "copy",
            "geometries": self.chosen_geometries(),
            "formats": [(n, f.value) for n, (c, f) in self.candidate_checks.items() if c.isChecked()],
            "reproject_to": None if self.connected else reproject,
            "separate_types": self.connected and self.separate.isChecked(),
            "name": self.name_edit.text().strip(),
        }

    @staticmethod
    def ask(plan: LoadPlan, name: str, kind_index: int, parent: QWidget) -> dict[str, Any] | None:
        dialog = LoadOptionsDialog(plan, name, kind_index, parent)
        return dialog.choice() if dialog.exec() == QDialog.DialogCode.Accepted else None
