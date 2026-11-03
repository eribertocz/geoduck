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


class ExportFormat(str, Enum):
    CSV = "csv"
    PARQUET = "parquet"

    @property
    def suffix(self) -> str:
        return "." + self.value


@dataclass(frozen=True)
class ExportRequest:
    sql: str
    path: str
    format: ExportFormat
    #: Base donde se ejecutó el resultado de la celda (G7); la base en uso no cambia.
    database: str | None = None


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
