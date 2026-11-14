# SPDX-License-Identifier: GPL-2.0-or-later
"""Base de cada celda contra DuckDB real (G7 · E1, AT-NB-003, AT-NB-004; sql-editor-spec §7)."""

from __future__ import annotations

import pytest

from geoduck.domain.errors import InvalidArgumentError
from geoduck.domain.sql import OutputKind, RunScope, StatementStatus
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30


@pytest.fixture
def worker(tmp_path):
    w = SessionWorker()
    w.start().result(TIMEOUT)
    for name in ("db", "mis ventas"):
        path = tmp_path / f"{name}.duckdb"
        run_sql(w, f"ATTACH {quote_string_literal(str(path))} AS {quote_identifier(name)}")
        run_sql(
            w, f"CREATE TABLE {quote_identifier(name)}.t AS SELECT {quote_string_literal(name)} AS origen"
        )
    run_sql(w, "CREATE TABLE memory.tabla_memoria AS SELECT range AS n FROM range(1, 5)")
    yield w
    w.close().result(TIMEOUT)


def run_sql(worker, sql):
    return worker.submit(lambda h, t: h.execute(sql)).future.result(TIMEOUT)


def cell(worker, sql, database, **kw):
    return worker.run_script(run_id=1, text=sql, scope=RunScope.ALL, database=database, **kw).future.result(
        TIMEOUT
    )


def value(run):
    return run.results[-1].preview.rows[0][0]


def test_each_cell_reads_its_own_base_in_any_order(worker):
    assert value(cell(worker, "SELECT origen FROM t", "db")) == "db"
    assert value(cell(worker, "SELECT origen FROM t", "mis ventas")) == "mis ventas"
    run = cell(worker, "SELECT origen FROM t", "db")
    assert value(run) == "db" and run.current_database == "db"  # la base en uso, la de la última celda


def test_a_cell_reads_other_bases_by_their_name_like_the_owner_example(worker):
    # celda en `memory` que lee `db`, y celda en `db` que lee `memory`
    assert value(cell(worker, "SELECT origen FROM db.main.t", "memory")) == "db"
    run = cell(worker, "SELECT * FROM memory.tabla_memoria", "db")
    assert [r[0] for r in run.results[-1].preview.rows] == [1, 2, 3, 4]


def test_several_statements_run_in_order_and_the_last_result_is_the_one_shown(worker):
    run = cell(worker, "CREATE TABLE memory.x AS SELECT 7 AS v; SELECT v FROM memory.x", "db")
    assert [r.status for r in run.results] == [StatementStatus.OK, StatementStatus.OK]
    assert run.results[-1].output is OutputKind.TABULAR and value(run) == 7


def test_a_use_written_in_the_cell_wins(worker):
    run = cell(worker, 'USE "mis ventas"; SELECT origen FROM t', "db")
    assert value(run) == "mis ventas" and run.current_database == "mis ventas"


def test_temporaries_are_seen_from_any_base(worker):
    run_sql(worker, "CREATE TEMP TABLE tmp AS SELECT 1 AS y")
    assert value(cell(worker, "SELECT y FROM tmp", "db")) == 1


def test_a_detached_base_runs_nothing(worker):
    run_sql(worker, 'DETACH "mis ventas"')
    with pytest.raises(InvalidArgumentError, match="ya no está adjunta"):
        cell(worker, "CREATE TABLE memory.nunca AS SELECT 1", "mis ventas")
    rows = run_sql(worker, "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'nunca'").rows
    assert rows == ((0,),)


def test_explain_runs_in_the_base_of_the_cell(worker):
    run = cell(worker, "EXPLAIN SELECT origen FROM t", "db")
    assert run.results[0].output is OutputKind.PLAN and run.current_database == "db"


def test_a_transaction_can_write_only_to_one_base(worker):
    cell(worker, "BEGIN; INSERT INTO t VALUES ('uno')", "db")
    run = cell(worker, "INSERT INTO t VALUES ('dos')", "mis ventas")
    assert run.results[-1].status is StatementStatus.FAILED  # error de DuckDB, tal cual
    assert "transaction" in run.results[-1].message.lower()


# -- «Cargar» del resultado de una celda en la base donde se ejecutó -------------------------------------


def current(worker):
    return run_sql(worker, "SELECT current_database()").rows[0][0]


def test_each_result_remembers_the_base_where_it_ran(worker):
    run = cell(worker, "SELECT origen FROM t; USE memory; SELECT count(*) FROM tabla_memoria", "db")
    assert [r.database for r in run.results] == ["db", None, "memory"]  # el USE no tiene vista previa


def test_operations_run_in_the_base_of_the_result_and_restore_the_base_in_use(worker):
    cell(worker, "SELECT 1", "mis ventas")
    assert current(worker) == "mis ventas"
    plan = worker.prepare_load("SELECT origen FROM t", database="db").result(TIMEOUT)
    assert [f.name for f in plan.fields] == ["origen"]
    batches = worker.read_table("SELECT origen FROM t", database="db").future.result(TIMEOUT)
    assert batches[0].to_pylist() == [{"origen": "db"}]
    assert worker.query("SELECT origen FROM t", database="db").future.result(TIMEOUT).rows == (("db",),)
    assert current(worker) == "mis ventas"  # la base en uso no cambió
    assert worker.query("SELECT origen FROM t").future.result(TIMEOUT).rows == (("mis ventas",),)


def test_an_operation_on_a_detached_base_fails_and_keeps_the_base_in_use(worker):
    with pytest.raises(InvalidArgumentError, match="ya no está adjunta"):
        worker.query("SELECT 1", database="no_existe").future.result(TIMEOUT)
    assert current(worker) == "memory"


def test_the_base_in_use_comes_back_even_when_the_read_fails(worker):
    cell(worker, "SELECT 1", "mis ventas")
    with pytest.raises(Exception, match="no_hay"):
        worker.query("SELECT * FROM no_hay", database="db").future.result(TIMEOUT)
    assert current(worker) == "mis ventas"
