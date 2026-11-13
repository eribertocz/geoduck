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
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeatureRequest,
    QgsProject,
    QgsProviderRegistry,
    QgsTask,
    QgsVectorLayer,
    QgsVectorLayerFeatureSource,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, QTimer, QVariant

from geoduck.domain.channel import BatchChannel, ConsumerGoneError
from geoduck.domain.errors import InvalidArgumentError, OperationCancelledError
from geoduck.domain.files import OTHER, FileLayer, Reader, file_job, format_for, select_sql, vsi_path
from geoduck.domain.i18n import tr
from geoduck.domain.importing import (
    PATH_CONNECTED,
    PATH_FILE,
    PATH_GDAL,
    PATH_PARQUET,
    PATH_QGIS,
    SELECTION_VIEW,
    WKB_COLUMN,
    ImportColumn,
    ImportGeometry,
    ImportJob,
    ImportMode,
    ImportReport,
    SendCandidate,
    SendItem,
    SendRequest,
    column_names,
    duck_type_for,
    table_name_for,
    unique_name,
)
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.copies import is_copy
from geoduck.qgis_bridge.provider import FID, KEY, id_columns, key_alias
from geoduck.qgis_bridge.reproject import Reprojector

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

# -- plan de una capa ---------------------------------------------------------------------------------


@dataclass
class LayerPlan:
    """Lo que se enviará de una capa. `job` va al motor; el resto lo usan el lector y el diálogo."""

    #: None para un archivo (Archivos → DuckDB, §10).
    layer: QgsVectorLayer | None
    job: ImportJob
    path: str
    #: Solo estas entidades (la selección); None = todas las que muestra la capa (con su filtro).
    fids: list[int] | None = None
    #: Entidades que se enviarán (progreso y aviso de capa grande); -1 si QGIS no lo sabe.
    features: int = 0
    warnings: list[str] = field(default_factory=list)
    #: Columnas con su tipo en DuckDB, también en el camino SQL: para el diálogo y «Añadir filas».
    columns: tuple[ImportColumn, ...] = ()
    #: «Reproyectar a…»: transforma cada geometría al leerla (camino general).
    reprojector: Reprojector | None = None


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
    authid = str(crs.authid())
    if authid.split(":", maxsplit=1)[0].upper() in _AUTHORITIES:
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


def copy_fid_fields(layer: Any) -> set[int]:
    """El identificador que el GeoPackage de una «Copia» de GeoDuck añadió (`fid`, `geoduck_fid`…): no es un
    dato de la tabla y no vuelve a DuckDB (si volviera, cada ida y vuelta sumaría una columna y la tercera
    carga fallaría; observación del propietario, 2026-11-06). Las columnas de la tabla se envían todas."""
    if not is_copy(layer) or layer.providerType() != "ogr":
        return set()
    fields = layer.fields()
    return {
        i
        for i in layer.primaryKeyAttributes()
        if fields.at(i).name() == "fid" or fields.at(i).name().startswith("geoduck_fid")
    }


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
        # la ruta que usa el proveedor (absoluta); `source()` puede venir relativa al proyecto
        name = _ogr_geometry_column(layer.dataProvider().dataSourceUri() or layer.source())
    return name or "geom"


def _ogr_geometry_column(source: str) -> str:
    """Nombre de la geometría según GDAL (`GetGeometryColumn`); vacío si el formato no tiene (Shapefile)."""
    from osgeo import ogr  # noqa: PLC0415 - GDAL viene con QGIS

    parts = QgsProviderRegistry.instance().decodeUri("ogr", source)
    try:  # con `UseExceptions` (QGIS 4 en Windows) GDAL lanza en vez de devolver None
        ds = ogr.Open(parts.get("path", ""))
    except (RuntimeError, OSError):
        return ""
    if ds is None:
        return ""
    name = parts.get("layerName")
    lyr = ds.GetLayerByName(name) if name else ds.GetLayer(0)
    return str(lyr.GetGeometryColumn() or "") if lyr is not None else ""


def _parquet_metadata(path: str) -> dict[bytes, bytes] | None:
    """Metadatos de un Parquet, o None si este PyArrow no trae Parquet (F-130).

    `pyarrow.parquet` se importa aquí y no al cargar GeoDuck: en algunos QGIS de Windows (OSGeo4W) su DLL no
    carga («not built with support for the Parquet file format») y GeoDuck no debe dejar de abrir por eso.
    Sin él, una capa GeoParquet se envía por el camino general (QGIS la lee), igual de correcta."""
    try:
        import pyarrow.parquet as pq  # noqa: PLC0415 - opcional; ver arriba
    except ImportError:
        return None
    try:
        return pq.read_schema(path).metadata or {}
    except (OSError, ValueError):
        return None


def geoparquet_path(layer: QgsVectorLayer) -> str | None:
    """Ruta del archivo si la capa es un GeoParquet que DuckDB lee directo (§5.2)."""
    if layer.providerType() != "ogr":
        return None
    path = QgsProviderRegistry.instance().decodeUri("ogr", layer.source()).get("path", "")
    if not path.lower().endswith(".parquet") or not Path(path).is_file():
        return None
    metadata = _parquet_metadata(path)
    return path if metadata is not None and b"geo" in metadata else None


def gdal_source(layer: Any) -> tuple[str, str | None] | None:
    """La capa viene de un archivo de la lista de GeoDuck que el GDAL de DuckDB lee (GeoPackage, Shapefile,
    FlatGeobuf, GeoJSON, KML, Geodatabase, Excel…): su ruta para `ST_Read` y la capa de adentro (§5.4)."""
    found = direct_source(layer)
    if found is None or found[2] is not Reader.GDAL:
        return None
    return found[0], found[1]


def direct_source(layer: Any) -> tuple[str, str | None, Reader] | None:
    """La capa viene de un archivo de la lista de GeoDuck que DuckDB lee sin QGIS (§5.4, #140): con GDAL
    (`ST_Read`, necesita `spatial`) o con su lector propio (Parquet, Arrow; CSV y JSON solo sin geometría,
    porque QGIS la arma de columnas de texto que DuckDB no ve como geometría). Ruta, capa de adentro y lector.
    Una unidad montada (Google Drive, OneDrive) es una ruta más."""
    if layer.providerType() != "ogr":
        return None
    uri = layer.dataProvider().dataSourceUri() or layer.source()  # absoluta: la «Copia» es un .gpkg
    parts = QgsProviderRegistry.instance().decodeUri("ogr", uri)
    path = str(parts.get("path") or "")
    if not path or not (os.path.isfile(path) or path.lower().endswith(".gdb")):
        return None
    fmt = format_for(path)
    if fmt is OTHER:
        return None
    if fmt.reader is Reader.GDAL:
        return vsi_path(path), (str(parts.get("layerName") or "") or None), Reader.GDAL
    if fmt.reader in (Reader.CSV, Reader.JSON) and layer.isSpatial():
        return None
    return path, None, fmt.reader


def plan_layer(  # noqa: PLR0912, PLR0915 - un camino por rama (§5)
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
    reproject_to: str | None = None,
    duckdb_reads: bool = False,
    direct: bool = True,
) -> LayerPlan:
    """El envío de una capa a `table`. `duckdb_reads`: `spatial` cargada (DuckDB lee con GDAL); `direct`:
    DuckDB puede leer el archivo de la capa (False tras un intento que falló: entonces lee QGIS, #140).
    `without_crs`: el usuario eligió enviar sin SRC (F-120, §7).
    `reproject_to`: «Reproyectar a…» (§3), con QGIS/PROJ al leer; obliga al camino general (§5.3)."""
    fids = sorted(layer.selectedFeatureIds()) if only_selected else None
    features = len(fids) if fids is not None else layer.featureCount()
    warnings: list[str] = []
    geometry = None
    reprojector = None
    if layer.isSpatial() and reproject_to:
        # Sin SRC de origen, Reprojector explica que hace falta uno (nunca se inventa: C4)
        reprojector = Reprojector(layer.crs(), reproject_to, sending=True)
    if layer.isSpatial():
        source_crs = reprojector.target if reprojector is not None else layer.crs()
        crs = None if without_crs else crs_text(source_crs)
        if crs is None and not without_crs and source_crs.isValid():
            raise InvalidArgumentError(
                tr("The CRS of «{0}» cannot be expressed: reproject the layer or send it without CRS").format(
                    layer.name()
                )
            )
        geometry = ImportGeometry(geometry_column_name(layer), crs)
    skipped = copy_fid_fields(layer)
    fields = [(i, f) for i, f in enumerate(layer.fields()) if i not in skipped]
    if geometry is not None and QgsWkbTypes.isCurvedType(layer.wkbType()):
        warnings.append(tr("Curves are converted to straight segments: DuckDB has no curves"))
    taken = [geometry.name] if geometry is not None else []
    names, renamed = column_names([*taken, *(f.name() for _i, f in fields)])
    warnings += renamed
    columns: list[ImportColumn] = []
    for k, (i, f) in enumerate(fields):
        duck, note = duck_type_for(type_name(f.type()), type_name(f.subType()) or None)
        if note:
            warnings.append(f"«{f.name()}»: {note}")
        columns.append(ImportColumn(names[len(taken) + k], f"c{i}", duck))
    common: dict[str, Any] = {"database": database, "schema": schema, "temporary": temporary}

    provider = layer.dataProvider()
    same_session = layer.providerType() == KEY and provider.engine() is not None
    connected = same_session and provider.engine() is sessions.current()
    if reprojector is not None and connected:
        # Leerla con QGIS pediría páginas al mismo worker que está escribiendo el envío: se bloquearía
        raise InvalidArgumentError(
            tr("A Connected layer of this session is sent with its CRS: it cannot be reprojected")
        )
    if reprojector is not None:  # DuckDB no transforma sin `spatial`: lee QGIS (§5.3)
        if as_view:
            raise InvalidArgumentError(tr("A view cannot be reprojected: it is sent as a copy"))
        job = ImportJob(layer.name(), table, mode, tuple(columns), geometry, **common)
        warnings.append(reprojector.note)
        return LayerPlan(layer, job, PATH_QGIS, fids, features, warnings, tuple(columns), reprojector)

    # Camino 1: capa Conectada de esta sesión → SQL dentro de DuckDB (§5.1)
    if connected:
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
        # Las columnas de la capa Conectada conservan su tipo de DuckDB (no pasan por QGIS)
        kept = tuple(
            ImportColumn(c.name, c.source, f.source_type)
            for f, c in zip(provider.plan.fields, columns, strict=True)
        )
        return LayerPlan(layer, job, PATH_CONNECTED, fids, features, warnings, kept)

    # Camino 2: GeoParquet sin selección ni filtro → read_parquet (§5.2)
    parquet = geoparquet_path(layer)
    if parquet is not None and fids is None and not layer.subsetString():
        sql = _parquet_sql(parquet, geometry)
        job = ImportJob(layer.name(), table, mode, (), geometry, source_sql=sql, as_view=as_view, **common)
        return LayerPlan(layer, job, PATH_PARQUET, None, features, warnings, tuple(columns))
    if as_view:
        raise InvalidArgumentError(
            tr("A view is only possible for a GeoParquet layer without selection or filter")
        )

    # Camino 4: archivo que DuckDB lee → `ST_Read` (GDAL, con `spatial`) o su lector propio (Parquet, Arrow,
    # CSV, JSON; #140), sin pasar por QGIS (§5.4; hasta 23× más rápido, medido 2026-11-07). El filtro de la
    # capa va como `WHERE` y se comprueba con las filas que muestra QGIS. Sin selección ni «Añadir filas» (las
    # columnas del lector pueden no ser las de QGIS).
    if direct and mode is not ImportMode.APPEND and fids is None:
        job_direct = _direct_job(layer, table, mode, geometry, without_crs, common, spatial=duckdb_reads)
        if job_direct is not None:
            return LayerPlan(layer, job_direct, PATH_GDAL, None, features, warnings, tuple(columns))

    # Camino 3: lectura de QGIS por lotes Arrow (§5.3)
    job = ImportJob(layer.name(), table, mode, tuple(columns), geometry, **common)
    return LayerPlan(layer, job, PATH_QGIS, fids, features, warnings, tuple(columns))


def _direct_job(  # noqa: PLR0917 - lo que ya decidió `plan_layer`
    layer: QgsVectorLayer,
    table: str,
    mode: ImportMode,
    geometry: ImportGeometry | None,
    without_crs: bool,
    common: dict[str, Any],
    *,
    spatial: bool,
) -> ImportJob | None:
    source = direct_source(layer)
    if source is None:
        return None
    path, inner, reader = source
    if reader is Reader.GDAL and not spatial:
        return None  # sin `spatial` cargada, DuckDB no lee con GDAL: lee QGIS (o el usuario la activa)
    item = FileLayer(
        path,
        format_for(path).key,
        layer.name(),
        layer=inner,
        gdal_source=path if reader is Reader.GDAL else "",
        geometry_column=geometry.name if geometry is not None else None,
        crs=geometry.crs if geometry is not None else None,
    )
    sql = select_sql(item, without_crs=without_crs)
    subset = layer.subsetString().strip()
    expected = None
    if subset:  # el filtro de QGIS, como lo escribió el usuario; si DuckDB da otras filas, falla (§5.4)
        sql = f"SELECT * FROM ({sql}) AS __geoduck_layer WHERE {subset}"
    count = int(layer.featureCount())
    if (subset or reader in (Reader.CSV, Reader.JSON)) and count >= 0:
        # CSV y JSON: QGIS y DuckDB pueden entender distinto el archivo; si dan otras filas, lee QGIS
        expected = count
    return ImportJob(
        layer.name(),
        table,
        mode,
        (),
        geometry,
        source_sql=sql,
        expected_rows=expected,
        source_arrow=item.path if reader is Reader.ARROW else None,
        **common,
    )


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
    geo = json.loads((_parquet_metadata(path) or {})[b"geo"])
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
        super().__init__(tr("GeoDuck: add QGIS layers to DuckDB"), QgsTask.Flag.CanCancel)
        # Las fuentes se crean aquí, en el hilo principal; se leen en el hilo de la tarea (F-117)
        self._sources = [
            (i, p.job, p.fids, p.reprojector, QgsVectorLayerFeatureSource(p.layer)) for i, p in plans
        ]
        self._linear = {i: may_have_curves(p.layer.wkbType()) for i, p in plans}
        self._channel = channel
        self._on_read = on_read
        self._total = max(sum(max(p.features, 0) for _, p in plans), 1)
        self._read_rows = 0

    def run(self) -> bool:
        try:
            for index, job, fids, reprojector, source in self._sources:
                self._read(index, job, fids, reprojector, source)
            self._channel.finish()
        except ConsumerGoneError:
            return False  # el motor ya terminó (error o cancelación) e informa él
        except Exception as exc:  # el motor revierte y lo informa
            self._channel.fail(exc)
            return False
        return True

    def _read(
        self, index: int, job: ImportJob, fids: list[int] | None, reprojector: Reprojector | None, source: Any
    ) -> None:
        request = QgsFeatureRequest()
        if fids is not None:
            request.setFilterFids(fids)
        if job.geometry is None:
            request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
        indexes = [int(c.source[1:]) for c in job.columns]  # `c{i}`: el campo i de la capa
        linearize = self._linear.get(index, False)
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
                if linearize and not g.isNull() and QgsWkbTypes.isCurvedType(g.wkbType()):
                    g.convertToStraightSegment()  # DuckDB no tiene curvas: segmentos rectos (#141)
                if reprojector is not None and not g.isNull() and not g.isEmpty():
                    g = reprojector.geometry(g, f.id())  # el FID: la entidad que falla, para buscarla en QGIS
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


def may_have_curves(wkb_type: Any) -> bool:
    """La capa es de curvas, o de un tipo que puede traerlas (colecciones, «desconocido»)."""
    flat = QgsWkbTypes.flatType(wkb_type)
    return bool(QgsWkbTypes.isCurvedType(wkb_type)) or flat in (
        Qgis.WkbType.Unknown,
        Qgis.WkbType.GeometryCollection,
    )


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


# -- el diálogo y el envío (G8 · E3) -------------------------------------------------------------------


def _source_label(layer: Any) -> str:
    provider = str(layer.providerType())
    if provider == KEY:
        return tr("Connected (GeoDuck)")
    if provider == "memory":
        return tr("Memory")
    if provider == "delimitedtext":
        return "CSV"
    if provider == "postgres":
        return "PostGIS"
    if provider == "ogr":
        storage = str(layer.dataProvider().storageType() or "OGR")
        return "GeoPackage" if storage == "GPKG" else storage
    return provider


#: Proveedores de QGIS que leen de una base de datos o de un servicio web (trazabilidad del paso 3).
_DATABASES = {
    "postgres": "POSTGIS",
    "mssql": "SQL SERVER",
    "oracle": "ORACLE",
    "hana": "HANA",
    "spatialite": "SPATIALITE",
}
_WEB = {"wfs": "WFS", "oapif": "OGC API", "arcgisfeatureserver": "ARCGIS"}


def source_trace(layer: Any) -> tuple[str, str]:
    """De dónde viene la capa (tipo y formato corto) para la trazabilidad (workspace-pro-spec §9)."""
    provider = str(layer.providerType())
    if provider == KEY:
        return "duckdb", "DUCKDB"
    if provider == "memory":
        return "memory", tr("MEMORY")
    if provider in _DATABASES:
        return "database", _DATABASES[provider]
    if provider in _WEB:
        return "web", _WEB[provider]
    if provider in ("ogr", "delimitedtext"):
        path = str(QgsProviderRegistry.instance().decodeUri(provider, layer.source()).get("path") or "")
        if path:
            name = os.path.basename(path.rstrip("/\\")).lower()
            short = "OSM" if name.endswith(".osm.pbf") else (os.path.splitext(name)[1].lstrip(".") or "OGR")
            return "file", short.upper()
    return "other", provider.upper()


def _crs_label(layer: QgsVectorLayer) -> str | None:
    crs = layer.crs()
    if not layer.isSpatial() or not crs.isValid():
        return None
    return crs.authid() or tr("custom")


def _vector_layer(layer: Any) -> bool:
    return isinstance(layer, QgsVectorLayer)


def describe_layer(layer: Any, table: str) -> SendCandidate:
    """La capa para el diálogo: sin leer entidades. Una capa que no se puede enviar lleva su motivo."""
    name = layer.name()
    if not _vector_layer(layer):
        return SendCandidate(
            layer.id(),
            name,
            "",
            -1,
            0,
            None,
            None,
            False,
            PATH_QGIS,
            (),
            None,
            (),
            table,
            problem=tr("only vector layers can be sent"),
        )
    if not layer.isValid():
        return SendCandidate(
            layer.id(),
            name,
            _source_label(layer),
            -1,
            0,
            None,
            None,
            False,
            PATH_QGIS,
            (),
            None,
            (),
            table,
            problem=tr("the layer is not valid"),
        )
    crs_problem = False
    try:
        plan = plan_layer(layer, table=table)
    except InvalidArgumentError:  # SRC que no se puede expresar (§7): solo «sin SRC»
        plan = plan_layer(layer, table=table, without_crs=True)
        crs_problem = True
    path = plan.path
    direct = direct_source(layer)
    if path == PATH_QGIS and direct is not None:
        path = PATH_GDAL  # la copia DuckDB (con GDAL, si `spatial` está cargada o el usuario la activa)
    geometry_type = QgsWkbTypes.displayString(layer.wkbType()) if layer.isSpatial() else None
    kind, short = source_trace(layer)
    warnings = list(plan.warnings)
    crs = layer.crs()
    if (
        layer.isSpatial()
        and crs.isValid()
        and not crs_problem
        and crs.authid().split(":", 1)[0] not in _AUTHORITIES
    ):
        warnings.append(tr("Custom CRS: it is stored with its full definition (PROJJSON)"))
    return SendCandidate(
        layer.id(),
        name,
        _source_label(layer),
        layer.featureCount(),
        layer.selectedFeatureCount(),
        geometry_type,
        _crs_label(layer),
        bool(layer.subsetString()),
        path,
        plan.columns,
        plan.job.geometry,
        tuple(warnings),
        table,
        crs_problem=crs_problem,
        source_kind=kind,
        source_format=short,
        needs_spatial=direct is None or direct[2] is Reader.GDAL,
    )


class LayerSender:
    """Puerto `LayerSender` (app): describe las capas para el diálogo y envía lo que el usuario confirmó."""

    def __init__(self, project: QgsProject | None = None) -> None:
        self._project = project or QgsProject.instance()

    def describe(self, layer_ids: list[str] | None) -> list[SendCandidate]:
        if layer_ids is None:
            layers = [n.layer() for n in self._project.layerTreeRoot().findLayers()]
        else:
            layers = [self._project.mapLayer(i) for i in layer_ids]
        out: list[SendCandidate] = []
        taken: list[str] = []
        for layer in layers:
            if layer is None:
                continue
            table = unique_name(table_name_for(layer.name()), taken)
            taken.append(table)
            out.append(describe_layer(layer, table))
        return out

    def start(
        self,
        engine: Any,
        request: SendRequest,
        *,
        on_progress: Callable[[int], None],
        on_done: Callable[[ImportReport | BaseException], None],
    ) -> LayerImport:
        plans = []
        for item in request.items:
            if item.file is not None:  # Archivos → DuckDB (§10): lo lee y lo copia DuckDB
                plans.append(self._file_plan(item, request))
                continue
            layer = self._project.mapLayer(item.layer_id)
            if not _vector_layer(layer):
                raise InvalidArgumentError(tr("The layer is no longer in the project"))
            parquet = geoparquet_path(layer) is not None
            plans.append(
                plan_layer(
                    layer,
                    table=item.table,
                    mode=item.mode,
                    database=request.database,
                    schema=request.schema,
                    temporary=request.temporary,
                    only_selected=request.only_selected and layer.selectedFeatureCount() > 0,
                    as_view=request.as_view
                    and not request.reproject_to
                    and parquet
                    and not layer.subsetString()
                    and not (request.only_selected and layer.selectedFeatureCount() > 0),
                    without_crs=request.without_crs,
                    reproject_to=request.reproject_to,
                    duckdb_reads=request.duckdb_reads,
                    direct=request.direct,
                )
            )
        job = LayerImport(engine, plans, on_progress=on_progress, on_done=on_done)
        job.start()
        return job

    @staticmethod
    def _file_plan(item: SendItem, request: SendRequest) -> LayerPlan:
        source = item.file
        job = file_job(
            source,
            table=item.table,
            mode=item.mode,
            database=request.database,
            schema=request.schema,
            temporary=request.temporary,
            without_crs=request.without_crs,
        )
        return LayerPlan(None, job, PATH_FILE, None, max(source.rows, 0), [], ())
