# SPDX-License-Identifier: GPL-2.0-or-later
"""Lectura del catálogo desde DuckDB (GD-CAT-001, base de G1).

Se ejecuta como una sola operación del worker, así que ninguna otra sentencia puede intercalarse entre
las dos consultas (ADR-0006). Nunca devuelve un catálogo parcial: si DuckDB lista más bases de las que
se pueden leer, o la información es incoherente, falla.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from geoduck.domain.catalog import AccessMode, AttachedDatabase, CatalogSnapshot
from geoduck.domain.errors import EngineError

if TYPE_CHECKING:
    from geoduck.engine.worker import ConnectionHandle

#: Máximo de bases que se leen; por encima, la lectura falla en vez de truncarse.
CATALOG_LIMIT = 10_000

_DATABASES_SQL = (
    "SELECT database_name, path, readonly, type FROM duckdb_databases() "
    "WHERE NOT internal ORDER BY database_oid"
)
_CURRENT_SQL = "SELECT current_database()"


def read_catalog(handle: ConnectionHandle, root: str) -> CatalogSnapshot:
    listed = handle.execute(_DATABASES_SQL, max_rows=CATALOG_LIMIT)
    if listed.truncated:
        raise EngineError(f"El catálogo tiene más de {CATALOG_LIMIT} bases; no se muestra incompleto")
    current = handle.execute(_CURRENT_SQL).rows
    databases = tuple(
        AttachedDatabase(
            name=str(name),
            path=None if path is None else str(path),
            access=AccessMode.READ_ONLY if readonly else AccessMode.READ_WRITE,
            storage=str(storage),
        )
        for name, path, readonly, storage in listed.rows
    )
    try:
        return CatalogSnapshot(databases, root=root, default=str(current[0][0]))
    except (ValueError, IndexError) as exc:
        raise EngineError(f"Catálogo incoherente: {exc}") from exc
