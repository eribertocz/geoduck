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

from qgis.core import QgsCoordinateReferenceSystem, QgsFeature, QgsProject
from qgis.PyQt.QtCore import QTimer

from geoduck.domain.bridge_types import LoadPlan, missing_crs_warning
from geoduck.domain.channel import BatchChannel
from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.i18n import tr
from geoduck.domain.load import COPY_ACCESS, LoadMode, LoadReport, LoadRequest, describe_origin
from geoduck.domain.operations import ReadOutcome
from geoduck.qgis_bridge.convert import (
    column_converter,
    crs_from_field,
    fields_for,
    geometry_from_wkb,
    strip_unreadable,
)
from geoduck.qgis_bridge.copies import mark_copy
from geoduck.qgis_bridge.families import FamilyLayers
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
        self._layers: FamilyLayers | None = None
        self._reprojector: Reprojector | None = None
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
            database=self._request.database,
            on_plan=on_plan,
            on_batch=self._channel.put,
        )
        self._handle.future.add_done_callback(self._on_read_done)
        self._timer.start()

    def cancel(self) -> None:
        if self._finished:
            return
        self._fail(LoadCancelledError(tr("Loading cancelled")))

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
            self._channel.fail(LoadCancelledError(tr("Loading cancelled")))
        else:
            self._channel.fail(GeoDuckError(tr("Reading failed: {0}").format(outcome.summary.error)))

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
        if self._layers is None:
            self._create_layers(piece)
        assert self._layers is not None
        fields = self._layers.fields
        features = []
        for i in range(piece.num_rows):
            f = QgsFeature(fields)
            f.setAttributes([col[i] for col in columns])
            g = geometry_from_wkb(wkbs[i]) if wkbs is not None else None
            if g is not None and not g.isNull():
                if self._reprojector is not None and not g.isEmpty():
                    g = self._reprojector.geometry(g, self._rows + i + 1)
                f.setGeometry(g)
            features.append(f)
        self._layers.add(features)
        self._rows += piece.num_rows
        now = time.monotonic()
        if now - self._last_progress >= _PROGRESS_EVERY:
            self._last_progress = now
            self._on_progress(self._rows)

    def _create_layers(self, piece: Any) -> None:
        plan = self._plan
        assert plan is not None
        crs = QgsCoordinateReferenceSystem()
        if plan.geometry is not None:
            # Siempre explícito: sin CRS, QGIS asignaría uno por defecto en silencio (C4).
            crs = crs_from_field(piece.schema.field(plan.geometry.name), self._request.crs_override)
            if self._request.reproject_to:  # QGIS/PROJ, nunca DuckDB (spatial-spec §4)
                self._reprojector = Reprojector(crs, self._request.reproject_to)
                crs = self._reprojector.target
        self._layers = FamilyLayers(
            self._request.layer_name, fields_for(plan), crs, split=self._request.split_families
        )

    def _finish(self) -> None:
        plan = self._plan
        if plan is None:
            raise GeoDuckError(tr("Reading ended without a plan"))
        if self._layers is None:  # resultado vacío
            self._layers = FamilyLayers(
                self._request.layer_name, fields_for(plan), QgsCoordinateReferenceSystem(), split=True
            )
        layers, notes = self._layers.finish()
        read = self._summary.rows if self._summary is not None else -1
        count = sum(layer.featureCount() for layer in layers)
        if not (read == self._rows == count):
            raise GeoDuckError(
                tr("Different counts: read {0}, converted {1}, in the layers {2}").format(
                    read, self._rows, count
                )
            )
        self._timer.stop()
        self._finished = True
        for item in layers:
            mark_copy(item)  # «Guardar las copias junto al proyecto» (G9) la reconoce
        self._project.addMapLayers(layers)  # todas o ninguna (§8)
        layer = layers[0]
        warnings = (*plan.warnings, *notes)
        if self._reprojector is not None:
            warnings = (*warnings, self._reprojector.note)
        if plan.geometry is not None and not self._layers.types:
            warnings = (*warnings, tr("No geometries: loaded as a table"))
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
                layers=tuple((lyr.id(), lyr.name()) for lyr in layers) if len(layers) > 1 else (),
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
        self._layers = None  # privadas: nunca se publicaron; se liberan con la referencia
        self._on_done(exc)
