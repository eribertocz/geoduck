# SPDX-License-Identifier: GPL-2.0-or-later
"""Normalización de tipos de qgis-bridge-spec §7 (GD-BRD-007), sin DuckDB."""

from __future__ import annotations

import pytest

from geoduck.domain.bridge_types import (
    UNREADABLE,
    GeometryColumn,
    GeometryFormat,
    build_load_plan,
    geometry_write_sql,
    is_geometry_type,
    plan_field,
    strip_terminator,
)
from geoduck.domain.bridge_types import (
    FieldKind as K,
)
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.load import LoadMode, LoadRequest

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
    ("TIME", K.TIME, True, False),  # hora del día: QTime (#141)
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
    assert any("Columna «a» omitida (geometría secundaria)" in w for w in plan.warnings)


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


def test_prepare_can_propose_the_first_of_several_geometries():
    plan = build_load_plan("SELECT 1", [("a", "GEOMETRY"), ("b", "GEOMETRY('OGC:CRS84')")], pick_first=True)
    assert plan.geometry.name == "a"
    assert [g.name for g in plan.geometries] == ["a", "b"]
    assert plan.geometries[1].declared_crs == "OGC:CRS84"


# -- G4/E1: columnas BLOB/VARCHAR marcadas como geometría (spatial-spec §2.2) ------------------------


def test_marked_columns_become_geometries_without_inference():
    cols = [("id", "INTEGER"), ("w", "BLOB"), ("t", "VARCHAR"), ("g", "GEOMETRY")]
    plan = build_load_plan("SELECT 1", cols)
    assert plan.geometry.name == "g"
    assert dict(plan.candidates) == {"w": GeometryFormat.WKB, "t": GeometryFormat.WKT}
    assert [f.name for f in plan.fields] == ["id", "w", "t"]  # sin marcar: atributos
    marked = build_load_plan("SELECT 1", cols, geometry="w", formats={"w": "wkb", "t": "wkt"})
    assert marked.geometry == GeometryColumn("w", "BLOB", None, GeometryFormat.WKB)
    assert [f.name for f in marked.fields] == ["id"]
    assert 'TRY(ST_GeomFromWKB("w")) AS "w"' in marked.sql
    assert marked.unreadable_flag == UNREADABLE
    assert f'("w" IS NOT NULL AND TRY(ST_GeomFromWKB("w")) IS NULL) AS "{UNREADABLE}"' in marked.sql
    assert "Columna «t» omitida (geometría secundaria)" in marked.warnings
    text = build_load_plan("SELECT 1", cols, geometry="t", formats={"t": "wkt"})
    assert 'TRY(CAST("t" AS GEOMETRY)) AS "t"' in text.sql


@pytest.mark.parametrize(("column", "fmt"), [("id", "wkb"), ("w", "wkt"), ("t", "wkb"), ("g", "geometry")])
def test_only_blob_as_wkb_and_varchar_as_wkt(column, fmt):
    cols = [("id", "INTEGER"), ("w", "BLOB"), ("t", "VARCHAR"), ("g", "GEOMETRY")]
    with pytest.raises(GeoDuckError):
        build_load_plan("SELECT 1", cols, geometry=column, formats={column: fmt})


def test_geometry_write_back_in_its_format():
    assert geometry_write_sql("x", GeometryFormat.WKB) == "ST_AsWKB(x)"
    assert geometry_write_sql("x", GeometryFormat.WKT) == "ST_AsText(x)"
    assert geometry_write_sql("x", GeometryFormat.GEOMETRY) == "x"


def test_request_split_one_layer_per_geometry():
    request = LoadRequest(
        "SELECT 1", LoadMode.MEMORY, "z", geometries=("a", "b"), crs_overrides=(("b", "EPSG:32719"),)
    )
    parts = request.split()
    assert [(p.geometry, p.layer_name, p.crs_override, p.geometries) for p in parts] == [
        ("a", "z · a", None, ()),
        ("b", "z · b", "EPSG:32719", ()),
    ]
    single = LoadRequest("SELECT 1", LoadMode.MEMORY, "z", geometry="a", crs_overrides=(("a", ""),))
    assert [(p.geometry, p.layer_name, p.crs_override) for p in single.split()] == [("a", "z", "")]
