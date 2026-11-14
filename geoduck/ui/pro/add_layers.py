# SPDX-License-Identifier: GPL-2.0-or-later
"""«Capas de QGIS → DuckDB»: una sola ventana de tres pasos para las tres formas de añadir capas
(observaciones de la prueba en Windows, F-131; propietario, 2026-11-06; workspace-pro-spec §9).

- Arrastrar capas a GeoDuck → paso 1 con esas capas (y la base donde se soltaron, ya elegida en el paso 2).
- Clic derecho en QGIS › «Añadir a DuckDB…» → paso 1 con las capas seleccionadas.
- «+» o Ctrl+K › «Añadir capas de QGIS a DuckDB…» → paso 1 con todas las capas del proyecto.

1. **Capas:** agrupadas en puntos, líneas, polígonos y tablas sin geometría, con el icono de QGIS, cuántas
   entidades y el SRC; las que no se pueden, en gris con su motivo. Sin capas, la ventana lo dice.
2. **Dónde:** base y esquema (se pueden cambiar), qué pasará con cada capa y una frase de lo que ocurrirá
   (el diálogo de G8 con el estilo nuevo, dentro de esta ventana).
3. **Progreso:** cada capa con su estado; «×» quita una capa en espera o detiene la que se copia; «Cancelar
   todo»; «Seguir en segundo plano». Al terminar: qué pasó con cada una, «Deshacer», «Abrir» y «Cerrar».

**Cada capa se guarda por separado** (una transacción por capa): las que terminaron quedan aunque se cancelen
las demás; «Deshacer» borra las tablas nuevas. DuckDB escribe de a una cosa: las capas van una tras otra.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable
from typing import Any

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import QComboBox, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from geoduck.app.events import (
    AppEvent,
    SendFailed,
    SendFinished,
    SendProgressed,
    SendUndoFailed,
    SendUndone,
    SpatialActivated,
    SpatialActivationFailed,
    SpatialChecked,
)
from geoduck.domain.errors import GeoDuckError, SessionStateError
from geoduck.domain.files import candidate_for, file_formats_needing_spatial, size_label
from geoduck.domain.i18n import number as number_text
from geoduck.domain.i18n import rows as rows_text
from geoduck.domain.importing import (
    PATH_CONNECTED,
    PATH_GDAL,
    PATH_QGIS,
    Conflict,
    ImportedTable,
    SendCandidate,
    SendRequest,
    table_name_for,
    unique_name,
)
from geoduck.domain.session import SessionState
from geoduck.domain.sql_errors import explain
from geoduck.ui.i18n import tr
from geoduck.ui.pro.error_card import ErrorCardView
from geoduck.ui.pro.timeline import SKIPPED, Step, seconds_text  # los demás estados se escriben igual
from geoduck.ui.pro.transfer import APPEND, CONFLICT, ERROR, FORM, RENAME, REPLACE, NameRow, TransferWindow
from geoduck.ui.pro.widgets import button, label, lines_html
from geoduck.ui.send_dialog import TEMPORARY, SendDialog

#: Ícono de cada origen en la línea de tiempo.
SOURCE_ICONS = {
    "file": "file",
    "database": "database",
    "web": "globe",
    "memory": "memory",
    "duckdb": "database",
}

#: Motivo de un archivo de GDAL sin `spatial` cargada (`geoduck.engine.files.NEEDS_SPATIAL`).
NEEDS_SPATIAL = "needs-spatial"

#: Estado de cada capa (y de cada paso de su línea de tiempo: se escriben igual).
WAITING, RUNNING, DONE, CANCELLED, FAILED = "waiting", "running", "done", "cancelled", "failed"
#: Segundos que se ve el aviso final cuando la ventana está cerrada.
DONE_SECONDS = 15


def _count(n: int) -> str:
    return number_text(n)


def group_of(candidate: SendCandidate) -> int:
    """0 puntos, 1 líneas, 2 polígonos, 3 tablas sin geometría, 4 esperan `spatial`, 5 no se puede."""
    if candidate.problem == NEEDS_SPATIAL:
        return 4
    if candidate.problem is not None:
        return 5
    kind = (candidate.geometry_type or "").lower()
    if not kind:
        return 3
    if "point" in kind:
        return 0
    if "line" in kind or "curve" in kind:
        return 1
    return 2


def group_titles() -> list[str]:
    return [
        tr("Points"),
        tr("Lines"),
        tr("Polygons"),
        tr("Tables without geometry"),
        tr("Need «spatial»"),
        tr("Cannot be added"),
    ]


class AddLayersWindow(TransferWindow):
    """El diálogo único hacia GeoDuck (#148): de dónde → GeoDuck, destino (base y esquema), una fila por capa
    con su nombre en el destino y, al enviar, la línea de tiempo. Lo maneja `AddLayers`."""

    def __init__(self, flow: AddLayers, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.flow = flow
        self.database = QComboBox()
        self.database.setAccessibleName(tr("Destination database"))
        self.schema = QComboBox()
        self.schema.setAccessibleName(tr("Destination schema"))
        self.destination.addWidget(self.database)
        self.destination.addWidget(self.schema)
        self.database.currentIndexChanged.connect(lambda _i: flow.database_changed())
        self.schema.currentIndexChanged.connect(lambda _i: flow.schema_changed())
        # `spatial`, solo con el permiso del usuario (spatial-spec §10, ADR-0011)
        self.note = QFrame()
        self.note.setProperty("pro", "name-note")
        self.note.setProperty("tone", "conflict")
        self.note.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        note_row = QHBoxLayout(self.note)
        note_row.setContentsMargins(10, 8, 10, 8)
        self.note_text = label("", "muted")
        self.note_text.setWordWrap(True)
        note_row.addWidget(self.note_text, 1)
        self.spatial_button = button("", "primary")
        self.spatial_button.clicked.connect(lambda _c=False: self.flow.activate_spatial())
        note_row.addWidget(self.spatial_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.note.setVisible(False)
        self.extra.addWidget(self.note)
        self.options = QVBoxLayout()
        self.options.setSpacing(4)
        self.extra.addLayout(self.options)
        self.rows: dict[str, NameRow] = {}
        self.send_dialog: SendDialog | None = None
        self.on_close = flow.window_closed
        self.on_escape = flow.escape

    def fill(self, candidates: list[SendCandidate], checked: set[str]) -> None:
        """Una fila por capa (las que no se pueden, en gris con su motivo), en el orden de siempre: puntos,
        líneas, polígonos, tablas sin geometría, las que esperan `spatial` y las que no se pueden."""
        self.names.clear()
        self.rows = {}
        for c in sorted(candidates, key=group_of):
            row = NameRow(
                self.colors,
                c.table,
                self._origin(c),
                enabled=c.problem is None,
                checked=c.layer_id in checked,
            )
            if c.file is not None:
                row.origin.setToolTip(c.file.path)
            row.layer_id = c.layer_id  # type: ignore[attr-defined]
            self.names.add(row)
            self.rows[c.layer_id] = row
        self.names.setVisible(bool(candidates))
        self.empty.setVisible(not any(c.problem is None for c in candidates))

    @staticmethod
    def _origin(c: SendCandidate) -> str:
        """«de: predios · GPKG · 10 000»; para un archivo, «lecturas.parquet · Parquet · 2 400 000 filas»; las
        que no se pueden, con su motivo."""
        if c.file is None:
            parts = [c.name, c.source_format or c.source]
            if c.problem:
                parts.append(c.problem)
            elif c.features >= 0:
                parts.append(_count(c.features))
            if c.filtered and not c.problem:
                parts.append(tr("with filter"))
            return " · ".join(p for p in parts if p)
        if c.problem and c.file.file_format.key == "other":
            return c.problem
        parts = [c.name, c.source]
        if c.problem and c.problem != NEEDS_SPATIAL:
            parts.append(c.problem)
        else:
            parts.append(rows_text(c.features) if c.features >= 0 else size_label(c.file.size))
        return " · ".join(p for p in parts if p)

    def chosen(self) -> list[str]:
        return [layer_id for layer_id, row in self.rows.items() if row.included]


class AddLayers:
    """El flujo «Capas de QGIS → DuckDB» y su único envío a la vez. `host` es el workspace: su pie
    (`show_progress`, `set_progress`, `hide_progress`, `progress_text`), `notify`, `toast` y `open_table`."""

    def __init__(self, coordinator: Any, host: Any) -> None:
        self._coordinator = coordinator
        self._host = host
        self.window: AddLayersWindow | None = None
        self._candidates: list[SendCandidate] = []
        self._destination: tuple[str, str] | None = None
        self.request: SendRequest | None = None
        #: Por capa del envío: estado, filas copiadas, total esperado (-1 = no se sabe) y mensaje.
        self.states: list[dict[str, Any]] = []
        self._current: int | None = None
        self._mine = False
        self._stop_all = False
        self._undoing = False
        self.tables: list[ImportedTable] = []
        self.running = False
        #: Archivos → DuckDB (qgis-import-spec §10) en vez de capas de QGIS.
        self.files = False
        self._paths: list[str] = []
        self._scanning = False
        self._spatial_installed: bool | None = None
        #: `spatial` cargada en la sesión (capas que vienen de un archivo: las copia DuckDB, §5.4).
        self._spatial_loaded = False
        self._activating = False
        self._unsubscribe = coordinator.subscribe(self._on_event)

    # -- abrir ------------------------------------------------------------------------------------------

    def open(
        self,
        layer_ids: list[str] | None,
        destination: tuple[str, str] | None = None,
        *,
        checked: list[str] | None = None,
    ) -> None:
        """Paso 1 con `layer_ids` (arrastradas o del clic derecho) o, con None, todas las capas del proyecto
        (marcadas las de `checked`). Si ya hay capas copiándose, muestra ese progreso."""
        if self.running:
            self.show_window()
            self._host.notify(tr("Finish or cancel these layers to add more."))
            return
        coordinator = self._coordinator
        if coordinator.state is not SessionState.READY or coordinator.catalog is None:
            self._host.notify(tr("Start GeoDuck to add layers."))
            return
        self.files = False
        self._candidates = coordinator.send_candidates(layer_ids)
        self._destination = destination
        self._spatial_loaded = False
        if any(c.path == PATH_GDAL and c.needs_spatial for c in self._candidates):
            coordinator.check_spatial()  # responde con SpatialChecked: nota «Instalar y acelerar»
        marked = set(layer_ids) if layer_ids is not None else set(checked or [])
        window = self._window()
        window.fill(self._candidates, marked)
        window.note.setVisible(False)
        self._build_model(marked)
        self._show_form()
        window.show()
        window.raise_()
        window.activateWindow()

    def open_files(self, paths: list[str], destination: tuple[str, str] | None = None) -> None:
        """«Importar archivos…», soltar archivos o «Importar archivos aquí…» (qgis-import-spec §10): el paso 1
        con lo que DuckDB lee de cada archivo (solo metadatos), todo marcado."""
        if self.running:
            self.show_window()
            self._host.notify(tr("Finish or cancel these layers to add more."))
            return
        coordinator = self._coordinator
        if coordinator.state is not SessionState.READY or coordinator.catalog is None:
            self._host.notify(tr("Start GeoDuck to import files."))
            return
        if not paths:
            return
        self.files = True
        self._paths = list(paths)
        self._destination = destination
        self._candidates = []
        window = self._window()
        window.fill([], set())
        window.empty.setText(tr("Reading the files…"))
        window.empty.setVisible(True)
        window.note.setVisible(False)
        self._build_model(set())
        self._show_form()
        window.show()
        window.raise_()
        window.activateWindow()
        self._scan()

    def _scan(self) -> None:
        self._scanning = True
        try:
            self._scan_op = self._coordinator.scan_files(self._paths, self._scanned)
        except GeoDuckError as exc:
            self._scanning = False
            self._host.notify(exc.message)

    def _scanned(self, result: Any) -> None:
        self._scanning = False
        window = self.window
        if window is None or not self.files:
            return
        if isinstance(result, BaseException):
            window.empty.setText(tr("The files could not be read: ") + str(result))
            window.empty.setVisible(True)
            return
        taken: list[str] = []
        candidates = []
        for i, item in enumerate(result):
            table = unique_name(table_name_for(item.name), taken)
            taken.append(table)
            candidates.append(candidate_for(item, i, table))
        self._candidates = candidates
        marked = {c.layer_id for c in candidates if c.problem is None}
        window.fill(candidates, marked)
        self._build_model(marked)
        window.empty.setText(tr("None of these files can be read."))
        window.empty.setVisible(not any(c.problem is None for c in candidates))
        if any(c.problem == NEEDS_SPATIAL for c in candidates):
            window.empty.setVisible(False)
            self._show_spatial_note()
            self._coordinator.check_spatial()
        else:
            window.note.setVisible(False)
        self.choice_changed()

    def _show_speed_note(self, error: str = "") -> None:
        """Capas de QGIS que vienen de un archivo: con `spatial`, DuckDB las copia mucho más rápido (§5.4).
        Sin el clic, las copia QGIS como siempre: nunca bloquea."""
        window = self._window()
        installed = self._spatial_installed
        label_text = tr("Load and speed up") if installed else tr("Install and speed up")
        text = tr(
            "With the «spatial» extension, layers that come from a file are copied directly by GeoDuck: "
            "up to 20 times faster."
        )
        text += " " + (
            tr("It is installed but not loaded: GeoDuck will load it when you press «{0}».")
            if installed
            else tr(
                "It is not installed: GeoDuck will install it when you press «{0}» (only once, about 40 MB)."
            )
        ).format(label_text)
        text += " " + tr("Without it, QGIS copies them as usual.")
        if error:
            text += "\n" + tr("It could not be activated: ") + error
        window.note_text.setText(text)
        window.spatial_button.setText(label_text)
        window.spatial_button.setEnabled(not self._activating)
        window.note.setVisible(True)

    def _show_spatial_note(self, error: str = "") -> None:
        if not self.files:
            self._show_speed_note(error)
            return
        window = self._window()
        formats = file_formats_needing_spatial(
            [c.file for c in self._candidates if c.problem == NEEDS_SPATIAL]
        )
        installed = self._spatial_installed
        if installed:
            action = tr("It is installed but not loaded: GeoDuck will load it when you press «{0}».")
            label_text = tr("Load and continue")
        else:
            action = tr(
                "It is not installed: GeoDuck will install it when you press «{0}» (only once, about 40 MB)."
            )
            label_text = tr("Install and continue")
        text = tr("{0} are read with the «spatial» extension (the fastest).").format(formats)
        text += " " + action.format(label_text)
        if error:
            text += "\n" + tr("It could not be activated: ") + error
        window.note_text.setText(text)
        window.spatial_button.setText(label_text)
        window.spatial_button.setEnabled(not self._activating)
        window.note.setVisible(True)

    def activate_spatial(self) -> None:
        """«Instalar y continuar» o «Cargar y continuar»: el único lugar donde GeoDuck instala o carga
        `spatial`, porque el usuario lo pidió (spatial-spec §10)."""
        if self._activating:
            return
        self._activating = True
        try:
            self._coordinator.activate_spatial(install=not self._spatial_installed)
        except GeoDuckError as exc:
            self._activating = False
            self._show_spatial_note(exc.message)
            return
        window = self._window()
        window.spatial_button.setEnabled(False)
        window.spatial_button.setText(tr("Installing…") if not self._spatial_installed else tr("Loading…"))

    def _window(self) -> AddLayersWindow:
        if self.window is None:
            self.window = AddLayersWindow(self, self._host if isinstance(self._host, QWidget) else None)
        return self.window

    def show_window(self) -> None:
        """Volver a la ventana (pie, Ctrl+K): en el paso en que quedó."""
        if self.window is not None:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def window_closed(self) -> None:
        """Cerrar con la X: un envío en curso sigue en segundo plano (el pie lo trae de vuelta); la lectura
        de los archivos, que nadie verá, se cancela (#171)."""
        if getattr(self, "_scanning", False) and getattr(self, "_scan_op", None) is not None:
            self._coordinator.cancel_operation(self._scan_op)
            self._scan_op = None  # una sola vez (la ventana avisa al cerrarse y al ocultarse)

    # -- destino y nombres (#148, puntos 15 y 16) ----------------------------------------------------------

    def _build_model(self, marked: set[str]) -> None:
        """Las reglas de siempre (qué se envía, nombres válidos, SRC, selección, reproyectar) son las del
        diálogo de G8, sin mostrarlo: la ventana es su vista. Sus opciones («Solo seleccionadas», «Más
        opciones») pasan a la ventana."""
        self._drop_send_dialog()
        window = self._window()
        coordinator = self._coordinator
        dialog = SendDialog(
            self._candidates,
            coordinator.catalog,
            coordinator.read_import_target,
            window,
            checked=marked,
            destination=self._destination,
            pro=True,
        )
        dialog.hide()
        dialog.duckdb_reads = self._spatial_loaded  # §5.4: las capas de archivo, por DuckDB
        dialog.on_target = self.sync
        window.send_dialog = dialog
        for widget in (
            dialog.only_selected,
            dialog.more_button,
            dialog.as_view,
            dialog.reproject_row,
            dialog.without_crs,
            dialog.crs_note,
        ):
            if widget is not None:
                window.options.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
        for row in window.rows.values():
            row.changed.connect(self.sync)
        self._fill_destinations()
        self.sync()

    def _fill_destinations(self) -> None:
        """Base y esquema (#148): las bases en escritura y, al final, «Tabla temporal (solo esta sesión)»."""
        window = self._window()
        dialog = window.send_dialog
        if dialog is None:
            return
        databases: list[str] = []
        for database, _schema in dialog.destinations:
            if database not in databases:
                databases.append(database)
        current = dialog.destination_value
        window.database.blockSignals(True)
        window.database.clear()
        for database in databases:
            text = tr("Temporary table (this session only)") if (database, "main") == TEMPORARY else database
            window.database.addItem(text, database)
        window.database.setCurrentIndex(max(0, databases.index(current[0]) if current[0] in databases else 0))
        window.database.blockSignals(False)
        self._fill_schemas(current[1])

    def _fill_schemas(self, wanted: str | None = None) -> None:
        window = self._window()
        dialog = window.send_dialog
        if dialog is None:
            return
        database = window.database.currentData()
        schemas = [s for d, s in dialog.destinations if d == database]
        window.schema.blockSignals(True)
        window.schema.clear()
        for schema in schemas:
            window.schema.addItem(schema)
        if wanted in schemas:
            window.schema.setCurrentIndex(schemas.index(wanted))
        elif "main" in schemas:
            window.schema.setCurrentIndex(schemas.index("main"))
        window.schema.blockSignals(False)
        window.schema.setVisible((database, "main") != TEMPORARY)

    def database_changed(self) -> None:
        self._fill_schemas()
        self.schema_changed()

    def schema_changed(self) -> None:
        window = self._window()
        dialog = window.send_dialog
        if dialog is None:
            return
        wanted = (window.database.currentData(), window.schema.currentText() or "main")
        if wanted in dialog.destinations:
            dialog.destination.setCurrentIndex(dialog.destinations.index(wanted))
        self.sync()

    def _effective_names(self) -> list[str]:
        """El nombre con que se crea cada tabla: el de la fila, o «nombre_2» si ya existe y se eligió «Usar
        «nombre_2»» (lo propuesto, #148, punto 16)."""
        window = self._window()
        dialog = window.send_dialog
        target = dialog._target if dialog is not None else None
        taken = [*target.tables, *target.views] if target is not None else []
        names = []
        for c in self._candidates:
            row = window.rows.get(c.layer_id)
            name = row.name if row is not None else c.table
            renamed = row is not None and row.included and row.choice == RENAME
            if renamed and target is not None and name.lower() in target.tables:
                name = unique_name(name, taken)
            taken.append(name)
            names.append(name)
        return names

    def sync(self) -> None:
        """Lleva lo elegido en la ventana a las reglas y trae de vuelta qué pasa con cada fila."""
        window = self.window
        dialog = window.send_dialog if window is not None else None
        if window is None or dialog is None or self.running:
            return
        conflict = {REPLACE: Conflict.REPLACE, APPEND: Conflict.APPEND, RENAME: Conflict.SKIP}
        dialog.tree.blockSignals(True)
        for i, (c, name) in enumerate(zip(self._candidates, self._effective_names(), strict=True)):
            row = window.rows.get(c.layer_id)
            if row is None:
                continue
            state = Qt.CheckState.Checked if row.included else Qt.CheckState.Unchecked
            dialog.items[i].setCheckState(0, state)
            dialog.names[i].blockSignals(True)
            dialog.names[i].setText(name)
            dialog.names[i].blockSignals(False)
            box = dialog.conflicts[i]
            box.blockSignals(True)
            box.setCurrentIndex(max(0, box.findData(conflict[row.choice])))
            box.blockSignals(False)
        dialog.tree.blockSignals(False)
        dialog.refresh()
        self._show_notes()
        self.choice_changed()

    def _show_notes(self) -> None:
        """Bajo cada fila: «Ya existe en memory.main · Usar «lecturas_2» · Reemplazar · Añadir filas», o por
        qué no se puede."""
        window = self._window()
        dialog = window.send_dialog
        if dialog is None:
            return
        target = dialog._target
        database, schema = dialog.destination_value
        where = tr("this session (temporary)") if dialog.temporary else f"{database}.{schema}"
        taken = [*target.tables, *target.views] if target is not None else []
        for i, c in enumerate(self._candidates):
            row = window.rows.get(c.layer_id)
            if row is None or c.problem is not None:
                continue
            if not row.included:
                row.set_note(None)
                continue
            state = dialog.row_state(i)
            exists = target is not None and row.name.lower() in target.tables
            if exists:
                text = tr("Already exists in {0}").format(where)
                if state.kind == "blocked":
                    text += " · " + state.text
                row.set_note(
                    CONFLICT,
                    text,
                    {
                        RENAME: tr("Use «{0}»").format(unique_name(row.name, taken)),
                        REPLACE: tr("Replace"),
                        APPEND: tr("Add rows"),
                    },
                )
            elif state.kind == "blocked":
                row.set_note(ERROR, state.text)
            else:
                row.set_note(None)

    def _show_form(self) -> None:
        window = self._window()
        self._final_shown = None
        count = sum(1 for c in self._candidates if c.problem is None)
        if self.files:
            source = (
                "file",
                tr("1 file") if len(self._paths) == 1 else tr("{0} files").format(len(self._paths)),
            )
            title = tr("Import to GeoDuck")
        else:
            source = ("layers", tr("1 QGIS layer") if count == 1 else tr("{0} QGIS layers").format(count))
            title = tr("Send to GeoDuck")
        window.set_route(title, source, ("logo", tr("GeoDuck")))
        window.show_form()
        self.count_label = label("", "muted")
        cancel = button(tr("Cancel"))
        cancel.clicked.connect(window.reject)
        self.add_button = button("", "primary")
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.start)
        self.next_button = self.add_button  # compatibilidad: «Siguiente» ya no existe (un solo paso)
        window.set_footer([self.count_label], [cancel, self.add_button])
        window.fit_screen()
        self.choice_changed()

    def choice_changed(self) -> None:
        window = self.window
        if window is None or window.stack.currentIndex() != FORM or not hasattr(self, "add_button"):
            return
        dialog = window.send_dialog
        count = len(dialog.request().items) if dialog is not None and dialog.target_ready else 0
        chosen = len(window.chosen())
        self.count_label.setText(
            tr("1 layer chosen") if chosen == 1 else tr("{0} layers chosen").format(chosen)
        )
        verb = tr("Import") if self.files else tr("Send")
        self.add_button.setText(
            verb + " " + (tr("1 layer") if count == 1 else tr("{0} layers").format(count))
        )
        self.add_button.setEnabled(dialog is not None and dialog.send_button.isEnabled() and count > 0)

    def _drop_send_dialog(self) -> None:
        window = self.window
        if window is not None and window.send_dialog is not None:
            window.send_dialog.on_target = None
            window.send_dialog.hide()
            window.send_dialog.setParent(None)
            window.send_dialog.deleteLater()
            window.send_dialog = None

    # -- paso 3: enviar capa por capa --------------------------------------------------------------------

    def start(self) -> None:
        window = self._window()
        dialog = window.send_dialog
        if dialog is None or not self.add_button.isEnabled():
            return
        self.sync()
        request = dialog.request()
        only = request.only_selected
        by_id = {c.layer_id: c for c in self._candidates}
        if self.files:  # cada fila lleva su archivo hasta el motor
            request = dataclasses.replace(
                request,
                items=tuple(dataclasses.replace(i, file=by_id[i.layer_id].file) for i in request.items),
            )
        self.request = request
        self.states = []
        for item in request.items:
            c = by_id[item.layer_id]
            total = (
                c.rows_for(only)
                if c.path_for(only, request.reproject_to is not None, request.duckdb_reads) == PATH_QGIS
                else -1
            )
            self.states.append({"state": WAITING, "rows": 0, "total": total, "name": c.name, "message": ""})
        self.tables = []
        self._stop_all = False
        self.running = True
        self.started = time.monotonic()
        self._build_progress()
        self._host.show_progress(self.progress_text(), 0)
        QTimer.singleShot(0, self._next)

    def _next(self, attempt: int = 0) -> None:
        if not self.running:
            return
        waiting = [i for i, s in enumerate(self.states) if s["state"] == WAITING]
        if self._stop_all or not waiting:
            self._finish()
            return
        index = waiting[0]
        assert self.request is not None
        fallback = bool(self.states[index].get("fallback"))
        single = dataclasses.replace(
            self.request,
            items=(self.request.items[index],),
            duckdb_reads=self.request.duckdb_reads and not fallback,  # §5.4: tras un filtro distinto, QGIS
            direct=self.request.direct and not fallback,  # #140: tras un intento directo que falló, QGIS
        )
        self._current = index
        self.states[index]["state"] = RUNNING
        self.states[index]["started"] = time.monotonic()
        self._mine = True  # `SendStarted` llega antes de que `send_layers` devuelva
        try:
            self._coordinator.send_layers(single)
        except SessionStateError:
            self._mine = False
            self.states[index]["state"] = WAITING
            if attempt < 50:  # la sesión aún relee el catálogo de la capa anterior
                QTimer.singleShot(100, lambda: self._next(attempt + 1))
                return
            self._mark(index, FAILED, tr("GeoDuck is busy"))
            QTimer.singleShot(0, self._next)
        except GeoDuckError as exc:
            self._mine = False
            self._mark(index, FAILED, exc.message)
            QTimer.singleShot(0, self._next)
        self._refresh()

    def _mark(self, index: int, state: str, message: str = "") -> None:
        self.states[index]["state"] = state
        self.states[index]["message"] = message
        if self._current == index and state != RUNNING:
            self._current = None

    def remove(self, index: int) -> None:
        """«×» de una capa: quita la que espera o detiene la que se copia (esa no queda en DuckDB)."""
        state = self.states[index]["state"]
        if state == WAITING:
            self._mark(index, CANCELLED)
            self._refresh()
        elif state == RUNNING:
            self._coordinator.cancel_current_operation()

    def cancel_all(self) -> None:
        self._stop_all = True
        for i, s in enumerate(self.states):
            if s["state"] == WAITING:
                self._mark(i, CANCELLED)
        if self._current is not None:
            self._coordinator.cancel_current_operation()
        else:
            self._finish()
        self._refresh()

    def _on_spatial(self, event: AppEvent) -> bool:  # noqa: PLR0911 - un evento por rama
        """`spatial` consultada, activada o fallida: la nota del paso 1. True si el evento era ese."""
        if not self.files and not self.running and isinstance(event, SpatialChecked):
            self._spatial_installed = event.installed
            self._spatial_loaded = event.loaded
            needs = any(c.path == PATH_GDAL and c.needs_spatial for c in self._candidates)
            if (
                needs
                and not event.loaded
                and self.window is not None
                and self.window.stack.currentIndex() == FORM
            ):
                self._show_speed_note()
            return True
        if not self.files and isinstance(event, SpatialActivated) and self._activating:
            self._activating = False
            self._spatial_installed = self._spatial_loaded = True
            if self.window is not None:
                self.window.note.setVisible(False)
                if self.window.send_dialog is not None:  # desde ya, las capas de archivo las copia DuckDB
                    self.window.send_dialog.duckdb_reads = True
                    self.sync()
            self._host.notify(
                tr("«spatial» is loaded: GeoDuck copies the layers that come from a file directly.")
            )
            return True
        if not self.files and isinstance(event, SpatialActivationFailed) and self._activating:
            self._activating = False
            self._show_speed_note(event.message)
            return True
        if self.files and isinstance(event, SpatialChecked):
            self._spatial_installed = event.installed
            if event.loaded:  # alguien la cargó (p. ej. con SQL): basta con volver a leer
                self._scan()
            elif self.window is not None and self.window.note.isVisible():
                self._show_spatial_note()
            return True
        if self.files and isinstance(event, SpatialActivated) and self._activating:
            self._activating = False
            self._spatial_installed = True
            if self.window is not None:
                self.window.note.setVisible(False)
            self._scan()
            return True
        if self.files and isinstance(event, SpatialActivationFailed) and self._activating:
            self._activating = False
            self._show_spatial_note(event.message)
            return True
        return False

    def _on_event(self, event: AppEvent) -> None:
        if self._on_spatial(event):
            return
        index = self._current
        if isinstance(event, SendProgressed) and self._mine and index is not None:
            self.states[index]["rows"] = event.rows
            self._refresh()
        elif isinstance(event, SendFinished) and self._mine and index is not None:
            self._mine = False
            rows = sum(t.rows for t in event.report.tables)
            self.states[index]["rows"] = rows
            started = self.states[index].get("started")
            self.states[index]["seconds"] = time.monotonic() - started if started else None
            request = self.request
            candidate = (
                next((c for c in self._candidates if c.layer_id == request.items[index].layer_id), None)
                if request is not None
                else None
            )
            self.states[index]["checked"] = bool(
                request is not None
                and candidate is not None
                and candidate.filtered
                and not self.states[index].get("fallback")
                and candidate.path_for(
                    request.only_selected, request.reproject_to is not None, request.duckdb_reads
                )
                == PATH_GDAL
            )
            self._mark(index, DONE, " · ".join(event.report.warnings))
            self.tables.extend(event.report.tables)
            QTimer.singleShot(0, self._next)
            self._refresh()
        elif isinstance(event, SendFailed) and self._mine and index is not None and self._retry(index, event):
            self._mine = False
            QTimer.singleShot(0, self._next)
            self._refresh()
        elif isinstance(event, SendFailed) and self._mine and index is not None:
            self._mine = False
            self._mark(
                index, CANCELLED if event.cancelled else FAILED, "" if event.cancelled else event.message
            )
            QTimer.singleShot(0, self._next)
            self._refresh()
        elif isinstance(event, SendUndone) and self._undoing:
            self._undoing = False
            self._host.notify(tr("Undone: {0}").format(", ".join(t.display for t in event.tables)))
            self.tables = [t for t in self.tables if t not in event.tables]
            self._refresh()
        elif isinstance(event, SendUndoFailed) and self._undoing:
            self._undoing = False
            self._host.notify(tr("It could not be undone:") + f" {event.message}")

    def _retry(self, index: int, event: SendFailed) -> bool:
        """Una capa de archivo leída por DuckDB que falló (filtro que DuckDB no entiende o que da otras
        filas; o un Parquet, Arrow, CSV o JSON que DuckDB entiende distinto que QGIS, #140): se copia por
        QGIS, sin error para el usuario (§5.4). True si se reintenta."""
        state = self.states[index]
        if event.cancelled or state.get("fallback") or self.request is None:
            return False
        request = self.request
        candidate = next((c for c in self._candidates if c.layer_id == request.items[index].layer_id), None)
        if candidate is None or candidate.path != PATH_GDAL:
            return False
        if candidate.path_for(
            request.only_selected, request.reproject_to is not None, request.duckdb_reads
        ) != (PATH_GDAL):
            return False  # no se leyó directo: el error es de QGIS, no se repite
        if candidate.needs_spatial and not candidate.filtered:
            return False
        state["fallback"] = True
        state["state"] = WAITING
        state["rows"] = 0
        state["total"] = candidate.rows_for(self.request.only_selected)
        self._current = None
        return True

    def _finish(self) -> None:
        if not self.running:
            return
        self.running = False
        self._current = None
        self.seconds = time.monotonic() - getattr(self, "started", time.monotonic())
        if getattr(self, "_clock", None) is not None:
            self._clock.stop()
        self._host.hide_progress()
        self._refresh()
        text = lines_html(self.done_lines())
        # un solo aviso: el resumen del paso 3 o, con la ventana cerrada, el aviso con «×»; nada en el pie,
        # que quedaría desactualizado (observación del propietario, 2026-11-06)
        self._host.notify("")
        if self.window is None or not self.window.isVisible():
            actions: list[tuple[str, Callable[[], None]]] = []
            if self.tables:
                actions.append((tr("Open"), lambda: self._host.open_table(self.tables[0])))
            if any(t.can_undo for t in self.tables):
                actions.append((tr("Undo"), self.undo))
            self._host.toast(text, actions, DONE_SECONDS)

    def done_lines(self) -> list[str]:
        """El resumen, una idea por línea: cuántas y en qué sentido; en qué base; canceladas; con error."""
        added = sum(1 for s in self.states if s["state"] == DONE)
        database = self.request.database if self.request is not None else ""
        schema = self.request.schema if self.request is not None else ""
        if self.files:
            lines = [
                tr("1 table added to GeoDuck from files")
                if added == 1
                else tr("{0} tables added to GeoDuck from files").format(added)
            ]
        elif added == 1:
            lines = [tr("1 QGIS layer added to GeoDuck")]
        else:
            lines = [tr("{0} QGIS layers added to GeoDuck").format(added)]
        lines.append(tr("Catalog: {0} · Schema: {1}").format(database, schema))
        cancelled = [s["name"] for s in self.states if s["state"] == CANCELLED]
        failed = [s["name"] for s in self.states if s["state"] == FAILED]
        if cancelled:
            lines.append(tr("{0} cancelled ({1})").format(len(cancelled), ", ".join(cancelled)))
        if failed:
            lines.append(tr("{0} with error ({1})").format(len(failed), ", ".join(failed)))
        return lines

    def done_text(self) -> str:
        return " · ".join(self.done_lines())

    def progress_text(self) -> str:
        """La línea del pie: «⟳ Añadiendo 2 de 4 · redes_bt 62 %» (clic: vuelve al paso 3)."""
        total = len(self.states)
        done = sum(1 for s in self.states if s["state"] in (DONE, CANCELLED, FAILED))
        index = self._current
        text = "⟳ " + tr("Adding {0} of {1} to GeoDuck").format(min(done + 1, total), total)
        if index is not None:
            s = self.states[index]
            text += f" · {s['name']}"
            if s["total"] > 0:
                text += f" {min(100, s['rows'] * 100 // s['total'])} %"
        return text

    def undo(self) -> None:
        undoable = [t for t in self.tables if t.can_undo]
        if not undoable:
            return
        self._undoing = True
        try:
            self._coordinator.undo_send(undoable)
        except GeoDuckError as exc:
            self._undoing = False
            self._host.notify(tr("It could not be undone:") + f" {exc.message}")

    # -- progreso: la línea de tiempo (#148, punto 19) ------------------------------------------------------

    def _build_progress(self) -> None:
        """El mismo diálogo pasa a la línea de tiempo: el total arriba y una fila plegable por capa."""
        window = self._window()
        window.show_progress()
        view = window.timeline
        view.clear()
        assert self.request is not None
        self.timeline_rows = [
            view.add_row(self.states[i]["name"], on_remove=lambda _c=False, index=i: self.remove(index))
            for i in range(len(self.request.items))
        ]
        stop = button(tr("Cancel") + " · Esc")
        stop.clicked.connect(self.cancel_all)
        self.cancel_all_button = stop
        self.background = button(tr("Continue in the background"), "ghost")
        self.background.clicked.connect(window.hide)
        window.set_footer([self.background], [stop])
        self._clock = QTimer(window)
        self._clock.setInterval(250)
        self._clock.timeout.connect(self._refresh)
        self._clock.start()
        self._refresh()

    def _candidate(self, index: int) -> SendCandidate:
        assert self.request is not None
        item = self.request.items[index]
        return next(x for x in self._candidates if x.layer_id == item.layer_id)

    def _route(self, index: int) -> tuple[bool, str]:
        """El camino de una capa y por qué, en una frase (workspace-pro-spec §9): (directo, motivo)."""
        assert self.request is not None
        request = self.request
        c = self._candidate(index)
        fallback = bool(self.states[index].get("fallback"))
        reproject = request.reproject_to is not None
        path = c.path_for(
            request.only_selected, reproject, request.duckdb_reads and not fallback, not fallback
        )
        if path == PATH_CONNECTED:
            return True, tr("Copied inside the database (Connected layer)")
        if path != PATH_QGIS:
            why = tr("QGIS is skipped: GeoDuck read the file")
            if c.filtered:
                why += " " + tr("with the same filter")
            return True, why
        if fallback and c.filtered:
            reason = tr("GeoDuck does not understand its filter, so QGIS applies it")
        elif fallback:
            reason = tr("GeoDuck reads the file differently from QGIS")
        elif reproject and c.geometry is not None:
            reason = tr("it is reprojected")
        elif request.only_selected and c.selected:
            reason = tr("only the selection")
        elif c.path == PATH_GDAL and c.needs_spatial:
            reason = tr("«spatial» is not loaded")
        elif c.source_kind == "memory":
            reason = tr("temporary layer, without a file")
        elif c.source_kind == "database":
            reason = tr("it comes from a database ({0})").format(c.source_format)
        elif c.source_kind == "web":
            reason = tr("it comes from a web service ({0})").format(c.source_format)
        else:
            reason = tr("QGIS reads this kind of layer")
        return False, reason

    def _steps(self, index: int) -> list[Step]:  # noqa: PLR0912, PLR0915 - un paso por estado, en orden
        """Los pasos de una capa: origen y filtro → lectura (⚡ DuckDB o QGIS y por qué) → copia → destino."""
        assert self.request is not None
        request = self.request
        s = self.states[index]
        c = self._candidate(index)
        item = request.items[index]
        state = s["state"]
        direct, why = self._route(index)
        origin = [c.file.path if c.file is not None else c.source]
        if c.file is None:
            origin.append(tr("layer «{0}»").format(c.name))
        if c.filtered:
            origin.append(tr("with filter"))
        source_icon = SOURCE_ICONS.get(c.source_kind, "file")
        fmt = c.source_format or c.source
        started = state != WAITING
        steps = [
            Step(
                source_icon,
                tr("Source") + (f" · {fmt}" if fmt else ""),
                " · ".join(o for o in origin if o),
                DONE if started else WAITING,
            )
        ]
        rows, total = s["rows"], s["total"]
        seconds = s.get("seconds")
        elapsed = time.monotonic() - s["started"] if state == RUNNING and s.get("started") else seconds
        if direct:
            read = Step(
                "bolt",
                tr("Direct read with GeoDuck"),
                why + (" · " + tr("same rows as in QGIS") if s.get("checked") else ""),
            )
        else:
            read = Step("qgis-layers", tr("Read with QGIS"), why[:1].upper() + why[1:])
        copy = Step("database", tr("Copy to GeoDuck"))
        where = ("temp" if request.temporary else request.database) + f".{request.schema}.{item.table}"
        dest = Step("table", tr("Destination"), where)
        if state == RUNNING:
            if direct or rows > 0:
                read.state = DONE
                copy.state = RUNNING
                copy.title = tr("Copying to GeoDuck")
                if total > 0:
                    copy.progress = min(rows, total) / total
                    copy.detail = tr("{0} of {1} rows").format(_count(rows), _count(total))
                    rate = rows / elapsed if elapsed else 0
                    if rate > 0 and rows < total:
                        copy.detail += " · ≈ " + tr("{0} left").format(seconds_text((total - rows) / rate))
                elif direct:
                    copy.detail = tr("GeoDuck copies it with SQL")
                copy.seconds = elapsed
            else:
                read.state = RUNNING
        elif state == DONE:
            read.state = copy.state = dest.state = DONE
            copy.seconds = seconds
            copy.detail = rows_text(rows)
            crs = request.reproject_to or c.crs_label
            dest.detail = " · ".join(
                p
                for p in (
                    where,
                    rows_text(rows),
                    crs if c.geometry_type and not request.without_crs else "",
                )
                if p
            )
            if s["message"]:
                dest.detail += "\n⚠ " + s["message"]
        elif state == FAILED:
            read.state = DONE if direct else FAILED
            failed = copy if direct else read
            failed.state = FAILED
            failed.seconds = seconds
            if s.get("card") is None:
                card = ErrorCardView(
                    explain("", s["message"] or tr("Unknown error"), "", None), self._window().colors
                )
                card.go_button.hide()
                s["card"] = card
            failed.card = s["card"]
            copy.state = copy.state if failed is copy else SKIPPED
            dest.state = SKIPPED
        elif state == CANCELLED:
            read.state = DONE if started else SKIPPED
            copy.state = dest.state = SKIPPED
        return [steps[0], read, copy, dest]

    def _status(self, i: int) -> tuple[str, str | None]:
        """La cabecera de cada fila: «Copiando… 182 000 de 300 000», «✓ 10 000 filas · 0,1 s», «En espera»."""
        s = self.states[i]
        state = s["state"]
        if state == RUNNING:
            text = tr("Copying…")
            if s["total"] > 0:
                text += " " + tr("{0} of {1}").format(_count(s["rows"]), _count(s["total"]))
            return text, "accent"
        if state == DONE:
            text = "✓ " + rows_text(s["rows"])
            if s.get("seconds") is not None:
                text += " · " + seconds_text(s["seconds"])
            c = self._candidate(i)
            if c.source_kind == "memory":
                text += " · " + tr("temporary layer")
            return text, "ok"
        if state == CANCELLED:
            return tr("Cancelled"), None
        if state == FAILED:
            return tr("Error"), "error"
        return tr("Waiting"), None

    def _refresh(self) -> None:
        window = self.window
        if window is None or self.request is None or not getattr(self, "timeline_rows", None):
            return
        view = window.timeline
        fast = 0
        current = None
        for i, row in enumerate(self.timeline_rows):
            direct, _why = self._route(i)
            fast += direct
            row.set_steps(self._steps(i))
            text, tone = self._status(i)
            row.set_status(text, tone)
            if row.remove is not None:
                row.remove.setVisible(self.running and self.states[i]["state"] in (WAITING, RUNNING))
                row.remove.setToolTip(
                    tr("Remove this layer") if self.states[i]["state"] == WAITING else tr("Stop this layer")
                )
            if self.states[i]["state"] in (RUNNING, FAILED) and current is None:
                current = row
        total = len(self.states)
        finished = sum(1 for s in self.states if s["state"] in (DONE, CANCELLED, FAILED))
        request = self.request
        where = ("temp" if request.temporary else request.database) + f" · {request.schema}"
        seconds = time.monotonic() - getattr(self, "started", time.monotonic())
        head = tr("Files → GeoDuck") if self.files else tr("QGIS layers → GeoDuck")
        if self.running:
            fraction = finished
            if self._current is not None:
                s = self.states[self._current]
                if s["total"] > 0:
                    fraction += min(s["rows"], s["total"]) / s["total"]
            view.set_header(
                head, where + " · " + tr("{0} of {1}").format(min(finished + 1, total), total), seconds
            )
            view.set_total(fraction / total if total else None)
            view.follow(current)
            self._host.set_progress(self.progress_text())
        else:
            added = sum(1 for s in self.states if s["state"] == DONE)
            rows = sum(s["rows"] for s in self.states if s["state"] == DONE)
            title = (
                tr("Done: 1 layer in GeoDuck")
                if added == 1
                else tr("Done: {0} layers in GeoDuck").format(added)
            )
            if added < total:
                title = tr("{0} of {1} layers in GeoDuck").format(added, total)
            spent = getattr(self, "seconds", seconds)
            pill = "⚡ " + tr("{0} directly by GeoDuck").format(fast)
            if not self.files:
                pill += " · " + tr("{0} through QGIS").format(total - fast)
            view.set_header(
                title,
                f"{where} · " + rows_text(rows) + f" · {seconds_text(spent)}",
                pill=pill,
            )
            view.set_total(None)
            view.follow(current)
            self._final_footer()

    def _final_footer(self) -> None:
        window = self._window()
        if getattr(self, "_final_shown", None) is self.request:
            return
        self._final_shown = self.request
        undo = button(tr("Undo"))
        undo.setEnabled(any(t.can_undo for t in self.tables))
        undo.clicked.connect(self.undo)
        undo.clicked.connect(lambda: undo.setEnabled(False))
        open_button = button(tr("Open"))
        open_button.setEnabled(bool(self.tables))
        open_button.clicked.connect(lambda: self.tables and self._host.open_table(self.tables[0]))
        close = button(tr("Close"), "primary")
        close.clicked.connect(window.hide)
        window.set_footer([undo], [open_button, close])

    def escape(self) -> None:
        """Esc: mientras corre, «Cancelar · Esc» (las terminadas quedan); si no, cierra."""
        window = self._window()
        if self.running:
            self.cancel_all()
            return
        self.window_closed()
        window.hide()

    def detach(self) -> None:
        self._unsubscribe()
        if self.window is not None:
            self._drop_send_dialog()
            self.window.hide()
            self.window.deleteLater()
            self.window = None
