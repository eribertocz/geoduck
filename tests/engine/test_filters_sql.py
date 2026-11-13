# SPDX-License-Identifier: GPL-2.0-or-later
"""Los filtros del resultado (#144) contra DuckDB real (1.5 y 2.x): cada forma da las filas esperadas."""

from __future__ import annotations

import duckdb
import pytest

from geoduck.domain.browse import Browse
from geoduck.domain.catalog import ColumnInfo
from geoduck.domain.filters import EXCLUDE, FILTER, cell_filters

COLUMNS = (
    ColumnInfo("id", "INTEGER", None),
    ColumnInfo("zona", "VARCHAR", None),
    ColumnInfo("kwh", "DOUBLE", None),
    ColumnInfo("fecha", "DATE", None),
)


@pytest.fixture
def con():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t AS SELECT * FROM (VALUES"
        " (1, 'Sur', 71.2, DATE '2024-01-05'), (2, 'Norte', 50.8, DATE '2024-03-01'),"
        " (3, 'Sur', 93.5, NULL), (4, NULL, 120.0, DATE '2024-12-31'), (5, '', 10.0, DATE '2023-07-01'),"
        " (6, 'cliente 6', NULL, DATE '2024-06-30')) v(id, zona, kwh, fecha)"
    )
    yield con
    con.close()


def ids(con, browse):
    return sorted(row[0] for row in con.execute(browse.page_sql(0)).fetchall())


@pytest.mark.parametrize(
    ("column", "text", "expected"),
    [
        ("zona", "sur", [1, 3]),
        ("zona", "=Sur", [1, 3]),
        ("kwh", ">50", [1, 2, 3, 4]),
        ("kwh", "> 50 AND < 100", [1, 2, 3]),
        ("kwh", "10..71.2", [1, 2, 5]),
        ("fecha", "2024-01-01..2024-06-30", [1, 2, 6]),
        ("fecha", ">2024-06-01", [4, 6]),
        ("zona", "vacío", [4, 5]),
        ("zona", "not empty", [1, 2, 3, 6]),
        ("kwh", "empty", [6]),
        ("zona", "/^s/i", [1, 3]),
        ("zona", "/^cliente [0-9]+$/", [6]),
        ("kwh", "IN (10, 120)", [4, 5]),
        ("zona", "LIKE 'N%'", [2]),
        ("kwh", "BETWEEN 50 AND 80 OR > 100", [1, 2, 4]),
        ("fecha", "IS NULL", [3]),
    ],
)
def test_each_box_form_runs_in_duckdb(con, column, text, expected):
    browse = Browse("memory", "main", "t", COLUMNS).with_box(column, text)
    assert ids(con, browse) == expected
    assert con.execute(browse.count_sql()).fetchone()[0] == len(expected)


def test_right_click_and_the_where_bar_run_in_duckdb(con):
    columns = {c.name: c for c in COLUMNS}
    boxes, _ = cell_filters([(columns["zona"], "Sur"), (columns["zona"], None)], FILTER)
    browse = Browse("memory", "main", "t", COLUMNS).with_box("zona", boxes["zona"])
    assert ids(con, browse) == [1, 3, 4]
    boxes, _ = cell_filters([(columns["zona"], "Sur")], EXCLUDE)
    assert ids(con, Browse("memory", "main", "t", COLUMNS).with_box("zona", boxes["zona"])) == [2, 4, 5, 6]
    _, extra = cell_filters([(columns["zona"], "Sur"), (columns["kwh"], 71.2)], EXCLUDE)
    assert ids(con, Browse("memory", "main", "t", COLUMNS).with_extra(extra)) == [2, 3, 4, 5, 6]
    browse = Browse("memory", "main", "t", COLUMNS).with_where("kwh > 60 AND zona <> 'Sur'")
    assert ids(con, browse) == []  # la 4 tiene zona NULL: no pasa «<>»
    assert con.execute(browse.check_sql("kwh > 1")).fetchall() == []


def test_a_query_result_filters_sorts_and_summarizes_in_duckdb(con):
    browse = Browse("", "", "", COLUMNS, subquery="SELECT * FROM t WHERE id < 6\n", has_rowid=False)
    browse = browse.with_box("kwh", ">= 50").next_order("kwh")
    assert [r[0] for r in con.execute(browse.page_sql(0)).fetchall()] == [2, 1, 3, 4]
    total, mean, low, high, nulls = con.execute(browse.summary_sql(COLUMNS[2])).fetchone()
    assert (round(float(total), 1), float(low), float(high), nulls) == (335.5, 50.8, 120.0, 0)
    assert float(mean) == pytest.approx(83.875)
    assert con.execute(browse.summary_sql(COLUMNS[1])).fetchone()[2:] == ("Norte", "Sur", 1)
    assert con.execute(browse.values_sql(("zona",), 2)).fetchall() == [("Norte",), ("Sur",)]
    assert con.execute(browse.total_sql()).fetchone()[0] == 5
