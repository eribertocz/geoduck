# SPDX-License-Identifier: GPL-2.0-or-later
"""Pedido y resultado de una carga en QGIS (qgis-bridge-spec §1, ADR-0012)."""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass(frozen=True)
class LoadReport:
    """Carga terminada y publicada en el proyecto."""

    layer_id: str
    layer_name: str
    mode: LoadMode
    rows: int
    warnings: tuple[str, ...] = field(default=())
