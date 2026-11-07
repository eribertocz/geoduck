# SPDX-License-Identifier: GPL-2.0-or-later
"""SQL de la pestaña de tabla (G9 · E3; workspace-pro-spec §4; AT-WSP-003): filtros, búsqueda, orden y
páginas, comparados con DuckDB real (1.5.x y 2.x)."""

from __future__ import annotations

import duckdb
import pytest

from geoduck.domain.browse import (
    CONTAINS,
    EQ,
    GT,
    IS_NULL,
    NE,
    NOT_NULL,
    PAGE,
    STARTS,
    Browse,
    Filter,
    geometry_summary,
    page_label,
    size_sql,
    structure_sql,
)
from geoduck.domain.catalog import ColumnInfo
from geoduck.domain.i18n import tr

COLUMNS = (
    ColumnInfo("id", "INTEGER", True),
    ColumnInfo("nombre", "VARCHAR", True),
    ColumnInfo("kwh", "DOUBLE", True),
)


@pytest.fixture
def con():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t AS SELECT range AS id, CASE WHEN range % 10 = 0 THEN NULL "
        "ELSE 'Cliente ' || range END AS nombre, range * 1.5 AS kwh FROM range(1000)"
    )
    con.execute('CREATE TABLE "raro ""x""" (a INTEGER)')
    yield con
    con.close()


def browse(**kwargs):
    return Browse("memory", "main", "t", COLUMNS, **kwargs)


def ids(con, sql):
    return [row[0] for row in con.execute(sql).fetchall()]


def test_a_page_is_100_rows_and_the_count_is_apart(con):
    b = browse()
    assert len(con.execute(b.page_sql(0)).fetchall()) == PAGE
    assert len(con.execute(b.page_sql(950)).fetchall()) == 50
    assert con.execute(b.count_sql()).fetchone()[0] == 1000


@pytest.mark.parametrize(
    ("item", "where"),
    [
        (Filter("id", EQ, "7"), "id = 7"),
        (Filter("id", NE, "7"), "id <> 7"),
        (Filter("kwh", GT, "1400"), "kwh > 1400"),
        (Filter("nombre", CONTAINS, "TE 99"), "lower(nombre) LIKE '%te 99%'"),
        (Filter("nombre", STARTS, "cliente 5"), "lower(nombre) LIKE 'cliente 5%'"),
        (Filter("nombre", IS_NULL), "nombre IS NULL"),
        (Filter("nombre", NOT_NULL), "nombre IS NOT NULL"),
    ],
)
def test_each_operator_matches_plain_sql(con, item, where):
    b = browse(filters=(item,), order=("id", True))
    expected = ids(con, f"SELECT id FROM t WHERE {where} ORDER BY id")
    assert ids(con, f"SELECT id FROM ({b.count_sql().replace('count(*)', 'id')}) ORDER BY id") == expected
    assert con.execute(b.count_sql()).fetchone()[0] == len(expected)


def test_two_chips_combine_with_and_and_search_looks_in_text_columns(con):
    b = (
        browse(order=("id", False))
        .with_filter(Filter("kwh", GT, "300"))
        .with_filter(Filter("id", "<", "400"))
    )
    b = b.with_search("  ente 3 ")
    expected = ids(
        con,
        "SELECT id FROM t WHERE kwh > 300 AND id < 400 AND lower(nombre) LIKE '%ente 3%' ORDER BY id DESC",
    )
    assert ids(con, b.page_sql(0)) == expected[:PAGE]
    assert b.without_filter(0).filters == (Filter("id", "<", "400"),)


def test_values_and_names_are_quoted(con):
    b = Browse("memory", "main", 'raro "x"', (ColumnInfo("a", "INTEGER", True),))
    assert con.execute(b.count_sql()).fetchone()[0] == 0
    tricky = browse(filters=(Filter("nombre", EQ, "O'Brien'; DROP TABLE t; --"),))
    assert con.execute(tricky.count_sql()).fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 1000


def test_sort_cycles_ascending_descending_none_and_nulls_go_last(con):
    b = browse()
    b = b.next_order("nombre")
    assert b.order == ("nombre", True)
    rows = con.execute(b.page_sql(900)).fetchall()
    assert rows[-1][1] is None
    b = b.next_order("nombre")
    assert b.order == ("nombre", False)
    assert con.execute(b.page_sql(0)).fetchone()[1] is not None
    assert b.next_order("nombre").order is None
    assert b.next_order("id").order == ("id", True)


def test_view_sql_is_the_same_query(con):
    b = browse(filters=(Filter("kwh", GT, "1400"),), order=("id", True)).with_search("cliente")
    shown = b.display_sql()
    assert shown.startswith('SELECT *\nFROM "memory"."main"."t"\nWHERE ')
    assert ids(con, shown) == ids(
        con, "SELECT id FROM t WHERE kwh > 1400 AND nombre LIKE 'Cliente%' ORDER BY id"
    )


def test_geometries_are_read_as_text(con):
    try:
        con.execute("CREATE TABLE g AS SELECT 1 AS id, 'POLYGON((0 0, 1 0, 1 1, 0 0))'::GEOMETRY AS geom")
    except duckdb.Error:
        pytest.skip("este DuckDB no tiene el tipo GEOMETRY sin spatial")
    columns = (ColumnInfo("id", "INTEGER", True), ColumnInfo("geom", "GEOMETRY", True))
    b = Browse("memory", "main", "g", columns)
    assert con.execute(b.page_sql(0)).fetchone() == (1, "POLYGON ((0 0, 1 0, 1 1, 0 0))")
    assert con.execute(b.row_sql(0)).fetchone()[1].startswith("POLYGON")


def test_search_without_text_columns_finds_nothing(con):
    b = Browse("memory", "main", "t", (ColumnInfo("id", "INTEGER", True),)).with_search("x")
    assert con.execute(b.count_sql()).fetchone()[0] == 0


def test_page_label():
    assert page_label(0, 100, 48312) == tr("Rows {} of {}").format("1–100", "48 312")
    assert page_label(100, 100, None) == tr("Rows {} of …").format("101–200")
    assert page_label(0, 0, 0) == tr("No rows")


def test_geometry_summary():
    assert geometry_summary("POLYGON ((0 0, 1 0, 1 1, 0 0))", "GEOMETRY('EPSG:4326')") == (
        "POLYGON",
        "EPSG:4326",
        4,
    )
    assert geometry_summary("POINT Z (1 2 3)", "GEOMETRY") == ("POINT", "", 1)
    assert geometry_summary("POINT EMPTY", "GEOMETRY")[2] == 0
    assert geometry_summary("MULTIPOINT ((1 2), (3 -4.5e2))", "GEOMETRY") == ("MULTIPOINT", "", 2)


def test_structure_of_a_table_and_of_a_view(con):
    con.execute("CREATE TABLE k (id INTEGER PRIMARY KEY, code VARCHAR UNIQUE, x DOUBLE)")
    con.execute("CREATE VIEW v AS SELECT id FROM k")
    rows = con.execute(structure_sql("memory", "main", "k")).fetchall()
    definition = [r for r in rows if r[0] == "definition"]
    assert len(definition) == 1 and definition[0][1].startswith("CREATE TABLE k")
    keys = {(r[1], tuple(r[3])) for r in rows if r[0] == "key"}
    assert keys == {("PRIMARY KEY", ("id",)), ("UNIQUE", ("code",))}
    view = con.execute(structure_sql("memory", "main", "v")).fetchall()
    assert [r[0] for r in view] == ["definition"] and "SELECT id FROM k" in view[0][1]
    con.execute("CREATE TEMP TABLE tmp (a INTEGER)")
    assert con.execute(structure_sql("temp", "main", "tmp")).fetchall()[0][1].startswith("CREATE")


def test_ties_are_broken_so_pages_never_repeat_or_skip_rows(con):
    b = browse(order=("kwh", False))
    con.execute("CREATE TABLE empates AS SELECT range AS id, range % 3 AS g FROM range(1000)")
    tied = Browse(
        "memory", "main", "empates", (ColumnInfo("id", "BIGINT", True), ColumnInfo("g", "BIGINT", True))
    )
    tied = tied.next_order("g")
    seen = [
        row[0] for offset in range(0, 1000, PAGE) for row in con.execute(tied.page_sql(offset)).fetchall()
    ]
    assert sorted(seen) == list(range(1000))
    assert "rowid" in b.page_sql(0)
    view = Browse("memory", "main", "v", COLUMNS, order=("kwh", True), has_rowid=False)
    assert view.page_sql(0).endswith('ORDER BY "kwh" ASC NULLS LAST, "id", "nombre" LIMIT 100 OFFSET 0')


def test_size_on_disk_of_a_saved_table(tmp_path):
    con = duckdb.connect()
    con.execute(f"ATTACH '{tmp_path / 'db.duckdb'}' AS db")
    con.execute('CREATE TABLE db.main."Raro t" AS SELECT range AS a FROM range(300000)')
    con.execute("CHECKPOINT db")
    assert con.execute(size_sql("db", "main", "Raro t")).fetchone()[0] >= 262144
    con.execute("CREATE TABLE memoria AS SELECT 1 AS a")
    assert not con.execute(size_sql("memory", "main", "memoria")).fetchone()[0]
