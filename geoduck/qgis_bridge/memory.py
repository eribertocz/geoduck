# SPDX-License-Identifier: GPL-2.0-or-later
"""Modalidad Memoria: DuckDB → PyArrow → PyQGIS → `QgsVectorLayer("memory")` (qgis-bridge-spec §3).

El worker lee lotes normalizados y los deja en un `BatchChannel` (2 en vuelo). El hilo principal los
convierte en tramos de 1 024 filas desde un `QTimer`, de modo que la interfaz atiende eventos entre
tramos (F-44). La capa es privada hasta que la lectura termina y los conteos coinciden; entonces se
publica. En error o cancelación se descarta y no queda nada en el proyecto (GD-BRD-004).
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable
from typing import Any

from qgis.core import QgsFeature, QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QTimer

from geoduck.domain.bridge_types import LoadPlan, missing_crs_warning
from geoduck.domain.channel import BatchChannel
from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.load import COPY_ACCESS, LoadMode, LoadReport, LoadRequest, describe_origin
from geoduck.domain.operations import ReadOutcome
from geoduck.qgis_bridge.convert import (
    column_converter,
    crs_from_field,
    fields_for,
    fit_geometry,
    geometry_from_wkb,
    layer_type_for,
    strip_unreadable,
)
from geoduck.qgis_bridge.reproject import Reprojector

#: Filas convertidas por tramo en el hilo principal (F-44: bloqueo ≤ 200 ms).
CHUNK = 1024
_PROGRESS_EVERY = 0.2

Done = Callable[[LoadReport | BaseException], None]


class LoadCancelledError(GeoDuckError):
    code = ErrorCode.CANCELLED


class MemoryLoad:
    """Una carga en curso. Se crea y se usa solo en el hilo principal."""

    mode = LoadMode.MEMORY

    def __init__(
        self,
        engine: Any,
        request: LoadRequest,
        *,
        on_progress: Callable[[int], None],
        on_done: Done,
        project: QgsProject | None = None,
    ) -> None:
        self._engine = engine
        self._request = request
        self._on_progress = on_progress
        self._on_done = on_done
        self._project = project or QgsProject.instance()
        self._channel: BatchChannel[Any] = BatchChannel(capacity=2)
        self._plan: LoadPlan | None = None
        self._summary: Any = None
        self._handle: Any = None
        self._layer: QgsVectorLayer | None = None
        self._layer_type: Any = None
        self._reprojector: Reprojector | None = None
        self._pending: list[QgsFeature] = []  # entidades sin geometría antes de conocer el tipo
        self._batch: Any = None
        self._offset = 0
        self._rows = 0
        self._last_progress = 0.0
        self._finished = False
        self._timer = QTimer()
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._pump)

    # -- ciclo de vida ---------------------------------------------------------------------------

    def start(self) -> None:
        def on_plan(plan: LoadPlan) -> None:  # hilo del worker; visible antes del primer lote (cola)
            self._plan = plan

        self._handle = self._engine.load_query(
            self._request.sql,
            geometry=self._request.geometry,
            formats=self._request.format_map or None,
            on_plan=on_plan,
            on_batch=self._channel.put,
        )
        self._handle.future.add_done_callback(self._on_read_done)
        self._timer.start()

    def cancel(self) -> None:
        if self._finished:
            return
        self._fail(LoadCancelledError("Carga cancelada"))

    def _on_read_done(self, fut: Any) -> None:  # hilo del worker
        exc = fut.exception()
        if exc is not None:
            self._channel.fail(exc)
            return
        outcome = fut.result()
        self._summary = outcome.summary
        if outcome.summary.outcome is ReadOutcome.EXHAUSTED:
            self._channel.finish()
        elif outcome.summary.outcome is ReadOutcome.CANCELLED:
            self._channel.fail(LoadCancelledError("Carga cancelada"))
        else:
            self._channel.fail(GeoDuckError(f"La lectura falló: {outcome.summary.error}"))

    # -- hilo principal --------------------------------------------------------------------------

    def _pump(self) -> None:
        if self._finished:
            return
        try:
            if self._batch is None:
                try:
                    has_batch, batch = self._channel.get(timeout=0)
                except queue.Empty:
                    return
                if not has_batch:
                    self._finish()
                    return
                self._batch, self._offset = batch, 0
            self._convert_chunk()
        except BaseException as exc:
            self._fail(exc)

    def _convert_chunk(self) -> None:
        batch = self._batch
        piece = batch.slice(self._offset, CHUNK)
        self._offset += piece.num_rows
        if self._offset >= batch.num_rows:
            self._batch = None
        plan = self._plan
        assert plan is not None
        piece = strip_unreadable(piece, plan, self._rows)
        names = piece.schema.names
        columns = [column_converter(f.kind)(piece.column(names.index(f.name))) for f in plan.fields]
        wkbs = piece.column(names.index(plan.geometry.name)).to_pylist() if plan.geometry else None
        geoms = [geometry_from_wkb(w) for w in wkbs] if wkbs is not None else None
        if self._layer is None:
            self._create_layer(piece, geoms)
        fields = self._fields
        features = []
        for i in range(piece.num_rows):
            f = QgsFeature(fields)
            f.setAttributes([col[i] for col in columns])
            g = geoms[i] if geoms is not None else None
            if g is not None and not g.isNull():
                if self._reprojector is not None and not g.isEmpty():
                    g = self._reprojector.geometry(g, self._rows + i + 1)
                if self._layer_type is not None:
                    g = fit_geometry(g, self._layer_type)
                f.setGeometry(g)
            features.append(f)
        if self._layer is None:  # todavía no hay ninguna geometría: se espera a conocer el tipo
            self._pending.extend(features)
        else:
            self._add(features)
        self._rows += piece.num_rows
        now = time.monotonic()
        if now - self._last_progress >= _PROGRESS_EVERY:
            self._last_progress = now
            self._on_progress(self._rows)

    def _create_layer(self, piece: Any, geoms: list[Any] | None) -> None:
        plan = self._plan
        assert plan is not None
        self._fields = fields_for(plan)
        if plan.geometry is None:
            uri = "None"
        else:
            layer_type = layer_type_for(geoms or [])
            if layer_type is None:
                return  # ni una geometría en este tramo: se decide con el siguiente
            self._layer_type = layer_type
            uri = QgsWkbTypes.displayString(layer_type)
        layer = QgsVectorLayer(uri, self._request.layer_name, "memory")
        if plan.geometry is not None and self._layer_type is not None:
            # Siempre explícito: sin CRS en la URI, QGIS asignaría uno por defecto en silencio (C4).
            crs = crs_from_field(piece.schema.field(plan.geometry.name), self._request.crs_override)
            if self._request.reproject_to:  # QGIS/PROJ, nunca DuckDB (spatial-spec §4)
                self._reprojector = Reprojector(crs, self._request.reproject_to)
                crs = self._reprojector.target
            layer.setCrs(crs)
        if not layer.isValid():
            raise GeoDuckError("QGIS no pudo crear la capa en memoria")
        provider = layer.dataProvider()
        if self._fields.count() and not provider.addAttributes(list(self._fields)):
            raise GeoDuckError(f"QGIS rechazó los campos: {provider.lastError()}")
        layer.updateFields()
        self._fields = layer.fields()
        self._layer = layer
        if self._pending:
            pending, self._pending = self._pending, []
            self._add(pending)

    def _add(self, features: list[QgsFeature]) -> None:
        assert self._layer is not None
        provider = self._layer.dataProvider()
        ok, _ = provider.addFeatures(features)
        if not ok:
            raise GeoDuckError(f"QGIS rechazó entidades: {provider.lastError() or 'sin detalle'}")

    def _finish(self) -> None:
        plan = self._plan
        if plan is None:
            raise GeoDuckError("La lectura terminó sin plan")
        if self._layer is None:  # sin ninguna geometría no nula en todo el resultado
            self._layer_type = None
            self._plan = plan
            self._fields = fields_for(plan)
            layer = QgsVectorLayer("None", self._request.layer_name, "memory")
            if self._fields.count():
                layer.dataProvider().addAttributes(list(self._fields))
            layer.updateFields()
            self._layer = layer
            self._fields = layer.fields()
            pending, self._pending = self._pending, []
            if pending:
                for f in pending:
                    f.setFields(self._fields, False)
                self._add(pending)
        layer = self._layer
        read = self._summary.rows if self._summary is not None else -1
        count = layer.featureCount()
        if not (read == self._rows == count):
            raise GeoDuckError(
                f"Conteos distintos: leídas {read}, convertidas {self._rows}, en la capa {count}"
            )
        self._timer.stop()
        self._finished = True
        self._project.addMapLayer(layer)
        warnings = plan.warnings
        if self._reprojector is not None:
            warnings = (*warnings, self._reprojector.note)
        if plan.geometry is not None and self._layer_type is None:
            warnings = (*warnings, "Sin geometrías: se carga como tabla")
        elif plan.geometry is not None and not layer.crs().isValid():
            warnings = (*warnings, missing_crs_warning(plan.geometry, self._request.crs_override))
        self._on_progress(self._rows)
        self._on_done(
            LoadReport(
                layer.id(),
                layer.name(),
                LoadMode.MEMORY,
                self._rows,
                warnings,
                origin=describe_origin(self._request),
                access=COPY_ACCESS,
            )
        )

    def _fail(self, exc: BaseException) -> None:
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        self._channel.abandon()
        if self._handle is not None and not self._handle.future.done():
            self._engine.cancel(self._handle.op_id)
        self._layer = None  # privada: nunca se publicó; se libera con la referencia
        self._pending = []
        self._on_done(exc)
