# SPDX-License-Identifier: GPL-2.0-or-later
"""Cuadernos y «Ejecutar todo» (G7 · E1, AT-NB-001..004) con dobles: sin DuckDB ni Qt."""

from __future__ import annotations

import pytest

from geoduck.app.notebook_runner import NotebookRunner
from geoduck.domain.catalog import AccessMode, AttachedDatabase, CatalogSnapshot
from geoduck.domain.errors import InvalidArgumentError
from geoduck.domain.notebook import Cell, Notebook
from geoduck.domain.sql import RunScope, ScriptRun, SqlStatement, StatementResult, StatementStatus
from tests.unit.test_coordinator import INFO, FakeEngine, QueueDispatcher

ROOT = AttachedDatabase("memory", None, AccessMode.READ_WRITE, "memory")
DB = AttachedDatabase("db", "/datos/db.duckdb", AccessMode.READ_WRITE, "duckdb")
SALES = AttachedDatabase("mis ventas", "/datos/v.duckdb", AccessMode.READ_ONLY, "duckdb")
CATALOG = CatalogSnapshot((ROOT, DB, SALES), root="memory", default="memory")
WITHOUT_SALES = CatalogSnapshot((ROOT, DB), root="memory", default="memory")


# -- modelo -----------------------------------------------------------------------------------------------


def test_a_notebook_always_has_a_cell_and_keeps_the_order():
    nb = Notebook("Consumidores")
    assert len(nb.cells) == 1
    a = nb.cells[0]
    b = nb.insert(1, "db", "SELECT 2")
    c = nb.insert(0, None, "SELECT 0")  # encima de la primera
    assert [x.id for x in nb.cells] == [c.id, a.id, b.id]
    nb.move(c.id, 2)  # arrastrar al final: texto y base van con ella
    assert [x.id for x in nb.cells] == [a.id, b.id, c.id] and c.sql == "SELECT 0"
    d = nb.duplicate(b.id)
    assert nb.index_of(d.id) == nb.index_of(b.id) + 1 and (d.sql, d.database) == ("SELECT 2", "db")
    for cell in list(nb.cells):
        nb.remove(cell.id)
    assert len(nb.cells) == 1 and nb.cells[0].sql == ""
    with pytest.raises(InvalidArgumentError):
        nb.index_of(-1)


def test_a_detached_base_is_reported_by_the_cell():
    assert Cell("SELECT 1", "mis ventas").database_problem(CATALOG) is None
    problem = Cell("SELECT 1", "mis ventas").database_problem(WITHOUT_SALES)
    assert problem is not None and "mis ventas" in problem
    assert Cell("SELECT 1", None).database_problem(None) is None  # sin base propia: la de la sesión


def test_a_use_written_in_the_cell_updates_its_selector():
    cell = Cell('USE "mis ventas"; SELECT 1', "db")
    cell.follow_use("MIS VENTAS", CATALOG)  # DuckDB compara sin mayúsculas: grafía del catálogo
    assert cell.database == "mis ventas"
    cell.follow_use("mis ventas", CATALOG)
    assert cell.database == "mis ventas"


# -- «Ejecutar todo» --------------------------------------------------------------------------------------


@pytest.fixture
def env():
    from geoduck.app.coordinator import SessionCoordinator

    engines: list[FakeEngine] = []

    def factory():
        engines.append(FakeEngine())
        return engines[-1]

    dispatcher = QueueDispatcher()
    coordinator = SessionCoordinator(factory, dispatcher)
    coordinator.start_memory_session()
    engines[0].started.set_result(INFO)
    dispatcher.drain()
    coordinator.refresh_catalog()
    engines[0].catalog_reads[-1].set_result(CATALOG)
    dispatcher.drain()
    runner = NotebookRunner(coordinator, dispatcher)
    seen, done = [], []
    runner.on_cell = seen.append
    runner.on_done = done.append
    return coordinator, dispatcher, engines[0], runner, seen, done


def finish(engine, dispatcher, status=StatementStatus.OK, database=None):
    """El worker termina el último script: una sentencia con `status`; base en uso `database`."""
    script = engine.scripts[-1]
    st = SqlStatement(0, "SELECT", script["text"], 0, len(script["text"]))
    run = ScriptRun(
        script["run_id"],
        RunScope.ALL,
        (StatementResult(st, status),),
        current_database=database or script.get("database") or "memory",
    )
    script["future"].set_result(run)
    dispatcher.drain()


def test_run_all_goes_in_order_with_the_base_of_each_cell(env):
    _coordinator, dispatcher, engine, runner, seen, done = env
    cells = [Cell("SELECT 1", "db"), Cell("   ", "db"), Cell("SELECT 2", "mis ventas"), Cell("SELECT 3")]
    assert runner.run(cells)
    for _ in range(3):
        finish(engine, dispatcher)
        if engine.catalog_reads[-1].done() is False:  # el cambio de base relee el catálogo antes de seguir
            engine.catalog_reads[-1].set_result(CATALOG)
            dispatcher.drain()
    assert [(s["text"], s.get("database"), s["scope"]) for s in engine.scripts] == [
        ("SELECT 1", "db", RunScope.ALL),
        ("SELECT 2", "mis ventas", RunScope.ALL),
        ("SELECT 3", None, RunScope.ALL),  # sin base propia: la de la sesión; la vacía se saltó
    ]
    assert [o.ok for o in seen] == [True, True, True] and len(done) == 1 and not runner.running


def test_run_all_stops_at_the_first_failure(env):
    _coordinator, dispatcher, engine, runner, _seen, done = env
    runner.run([Cell("SELECT 1"), Cell("SELECT nada"), Cell("SELECT 3")])
    finish(engine, dispatcher)
    finish(engine, dispatcher, StatementStatus.FAILED)
    assert len(engine.scripts) == 2  # la tercera no se ejecuta
    assert [o.ok for o in done[0]] == [True, False]


def test_a_cell_with_a_detached_base_stops_without_running(env):
    coordinator, dispatcher, engine, runner, seen, done = env
    coordinator._catalog = WITHOUT_SALES  # p. ej. «mis ventas» se desadjuntó desde el explorador
    runner.run([Cell("SELECT 1", "mis ventas"), Cell("SELECT 2")])
    dispatcher.drain()
    assert engine.scripts == [] and seen[0].error and "mis ventas" in seen[0].error
    assert len(done) == 1


def test_the_catalog_is_read_again_when_the_base_in_use_changes(env):
    _coordinator, dispatcher, engine, runner, _seen, _done = env
    reads = len(engine.catalog_reads)
    runner.run([Cell("SELECT 1", "db")])
    finish(engine, dispatcher, database="db")
    assert len(engine.catalog_reads) == reads + 1  # «en uso» cambia en el explorador


def test_a_use_in_the_cell_is_reflected_in_its_selector(env):
    _coordinator, dispatcher, engine, runner, seen, _done = env
    cell = Cell('USE "mis ventas"; SELECT 1', "db")
    runner.run([cell])
    finish(engine, dispatcher, database="mis ventas")
    assert cell.database == "mis ventas" and seen[0].ok


def test_only_one_batch_at_a_time(env):
    _coordinator, _dispatcher, _engine, runner, _seen, _done = env
    assert runner.run([Cell("SELECT 1")])
    assert not runner.run([Cell("SELECT 2")])
