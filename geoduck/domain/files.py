# SPDX-License-Identifier: GPL-2.0-or-later
"""Archivos → DuckDB: formatos, filtros del selector y el SQL que los lee, siempre con el motor de DuckDB
(qgis-import-spec §10; decisión del propietario, 2026-11-07). Sin Qt ni DuckDB.

- Parquet, CSV y JSON: lectores incluidos en DuckDB (`read_parquet`, `read_csv`, `read_json`).
- Arrow/Feather: PyArrow (`pyarrow.dataset`) registrado en DuckDB, que lo lee por flujo.
- GeoPackage, Shapefile, FlatGeobuf, GeoJSON, KML/KMZ, Geodatabase, OSM y Excel: `ST_Read` de la extensión
  `spatial`, con consentimiento (spatial-spec §10).
- Ningún otro formato: se abre primero en QGIS y se añade como capa (decisión del propietario, 2026-11-07).
"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from enum import Enum

from geoduck.domain.i18n import tr
from geoduck.domain.importing import (
    PATH_FILE,
    ImportGeometry,
    ImportJob,
    ImportMode,
    SendCandidate,
    table_name_for,
    unique_name,
)
from geoduck.domain.sql_text import quote_identifier, quote_string_literal, sql_name

#: Vista con la que el motor registra un archivo Arrow (PyArrow) durante la importación.
ARROW_VIEW = "__geoduck_file"


class Reader(str, Enum):
    PARQUET = "parquet"
    CSV = "csv"
    JSON = "json"
    ARROW = "arrow"
    GDAL = "gdal"


@dataclass(frozen=True)
class FileFormat:
    key: str
    #: Nombre para el usuario (sin traducir: se traduce al mostrarlo).
    label: str
    #: Extensiones en minúsculas, con el punto (`.osm.pbf` incluido).
    suffixes: tuple[str, ...]
    reader: Reader
    #: ⚡ en el selector: columnar o de lectura por flujo, lo más rápido para muchos datos.
    fast: bool = False

    @property
    def needs_spatial(self) -> bool:
        return self.reader is Reader.GDAL

    @property
    def patterns(self) -> str:
        return " ".join("*" + s for s in self.suffixes)


#: En el orden del selector (maqueta aprobada, 2026-11-07).
FORMATS: tuple[FileFormat, ...] = (
    FileFormat("parquet", "Parquet / GeoParquet", (".parquet",), Reader.PARQUET, fast=True),
    FileFormat("arrow", "Arrow / Feather", (".arrow", ".feather", ".ipc"), Reader.ARROW, fast=True),
    FileFormat("fgb", "FlatGeobuf", (".fgb",), Reader.GDAL, fast=True),
    FileFormat("csv", "CSV / TSV", (".csv", ".tsv"), Reader.CSV, fast=True),
    FileFormat("json", "JSON / NDJSON", (".json", ".ndjson", ".jsonl"), Reader.JSON),
    FileFormat("gpkg", "GeoPackage", (".gpkg",), Reader.GDAL),
    FileFormat("shp", "Shapefile", (".shp", ".zip"), Reader.GDAL),
    FileFormat("geojson", "GeoJSON", (".geojson", ".geojsonl", ".geojsons"), Reader.GDAL),
    FileFormat("kml", "KML / KMZ", (".kml", ".kmz"), Reader.GDAL),
    FileFormat("gdb", "ArcGIS Geodatabase", (".gdb",), Reader.GDAL),
    FileFormat("osm", "OpenStreetMap", (".osm.pbf",), Reader.GDAL),
    FileFormat("xlsx", "Excel", (".xlsx",), Reader.GDAL),
)
#: Cualquier otro archivo: no se acepta (decisión del propietario, 2026-11-07). Solo formatos modernos,
#: rápidos o muy usados; otro (p. ej. SpatiaLite) se abre primero en QGIS y se añade como capa de QGIS.
OTHER = FileFormat("other", "Unsupported format", (), Reader.GDAL)


def label_text(label: str) -> str:
    """El nombre de un formato para el usuario: los nombres propios no se traducen."""
    names = {
        "ArcGIS Geodatabase": tr("ArcGIS Geodatabase"),
        "JSON (one object per line)": tr("JSON (one object per line)"),
        "Unsupported format": tr("Unsupported format"),
    }
    return names.get(label, label)


def _gdb_folder(path: str) -> str | None:
    """Una Geodatabase es una carpeta `.gdb`: también vale un archivo de adentro (el selector no elige
    carpetas)."""
    clean = path.rstrip("/\\")
    if clean.lower().endswith(".gdb"):
        return clean
    parent = os.path.dirname(clean)
    return parent if parent.lower().endswith(".gdb") else None


def format_for(path: str) -> FileFormat:
    """El formato de un archivo por su extensión; `OTHER` si no es uno de la lista."""
    if _gdb_folder(path) is not None:
        return next(f for f in FORMATS if f.key == "gdb")
    lower = path.lower()
    for fmt in FORMATS:
        if any(lower.endswith(s) for s in fmt.suffixes):
            return fmt
    return OTHER


def source_path(path: str) -> str:
    """La ruta que se lee: la carpeta de una Geodatabase, o la ruta tal cual."""
    return _gdb_folder(path) or path


def needs_spatial(paths: list[str]) -> bool:
    return any(format_for(p).needs_spatial for p in paths)


def file_filters() -> list[str]:
    """Filtros del selector de archivos: «Todos los compatibles» y uno por formato."""
    every = " ".join(f.patterns for f in FORMATS)
    out = [tr("All supported files") + f" ({every})"]
    for fmt in FORMATS:
        mark = "⚡ " if fmt.fast else ""
        out.append(f"{mark}{label_text(fmt.label)} ({fmt.patterns})")
    return out


def unsupported_reason() -> str:
    return tr("Format not supported: open it in QGIS first, then add the layer to DuckDB")


@dataclass(frozen=True)
class FileLayer:
    """Una capa (o una hoja) de un archivo, tal como la leyó el motor para el paso 1."""

    path: str
    format: str
    #: Nombre que se muestra (la capa, la hoja o el nombre del archivo).
    name: str
    #: Capa dentro del archivo (`ST_Read(…, layer=…)`); None = la única.
    layer: str | None = None
    #: Ruta para GDAL (`/vsizip/…` para un `.zip` o un `.kmz`); vacío = `path`.
    gdal_source: str = ""
    #: Columna de geometría que da el lector; None = sin geometría.
    geometry_column: str | None = None
    #: «Point», «MultiPolygon»…; vacío si no se sabe.
    geometry_type: str = ""
    #: `EPSG:…` del archivo; None = sin SRC (o desconocido).
    crs: str | None = None
    #: Filas según los metadatos; -1 = no se sabe sin leer todo (CSV, JSON).
    rows: int = -1
    #: Tamaño del archivo en bytes.
    size: int = 0
    #: Motivo por el que no se puede leer; None = se puede.
    problem: str | None = None

    @property
    def file_format(self) -> FileFormat:
        return next((f for f in FORMATS if f.key == self.format), OTHER)

    @property
    def reader(self) -> Reader:
        return self.file_format.reader

    @property
    def display_source(self) -> str:
        base = os.path.basename(self.path.rstrip("/\\"))
        return f"{base} › {self.layer}" if self.layer and self.layer != self.name else base


def gdal_read(source: str, layer: str | None) -> str:
    args = [quote_string_literal(source)]
    if layer:
        args.append("layer = " + quote_string_literal(layer))
    return f"ST_Read({', '.join(args)})"


def reader_sql(item: FileLayer) -> str:
    """La función de tabla que lee el archivo (para `FROM`)."""
    path = quote_string_literal(item.path)
    if item.reader is Reader.PARQUET:
        return f"read_parquet({path})"
    if item.reader is Reader.CSV:
        return f"read_csv({path})"
    if item.reader is Reader.JSON:
        return f"read_json({path})"
    if item.reader is Reader.ARROW:
        return quote_identifier(ARROW_VIEW)
    return gdal_read(item.gdal_source or item.path, item.layer)


def select_sql(item: FileLayer, *, without_crs: bool = False) -> str:
    """`SELECT` de la importación: todas las columnas; la geometría con el SRC del archivo (GeoParquet sin
    `spatial` no lo lee: F-118), o sin SRC si el usuario lo eligió (F-120)."""
    source = reader_sql(item)
    column = item.geometry_column
    if column is None or (not without_crs and not item.crs):
        return f"SELECT * FROM {source}"
    name = quote_identifier(column)
    if without_crs:
        value = f"CAST({name} AS GEOMETRY)"
    else:
        assert item.crs is not None
        value = f"ST_SetCRS({name}, {quote_string_literal(item.crs)})"
    return f"SELECT * REPLACE ({value} AS {name}) FROM {source}"


def editor_sql(item: FileLayer) -> str:
    """Lo que escribe en el editor un archivo soltado ahí: su lectura, sin ejecutarla."""
    if item.reader is Reader.ARROW:
        return ""  # DuckDB no lee Arrow sin PyArrow: se importa con «Importar archivos…»
    return f"SELECT * FROM {reader_sql(item)}"


def editor_sql_for_path(path: str) -> str:
    """`editor_sql` sin leer el archivo con el motor (soltar en el editor no espera a DuckDB)."""
    fmt = format_for(path)
    real = source_path(path)
    if fmt.reader is Reader.GDAL:
        return f"SELECT * FROM {gdal_read(vsi_path(real), None)}"
    return editor_sql(FileLayer(real, fmt.key, os.path.basename(real)))


def vsi_path(path: str) -> str:
    """Un `.zip` (Shapefile comprimido) se lee por dentro con `/vsizip/`; un `.kmz`, su `.kml` de adentro."""
    lower = path.lower()
    if not lower.endswith((".zip", ".kmz")):
        return path
    base = "/vsizip/" + path.replace("\\", "/")
    if lower.endswith(".kmz"):
        try:
            with zipfile.ZipFile(path) as archive:
                inner = next((n for n in archive.namelist() if n.lower().endswith(".kml")), "doc.kml")
        except (OSError, zipfile.BadZipFile):
            inner = "doc.kml"
        return f"{base}/{inner}"
    return base


def size_label(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1024
    return ""


# -- del paso 1 al envío -------------------------------------------------------------------------------


def file_formats_needing_spatial(items: list[FileLayer]) -> str:
    """«GeoPackage, Shapefile y Excel» (sin repetir, en el orden del selector)."""
    keys = {i.format for i in items}
    names = [label_text(f.label) for f in (*FORMATS, OTHER) if f.key in keys]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " " + tr("and") + " " + names[-1]


def format_label(item: FileLayer) -> str:
    fmt = item.file_format
    return ("⚡ " if fmt.fast else "") + label_text(fmt.label)


def candidate_for(item: FileLayer, index: int, table: str) -> SendCandidate:
    """La fila del diálogo de tres pasos (el mismo de «Capas de QGIS → DuckDB»)."""
    geometry = ImportGeometry(item.geometry_column, item.crs) if item.geometry_column else None
    return SendCandidate(
        layer_id=f"file:{index}",
        name=item.name,
        source=format_label(item),
        features=item.rows,
        selected=0,
        geometry_type=(item.geometry_type or "Geometry") if geometry is not None else None,
        crs_label=item.crs,
        filtered=False,
        path=PATH_FILE,
        columns=(),
        geometry=geometry,
        warnings=(),
        table=table,
        problem=item.problem,
        file=item,
    )


def file_job(
    item: FileLayer,
    *,
    table: str,
    mode: ImportMode,
    database: str,
    schema: str,
    temporary: bool,
    without_crs: bool = False,
) -> ImportJob:
    """Una capa del archivo → una tabla, con `CREATE TABLE … AS SELECT` dentro de DuckDB."""
    geometry = None
    if item.geometry_column:
        geometry = ImportGeometry(item.geometry_column, None if without_crs else item.crs)
    return ImportJob(
        item.name,
        table,
        mode,
        (),
        geometry,
        database=database,
        schema=schema,
        temporary=temporary,
        source_sql=select_sql(item, without_crs=without_crs),
        source_arrow=item.path if item.reader is Reader.ARROW else None,
    )


def unsupported_lines(paths: list[str], supported: int) -> list[str]:
    """El aviso de archivos que GeoDuck no importa, una idea por línea (decisión del propietario, 2026-11-07):
    cuáles, qué hacer, y si los demás sí siguen."""
    names = ", ".join(os.path.basename(p.rstrip("/\\")) for p in paths)
    count = len(paths)
    lines = [
        tr("1 file is not supported by GeoDuck: {0}").format(names)
        if count == 1
        else tr("{0} files are not supported by GeoDuck: {1}").format(count, names)
    ]
    lines.append(
        tr("Open it in QGIS and then add the layer to DuckDB")
        if count == 1
        else tr("Open them in QGIS and then add the layers to DuckDB")
    )
    if supported:
        lines.append(
            tr("The other file goes on to «Files → DuckDB»")
            if supported == 1
            else tr("The other {0} files go on to «Files → DuckDB»").format(supported)
        )
    return lines


def editor_readable(path: str) -> bool:
    """El editor puede escribir la lectura de este archivo con SQL (Arrow no: lo lee PyArrow)."""
    fmt = format_for(path)
    return fmt is not OTHER and fmt.reader is not Reader.ARROW


def create_sql(
    paths: list[str],
    database: str,
    schema: str,
    taken: list[str],
    *,
    spatial: str = "",
    reserved: frozenset[str] | None = None,
) -> str:
    """Archivos soltados en el editor (decisión del propietario, 2026-11-07): llevarlos a DuckDB con un
    `CREATE TABLE … AS SELECT *` por archivo, sin ejecutarlo. Nombres que no chocan con `taken` (nunca
    `OR REPLACE`). `spatial`: «load» o «install» antepone `LOAD spatial;` (o también `INSTALL`), visible
    para que el usuario decida (ADR-0011)."""
    names = list(taken)
    parts = []
    if spatial == "install":
        parts.append("INSTALL spatial;\nLOAD spatial;")
    elif spatial == "load":
        parts.append("LOAD spatial;")
    for path in paths:
        real = source_path(path)
        base = os.path.basename(real.rstrip("/\\"))
        stem = base[: -len(".osm.pbf")] if base.lower().endswith(".osm.pbf") else os.path.splitext(base)[0]
        table = unique_name(table_name_for(stem), names)
        names.append(table)
        target = ".".join(sql_name(x, reserved) for x in (database, schema, table))
        reading = editor_sql_for_path(path).removeprefix("SELECT * FROM ")
        parts.append(f"CREATE TABLE {target} AS\nSELECT * FROM {reading};")
    return "\n\n".join(parts)
