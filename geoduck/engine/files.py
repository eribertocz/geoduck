# SPDX-License-Identifier: GPL-2.0-or-later
"""Archivos → DuckDB en el worker: qué hay en cada archivo (paso 1) y la lectura de Arrow con PyArrow
(qgis-import-spec §10). Todo lo lee DuckDB; nunca QGIS.

El paso 1 lee solo metadatos: `parquet_file_metadata` y `parquet_kv_metadata` (Parquet), `ST_Read_Meta`
(GDAL), el esquema de PyArrow (Arrow) y `DESCRIBE` (columnas). CSV y JSON no se cuentan: habría que leerlos
enteros. Sin `spatial` cargada, los archivos de GDAL vuelven con el motivo (el diálogo pide permiso).
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.files import (
    OTHER,
    FileLayer,
    Reader,
    format_for,
    gdal_read,
    reader_sql,
    source_path,
    unsupported_reason,
    vsi_path,
)
from geoduck.domain.i18n import tr
from geoduck.domain.sql_text import quote_string_literal

if TYPE_CHECKING:
    from geoduck.engine.worker import ConnectionHandle

#: Motivo de un archivo de GDAL sin `spatial` cargada (el diálogo lo reconoce por este texto).
NEEDS_SPATIAL = "needs-spatial"


def spatial_loaded(handle: ConnectionHandle) -> bool:
    rows = handle.execute(
        "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'", max_rows=1
    ).rows
    return bool(rows and rows[0][0])


def arrow_dataset(path: str) -> Any:
    import pyarrow.dataset as ds  # noqa: PLC0415 - solo al importar Arrow

    return ds.dataset(path, format="arrow")


def _crs_of(crs: Any) -> str | None:
    """`EPSG:…` de un SRC de GDAL (`ST_Read_Meta`) o de PROJJSON (GeoParquet)."""
    if not isinstance(crs, dict):
        return None
    if crs.get("auth_name") and crs.get("auth_code"):
        return f"{crs['auth_name']}:{crs['auth_code']}"
    ident = crs.get("id")
    if isinstance(ident, dict) and ident.get("authority") and ident.get("code") is not None:
        return f"{ident['authority']}:{ident['code']}"
    return None


def _geometry_columns(handle: ConnectionHandle, source: str) -> list[tuple[str, str]]:
    rows = handle.execute(f"DESCRIBE SELECT * FROM {source}", max_rows=10_000).rows
    return [(str(r[0]), str(r[1])) for r in rows if is_geometry_type(str(r[1]))]


def _crs_from_type(kind: str) -> str | None:
    """`GEOMETRY('EPSG:32719')` → `EPSG:32719` (DuckDB 2.0 ya da el SRC en el tipo)."""
    if "(" not in kind:
        return None
    inner = kind[kind.index("(") + 1 : kind.rindex(")")].strip().strip("'\"")
    return inner or None


def _scan_parquet(handle: ConnectionHandle, item: FileLayer) -> FileLayer:
    path = quote_string_literal(item.path)
    rows = handle.execute(f"SELECT sum(num_rows) FROM parquet_file_metadata({path})", max_rows=1).rows
    count = int(str(rows[0][0])) if rows and rows[0][0] is not None else -1
    geo: dict[str, Any] = {}
    meta = handle.execute(
        f"SELECT decode(value) FROM parquet_kv_metadata({path}) WHERE decode(key) = 'geo'", max_rows=1
    ).rows
    if meta and meta[0][0]:
        try:
            geo = json.loads(str(meta[0][0]))
        except ValueError:
            geo = {}
    geometries = _geometry_columns(handle, reader_sql(item))
    column = str(geo.get("primary_column") or "") or (geometries[0][0] if geometries else "")
    if not column or not (geometries or geo):
        return _replace(item, rows=count)
    info = (geo.get("columns") or {}).get(column) or {}
    kinds = info.get("geometry_types") or []
    kind = next((k for c, k in geometries if c == column), "")
    crs = _crs_of(info.get("crs")) or _crs_from_type(kind)
    return _replace(
        item, rows=count, geometry_column=column, geometry_type=str(kinds[0]) if kinds else "", crs=crs
    )


def _scan_plain(handle: ConnectionHandle, item: FileLayer) -> FileLayer:
    geometries = _geometry_columns(handle, reader_sql(item))  # también comprueba que se pueda leer
    if not geometries:
        return item
    column, kind = geometries[0]
    return _replace(item, geometry_column=column, crs=_crs_from_type(kind))


def _scan_arrow(handle: ConnectionHandle, item: FileLayer) -> FileLayer:
    data = arrow_dataset(item.path)
    count = int(data.count_rows())
    column = None
    for field in data.schema:
        name = (field.metadata or {}).get(b"ARROW:extension:name", b"").decode()
        ext = getattr(field.type, "extension_name", "") or name
        if str(ext).startswith("geoarrow."):
            column = field.name
            break
    return _replace(item, rows=count, geometry_column=column)


def _scan_gdal(handle: ConnectionHandle, item: FileLayer) -> list[FileLayer]:
    source = vsi_path(item.path)
    rows = handle.execute(f"SELECT layers FROM ST_Read_Meta({quote_string_literal(source)})", max_rows=1).rows
    layers = list(rows[0][0] or []) if rows else []
    if not layers and item.format == "gdb":
        layers = _gdb_layers(handle, source)
    if not layers:
        return [_replace(item, gdal_source=source, problem=tr("No layers could be read in this file"))]
    many = len(layers) > 1
    out = []
    for layer in layers:
        name = str(layer.get("name") or "")
        fields = layer.get("geometry_fields") or []
        first = fields[0] if fields else {}
        kind = str(first.get("type") or "")
        if kind.lower().startswith("unknown") or kind.lower() == "none":
            kind = ""
        candidate = _replace(
            item,
            name=name if many or item.format in {"gpkg", "gdb", "xlsx", "osm"} else item.name,
            layer=name or None,
            gdal_source=source,
            rows=int(layer.get("feature_count") if layer.get("feature_count") is not None else -1),
            crs=_crs_of(first.get("crs")),
        )
        try:
            geometries = _geometry_columns(handle, gdal_read(source, name or None))
        except Exception as exc:
            out.append(_replace(candidate, problem=str(exc).splitlines()[0][:160]))
            continue
        if geometries:
            column, ctype = geometries[0]
            if not kind:  # GDAL no lo declara (p. ej. lo escribió DuckDB): la primera geometría lo dice
                sample = handle.execute(
                    f"SELECT ST_GeometryType({_ident(column)}) FROM {gdal_read(source, name or None)} "
                    f"WHERE {_ident(column)} IS NOT NULL LIMIT 1",
                    max_rows=1,
                ).rows
                kind = str(sample[0][0]) if sample else ""
            candidate = _replace(
                candidate,
                geometry_column=column,
                geometry_type=kind.title().replace("Multi", "Multi").replace("string", "String"),
                crs=candidate.crs or _crs_from_type(ctype),
            )
        out.append(candidate)
    return out


def _gdb_layers(handle: ConnectionHandle, folder: str) -> list[dict[str, Any]]:
    """`ST_Read_Meta` no lista una carpeta `.gdb`: las capas salen de su catálogo (`a00000001.gdbtable`),
    sin las tablas del sistema (`GDB_…`)."""
    catalog = os.path.join(folder, "a00000001.gdbtable")
    if not os.path.isfile(catalog):
        return []
    rows = handle.execute(f"SELECT Name FROM {gdal_read(catalog, None)}", max_rows=10_000).rows
    return [{"name": str(r[0])} for r in rows if r[0] and not str(r[0]).upper().startswith("GDB_")]


def _ident(name: str) -> str:
    from geoduck.domain.sql_text import quote_identifier  # noqa: PLC0415

    return quote_identifier(name)


def _replace(item: FileLayer, **changes: Any) -> FileLayer:
    import dataclasses  # noqa: PLC0415

    return dataclasses.replace(item, **changes)


def scan_files(handle: ConnectionHandle, paths: list[str]) -> list[FileLayer]:
    """Lo que hay en cada archivo, sin leerlo entero. Un archivo que falla vuelve con su motivo."""
    loaded = spatial_loaded(handle)
    out: list[FileLayer] = []
    seen: set[str] = set()
    for raw in paths:
        path = source_path(raw)
        if path in seen:  # dos archivos de la misma Geodatabase
            continue
        seen.add(path)
        fmt = format_for(path)
        name = os.path.basename(path.rstrip("/\\"))
        stem = name[: -len(".osm.pbf")] if name.lower().endswith(".osm.pbf") else os.path.splitext(name)[0]
        try:
            size = os.path.getsize(path) if os.path.isfile(path) else 0
        except OSError:
            size = 0
        item = FileLayer(path, fmt.key, stem, size=size)
        if fmt is OTHER:
            out.append(_replace(item, problem=unsupported_reason()))
            continue
        if fmt.needs_spatial and not loaded:
            out.append(_replace(item, problem=NEEDS_SPATIAL))
            continue
        try:
            if fmt.reader is Reader.PARQUET:
                out.append(_scan_parquet(handle, item))
            elif fmt.reader is Reader.ARROW:
                out.append(_scan_arrow(handle, item))
            elif fmt.reader is Reader.GDAL:
                out.extend(_scan_gdal(handle, item))
            else:
                out.append(_scan_plain(handle, item))
        except Exception as exc:
            out.append(_replace(item, problem=str(exc).splitlines()[0][:160] or tr("Cannot be read")))
    return out
