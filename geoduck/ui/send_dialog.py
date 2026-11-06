# SPDX-License-Identifier: GPL-2.0-or-later
"""Diálogo «Enviar a DuckDB» (G8 · E3; qgis-import-spec §3; maqueta `docs/g8/maqueta/Enviar.dc.html`).

Lo común se hace sin tocar nada: destino, nombres de tabla y caminos vienen bien elegidos y basta con
«Enviar» (decisión del propietario: «menos es más»). Lo demás aparece solo cuando aplica:

- «Qué pasará» por fila y en vivo: «Tabla nueva», «Ya existe» (con su elección, por defecto «No enviar»)
  o «No se puede» con el motivo;
- «Solo seleccionadas», solo si alguna capa tiene selección; «Vista en vez de copia», solo con GeoParquet;
- «Enviar sin SRC», solo si la base destino no guarda el SRC (F-120) o una capa tiene un SRC que no se
  puede expresar (§7);
- las columnas de cada capa, plegadas bajo su fila.

El diálogo no habla con DuckDB: pide el destino con `read_target` y devuelve un `SendRequest`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsSettings
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import QModelIndex, QRect, QSize, Qt
from qgis.PyQt.QtGui import QFont, QKeySequence, QPainter, QPalette
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QShortcut,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.catalog import AccessMode, CatalogSnapshot
from geoduck.domain.importing import (
    PATH_CONNECTED,
    PATH_QGIS,
    Conflict,
    ImportGeometry,
    ImportMode,
    ImportTarget,
    SendCandidate,
    SendItem,
    SendRequest,
    append_problem,
    estimated_seconds,
    is_large,
    path_label,
    unique_name,
)
from geoduck.ui import theme
from geoduck.ui.i18n import tr

#: «Abrir la tabla al terminar» (se recuerda).
OPEN_AFTER_SETTING = "geoduck/send/open_after"
TEMPORARY = ("temp", "main")
_NAME_RE_INVALID = ('"',)

ReadTarget = Callable[[str, str, Callable[[ImportTarget | BaseException], None]], None]

#: Textos de «Si ya existe» (§3), en el orden del desplegable.
CONFLICTS = (
    (Conflict.SKIP, tr("Do not send")),
    (Conflict.REPLACE, tr("Replace")),
    (Conflict.APPEND, tr("Add rows")),
    (Conflict.RENAME, tr("Another name")),
)


def _bold(label: QLabel) -> QLabel:
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


def _count(n: int) -> str:
    return f"{n:,}".replace(",", " ")


#: Rol con la línea de detalle de una capa («GeoPackage · 1 203 entidades · Point · EPSG:4326»).
DETAIL_ROLE = Qt.ItemDataRole.UserRole + 1


class LayerDelegate(QStyledItemDelegate):
    """Fila de capa en dos líneas: el nombre y, debajo, el detalle en gris (los campos, una sola línea)."""

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802 - API de Qt
        size = super().sizeHint(option, index)
        if index.data(DETAIL_ROLE):
            size.setHeight(option.fontMetrics.height() * 2 + 10)
        return size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        detail = index.data(DETAIL_ROLE)
        if not detail:
            super().paint(painter, option, index)
            return
        line = option.fontMetrics.height()
        top = QStyleOptionViewItem(option)
        top.rect = QRect(option.rect.x(), option.rect.y() + 4, option.rect.width(), line + 2)
        super().paint(painter, top, index)
        painter.save()
        painter.setPen(option.palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
        indent = option.fontMetrics.height() + 10  # bajo el nombre, después de la casilla
        rect = QRect(option.rect.x() + indent, option.rect.y() + line + 6, option.rect.width() - indent, line)
        text = option.fontMetrics.elidedText(str(detail), Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        painter.restore()


@dataclass
class RowState:
    """Qué pasará con una fila: `send` (se envía con `mode`), `skip` (no se envía) o `blocked` (motivo)."""

    kind: str
    text: str
    mode: ImportMode = ImportMode.CREATE


class SendDialog(QDialog):
    def __init__(  # noqa: PLR0915 - el diálogo se construye en un solo lugar, de arriba abajo
        self,
        candidates: list[SendCandidate],
        catalog: CatalogSnapshot | None,
        read_target: ReadTarget,
        parent: QWidget | None = None,
        *,
        checked: set[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Send to DuckDB"))
        self.setObjectName("geoduckSendDialog")
        self.setMinimumWidth(600)  # cabe en una pantalla pequeña; las columnas se ajustan
        self.resize(780, 540)
        self.setStyleSheet(theme.stylesheet(theme.palette_for(self)))
        self._candidates = candidates
        self._read_target = read_target
        self._target: ImportTarget | None = None
        self._target_error = ""
        self._asked: tuple[str, str] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # 1. Destino
        row = QHBoxLayout()
        row.addWidget(_bold(QLabel(tr("Destination"))))
        self.destination = QComboBox()
        #: (base, esquema) de cada entrada del desplegable, en su orden; la última, la tabla temporal.
        self.destinations: list[tuple[str, str]] = []
        self.destination.setAccessibleName(tr("Destination database"))
        for database, schema in self._destinations(catalog):
            self.destination.addItem(f"{database} · {schema}")
            self.destinations.append((database, schema))
        self.destination.addItem(tr("Temporary table (this session only)"))
        self.destinations.append(TEMPORARY)
        row.addWidget(self.destination, 1)
        layout.addLayout(row)

        # 2. Capas: una fila por capa, con su tabla y qué pasará; las columnas, plegadas debajo
        self.tree = QTreeWidget()
        self.tree.setObjectName("geoduckSendLayers")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("Layer"), tr("Table in DuckDB"), tr("What will happen")])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setItemDelegateForColumn(0, LayerDelegate(self.tree))
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.tree.header().resizeSection(1, 170)
        self.tree.header().resizeSection(2, 190)
        self.items: list[QTreeWidgetItem] = []
        self.names: list[QLineEdit] = []
        self.conflicts: list[QComboBox] = []
        self.states: list[QLabel] = []
        for c in candidates:
            self._add_row(c, checked)
        layout.addWidget(self.tree, 1)

        # 3. Opciones: solo las que aplican
        selected = sum(c.selected for c in candidates if c.problem is None)
        self.only_selected = QCheckBox(tr("Only selected features ({0})").format(_count(selected)))
        self.only_selected.setVisible(selected > 0)
        self.only_selected.setAccessibleName(tr("Send only the selected features"))
        self.as_view = QCheckBox(tr("View instead of copy (GeoParquet: no data is copied)"))
        self.as_view.setVisible(any(c.can_view for c in candidates))
        # «Reproyectar a…» (§3): con QGIS/PROJ al leer, nunca con DuckDB (sin `spatial`)
        self.reproject = QCheckBox(tr("Reproject to…"))
        self.reproject.setToolTip(tr("Transforms the coordinates while copying, with QGIS/PROJ."))
        self.reproject_crs = QgsProjectionSelectionWidget()
        self.reproject_crs.setAccessibleName(tr("Target CRS"))
        self.reproject_crs.setEnabled(False)
        project_crs = QgsProject.instance().crs()
        if project_crs.isValid():  # por defecto, el SRC del proyecto
            self.reproject_crs.setCrs(project_crs)
        self.reproject_row = QWidget()
        reproject_layout = QHBoxLayout(self.reproject_row)
        reproject_layout.setContentsMargins(0, 0, 0, 0)
        reproject_layout.addWidget(self.reproject)
        reproject_layout.addWidget(self.reproject_crs, 1)
        self.reproject_row.setVisible(any(c.geometry is not None for c in candidates))
        self.reproject.toggled.connect(self.reproject_crs.setEnabled)
        self.reproject_crs.crsChanged.connect(lambda _crs: self.refresh())
        self.without_crs = QCheckBox(tr("Send without CRS"))
        self.without_crs.setVisible(False)
        self.crs_note = QLabel()
        self.crs_note.setProperty("geoduck", "muted")
        self.crs_note.setWordWrap(True)
        self.crs_note.setVisible(False)
        layout.addWidget(self.only_selected)
        layout.addWidget(self.as_view)
        layout.addWidget(self.reproject_row)
        layout.addWidget(self.without_crs)
        layout.addWidget(self.crs_note)

        # 4. Resumen
        self.summary = QLabel()
        self.summary.setObjectName("geoduckSendSummary")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.summary)

        # 5. Pie
        footer = QHBoxLayout()
        self.open_after = QCheckBox(tr("Open the table when done"))
        self.open_after.setChecked(QgsSettings().value(OPEN_AFTER_SETTING, True, type=bool))
        footer.addWidget(self.open_after)
        footer.addStretch(1)
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.setProperty("geoduck", "secondary")
        self.cancel_button.clicked.connect(self.reject)
        self.send_button = QPushButton(tr("Send"))
        self.send_button.setProperty("geoduck", "primary")
        self.send_button.setDefault(True)
        self.send_button.setToolTip(tr("Ctrl+Enter"))
        self.send_button.clicked.connect(self.accept)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.send_button)
        layout.addLayout(footer)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, activated=self._send_if_ready)

        self.tree.itemChanged.connect(lambda *_: self.refresh())
        self.destination.currentIndexChanged.connect(self._destination_changed)
        for box in (self.only_selected, self.as_view, self.reproject, self.without_crs):
            box.toggled.connect(self.refresh)
        self._select_default_destination(catalog)
        self._destination_changed()

    # -- construcción ------------------------------------------------------------------------------

    @staticmethod
    def _destinations(catalog: CatalogSnapshot | None) -> list[tuple[str, str]]:
        """Bases en escritura y sus esquemas (§3: las de solo lectura no se ofrecen)."""
        if catalog is None:
            return []
        out = []
        for db in catalog.databases:
            if db.access is AccessMode.READ_ONLY:
                continue
            out.extend((db.name, schema) for schema in catalog.schemas_of(db.name))
        return out

    def _select_default_destination(self, catalog: CatalogSnapshot | None) -> None:
        """La base en uso y `main` (§3)."""
        if catalog is None:
            return
        wanted = (catalog.default_database.name, "main")
        for i, value in enumerate(self.destinations):
            if value == wanted:
                self.destination.setCurrentIndex(i)
                return

    def _add_row(self, c: SendCandidate, checked: set[str] | None) -> None:  # noqa: PLR0915 - una fila
        item = QTreeWidgetItem([c.name])
        details = [c.source] if c.source else []
        if c.features >= 0:
            details.append(tr("{0} features").format(_count(c.features)))
        details.append(c.geometry_type or tr("no geometry"))
        if c.geometry_type:
            details.append(c.crs_label or tr("no CRS"))
        if c.filtered:
            details.append(tr("with filter: only what the layer shows"))
        item.setData(0, DETAIL_ROLE, " · ".join(details))
        item.setToolTip(0, " · ".join(details))
        sendable = c.problem is None
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        wanted = sendable and (checked is None or c.layer_id in checked)
        item.setCheckState(0, Qt.CheckState.Checked if wanted else Qt.CheckState.Unchecked)
        if not sendable:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        for column in c.columns:  # §6: la conversión de cada campo, plegada
            child = QTreeWidgetItem([f"{column.name}  →  {column.duck_type}"])
            child.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.addChild(child)
        if c.geometry is not None:
            crs = c.geometry.crs if c.geometry.crs and len(c.geometry.crs) < 40 else ""
            child = QTreeWidgetItem([f"{c.geometry.name}  →  GEOMETRY{f'({crs})' if crs else ''}"])
            child.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.addChild(child)
        for warning in c.warnings:
            child = QTreeWidgetItem([f"⚠ {warning}"])
            child.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.addChild(child)
        self.tree.addTopLevelItem(item)
        name = QLineEdit(c.table)
        name.setAccessibleName(tr("Table name for {0}").format(c.name))
        name.setEnabled(sendable)
        conflict = QComboBox()
        for value, text in CONFLICTS:
            conflict.addItem(text, value)
        conflict.setAccessibleName(tr("If the table already exists"))
        state = QLabel()
        state.setWordWrap(True)
        cell = QWidget()
        box = QVBoxLayout(cell)
        box.setContentsMargins(2, 2, 2, 2)
        box.setSpacing(2)
        box.addWidget(state)
        box.addWidget(conflict)
        conflict.hide()
        self.tree.setItemWidget(item, 1, name)
        self.tree.setItemWidget(item, 2, cell)
        self.items.append(item)
        self.names.append(name)
        self.conflicts.append(conflict)
        self.states.append(state)
        name.textChanged.connect(self.refresh)
        index = len(self.items) - 1
        conflict.currentIndexChanged.connect(lambda _i, k=index: self._conflict_changed(k))

    # -- destino ----------------------------------------------------------------------------------

    @property
    def destination_value(self) -> tuple[str, str]:
        return self.destinations[self.destination.currentIndex()]

    @property
    def temporary(self) -> bool:
        return self.destination_value == TEMPORARY

    def _destination_changed(self) -> None:
        database, schema = self.destination_value
        self._target = None
        self._target_error = ""
        self._asked = (database, schema)
        self.refresh()
        self._read_target(
            database, schema, lambda result, asked=(database, schema): self.set_target(asked, result)
        )

    def set_target(self, asked: tuple[str, str], result: ImportTarget | BaseException) -> None:
        """Respuesta de `read_target`; se descarta si el destino cambió mientras tanto."""
        if asked != self._asked:
            return
        if isinstance(result, BaseException):
            self._target_error = str(getattr(result, "message", result))
        else:
            self._target = result
        self.refresh()

    # -- filas ------------------------------------------------------------------------------------

    def _checked(self, i: int) -> bool:
        return self.items[i].checkState(0) == Qt.CheckState.Checked

    def _conflict_changed(self, i: int) -> None:
        if self.conflicts[i].currentData() is Conflict.RENAME:
            taken = [n.text() for k, n in enumerate(self.names) if k != i]
            if self._target is not None:
                taken += [*self._target.tables, *self._target.views]
            self.conflicts[i].blockSignals(True)
            self.conflicts[i].setCurrentIndex(0)
            self.conflicts[i].blockSignals(False)
            self.names[i].setText(unique_name(self.names[i].text().strip(), taken))
            self.names[i].setFocus()
            self.names[i].selectAll()
        self.refresh()

    @property
    def reproject_to(self) -> str | None:
        """Definición del SRC destino de «Reproyectar a…» (`EPSG:…` o WKT2), o None si no se reproyecta."""
        if not self.reproject.isChecked():
            return None
        crs = self.reproject_crs.crs()
        if not crs.isValid():
            return None
        return crs.authid() or crs.toWkt(QgsCoordinateReferenceSystem.WktVariant.WKT2_2019)

    def _geometry_for(self, c: SendCandidate) -> ImportGeometry | None:
        """La geometría como llegará a DuckDB: con el SRC destino si se reproyecta; sin SRC si se pidió."""
        if c.geometry is None:
            return None
        if self.without_crs.isChecked():
            return ImportGeometry(c.geometry.name, None)
        target = self.reproject_to
        if target is not None:
            return ImportGeometry(c.geometry.name, target)
        return c.geometry

    def _needs_without_crs(self, c: SendCandidate) -> bool:
        if c.geometry is None:
            return False
        if c.crs_problem and self.reproject_to is None:
            return True
        crs = self.reproject_to if self.reproject_to is not None else c.geometry.crs
        return bool(crs) and self._target is not None and not self._target.stores_crs

    def row_state(self, i: int) -> RowState:  # noqa: PLR0911, PLR0912 - una regla por caso, en orden
        c = self._candidates[i]
        if c.problem is not None:
            return RowState("blocked", tr("Cannot: {0}").format(c.problem))
        if not self._checked(i):
            return RowState("skip", tr("Not selected"))
        name = self.names[i].text().strip()
        if not name or any(ch in name for ch in _NAME_RE_INVALID):
            return RowState("blocked", tr("Cannot: write a valid table name"))
        others = [
            self.names[k].text().strip().lower()
            for k in range(len(self.items))
            if k != i and self._checked(k)
        ]
        if name.lower() in others:
            return RowState("blocked", tr("Cannot: another layer uses this name"))
        if self.reproject_to is not None and c.geometry is not None and c.path == PATH_CONNECTED:
            return RowState(
                "blocked", tr("Cannot: a Connected layer is sent with its CRS, without reprojecting")
            )
        if self.reproject_to is not None and c.geometry is not None and c.crs_label is None:
            return RowState("blocked", tr("Cannot: the layer has no CRS to reproject from"))
        if self._needs_without_crs(c) and not self.without_crs.isChecked():
            return RowState("blocked", tr("Cannot: the CRS cannot be stored (see below)"))
        if self._target_error:
            return RowState("blocked", tr("Cannot: {0}").format(self._target_error))
        if self._target is None:
            return RowState("skip", tr("Checking…"))
        key = name.lower()
        if key in self._target.views:
            return RowState("blocked", tr("Cannot: a view has this name; choose another name"))
        view = (
            self.as_view.isChecked()
            and c.can_view
            and self.reproject_to is None
            and not (self.only_selected.isChecked() and c.selected)
        )
        if key not in self._target.tables:
            return RowState("send", tr("New view") if view else tr("New table"))
        choice = self.conflicts[i].currentData()
        if choice is Conflict.REPLACE:
            return RowState("send", tr("Already exists: it will be replaced"), ImportMode.REPLACE)
        if choice is Conflict.APPEND:
            if view:
                return RowState("blocked", tr("Cannot: rows cannot be added as a view"))
            problem = append_problem(c.columns, self._geometry_for(c), self._target.tables[key])
            if problem is not None:
                return RowState("blocked", tr("Cannot add rows: {0}").format(problem))
            return RowState("send", tr("Already exists: rows will be added"), ImportMode.APPEND)
        return RowState("skip", tr("Already exists: it will not be sent"))

    def refresh(self) -> None:
        """Recalcula «qué pasará», las opciones visibles, el resumen y si se puede enviar."""
        states = [self.row_state(i) for i in range(len(self.items))]
        for i, state in enumerate(states):
            exists = (
                self._target is not None
                and self._checked(i)
                and self.names[i].text().strip().lower() in self._target.tables
            )
            self.conflicts[i].setVisible(bool(exists))
            self.states[i].setText(state.text)
            self.states[i].setProperty("geoduck", "error-text" if state.kind == "blocked" else "muted")
            self.states[i].style().unpolish(self.states[i])
            self.states[i].style().polish(self.states[i])
        checked = [c for i, c in enumerate(self._candidates) if self._checked(i)]
        needs = [c for c in checked if self._needs_without_crs(c)]
        self.without_crs.setVisible(bool(needs) or self.without_crs.isChecked())
        self.crs_note.setVisible(bool(needs))
        if any(c.crs_problem for c in needs):
            self.crs_note.setText(
                tr(
                    "A layer has a CRS that cannot be expressed: "
                    "reproject it («Reproject to…») or send it without CRS."
                )
            )
        elif needs:
            self.crs_note.setText(
                tr(
                    "This database uses an older file format that cannot store the CRS of a geometry. "
                    "Send without CRS, or choose another database."
                )
            )
        self.summary.setText(self._summary(states))
        sending = [s for s in states if s.kind == "send"]
        blocked = [s for i, s in enumerate(states) if s.kind == "blocked" and self._checked(i)]
        crs_missing = self.reproject.isChecked() and self.reproject_to is None
        self.send_button.setEnabled(
            bool(sending) and not blocked and self._target is not None and not crs_missing
        )

    def _summary(self, states: list[RowState]) -> str:
        if self._target is None and not self._target_error:
            return tr("Checking the destination…")
        if self.reproject.isChecked() and self.reproject_to is None:
            return tr("Choose the target CRS of «Reproject to…».")
        sending = [(i, s) for i, s in enumerate(states) if s.kind == "send"]
        if not sending:
            return tr("Nothing to send: check at least one layer.")
        only = self.only_selected.isChecked()
        created = sum(1 for _, s in sending if s.mode is ImportMode.CREATE)
        replaced = sum(1 for _, s in sending if s.mode is ImportMode.REPLACE)
        added = sum(1 for _, s in sending if s.mode is ImportMode.APPEND)
        rows = sum(self._candidates[i].rows_for(only) for i, _ in sending)
        parts = []
        if created:
            parts.append(tr("{0} new").format(created))
        if replaced:
            parts.append(tr("{0} replaced").format(replaced))
        if added:
            parts.append(tr("{0} with more rows").format(added))
        lines = [f"<b>{' · '.join(parts)}</b> · " + tr("{0} rows").format(_count(rows))]
        reproject = self.reproject_to is not None
        paths = sorted({self._candidates[i].path_for(only, reproject) for i, _ in sending})
        lines.append(tr("How: {0}").format(", ".join(path_label(p) for p in paths)))
        if reproject:
            crs = self.reproject_crs.crs()
            label = crs.authid() or crs.description()
            lines.append(tr("Reprojected to {0} with QGIS/PROJ.").format(label))
        slow = sum(
            self._candidates[i].rows_for(only)
            for i, _ in sending
            if self._candidates[i].path_for(only, reproject) == PATH_QGIS
        )
        if is_large(slow):
            minutes = max(2, round(estimated_seconds(slow) / 60))
            lines.append(
                "⚠ " + tr("Large layers: it may take about {0} minutes. You can cancel.").format(minutes)
            )
        if replaced or added:
            lines.append(tr("Replacing or adding rows cannot be undone from GeoDuck."))
        if any(s.text == tr("New view") for _, s in sending):
            lines.append(tr("The view reads the file each time: it must stay where it is."))
        return "<br>".join(lines)

    # -- resultado ---------------------------------------------------------------------------------

    def _send_if_ready(self) -> None:
        if self.send_button.isEnabled():
            self.accept()

    def accept(self) -> None:
        QgsSettings().setValue(OPEN_AFTER_SETTING, self.open_after.isChecked())
        super().accept()

    def rows_read_by_qgis(self) -> int:
        """Entidades que leerá QGIS (camino general, §5.3): el total de la barra de progreso."""
        only = self.only_selected.isChecked()
        total = 0
        for i in range(len(self.items)):
            c = self._candidates[i]
            if (
                self.row_state(i).kind == "send"
                and c.path_for(only, self.reproject_to is not None) == PATH_QGIS
            ):
                total += c.rows_for(only)
        return total

    def request(self) -> SendRequest:
        """Lo confirmado: solo las filas que se envían (las «No enviar» no van)."""
        items = []
        for i in range(len(self.items)):
            state = self.row_state(i)
            if state.kind == "send":
                items.append(SendItem(self._candidates[i].layer_id, self.names[i].text().strip(), state.mode))
        database, schema = self.destination_value
        return SendRequest(
            tuple(items),
            database,
            schema,
            self.temporary,
            only_selected=self.only_selected.isChecked(),
            as_view=self.as_view.isChecked() and self.reproject_to is None,
            without_crs=self.without_crs.isChecked(),
            reproject_to=self.reproject_to,
        )
