# SPDX-License-Identifier: GPL-2.0-or-later
"""Modalidad Conectada: crear la capa `geoduck` (qgis-bridge-spec §5.1, ADR-0012).

Una sola operación del worker reúne los metadatos sin leer los datos en Python: columnas (`DESCRIBE`),
identificador (clave primaria entera o huella del contenido de la fila), conteo, tipos de geometría (cabecera
WKB), extensión (`ST_Extent_Agg` si `spatial` ya está cargada; si no, estadísticas de la columna) y el
campo GeoArrow para el CRS (C4). Después, en el hilo principal, se crea la capa con la URI y se publica.
No se cargan extensiones ni se cambia la configuración de la sesión (ADR-0011).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from typing import Any

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsGeometry, QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QTimer

from geoduck.domain.bridge_types import LoadPlan, build_load_plan, strip_terminator
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.convert import crs_from_field
from geoduck.qgis_bridge.memory import LoadCancelledError
from geoduck.qgis_bridge.provider import KEY, encode_uri

Done = Callable[[LoadReport | BaseException], None]

_INTEGER_KEYS = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "UTINYINT", "USMALLINT", "UINTEGER"}
_STATS_AXIS = re.compile(r"(?P<axis>[XY]): \[(?P<lo>[^,\]]+), (?P<hi>[^\]]+)\]")


def _rows(handle: Any, sql: str, max_rows: int = 100) -> list[tuple[Any, ...]]:
    return list(handle.execute(sql, max_rows=max_rows).rows)


def _source_info(handle: Any, source: tuple[str, str, str]) -> tuple[bool, list[str] | None]:
    """(es tabla base, columnas de su clave o None) — como QGIS con PostGIS: la clave primaria y, si no
    hay, la restricción `UNIQUE` con todas sus columnas `NOT NULL` (la de menos columnas, entera antes)."""
    db, schema, name = (quote_string_literal(p) for p in source)
    where = f"database_name = {db} AND schema_name = {schema} AND table_name = {name}"
    if not _rows(handle, f"SELECT 1 FROM duckdb_tables() WHERE {where}", 1):
        return False, None
    constraints = _rows(
        handle,
        "SELECT constraint_type, constraint_column_names FROM duckdb_constraints() "
        f"WHERE {where} AND constraint_type IN ('PRIMARY KEY', 'UNIQUE')",
        1000,
    )
    columns = _rows(
        handle, f"SELECT column_name, is_nullable, data_type FROM duckdb_columns() WHERE {where}", 10_000
    )
    not_null = {str(c) for c, nullable, _ in columns if not nullable}
    types = {str(c): str(t) for c, _, t in columns}
    primary = [list(map(str, cols)) for kind, cols in constraints if kind == "PRIMARY KEY"]
    if primary:
        return True, primary[0]
    unique = [
        list(map(str, cols))
        for kind, cols in constraints
        if kind == "UNIQUE" and set(map(str, cols)) <= not_null
    ]
    if not unique:
        return True, None
    unique.sort(key=lambda cols: (len(cols), not (len(cols) == 1 and types.get(cols[0]) in _INTEGER_KEYS)))
    return True, unique[0]


def _edit_info(
    handle: Any, source: tuple[str, str, str], key: str | None
) -> tuple[str | None, str | None, list[str]]:
    """(motivo por el que no es editable o None, `nextval(...)` de la clave entera, columnas con valor
    por defecto: en una alta sin valor, DuckDB lo pone)."""
    db, schema, name = (quote_string_literal(p) for p in source)
    readonly = _rows(handle, f"SELECT readonly FROM duckdb_databases() WHERE database_name = {db}", 1)
    if readonly and readonly[0][0]:
        return "base de datos de solo lectura", None, []
    rows = _rows(
        handle,
        f"SELECT column_name, column_default FROM duckdb_columns() WHERE database_name = {db} "
        f"AND schema_name = {schema} AND table_name = {name} AND column_default IS NOT NULL",
        10_000,
    )
    defaults = {str(c): str(d) for c, d in rows}
    expr = defaults.get(key) if key else None
    return None, expr if expr and expr.lower().startswith("nextval(") else None, sorted(defaults)


def _extent_from_stats(value: Any) -> tuple[float, float, float, float] | None:
    """Extensión desde `stats(geom)`: dict en DuckDB 2.x, texto en 1.5."""
    try:
        if isinstance(value, dict):
            e = value.get("extent") or {}
            box = (float(e["x_min"]), float(e["y_min"]), float(e["x_max"]), float(e["y_max"]))
        else:
            axes = {m["axis"]: (float(m["lo"]), float(m["hi"])) for m in _STATS_AXIS.finditer(str(value))}
            box = (axes["X"][0], axes["Y"][0], axes["X"][1], axes["Y"][1])
    except (KeyError, TypeError, ValueError):
        return None
    finite = all(math.isfinite(v) for v in box)
    return box if finite and box[0] <= box[2] and box[1] <= box[3] else None


def _scan_extent(handle: Any, token: Any, sql: str) -> tuple[float, float, float, float] | None:
    """Extensión exacta recorriendo la geometría una vez, en el worker; ignora nulas y vacías."""
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    with handle.arrow_batches(sql, batch_size=65_536) as reader:
        for batch in reader:
            token.raise_if_cancelled()
            for wkb in batch.column(0).to_pylist():
                if wkb is None:
                    continue
                g = QgsGeometry()
                g.fromWkb(wkb)
                if g.isNull() or g.isEmpty():
                    continue
                box = g.boundingBox()
                xmin, ymin = min(xmin, box.xMinimum()), min(ymin, box.yMinimum())
                xmax, ymax = max(xmax, box.xMaximum()), max(ymax, box.yMaximum())
    finite = all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax))
    return (xmin, ymin, xmax, ymax) if finite else None


def wkb_type_name(headers: list[str]) -> tuple[str, str | None]:
    """Tipo de capa (`Qgis.WkbType` por nombre) desde cabeceras WKB ISO en hex, y un aviso si hay mezcla."""
    types = set()
    for h in headers:
        if not h or len(h) < 10:
            continue
        raw = bytes.fromhex(h[2:10])
        code = int.from_bytes(raw, "little" if h[:2] == "01" else "big")
        types.add(Qgis.WkbType(code))
    if not types:
        return "Unknown", "Ninguna geometría no nula: tipo de geometría desconocido"
    if len(types) == 1:
        return Qgis.WkbType(next(iter(types))).name, None
    flat = {QgsWkbTypes.flatType(QgsWkbTypes.multiType(t)) for t in types}
    dims = {(QgsWkbTypes.hasZ(t), QgsWkbTypes.hasM(t)) for t in types}
    if len(flat) == 1 and len(dims) == 1:  # p. ej. Point y MultiPoint: la capa es Multi
        return Qgis.WkbType(QgsWkbTypes.multiType(next(iter(types)))).name, None
    return (
        "Unknown",
        "Geometrías de tipos distintos: la capa se dibuja, pero QGIS no puede simbolizarla por tipo",
    )


def _metadata(handle: Any, token: Any, request: LoadRequest) -> dict[str, Any]:  # noqa: PLR0912
    """Operación del worker: todo lo que la URI necesita, sin leer los datos en Python."""
    inner = strip_terminator(request.sql)
    described = _rows(handle, f"DESCRIBE SELECT * FROM (\n{inner}\n) AS __geoduck_q", 10_000)
    columns = [(str(r[0]), str(r[1])) for r in described]
    plan = build_load_plan(inner, columns, geometry=request.geometry)
    token.raise_if_cancelled()
    source_sql = ".".join(quote_identifier(p) for p in request.source) if request.source else None
    is_table, keys = _source_info(handle, request.source) if request.source else (False, None)
    scope = "session"
    if request.source is not None:
        path = _rows(
            handle,
            "SELECT path FROM duckdb_databases() WHERE NOT internal AND path IS NOT NULL "
            f"AND database_name = {quote_string_literal(request.source[0])}",
            1,
        )
        if path:  # base adjunta desde un archivo: la capa sobrevive a la sesión (§5.5)
            scope = "attached"
    if keys and len(keys) == 1 and dict(columns).get(keys[0]) in _INTEGER_KEYS:
        fid, key = "key", keys[0]  # el valor es el FID
    elif keys:
        fid, key = "map", None  # cualquier otra clave: FID asignado en memoria (PktFidMap de QGIS)
    elif is_table:
        fid, key = "rowid", None  # como `ctid` en PostgreSQL
    else:
        fid, key = "content", None
    readonly: str | None = None
    if request.source is not None and not is_table:
        readonly = "es una vista y DuckDB no escribe en vistas"
    elif not is_table:
        readonly = (
            "es el resultado de una consulta. Para editar, cargue la tabla desde el explorador "
            "(clic derecho o doble clic → Cargar en QGIS…)"
        )
    key_default: str | None = None
    defaults: list[str] = []
    if is_table and request.source is not None:
        readonly, key_default, defaults = _edit_info(handle, request.source, key)
    count = int(_rows(handle, f"SELECT count(*) FROM (\n{inner}\n) AS __geoduck_q", 1)[0][0])
    token.raise_if_cancelled()
    out: dict[str, Any] = {
        "plan": plan,
        "columns": columns,
        "fid": fid,
        "key": key,
        "readonly": readonly,
        "default": key_default,
        "defaults": defaults,
        "keys": keys,
        "table": is_table,
        "source": source_sql,
        "scope": scope,
        "count": count,
        "headers": [],
        "extent": None,
        "field": None,
    }
    if plan.geometry is None:
        return out
    g = quote_identifier(plan.geometry.name)
    out["headers"] = [
        str(r[0])
        for r in _rows(
            handle,
            f"SELECT DISTINCT hex(st_aswkb({g}))[1:10] FROM (\n{inner}\n) AS __geoduck_q "
            f"WHERE {g} IS NOT NULL",
            64,
        )
    ]
    token.raise_if_cancelled()
    spatial = _rows(handle, "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'", 1)
    if spatial and spatial[0][0]:
        box = _rows(
            handle,
            f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
            f"(SELECT ST_Extent_Agg({g}) AS e FROM (\n{inner}\n) AS __geoduck_q)",
            1,
        )[0]
        out["extent"] = tuple(float(v) for v in box) if None not in box else None
    else:
        stats = _rows(handle, f"SELECT stats({g}) FROM (\n{inner}\n) AS __geoduck_q LIMIT 1", 1)
        out["extent"] = _extent_from_stats(stats[0][0]) if stats else None
    if out["extent"] is None and count:
        # Estadísticas inservibles (p. ej. geometrías vacías dan -inf…inf): un recorrido de la geometría.
        out["extent"] = _scan_extent(handle, token, f"SELECT {g} FROM (\n{inner}\n) AS __geoduck_q")
    batches: list[Any] = []  # el campo GeoArrow (con su CRS) de una fila
    handle.read_arrow(
        f"SELECT {g} FROM ({plan.sql}) AS __geoduck_c WHERE {g} IS NOT NULL LIMIT 1",
        batch_size=1,
        on_batch=batches.append,
        token=token,
    )
    if batches:
        out["field"] = batches[0].schema.field(plan.geometry.name)
    return out


class ConnectedLoad:
    """Crea y publica una capa Conectada. Se crea y se usa en el hilo principal."""

    mode = LoadMode.CONNECTED

    def __init__(
        self,
        engine: Any,
        request: LoadRequest,
        *,
        on_progress: Callable[[int], None],
        on_done: Done,
        on_layer: Callable[[QgsVectorLayer], None] | None = None,
        project: QgsProject | None = None,
    ) -> None:
        self._engine = engine
        self._request = request
        self._on_progress = on_progress
        self._on_done = on_done
        self._on_layer = on_layer
        self._project = project or QgsProject.instance()
        self._handle: Any = None
        self._finished = False
        self._timer = QTimer()
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        request = self._request
        self._handle = self._engine.submit(lambda h, t: _metadata(h, t, request))
        self._timer.start()

    def cancel(self) -> None:
        if self._finished:
            return
        if self._handle is not None and not self._handle.future.done():
            self._engine.cancel(self._handle.op_id)
        self._end(LoadCancelledError("Carga cancelada"))

    def _poll(self) -> None:
        if self._finished or not self._handle.future.done():
            return
        exc = self._handle.future.exception()
        if exc is not None:
            self._end(exc)
            return
        try:
            report = self._publish(self._handle.future.result())
        except BaseException as err:
            self._end(err)
            return
        self._end(report)

    def _crs(self, meta: dict[str, Any], plan: LoadPlan) -> QgsCoordinateReferenceSystem:
        override = self._request.crs_override
        if meta["field"] is not None:
            return crs_from_field(meta["field"], override)
        if override:
            return QgsCoordinateReferenceSystem(override)
        declared = plan.geometry.declared_crs if plan.geometry is not None else None
        return QgsCoordinateReferenceSystem(declared) if declared else QgsCoordinateReferenceSystem()

    def _publish(self, meta: dict[str, Any]) -> LoadReport:
        plan: LoadPlan = meta["plan"]
        warnings = list(plan.warnings)
        params: dict[str, Any] = {
            "session": sessions.register(self._engine),
            "source": meta["source"],
            "scope": meta["scope"],
            "database": self._request.source[0] if self._request.source else None,
            "sql": strip_terminator(self._request.sql),
            "geom": plan.geometry.name if plan.geometry is not None else None,
            "fid": meta["fid"],
            "key": meta["key"],
            "edit": "1" if meta["readonly"] is None else None,
            "default": meta["default"],
            "defaults": json.dumps(meta["defaults"]) if meta["defaults"] else None,
            "keys": json.dumps(meta["keys"]) if meta["fid"] == "map" else None,
            "count": meta["count"],
            "columns": meta["columns"],
        }
        if plan.geometry is not None:
            type_name, note = wkb_type_name(meta["headers"])
            params["type"] = type_name
            if note:
                warnings.append(note)
            crs = self._crs(meta, plan)
            if crs.isValid():
                params["crs"] = crs.authid() or crs.toWkt()
            else:
                warnings.append("Capa sin CRS")
            if meta["extent"] is not None:
                params["extent"] = ",".join(repr(v) for v in meta["extent"])
            elif meta["count"]:
                warnings.append("Extensión desconocida: «Zoom a la capa» no está disponible")
        if meta["readonly"] is not None:
            warnings.append(f"Solo lectura: {meta['readonly']}")
        layer = QgsVectorLayer(encode_uri(params), self._request.layer_name, KEY)
        if not layer.isValid():
            raise GeoDuckError(f"QGIS no pudo crear la capa conectada: {layer.dataProvider().last_error}")
        if plan.geometry is not None and not layer.crs().isValid():
            layer.setCrs(QgsCoordinateReferenceSystem())  # sin CRS asignado en silencio (C4)
        self._finished = True  # antes de publicar: un error al dibujar no es un fallo de la carga
        self._project.addMapLayer(layer)
        if self._on_layer is not None:
            self._on_layer(layer)
        self._on_progress(meta["count"])
        return LoadReport(layer.id(), layer.name(), LoadMode.CONNECTED, meta["count"], tuple(warnings))

    def _end(self, result: LoadReport | BaseException) -> None:
        self._timer.stop()
        if isinstance(result, BaseException) and self._finished:
            return
        self._finished = True
        self._on_done(result)
