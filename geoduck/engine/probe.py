# SPDX-License-Identifier: GPL-2.0-or-later
"""Sondas de solo lectura sobre DuckDB para el diagnóstico.

Usa una conexión `:memory:` propia, creada, usada y cerrada en el hilo que llama (nunca la conexión de
la sesión). Desactiva la autoinstalación y la autocarga: el diagnóstico jamás descarga ni instala
extensiones (spec/docs/security.md §2).
"""

from __future__ import annotations

import duckdb

from geoduck.domain.diagnostics import SpatialProbe
from geoduck.domain.i18n import tr


def _setting(con: duckdb.DuckDBPyConnection, name: str) -> object:
    row = con.execute("SELECT current_setting(?)", [name]).fetchone()
    return row[0] if row else None


def probe_spatial() -> SpatialProbe:
    con = duckdb.connect(":memory:")
    try:
        con.execute("SET autoinstall_known_extensions = false")
        con.execute("SET autoload_known_extensions = false")
        row = con.execute(
            "SELECT installed, loaded, coalesce(extension_version, '') "
            "FROM duckdb_extensions() WHERE extension_name = 'spatial'"
        ).fetchone()
        installed = bool(row and row[0])
        version = str(row[2]) if row else ""
        ext_dir = str(_setting(con, "extension_directory") or "")
        unsigned = bool(_setting(con, "allow_unsigned_extensions"))
        loaded = bool(row and row[1])
        load_error = ""
        if installed and not loaded:
            try:
                con.execute("LOAD spatial")
                loaded = True
            except duckdb.Error as exc:
                load_error = str(exc).strip().splitlines()[0]
        always_xy = ""
        if loaded:  # AX-2: se muestra, nunca se modifica (spatial-spec §4)
            row = con.execute(
                "SELECT value FROM duckdb_settings() WHERE name = 'geometry_always_xy'"
            ).fetchone()
            if row is not None:
                always_xy = tr("not set") if row[0] in (None, "") else str(row[0]).lower()
        return SpatialProbe(
            installed=installed,
            always_xy=always_xy,
            loaded=loaded,
            load_error=load_error,
            extension_directory=ext_dir,
            allow_unsigned_extensions=unsigned,
            version=version,
        )
    finally:
        con.close()
