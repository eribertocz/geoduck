# SPDX-License-Identifier: GPL-2.0-or-later
"""Pedido y resultado de una carga en QGIS (qgis-bridge-spec §1, ADR-0012)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum


class LoadMode(str, Enum):
    """Las tres modalidades de ADR-0012. El valor es estable (se recuerda la última elegida)."""

    MEMORY = "memory"  # «Copia en memoria»
    SNAPSHOT = "snapshot"  # «Copia rápida» (GeoPackage en /vsimem)
    CONNECTED = "connected"  # «Conectada a DuckDB»


@dataclass(frozen=True)
class LoadRequest:
    """Qué cargar. `sql` es una consulta de lectura repetible; nunca DDL, DML ni `RETURNING`."""

    sql: str
    mode: LoadMode
    layer_name: str
    geometry: str | None = None
    #: CRS elegido por el usuario cuando el de los datos es desconocido (`authid` o WKT); "" = sin CRS.
    crs_override: str | None = None
    #: Tabla o vista del explorador `(base, esquema, nombre)`; None para un resultado del editor. La
    #: modalidad Conectada la usa para la clave y la editabilidad (qgis-bridge-spec §5.1).
    source: tuple[str, str, str] | None = None
    #: Tipo del origen del explorador: "table" o "view" (para indicarlo en los mensajes).
    source_kind: str | None = None
    #: Varias geometrías: una capa por columna (spatial-spec §7). Vacío o una sola = solo `geometry`.
    geometries: tuple[str, ...] = ()
    #: Columnas `BLOB`/`VARCHAR` marcadas como geometría: ((nombre, "wkb" | "wkt"), …) (spatial-spec §2.2).
    formats: tuple[tuple[str, str], ...] = ()
    #: CRS elegido por columna cuando el de sus datos es desconocido: ((columna, authid o WKT o ""), …).
    crs_overrides: tuple[tuple[str, str], ...] = ()

    @property
    def format_map(self) -> dict[str, str]:
        return dict(self.formats)

    def split(self) -> list[LoadRequest]:
        """Una petición por capa. Con varias geometrías, `<nombre> · <columna>` cada una."""
        columns = self.geometries or ((self.geometry,) if self.geometry is not None else ())
        overrides = dict(self.crs_overrides)
        if len(columns) <= 1:
            column = columns[0] if columns else None
            crs = overrides.get(column, self.crs_override) if column is not None else self.crs_override
            return [replace(self, geometry=column, geometries=(), crs_override=crs)]
        return [
            replace(
                self,
                geometry=column,
                geometries=(),
                layer_name=f"{self.layer_name} · {column}",
                crs_override=overrides.get(column, self.crs_override),
            )
            for column in columns
        ]


@dataclass(frozen=True)
class LoadReport:
    """Carga terminada y publicada en el proyecto."""

    layer_id: str
    layer_name: str
    mode: LoadMode
    rows: int
    warnings: tuple[str, ...] = field(default=())
    #: De dónde viene la capa, p. ej. «tabla db.main.consumidores» o «consulta SQL».
    origin: str = ""
    #: Acceso de la capa: «lectura y escritura», «solo lectura (…)» o «copia independiente de DuckDB».
    access: str = ""
    #: Todas las capas publicadas juntas por esta carga, (id, nombre); vacío = solo `layer_id`.
    layers: tuple[tuple[str, str], ...] = ()


_KINDS = {"table": "tabla", "view": "vista"}
COPY_ACCESS = "copia independiente de DuckDB"


def describe_origin(request: LoadRequest, kind: str | None = None) -> str:
    """Origen de una carga en los mensajes: «tabla db.main.t», «vista db.main.v» o «consulta SQL»."""
    if request.source is None:
        return "consulta SQL"
    label = _KINDS.get(kind or request.source_kind or "", "")
    return f"{label} {'.'.join(request.source)}".strip()
