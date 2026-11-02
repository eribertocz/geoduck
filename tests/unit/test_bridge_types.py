# SPDX-License-Identifier: GPL-2.0-or-later
"""Normalización de tipos de qgis-bridge-spec §7 (GD-BRD-007), sin DuckDB."""

from __future__ import annotations

import pytest

from geoduck.domain.bridge_types import (
    FieldKind as K,
)
from geoduck.domain.bridge_types import (
    build_load_plan,
    is_geometry_type,
    plan_field,
    strip_terminator,
)
from geoduck.domain.errors import GeoDuckError

# (tipo de DuckDB 1.5/2.x en DESCRIBE, campo resultante, escribible de vuelta, ¿avisa?)
CASES = [
    ("BOOLEAN", K.BOOL, True, False),
    ("TINYINT", K.INT, True, False),
    ("SMALLINT", K.INT, True, False),
    ("INTEGER", K.INT, True, False),
    ("UTINYINT", K.INT, True, False),
    ("USMALLINT", K.INT, True, False),
    ("UINTEGER", K.INT64, True, False),
    ("BIGINT", K.INT64, True, False),
    ("UBIGINT", K.TEXT, False, True),
    ("HUGEINT", K.TEXT, False, True),
    ("UHUGEINT", K.TEXT, False, True),
    ("BIGNUM", K.TEXT, False, True),
    ("FLOAT", K.DOUBLE, True, False),
    ("DOUBLE", K.DOUBLE, True, False),
    ("DECIMAL(9,2)", K.DOUBLE, True, False),
    ("DECIMAL(15,3)", K.DOUBLE, True, False),
    ("DECIMAL(16,3)", K.TEXT, False, True),
    ("DECIMAL(38,10)", K.TEXT, False, True),
    ("VARCHAR", K.TEXT, True, False),
    ("UUID", K.TEXT, True, False),
    ("ENUM('a', 'b')", K.TEXT, True, False),
    ("DATE", K.DATE, True, False),
    ("TIMESTAMP", K.DATETIME, True, False),
    ("TIMESTAMP_S", K.DATETIME, False, False),
    ("TIMESTAMP_MS", K.DATETIME, False, False),
    ("TIMESTAMP_NS", K.DATETIME, False, True),
    ("TIMESTAMP WITH TIME ZONE", K.DATETIME_TZ, True, False),
    ("TIME", K.TEXT, False, True),
    ("TIME WITH TIME ZONE", K.TEXT, False, True),
    ("INTERVAL", K.TEXT, False, True),
    ("BLOB", K.BINARY, True, False),
    ("BIT", K.TEXT, False, True),
    ("INTEGER[]", K.TEXT, False, True),
    ("INTEGER[2]", K.TEXT, False, True),
    ("STRUCT(x INTEGER)", K.TEXT, False, True),
    ("MAP(VARCHAR, INTEGER)", K.TEXT, False, True),
    ("UNION(num INTEGER)", K.TEXT, False, True),
    ('"NULL"', K.TEXT, False, True),  # columna NULL literal en DuckDB 2.0
]


@pytest.mark.parametrize(("source", "kind", "writable", "warns"), CASES, ids=[c[0] for c in CASES])
def test_every_type_has_an_explicit_rule(source, kind, writable, warns):
    plan = plan_field("c", source)
    assert plan.kind is kind
    assert plan.writable is writable
    assert bool(plan.note) is warns


def test_nested_types_become_json_text():
    assert plan_field("c", "STRUCT(x INTEGER)").expression == 'CAST(to_json("c") AS VARCHAR)'


def test_identifiers_are_quoted():
    assert plan_field('a"b', "HUGEINT").expression == 'CAST("a""b" AS VARCHAR)'


@pytest.mark.parametrize("t", ["GEOMETRY", "GEOMETRY('OGC:CRS84')", "GEOMETRY('EPSG:4326')"])
def test_geometry_types(t):
    assert is_geometry_type(t)


def test_plan_wraps_query_and_keeps_primary_geometry_last():
    plan = build_load_plan(
        "SELECT * FROM t;", [("id", "BIGINT"), ("g", "GEOMETRY('OGC:CRS84')"), ("n", "HUGEINT")]
    )
    assert plan.field_names == ("id", "n")
    assert plan.geometry.name == "g"
    assert plan.geometry.declared_crs == "OGC:CRS84"
    assert plan.sql.endswith('"g" FROM (\nSELECT * FROM t\n) AS __geoduck_q')
    assert any("HUGEINT" in w for w in plan.warnings)


def test_trailing_comment_cannot_swallow_the_closing_parenthesis():
    plan = build_load_plan("SELECT 1 AS a -- comentario", [("a", "INTEGER")])
    assert "-- comentario\n) AS __geoduck_q" in plan.sql


def test_several_geometries_require_a_choice():
    cols = [("a", "GEOMETRY"), ("b", "GEOMETRY")]
    with pytest.raises(GeoDuckError, match="varias columnas de geometría"):
        build_load_plan("SELECT 1", cols)
    plan = build_load_plan("SELECT 1", cols, geometry="b")
    assert plan.geometry.name == "b"
    assert any("«a»: geometría no primaria omitida" in w for w in plan.warnings)


def test_unknown_geometry_name_is_rejected():
    with pytest.raises(GeoDuckError, match="no es una columna de geometría"):
        build_load_plan("SELECT 1", [("a", "INTEGER")], geometry="a")


def test_table_without_geometry():
    plan = build_load_plan("SELECT 1", [("a", "INTEGER")])
    assert plan.geometry is None


def test_duplicate_column_names_are_rejected():
    with pytest.raises(GeoDuckError, match="repetido"):
        build_load_plan("SELECT 1", [("a", "INTEGER"), ("a", "BIGINT")])


@pytest.mark.parametrize("sql", ["", " ; ", ";;"])
def test_empty_query_is_rejected(sql):
    with pytest.raises(GeoDuckError):
        strip_terminator(sql)
