# SPDX-License-Identifier: GPL-2.0-or-later
"""«Exportar ▾» del resultado de una celda (G7 · E3, GD-NB-007; sql-editor-spec §7 «Exportar»).

Se exporta la **consulta completa** con `COPY (<consulta>) TO '<archivo>' (FORMAT …)`, nunca la vista previa,
y solo una consulta de lectura repetible (la misma regla que «Cargar en QGIS», GD-SQL-006).

Geometría en Parquet (verificado con DuckDB 1.5.0 y 2.0.0, decisión del propietario 2026-11-03):

- Sin SRC: todo lector supone `OGC:CRS84` (lo dice GeoParquet). GeoDuck no inventa un SRC: exporta con la
  opción por defecto (GeoParquet 1.0, la que más programas leen) y avisa.
- Con SRC (`GEOMETRY('EPSG:32719')`): la opción por defecto falla («GeoParquet V1 only supports PROJJSON»);
  con `GEOPARQUET_VERSION 'V2'` el SRC queda en el archivo (GDAL 3.13 lo lee como EPSG:32719).

En CSV la geometría sale como WKT (sin SRC).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.i18n import tr
from geoduck.domain.sql_text import quote_identifier, quote_string_literal


class ExportFormat(str, Enum):
    """Los formatos de «Exportar ▾», siempre con el motor de DuckDB (decisión del propietario, 2026-11-07):
    modernos, rápidos o muy usados; nunca SpatiaLite ni SQLite (GeoPackage los reemplaza)."""

    PARQUET = "parquet"
    GPKG = "gpkg"
    CSV = "csv"
    FGB = "fgb"
    ARROW = "arrow"
    JSON = "json"
    SHP = "shp"
    GEOJSON = "geojson"
    KML = "kml"
    GDB = "gdb"
    XLSX = "xlsx"

    @property
    def suffix(self) -> str:
        return {"json": ".ndjson"}.get(self.value, "." + self.value)

    @property
    def driver(self) -> str | None:
        """Controlador de GDAL (`FORMAT gdal`, extensión `spatial`); None = DuckDB o PyArrow."""
        return _DRIVERS.get(self)

    @property
    def needs_spatial(self) -> bool:
        return self.driver is not None

    @property
    def fast(self) -> bool:
        return self in (ExportFormat.PARQUET, ExportFormat.FGB, ExportFormat.ARROW)

    @property
    def main(self) -> bool:
        """En el menú principal; los demás, en «Más formatos ▸» (maqueta aprobada, 2026-11-07)."""
        return self in (ExportFormat.PARQUET, ExportFormat.GPKG, ExportFormat.CSV, ExportFormat.FGB)

    @property
    def label(self) -> str:
        from geoduck.domain.files import label_text  # noqa: PLC0415 - files importa importing

        return label_text(_LABELS[self])

    @property
    def pattern(self) -> str:
        """Filtro del diálogo de guardar."""
        return f"{self.label} (*{self.suffix})"

    @property
    def note(self) -> str:
        """Qué pasará, en una línea (la ayuda del menú)."""
        return _notes().get(self, "")


_DRIVERS = {
    ExportFormat.GPKG: "GPKG",
    ExportFormat.FGB: "FlatGeobuf",
    ExportFormat.SHP: "ESRI Shapefile",
    ExportFormat.GEOJSON: "GeoJSON",
    ExportFormat.KML: "KML",
    ExportFormat.GDB: "OpenFileGDB",
    ExportFormat.XLSX: "XLSX",
}
_LABELS = {
    ExportFormat.PARQUET: "Parquet / GeoParquet",
    ExportFormat.GPKG: "GeoPackage",
    ExportFormat.CSV: "CSV",
    ExportFormat.FGB: "FlatGeobuf",
    ExportFormat.ARROW: "Arrow / Feather",
    ExportFormat.JSON: "JSON (one object per line)",
    ExportFormat.SHP: "Shapefile",
    ExportFormat.GEOJSON: "GeoJSON",
    ExportFormat.KML: "KML",
    ExportFormat.GDB: "ArcGIS Geodatabase",
    ExportFormat.XLSX: "Excel",
}


def _notes() -> dict[ExportFormat, str]:
    return {
        ExportFormat.PARQUET: tr("Columnar and compressed: the fastest for large data"),
        ExportFormat.GPKG: tr("The standard for GIS: QGIS, ArcGIS and GDAL open it"),
        ExportFormat.CSV: tr("Text that any program opens; the geometry goes as WKT"),
        ExportFormat.FGB: tr("Fast geographic file, read in streaming"),
        ExportFormat.ARROW: tr("Columnar in memory format: fast between programs"),
        ExportFormat.JSON: tr("One JSON object per line; the geometry goes as WKT"),
        ExportFormat.SHP: tr("Column names of up to 10 letters; 2 GB limit; one geometry type"),
        ExportFormat.GEOJSON: tr("For the web; better in degrees (EPSG:4326)"),
        ExportFormat.KML: tr("For Google Earth; it is converted to degrees (EPSG:4326)"),
        ExportFormat.GDB: tr("A .gdb folder for ArcGIS; one geometry type"),
        ExportFormat.XLSX: tr("A sheet for Excel; the geometry goes as WKT"),
    }


@dataclass(frozen=True)
class ExportRequest:
    sql: str
    path: str
    format: ExportFormat
    #: Base donde se ejecutó el resultado de la celda (G7); la base en uso no cambia.
    database: str | None = None
    #: El usuario aceptó instalar o cargar `spatial` para un formato de GDAL (spatial-spec §10).
    allow_spatial: bool = False


@dataclass(frozen=True)
class ExportReport:
    path: str
    format: ExportFormat
    rows: int
    warnings: tuple[str, ...] = ()


def copy_options(columns: list[tuple[str, str]], fmt: ExportFormat) -> tuple[str, tuple[str, ...]]:
    """Opciones de `COPY … TO` para estas columnas (nombre, tipo de DuckDB) y los avisos para el usuario."""
    if fmt is ExportFormat.CSV:
        return "FORMAT csv, HEADER", ()
    if fmt is ExportFormat.JSON:
        return "FORMAT json", ()
    if fmt is ExportFormat.SHP:
        return _shapefile_options(columns)
    if fmt.driver is not None:
        return f"FORMAT gdal, DRIVER {quote_string_literal(fmt.driver)}", ()
    geometries = [(name, kind.strip()) for name, kind in columns if is_geometry_type(kind)]
    with_crs = [name for name, kind in geometries if "(" in kind]
    without_crs = [name for name, kind in geometries if "(" not in kind]
    options = "FORMAT parquet, GEOPARQUET_VERSION 'V2'" if with_crs else "FORMAT parquet"
    warnings = tuple(
        tr(
            "The geometry «{0}» has no CRS: whoever opens the file will assume degrees (OGC:CRS84). If your "
            "data uses another system, set it with ST_SetCRS in the query before exporting"
        ).format(name)
        for name in without_crs
    )
    return options, warnings


#: Un nombre de campo de Shapefile (dBASE) cabe en 10 bytes.
SHP_NAME_BYTES = 10


def _shapefile_options(columns: list[tuple[str, str]]) -> tuple[str, tuple[str, ...]]:
    """Shapefile (#141): el `.cpg` en UTF-8 (las tildes y la ñ se leen igual en cualquier programa) y un
    aviso con los nombres de campo que GDAL acortará a 10 bytes (dos largos pueden quedar «nombre_m_1»)."""
    options = "FORMAT gdal, DRIVER 'ESRI Shapefile', LAYER_CREATION_OPTIONS 'ENCODING=UTF-8'"
    long_names = [
        name
        for name, kind in columns
        if not is_geometry_type(kind) and len(name.encode("utf-8")) > SHP_NAME_BYTES
    ]
    if not long_names:
        return options, ()
    listed = ", ".join(f"«{n}»" for n in long_names[:5]) + (" …" if len(long_names) > 5 else "")
    warning = tr(
        "Shapefile keeps only 10 characters per field name: {0} will be shortened. To choose the names, "
        "rename them with AS in the query or export to GeoPackage"
    ).format(listed)
    return options, (warning,)


def gdal_select(body: str, columns: list[tuple[str, str]], fmt: ExportFormat) -> str:
    """La consulta para GDAL: Excel no guarda geometría (sale como WKT); las demás, tal cual."""
    if fmt is not ExportFormat.XLSX:
        return body
    geometries = [name for name, kind in columns if is_geometry_type(kind)]
    if not geometries:
        return body
    replaced = ", ".join(f"ST_AsText({quote_identifier(n)}) AS {quote_identifier(n)}" for n in geometries)
    return f"SELECT * REPLACE ({replaced}) FROM (\n{body}\n) AS geoduck_q"


#: Tipos de geometría que GDAL acepta en `GEOMETRY_TYPE` (Geodatabase).
GEOMETRY_TYPES = {
    "POINT": "POINT",
    "LINESTRING": "LINESTRING",
    "POLYGON": "POLYGON",
    "MULTIPOINT": "MULTIPOINT",
    "MULTILINESTRING": "MULTILINESTRING",
    "MULTIPOLYGON": "MULTIPOLYGON",
}
