# SPDX-License-Identifier: GPL-2.0-or-later
"""Enviar capas de QGIS a DuckDB: el lado de QGIS (G8 · E2; qgis-import-spec §5, §6, §7; ADR-0015).

- `plan_layer` decide, para una capa, las columnas (nombres y tipos de DuckDB), la geometría con su SRC y el
  camino: Conectada de esta sesión o GeoParquet → SQL dentro de DuckDB; el resto → lotes Arrow.
- `LayerReader` (una `QgsTask`) lee las capas del camino general desde `QgsVectorLayerFeatureSource` —con su
  filtro y, si se pide, solo la selección— y entrega lotes Arrow al canal del motor, con contrapresión.
- `LayerImport` (hilo principal) arranca el motor y el lector, informa del progreso y entrega el resultado
  una sola vez. Cancelar detiene a los dos: `ROLLBACK` y nada cambia.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsProviderRegistry,
    QgsTask,
    QgsVectorLayer,
    QgsVectorLayerFeatureSource,
)
from qgis.PyQt.QtCore import QMetaType, QTimer, QVariant

from geoduck.domain.channel import BatchChannel, ConsumerGoneError
from geoduck.domain.errors import InvalidArgumentError, OperationCancelledError
from geoduck.domain.i18n import tr
from geoduck.domain.importing import (
    SELECTION_VIEW,
    WKB_COLUMN,
    ImportColumn,
    ImportGeometry,
    ImportJob,
    ImportMode,
    ImportReport,
    column_names,
    duck_type_for,
)
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.provider import FID, KEY, id_columns, key_alias

#: Entidades por lote Arrow (spike G8-A, F-114).
BATCH = 50_000
#: Códigos de autoridad que DuckDB guarda tal cual sin `spatial`; el resto va como PROJJSON (F-116).
_AUTHORITIES = ("EPSG", "ESRI", "OGC")

#: Tipo de DuckDB → tipo Arrow del lote (los de `duck_type_for`).
_ARROW: dict[str, pa.DataType] = {
    "INTEGER": pa.int32(),
    "UINTEGER": pa.uint32(),
    "BIGINT": pa.int64(),
    "UBIGINT": pa.uint64(),
    "DOUBLE": pa.float64(),
    "BOOLEAN": pa.bool_(),
    "VARCHAR": pa.string(),
    "DATE": pa.date32(),
    "TIME": pa.time64("us"),
    "TIMESTAMP": pa.timestamp("us"),
    "TIMESTAMPTZ": pa.timestamp("us", tz="UTC"),
    "BLOB": pa.binary(),
    "VARCHAR[]": pa.list_(pa.string()),
    "BIGINT[]": pa.list_(pa.int64()),
    "DOUBLE[]": pa.list_(pa.float64()),
    "JSON": pa.string(),
}

#: Camino elegido, para el resumen del diálogo (§5).
PATH_CONNECTED = "connected"
PATH_PARQUET = "parquet"
PATH_QGIS = "qgis"


# -- plan de una capa ---------------------------------------------------------------------------------


@dataclass
class LayerPlan:
    """Lo que se enviará de una capa. `job` va al motor; el resto lo usan el lector y el diálogo."""

    layer: QgsVectorLayer
    job: ImportJob
    path: str
    #: Solo estas entidades (la selección); None = todas las que muestra la capa (con su filtro).
    fids: list[int] | None = None
    #: Entidades que se enviarán (progreso y aviso de capa grande); -1 si QGIS no lo sabe.
    features: int = 0
    warnings: list[str] = field(default_factory=list)


def type_name(type_id: Any) -> str:
    """Nombre del `QMetaType` de un campo (`int`, `QString`, `QDate`…): `QByteArray` en Qt 5, `bytes` en
    Qt 6. Vacío si no hay tipo (el subtipo de un campo que no es lista: `b''` en Qt 5, None en Qt 6)."""
    if type_id is None:
        return ""
    name = QMetaType(int(type_id)).name()
    if name is None:
        return ""
    if not isinstance(name, (bytes, bytearray)):
        name = name.data()  # QByteArray
    return bytes(name).decode()


def crs_text(crs: QgsCoordinateReferenceSystem) -> str | None:
    """SRC para `ST_SetCRS`: `EPSG:…`, `ESRI:…` u `OGC:…` o, si es personalizado, PROJJSON (F-116: DuckDB
    1.5.0 pierde un WKT2). None si la capa no tiene SRC o no se puede expresar."""
    if not crs.isValid():
        return None
    authid = crs.authid()
    if authid.split(":")[0].upper() in _AUTHORITIES:
        return authid
    if hasattr(crs, "toJsonString"):  # QGIS 4.x
        text = crs.toJsonString()
        if text:
            return str(text)
    from osgeo import osr  # noqa: PLC0415 - GDAL viene con QGIS

    srs = osr.SpatialReference()
    if srs.ImportFromWkt(crs.toWkt(QgsCoordinateReferenceSystem.WktVariant.WKT2_2019)) != 0:
        return None
    return str(srs.ExportToPROJJSON()) or None


def geometry_column_name(layer: QgsVectorLayer) -> str:
    """El nombre que la capa da a su geometría (`geom`, `geometry`, `shape`…); `geom` si no trae ninguno."""
    provider = layer.providerType()
    name = ""
    if provider == KEY:
        geometry = layer.dataProvider().plan.geometry
        name = geometry.name if geometry is not None else ""
    elif provider == "postgres":
        name = QgsProviderRegistry.instance().decodeUri(provider, layer.source()).get("geometryColumn", "")
    elif provider == "ogr":
        name = _ogr_geometry_column(layer.source())
    return name or "geom"


def _ogr_geometry_column(source: str) -> str:
    """Nombre de la geometría según GDAL (`GetGeometryColumn`); vacío si el formato no tiene (Shapefile)."""
    from osgeo import ogr  # noqa: PLC0415 - GDAL viene con QGIS

    parts = QgsProviderRegistry.instance().decodeUri("ogr", source)
    ds = ogr.Open(parts.get("path", ""))
    if ds is None:
        return ""
    name = parts.get("layerName")
    lyr = ds.GetLayerByName(name) if name else ds.GetLayer(0)
    return str(lyr.GetGeometryColumn() or "") if lyr is not None else ""


def geoparquet_path(layer: QgsVectorLayer) -> str | None:
    """Ruta del archivo si la capa es un GeoParquet que DuckDB lee directo (§5.2)."""
    if layer.providerType() != "ogr":
        return None
    path = QgsProviderRegistry.instance().decodeUri("ogr", layer.source()).get("path", "")
    if not path.lower().endswith(".parquet") or not Path(path).is_file():
        return None
    metadata = pq.read_schema(path).metadata or {}
    return path if b"geo" in metadata else None


def plan_layer(
    layer: QgsVectorLayer,
    *,
    table: str,
    mode: ImportMode = ImportMode.CREATE,
    database: str = "memory",
    schema: str = "main",
    temporary: bool = False,
    only_selected: bool = False,
    as_view: bool = False,
    without_crs: bool = False,
) -> LayerPlan:
    """El envío de una capa a `table`. `without_crs`: el usuario eligió enviar sin SRC (F-120, §7)."""
    fids = sorted(layer.selectedFeatureIds()) if only_selected else None
    features = len(fids) if fids is not None else layer.featureCount()
    warnings: list[str] = []
    geometry = None
    if layer.isSpatial():
        crs = None if without_crs else crs_text(layer.crs())
        if crs is None and not without_crs and layer.crs().isValid():
            raise InvalidArgumentError(
                tr("The CRS of «{0}» cannot be expressed: reproject the layer or send it without CRS").format(
                    layer.name()
                )
            )
        geometry = ImportGeometry(geometry_column_name(layer), crs)
    fields = list(layer.fields())
    taken = [geometry.name] if geometry is not None else []
    names, renamed = column_names([*taken, *(f.name() for f in fields)])
    warnings += renamed
    columns: list[ImportColumn] = []
    for i, f in enumerate(fields):
        duck, note = duck_type_for(type_name(f.type()), type_name(f.subType()) or None)
        if note:
            warnings.append(f"«{f.name()}»: {note}")
        columns.append(ImportColumn(names[len(taken) + i], f"c{i}", duck))
    common: dict[str, Any] = {"database": database, "schema": schema, "temporary": temporary}

    # Camino 1: capa Conectada de esta sesión → SQL dentro de DuckDB (§5.1)
    provider = layer.dataProvider()
    same_session = layer.providerType() == KEY and provider.engine() is not None
    if same_session and provider.engine() is sessions.current():
        sql, selection = _connected_sql(provider, columns, geometry, fids)
        job = ImportJob(
            layer.name(),
            table,
            mode,
            (),
            geometry,
            source_sql=sql,
            source_database=provider.use_database,
            selection=selection,
            **common,
        )
        return LayerPlan(layer, job, PATH_CONNECTED, fids, features, warnings)

    # Camino 2: GeoParquet sin selección ni filtro → read_parquet (§5.2)
    parquet = geoparquet_path(layer)
    if parquet is not None and fids is None and not layer.subsetString():
        sql = _parquet_sql(parquet, geometry)
        job = ImportJob(layer.name(), table, mode, (), geometry, source_sql=sql, as_view=as_view, **common)
        return LayerPlan(layer, job, PATH_PARQUET, None, features, warnings)
    if as_view:
        raise InvalidArgumentError(
            tr("A view is only possible for a GeoParquet layer without selection or filter")
        )

    # Camino 3: lectura de QGIS por lotes Arrow (§5.3)
    job = ImportJob(layer.name(), table, mode, tuple(columns), geometry, **common)
    return LayerPlan(layer, job, PATH_QGIS, fids, features, warnings)


def _connected_sql(
    provider: Any, columns: list[ImportColumn], geometry: ImportGeometry | None, fids: list[int] | None
) -> tuple[str, pa.Table | None]:
    """`SELECT` sobre la consulta de la capa Conectada (con su filtro). La selección va como tabla Arrow de
    identificadores unida con `SEMI JOIN` (F-119: un `IN` con 100 000 valores tarda hasta 1,2 s)."""
    parts = [
        f"{quote_identifier(f.name)} AS {quote_identifier(c.name)}"
        for f, c in zip(provider.plan.fields, columns, strict=True)
    ]
    if geometry is not None:
        geom = quote_identifier(provider.plan.geometry.name)
        if geometry.crs:
            geom = f"ST_SetCRS({geom}, {quote_string_literal(geometry.crs)})"
        parts.append(f"{geom} AS {quote_identifier(geometry.name)}")
    select = f"SELECT {', '.join(parts)} FROM ({provider.base}) AS __geoduck_layer"
    if fids is None:
        return select, None
    # Como `fid_filter_sql`: en modo `map`, los valores de la clave; en los demás, el FID
    if provider.fid_mode == "map":
        ids = id_columns("map", provider.keys)
        keys = provider.keys_for(fids)
        selection = pa.table({key_alias(i): [k[i] for k in keys] for i in range(len(ids))})
    else:
        ids = [FID]
        selection = pa.table({FID: pa.array(fids, type=pa.int64())})
    using = ", ".join(quote_identifier(c) for c in ids)
    return f"{select} SEMI JOIN {quote_identifier(SELECTION_VIEW)} USING ({using})", selection


def _parquet_sql(path: str, geometry: ImportGeometry | None) -> str:
    """`read_parquet` con la geometría y el SRC de la capa (sin `spatial`, DuckDB no lee el SRC: F-118)."""
    source = f"read_parquet({quote_string_literal(path)})"
    if geometry is None:
        return f"SELECT * FROM {source}"
    geo = json.loads(pq.read_schema(path).metadata[b"geo"])
    column = quote_identifier(str(geo.get("primary_column") or "geometry"))
    value = f"ST_SetCRS({column}, {quote_string_literal(geometry.crs)})" if geometry.crs else column
    return f"SELECT * EXCLUDE ({column}), {value} AS {quote_identifier(geometry.name)} FROM {source}"


# -- lectura en segundo plano ------------------------------------------------------------------------


def _value(v: Any) -> Any:
    """Valor de un atributo de QGIS para Arrow: NULL → None (QVariant en Qt 5, None en Qt 6); fechas, horas
    y bytes de Qt → Python."""
    if v is None or (isinstance(v, QVariant) and v.isNull()):
        return None
    if hasattr(v, "toPyDateTime"):
        return v.toPyDateTime() if v.isValid() else None
    if hasattr(v, "toPyDate"):
        return v.toPyDate() if v.isValid() else None
    if hasattr(v, "toPyTime"):
        return v.toPyTime() if v.isValid() else None
    if type(v).__name__ == "QByteArray":
        return None if v.isNull() else bytes(v.data())
    return v


def _array(values: list[Any], duck: str) -> pa.Array:
    if duck == "JSON":
        values = [None if v is None else json.dumps(v, default=str) for v in values]
    elif duck == "TIMESTAMPTZ":
        values = [v.astimezone(dt.timezone.utc) if isinstance(v, dt.datetime) else v for v in values]
    elif duck.endswith("[]"):
        values = [None if v is None else [_value(x) for x in v] for v in values]
    return pa.array(values, type=_ARROW[duck])


def _batch(job: ImportJob, rows: list[list[Any]], wkbs: list[bytes | None]) -> pa.RecordBatch:
    arrays = {c.source: _array([r[k] for r in rows], c.duck_type) for k, c in enumerate(job.columns)}
    if job.geometry is not None:
        arrays[WKB_COLUMN] = pa.array(wkbs, type=pa.binary())
    if not arrays:  # capa sin campos ni geometría: solo cuenta filas
        return pa.record_batch({"__geoduck_row": pa.nulls(len(rows))})
    return pa.record_batch(arrays)


class LayerReader(QgsTask):  # type: ignore[misc]
    """Lee las capas del camino general y entrega `(índice, lote)` al canal del motor.

    QGIS borra la tarea al terminar: quien la crea no la vuelve a tocar. Informa de lo leído con `on_read`
    (desde el hilo de la tarea) y se detiene sola cuando el motor abandona el canal (error o cancelación).
    Cancelarla desde la barra de tareas de QGIS cancela el envío entero: el motor revierte."""

    def __init__(
        self, plans: list[tuple[int, LayerPlan]], channel: BatchChannel[Any], on_read: Callable[[int], None]
    ) -> None:
        super().__init__(tr("GeoDuck: send layers to DuckDB"), QgsTask.Flag.CanCancel)
        # Las fuentes se crean aquí, en el hilo principal; se leen en el hilo de la tarea (F-117)
        self._sources = [(i, p.job, p.fids, QgsVectorLayerFeatureSource(p.layer)) for i, p in plans]
        self._channel = channel
        self._on_read = on_read
        self._total = max(sum(max(p.features, 0) for _, p in plans), 1)
        self._read_rows = 0

    def run(self) -> bool:
        try:
            for index, job, fids, source in self._sources:
                self._read(index, job, fids, source)
            self._channel.finish()
        except ConsumerGoneError:
            return False  # el motor ya terminó (error o cancelación) e informa él
        except Exception as exc:  # el motor revierte y lo informa
            self._channel.fail(exc)
            return False
        return True

    def _read(self, index: int, job: ImportJob, fids: list[int] | None, source: Any) -> None:
        request = QgsFeatureRequest()
        if fids is not None:
            request.setFilterFids(fids)
        if job.geometry is None:
            request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
        indexes = list(range(len(job.columns)))
        rows: list[list[Any]] = []
        wkbs: list[bytes | None] = []
        sent = False
        for f in source.getFeatures(request):
            if self._channel.abandoned:
                raise ConsumerGoneError
            if self.isCanceled():
                raise OperationCancelledError(tr("Sending cancelled"))
            attrs = f.attributes()
            rows.append([_value(attrs[k]) for k in indexes])
            if job.geometry is not None:
                g = f.geometry()
                wkbs.append(None if g.isNull() else bytes(g.asWkb()))
            if len(rows) == BATCH:
                self._put(index, job, rows, wkbs)
                rows, wkbs, sent = [], [], True
        if rows or not sent:  # una capa sin entidades envía un lote vacío: su tabla se crea igual
            self._put(index, job, rows, wkbs)

    def _put(self, index: int, job: ImportJob, rows: list[list[Any]], wkbs: list[bytes | None]) -> None:
        self._channel.put((index, _batch(job, rows, wkbs)))
        self._read_rows += len(rows)
        self._on_read(self._read_rows)
        self.setProgress(min(99.0, 100.0 * self._read_rows / self._total))


# -- orquestación ------------------------------------------------------------------------------------

Done = Callable[[ImportReport | BaseException], None]


class LayerImport:
    """Un envío en curso: el motor escribe y, si hay capas del camino general, `LayerReader` las lee. Se
    crea y se usa solo en el hilo principal; `on_done` se llama una vez."""

    def __init__(
        self,
        engine: Any,
        plans: list[LayerPlan],
        *,
        on_progress: Callable[[int], None],
        on_done: Done,
    ) -> None:
        self._engine = engine
        self._plans = plans
        self._on_progress = on_progress
        self._on_done = on_done
        self._channel: BatchChannel[Any] = BatchChannel(capacity=2)
        self._handle: Any = None
        #: Entidades leídas de QGIS (las escribe la tarea lectora; un `int` se asigna de una vez).
        self.read = 0
        #: Solo se guarda: sin una referencia de Python, PyQGIS pierde el `run` de la tarea. Nunca se usa,
        #: porque QGIS la borra al terminar.
        self._reader: LayerReader | None = None
        self._finished = False
        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._handle = self._engine.import_batches([p.job for p in self._plans], self._channel)
        general = [(i, p) for i, p in enumerate(self._plans) if not p.job.by_sql]
        if general:
            self._reader = LayerReader(general, self._channel, self._set_read)
            QgsApplication.taskManager().addTask(self._reader)
        else:
            self._channel.finish()
        self._timer.start()

    def _set_read(self, rows: int) -> None:
        self.read = rows

    @property
    def finished(self) -> bool:
        return self._finished

    def cancel(self) -> None:
        """`ROLLBACK` en el motor; el lector, al ver el canal abandonado, deja de leer."""
        if self._finished or self._handle is None:
            return
        self._engine.cancel(self._handle.op_id)
        self._channel.abandon()  # también si el motor aún no empezó el envío: nadie leerá el canal

    def _poll(self) -> None:
        if self._finished:
            return
        self._on_progress(self.read)
        if not self._handle.future.done():
            return
        self._finished = True
        self._timer.stop()
        self._channel.abandon()  # nadie más lee el canal: el lector, si sigue, se detiene
        exc = self._handle.future.exception()
        if exc is not None:
            self._on_done(exc)
            return
        report: ImportReport = self._handle.future.result()
        warnings = tuple(w for p in self._plans for w in p.warnings)
        self._on_done(ImportReport(report.tables, warnings + report.warnings))
