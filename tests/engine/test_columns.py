# SPDX-License-Identifier: GPL-2.0-or-later
"""Columnas de tablas y vistas contra DuckDB real (G6 · E1, GD-CAT-002, session-spec `ListColumns`)."""

from __future__ import annotations

import duckdb
import pytest

from geoduck.domain.errors import EngineError
from geoduck.domain.sql_text import quote_identifier, quote_string_literal, sql_name
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def run_sql(worker, sql):
    return worker.submit(lambda h, t: h.execute(sql)).future.result(TIMEOUT)


def root(worker):
    return worker.read_catalog().result(TIMEOUT).root


def test_columns_keep_their_order_exact_type_and_nullability(worker):
    run_sql(
        worker,
        'CREATE TABLE t (id INTEGER NOT NULL, "Mi ""col""" VARCHAR, g GEOMETRY, d DECIMAL(10,2), '
        "s STRUCT(a INTEGER), l INTEGER[])",
    )
    columns = worker.list_columns(root(worker), "main", "t").result(TIMEOUT)
    assert [(c.name, c.data_type, c.nullable) for c in columns] == [
        ("id", "INTEGER", False),
        ('Mi "col"', "VARCHAR", True),
        ("g", "GEOMETRY", True),
        ("d", "DECIMAL(10,2)", True),
        ("s", "STRUCT(a INTEGER)", True),
        ("l", "INTEGER[]", True),
    ]
    assert [c.is_geometry for c in columns] == [False, False, True, False, False, False]


def test_views_temporaries_and_attached_bases_in_other_schemas(worker, tmp_path):
    path = tmp_path / "otra base.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA ventas; CREATE TABLE ventas.pedidos (n BIGINT, fecha DATE)")
    con.close()
    run_sql(worker, f"ATTACH {quote_string_literal(str(path))} AS {quote_identifier('mi base')} (READ_ONLY)")
    run_sql(worker, "CREATE TEMP TABLE tmp (x DOUBLE)")
    run_sql(worker, "CREATE VIEW v AS SELECT 1 AS uno, 'a' AS letra")
    assert [c.name for c in worker.list_columns("mi base", "ventas", "pedidos").result(TIMEOUT)] == [
        "n",
        "fecha",
    ]
    assert [c.name for c in worker.list_columns("temp", "main", "tmp").result(TIMEOUT)] == ["x"]
    assert [
        (c.name, c.data_type) for c in worker.list_columns(root(worker), "main", "v").result(TIMEOUT)
    ] == [
        ("uno", "INTEGER"),
        ("letra", "VARCHAR"),
    ]


def test_a_missing_object_fails_without_breaking_the_session(worker):
    with pytest.raises(EngineError, match="ya no existe"):
        worker.list_columns(root(worker), "main", "no_existe").result(TIMEOUT)
    run_sql(worker, "CREATE TABLE ok (a INTEGER)")
    assert len(worker.list_columns(root(worker), "main", "ok").result(TIMEOUT)) == 1


def test_names_with_quotes_never_inject_sql(worker):
    run_sql(worker, "CREATE TABLE seguro (a INTEGER)")
    evil = "seguro' OR '1'='1"
    with pytest.raises(EngineError):
        worker.list_columns(root(worker), "main", evil).result(TIMEOUT)


def test_reserved_words_decide_when_a_name_is_quoted(worker):
    words = worker.reserved_words().result(TIMEOUT)
    assert {"select", "order"} <= words
    assert "fecha" not in words
    assert sql_name("fecha", words) == "fecha"
    assert sql_name("select", words) == '"select"'
    assert sql_name("Mi col", words) == '"Mi col"'
    # el nombre insertado se puede usar tal cual en una consulta
    run_sql(worker, 'CREATE TABLE r ("select" INTEGER, fecha INTEGER, "Mi ""col""" INTEGER)')
    cols = worker.list_columns(root(worker), "main", "r").result(TIMEOUT)
    names = ", ".join(sql_name(c.name, words) for c in cols)
    assert run_sql(worker, f"SELECT {names} FROM r").columns == ("select", "fecha", 'Mi "col"')
