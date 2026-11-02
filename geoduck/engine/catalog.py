# SPDX-License-Identifier: GPL-2.0-or-later
"""Lectura del catálogo desde DuckDB (GD-CAT-001, base de G1).

Se ejecuta como una sola operación del worker, así que ninguna otra sentencia puede intercalarse entre
las dos consultas (ADR-0006). Nunca devuelve un catálogo parcial: si DuckDB lista más bases de las que
se pueden leer, o la información es incoherente, falla.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from geoduck.domain.catalog import (
    TEMP_CATALOG,
    AccessMode,
    AttachedDatabase,
    CatalogObject,
    CatalogSnapshot,
    ObjectKind,
    catalog_key,
)
from geoduck.domain.errors import EngineError

if TYPE_CHECKING:
    from geoduck.engine.worker import ConnectionHandle

#: Máximo de bases que se leen; por encima, la lectura falla en vez de truncarse.
CATALOG_LIMIT = 10_000
#: Máximo de esquemas, tablas y vistas; por encima, la lectura falla en vez de truncarse.
OBJECT_LIMIT = 50_000

_DATABASES_SQL = (
    "SELECT database_name, path, readonly, type FROM duckdb_databases() "
    "WHERE NOT internal ORDER BY database_oid"
)
_CURRENT_SQL = "SELECT current_database()"
# `main` figura como `internal`, pero es un esquema del usuario: se filtra por base, no por esa marca.
_SCHEMAS_SQL = "SELECT database_name, schema_name FROM duckdb_schemas() ORDER BY database_oid, schema_name"
_TABLES_SQL = (
    "SELECT database_name, schema_name, table_name, temporary FROM duckdb_tables() "
    "WHERE NOT internal ORDER BY database_name, schema_name, table_name"
)
_VIEWS_SQL = (
    "SELECT database_name, schema_name, view_name, temporary FROM duckdb_views() "
    "WHERE NOT internal ORDER BY database_name, schema_name, view_name"
)


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
    listed_keys = {catalog_key(db.name) for db in databases}
    schemas = tuple(
        (str(db), str(schema))
        for db, schema in _bounded(handle, _SCHEMAS_SQL)
        if catalog_key(str(db)) in listed_keys
    )
    objects = tuple(
        CatalogObject(str(db), str(schema), str(name), kind, bool(temporary))
        for sql, kind in ((_TABLES_SQL, ObjectKind.TABLE), (_VIEWS_SQL, ObjectKind.VIEW))
        for db, schema, name, temporary in _bounded(handle, sql)
        if catalog_key(str(db)) in listed_keys or catalog_key(str(db)) == TEMP_CATALOG
    )
    try:
        return CatalogSnapshot(
            databases, root=root, default=str(current[0][0]), schemas=schemas, objects=objects
        )
    except (ValueError, IndexError) as exc:
        raise EngineError(f"Catálogo incoherente: {exc}") from exc


def _bounded(handle: ConnectionHandle, sql: str) -> tuple[tuple[object, ...], ...]:
    out = handle.execute(sql, max_rows=OBJECT_LIMIT)
    if out.truncated:
        raise EngineError(f"El catálogo tiene más de {OBJECT_LIMIT} objetos; no se muestra incompleto")
    return out.rows
