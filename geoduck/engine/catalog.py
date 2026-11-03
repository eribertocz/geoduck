# SPDX-License-Identifier: GPL-2.0-or-later
"""Lectura del catálogo desde DuckDB (GD-CAT-001, base de G1).

Se ejecuta como una sola operación del worker, así que ninguna otra sentencia puede intercalarse entre
las dos consultas (ADR-0006). Nunca devuelve un catálogo parcial: si DuckDB lista más bases de las que
se pueden leer, o la información es incoherente, falla.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from geoduck.domain.catalog import (
    TEMP_CATALOG,
    AccessMode,
    AttachedDatabase,
    CatalogObject,
    CatalogSnapshot,
    ColumnInfo,
    ObjectKind,
    catalog_key,
)
from geoduck.domain.completion import Vocabulary
from geoduck.domain.errors import EngineError
from geoduck.domain.i18n import tr
from geoduck.domain.sql_text import quote_string_literal

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
        raise EngineError(
            tr("The catalog has more than {0} databases; it is not shown incomplete").format(CATALOG_LIMIT)
        )
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
        raise EngineError(tr("Inconsistent catalog: {0}").format(exc)) from exc


def _bounded(handle: ConnectionHandle, sql: str) -> tuple[tuple[object, ...], ...]:
    out = handle.execute(sql, max_rows=OBJECT_LIMIT)
    if out.truncated:
        raise EngineError(
            tr("The catalog has more than {0} objects; it is not shown incomplete").format(OBJECT_LIMIT)
        )
    return out.rows


#: Máximo de columnas de un objeto; por encima, la lectura falla en vez de truncarse.
COLUMN_LIMIT = 10_000


def read_columns(handle: ConnectionHandle, database: str, schema: str, name: str) -> tuple[ColumnInfo, ...]:
    """Columnas de una tabla o vista, en su orden (session-spec `ListColumns`). Solo metadatos."""
    where = " AND ".join(
        f"{col} = {quote_string_literal(value)}"
        for col, value in (("database_name", database), ("schema_name", schema), ("table_name", name))
    )
    out = handle.execute(
        f"SELECT column_name, data_type, is_nullable FROM duckdb_columns() WHERE {where} "
        "ORDER BY column_index",
        max_rows=COLUMN_LIMIT,
    )
    if out.truncated:
        raise EngineError(
            tr("{0} has more than {1} columns; they are not shown incomplete").format(name, COLUMN_LIMIT)
        )
    if not out.rows:  # una tabla o vista siempre tiene columnas: el objeto ya no existe
        raise EngineError(tr("{0}.{1}.{2} no longer exists").format(database, schema, name))
    return tuple(
        ColumnInfo(str(col), str(data_type), None if nullable is None else bool(nullable))
        for col, data_type, nullable in out.rows
    )


def read_vocabulary(handle: ConnectionHandle) -> Vocabulary:
    """Palabras clave (`duckdb_keywords()`) y funciones (`duckdb_functions()`, sin `pragma` ni operadores)
    de la sesión, para citar nombres y para el autocompletado (G6 · E2)."""
    keywords = handle.execute(
        "SELECT keyword_name, keyword_category FROM duckdb_keywords() ORDER BY keyword_name",
        max_rows=OBJECT_LIMIT,
    )
    functions = handle.execute(
        "SELECT DISTINCT function_name FROM duckdb_functions() "
        "WHERE function_type <> 'pragma' ORDER BY function_name",
        max_rows=OBJECT_LIMIT,
    )
    return Vocabulary(
        reserved=frozenset(str(name) for name, category in keywords.rows if category != "unreserved"),
        keywords=tuple(str(name) for name, _category in keywords.rows),
        functions=tuple(str(row[0]) for row in functions.rows if _FUNCTION_NAME.match(str(row[0]))),
    )


_FUNCTION_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
