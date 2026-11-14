# SPDX-License-Identifier: GPL-2.0-or-later
"""Extensión `spatial` en la sesión (spatial-spec §10, ADR-0011, #193).

GeoDuck es para análisis espacial: la sesión la carga al iniciar (y la instala si falta, del repositorio
oficial firmado). Si no se pudo (sin internet), «Reintentar» vuelve a intentarlo con `activate_spatial`.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import duckdb

from geoduck.domain.sql_text import quote_string_literal
from geoduck.engine.sql import axis_order_setting

if TYPE_CHECKING:
    from geoduck.engine.worker import ConnectionHandle


@dataclass(frozen=True)
class SpatialState:
    installed: bool
    loaded: bool
    version: str = ""
    #: `geometry_always_xy` con `spatial` cargada («true», «false», «sin fijar»); GeoDuck no lo modifica.
    always_xy: str | None = None


def spatial_state(handle: ConnectionHandle) -> SpatialState:
    rows = handle.execute(
        "SELECT installed, loaded, coalesce(extension_version, '') FROM duckdb_extensions() "
        "WHERE extension_name = 'spatial'",
        max_rows=1,
    ).rows
    if not rows:
        return SpatialState(False, False)
    installed, loaded, version = bool(rows[0][0]), bool(rows[0][1]), str(rows[0][2])
    return SpatialState(installed, loaded, version, axis_order_setting(handle) if loaded else None)


def install_spatial_from(handle: ConnectionHandle, path: str) -> SpatialState:
    """«Instalar desde un archivo…» (#193): una red sin salida a internet. El archivo debe ser el de esta
    versión de DuckDB y este sistema; si no, DuckDB lo dice."""
    handle.execute(f"INSTALL {quote_string_literal(path)}", max_rows=1)
    return activate_spatial(handle, install=False)


def activate_spatial(handle: ConnectionHandle, *, install: bool) -> SpatialState:
    """`INSTALL spatial` (solo si `install`, del repositorio oficial firmado) y `LOAD spatial`."""
    if install:
        handle.execute("INSTALL spatial", max_rows=1)
    handle.execute("LOAD spatial", max_rows=1)
    with contextlib.suppress(duckdb.Error):  # longitud, latitud (#193); el ajuste existe desde spatial 2.0
        handle.execute("SET geometry_always_xy = true", max_rows=1)
    return spatial_state(handle)
