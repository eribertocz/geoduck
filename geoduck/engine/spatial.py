# SPDX-License-Identifier: GPL-2.0-or-later
"""Extensión `spatial` en la sesión, solo con consentimiento (spatial-spec §10, ADR-0011, security.md §2).

GeoDuck nunca la instala ni la carga por su cuenta: estas operaciones solo se ejecutan cuando el usuario
lo confirma en «Activar spatial…» (`LOAD` y, aparte, `INSTALL`). El consentimiento vale para la sesión.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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


def activate_spatial(handle: ConnectionHandle, *, install: bool) -> SpatialState:
    """`INSTALL spatial` (solo si `install`, del repositorio oficial firmado) y `LOAD spatial`."""
    if install:
        handle.execute("INSTALL spatial", max_rows=1)
    handle.execute("LOAD spatial", max_rows=1)
    return spatial_state(handle)
