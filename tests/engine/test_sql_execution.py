# SPDX-License-Identifier: GPL-2.0-or-later
"""Ejecución de scripts SQL del usuario contra DuckDB real (G2; GD-SQL-001, 002, 004, 005, 006).

Matriz 1.5.0 / 1.5.x / 2.x. Ver `docs/evidence/g2/README.md` (F-34..F-39).
"""

from __future__ import annotations

import threading
import time

import duckdb
import pytest

from geoduck.domain.errors import ErrorCode, InvalidArgumentError
from geoduck.domain.sql import PREVIEW_LIMITS, OutputKind, RunScope, StatementStatus
from geoduck.domain.transaction import TransactionState as T
from geoduck.engine.compat import EngineCapabilities
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30
OK, FAILED, CANCELLED, SKIPPED = (
    StatementStatus.OK,
    StatementStatus.FAILED,
    StatementStatus.CANCELLED,
    StatementStatus.SKIPPED,
)


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def run(worker, text, scope=RunScope.ALL, **kw):
    kw.setdefault("preview_limit", 200)
    return worker.run_script(run_id=1, text=text, scope=scope, **kw).future.result(TIMEOUT)


def query(worker, sql):
    return worker.submit(lambda h, t: h.execute(sql).rows).future.result(TIMEOUT)


# -- AT-SQL-002: script mixto, en orden, un resultado por lectura ------------------------------------


def test_create_and_two_selects_in_order_with_two_results(worker):
    """Gate de G2: «2 SELECT y CREATE correctos» (sql-editor-spec §8)."""
    script = (
        "CREATE TABLE productos AS SELECT 1 AS id, 'Medidor' AS nombre;\n"
        "SELECT * FROM productos;\n"
        "SELECT COUNT(*) AS n FROM productos;"
    )
    out = run(worker, script)
    assert [r.status for r in out.results] == [OK, OK, OK]
    assert [r.statement.type for r in out.results] == ["CREATE", "SELECT", "SELECT"]
    assert [r.output for r in out.results] == [OutputKind.STATUS, OutputKind.TABULAR, OutputKind.TABULAR]
    assert out.results[1].preview.rows == ((1, "Medidor"),) and out.results[1].preview.columns == (
        "id",
        "nombre",
    )
    assert out.results[2].preview.rows == ((1,),)
    for r in out.results:  # cada rango apunta a su propio texto en el editor
        assert script[r.statement.start : r.statement.end].strip().rstrip(";").strip() in r.statement.text


def test_tricky_text_is_split_by_the_real_parser(worker):
    script = (
        "-- comentario ; con punto y coma\n"
        "SELECT 'a;b' AS x; /* bloque ; */ SELECT 'x'';y' AS y;\n"
        "SELECT $$dólar ; ñ$$ AS z;"
    )
    out = run(worker, script)
    assert [r.preview.rows[0][0] for r in out.results] == ["a;b", "x';y", "dólar ; ñ"]


# -- errores: se detiene, informa la posición y comprueba la transacción ----------------------------


def test_first_error_stops_the_rest(worker):
    out = run(worker, "CREATE TABLE a(x INT);\nSELECT * FROM nada;\nCREATE TABLE b(x INT);")
    assert [r.status for r in out.results] == [OK, FAILED, SKIPPED]
    failed = out.results[1]
    assert failed.error_code is ErrorCode.ENGINE_ERROR and "nada" in failed.message
    assert query(worker, "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'b'") == ((0,),)


def test_error_position_points_into_the_editor(worker):
    script = "SELECT 1;\nSELECT * FROM nada;"
    failed = run(worker, script).results[1]
    assert failed.error_offset is not None
    assert script[failed.error_offset :].startswith("nada")


def test_syntax_error_executes_nothing(worker):
    """F-38: un error de sintaxis en cualquier sentencia impide ejecutar todo el script."""
    script = "CREATE TABLE a(x INT);\n\n  SELEC 2;"
    out = run(worker, script)
    assert out.results == () and out.parse_error.startswith("Parser Error")
    assert script[out.parse_error_offset :].startswith("SELEC")
    assert query(worker, "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'a'") == ((0,),)


# -- transacciones: estado después de cada sentencia (decisión del 2026-11-01) ----------------------


def test_transaction_state_is_checked_after_every_statement(worker):
    out = run(worker, "BEGIN; CREATE TABLE a(x INT); INSERT INTO a VALUES (1); COMMIT; SELECT 1;")
    assert [r.transaction for r in out.results] == [T.ACTIVE, T.ACTIVE, T.ACTIVE, T.NONE, T.NONE]
    assert out.last_transaction is T.NONE


def test_failure_inside_a_transaction_reports_its_state(worker):
    run(worker, "CREATE TABLE u(a INT PRIMARY KEY); INSERT INTO u VALUES (1);")
    out = run(worker, "BEGIN; INSERT INTO u VALUES (1); SELECT 1;")
    assert [r.status for r in out.results] == [OK, FAILED, SKIPPED]
    assert out.results[1].transaction is T.ABORTED  # restricción: aborta en todas las versiones (F-33)
    following = run(worker, "SELECT 1;").results[0]
    assert following.status is FAILED and following.error_code is ErrorCode.TRANSACTION_ABORTED
    run(worker, "ROLLBACK;")


# -- AT-SQL-004: actual, selección o todo ------------------------------------------------------------


def test_current_runs_only_the_statement_under_the_cursor(worker):
    script = "CREATE TABLE a(x INT);\nINSERT INTO a VALUES (1);\nSELECT count(*) FROM a;"
    run(worker, script.split("\n", maxsplit=1)[0])
    cursor = script.index("INSERT") + 3
    out = run(worker, script, RunScope.CURRENT, cursor=cursor)
    assert [r.statement.type for r in out.results] == ["INSERT"]
    assert query(worker, "SELECT count(*) FROM a") == ((1,),)  # ni el CREATE ni el SELECT se ejecutaron


def test_selection_runs_only_the_selected_text_with_editor_positions(worker):
    script = "CREATE TABLE a(x INT);\nINSERT INTO a VALUES (1);\nINSERT INTO a VALUES (2);"
    run(worker, "CREATE TABLE a(x INT);")
    start = script.index("INSERT INTO a VALUES (2)")
    out = run(worker, script[start:], RunScope.SELECTION, base=start)
    assert len(out.results) == 1 and out.results[0].statement.start == start
    assert query(worker, "SELECT x FROM a") == ((2,),)


# -- AT-SQL-005: vista previa acotada, sin fetchall --------------------------------------------------


@pytest.mark.parametrize("limit", list(PREVIEW_LIMITS))
def test_preview_is_bounded(worker, limit):
    result = run(worker, "SELECT range FROM range(1000000);", preview_limit=limit).results[0]
    assert len(result.preview.rows) == limit and result.preview.truncated and result.preview.limit == limit


def test_preview_limit_must_be_allowed(worker):
    with pytest.raises(InvalidArgumentError):
        run(worker, "SELECT 1;", preview_limit=10_000)


def test_no_reader_or_result_is_left_open(worker):
    run(worker, "SELECT range FROM range(1000000);")
    assert worker.submit(lambda h, t: h.reader_open).future.result(TIMEOUT) is False
    assert query(worker, "SELECT 42") == ((42,),)


# -- AT-SQL-006 y AT-SQL-001: salidas y repetición --------------------------------------------------


def test_outputs_and_replayability_follow_the_parser_type(worker):
    script = (
        "CREATE TABLE t(a INT);\n"
        "INSERT INTO t VALUES (1), (2);\n"
        "WITH n AS (SELECT 3 AS a) INSERT INTO t SELECT a FROM n RETURNING a;\n"
        "UPDATE t SET a = a + 10 WHERE a = 1;\n"
        "EXPLAIN SELECT * FROM t;\n"
        "SELECT * FROM t ORDER BY a;\n"
        "SET threads = 2;\n"
        "ATTACH ':memory:' AS m; DETACH m;"
    )
    out = run(worker, script)
    by_type = [
        (r.statement.type, r.output, r.statement.replayable, r.statement.may_change_state)
        for r in out.results
    ]
    assert by_type == [
        ("CREATE", OutputKind.STATUS, False, True),
        ("INSERT", OutputKind.STATUS, False, True),
        ("INSERT", OutputKind.MUTATION_ROWS, False, True),  # WITH … INSERT … RETURNING: es DML (F-34)
        ("UPDATE", OutputKind.STATUS, False, True),
        ("EXPLAIN", OutputKind.PLAN, False, False),
        ("SELECT", OutputKind.TABULAR, True, False),
        ("SET", OutputKind.STATUS, False, True),
        ("ATTACH", OutputKind.STATUS, False, True),
        ("DETACH", OutputKind.STATUS, False, True),
    ]
    assert out.results[1].message == "2 filas afectadas"
    assert out.results[2].preview.rows == ((3,),)


def test_returning_is_executed_exactly_once(worker):
    """AT-SQL-006: un RETURNING se ejecuta una sola vez aunque su vista previa se recorte."""
    run(worker, "CREATE TABLE t(a INT);")
    result = run(
        worker, "INSERT INTO t SELECT range FROM range(5000) RETURNING a;", preview_limit=50
    ).results[0]
    assert result.preview.truncated and len(result.preview.rows) == 50
    assert query(worker, "SELECT count(*) FROM t") == ((5000,),)  # todas, una vez


def test_pragma_is_located_even_when_rewritten(worker):
    """F-36: en 1.5.x PRAGMA se reescribe como SELECT y su texto no está en el script."""
    script = "SELECT 1;\nPRAGMA version;\nSELECT 2;"
    out = run(worker, script)
    assert [r.status for r in out.results] == [OK, OK, OK]
    pragma = out.results[1].statement
    assert "PRAGMA version" in script[pragma.start : pragma.end]
    assert not pragma.replayable or duckdb.__version__.startswith("1.5")  # en 1.5 llega como SELECT


# -- cancelación ---------------------------------------------------------------------------------


@pytest.mark.skipif(
    not EngineCapabilities.for_version(duckdb.__version__).interrupt_verified,
    reason="interrupt() no verificado en esta versión (ADR-0007)",
)
def test_cancel_marks_current_cancelled_and_skips_the_rest(worker):
    seen = []
    long_sql = "SELECT count(*) FROM range(5000000000) t(a) WHERE a % 7 = 3"
    handle = worker.run_script(
        run_id=7,
        text=f"SELECT 1; {long_sql}; CREATE TABLE nunca(x INT);",
        scope=RunScope.ALL,
        preview_limit=200,
        on_statement=seen.append,
    )
    deadline = time.monotonic() + 5
    while len(seen) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.3)
    worker.cancel(handle.op_id)
    out = handle.future.result(TIMEOUT)
    assert [r.status for r in out.results] == [OK, CANCELLED, SKIPPED]
    assert out.results[1].error_code is ErrorCode.CANCELLED and out.results[1].transaction is T.NONE
    assert [r.status for r in seen] == [OK, CANCELLED, SKIPPED]  # eventos por sentencia, en orden
    assert not worker.invalidation().done()
    assert query(worker, "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'nunca'") == ((0,),)


def test_concurrent_scripts_are_serialized(worker):
    run(worker, "CREATE TABLE c(x INT);")
    errors = []

    def client(n):
        try:
            for i in range(20):
                out = run(worker, f"INSERT INTO c VALUES ({n * 100 + i}); SELECT count(*) FROM c;")
                assert [r.status for r in out.results] == [OK, OK]
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=client, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert errors == [] and query(worker, "SELECT count(*) FROM c") == ((80,),)


def test_result_titles_match_in_every_duckdb_version(worker):
    """Los límites del texto de cada sentencia cambian entre 1.5 y 2.0 (F-35); el nombre no."""
    from geoduck.domain.sql import result_title

    script = (
        "CREATE TABLE productos AS SELECT 1 AS id;\n"
        "-- Catálogo completo\n"
        "SELECT * FROM productos;\n"
        "SELECT COUNT(*) AS n FROM productos;\n"
        "\n-- comentario suelto\n\n"
        "SELECT 42 AS respuesta;"
    )
    out = run(worker, script)
    assert [result_title(script, r.statement) for r in out.results] == [
        "Crear productos",
        "Catálogo completo",
        "Total productos",
        "Respuesta",
    ]


def test_guard_vetoes_the_whole_script_before_running_anything(worker):
    """qgis-bridge-spec §5.5: un DETACH real vetado no deja nada a medias (tampoco lo anterior)."""
    from geoduck.domain.errors import SessionStateError
    from geoduck.domain.sql import detach_target

    def guard(st):
        return "vetado" if detach_target(st) == "d" else None

    run(worker, "ATTACH ':memory:' AS d")
    with pytest.raises(SessionStateError, match="vetado"):
        run(worker, "CREATE TABLE antes (x INTEGER); DETACH d", guard=guard)
    assert query(worker, "SELECT count(*) FROM duckdb_tables() WHERE table_name = 'antes'") == ((0,),)
    ok = run(worker, "SELECT 'DETACH d' AS t; -- DETACH d\nCREATE TABLE despues (x INTEGER)", guard=guard)
    assert [r.status for r in ok.results] == [StatementStatus.OK, StatementStatus.OK]


def test_axis_order_is_reported_only_with_spatial_and_geometry(worker):
    """AX-2 (spatial-spec §4): sin `spatial` el ajuste no existe y no se informa; GeoDuck no lo fija."""
    run_ = run(worker, "SELECT 'POINT(1 2)'::GEOMETRY AS g; SELECT 1 AS n")
    assert all("geometry_always_xy" not in r.message for r in run_.results)
    state = worker.spatial_state().result(TIMEOUT)
    assert not state.loaded and state.always_xy is None


# -- EXPLAIN escrito en la celda (AT-SQL-010; G7 retira «Explicar») ----------------------------------------


@pytest.mark.parametrize(
    "sql",
    ["SELECT * FROM ex", "INSERT INTO ex VALUES (2)", "UPDATE ex SET x = 9", "DELETE FROM ex"],
)
def test_explain_shows_the_plan_and_never_runs_the_statement(worker, sql):
    worker.submit(lambda h, t: h.execute("CREATE OR REPLACE TABLE ex AS SELECT 1 AS x")).future.result(30)
    run = worker.run_script(run_id=1, text="EXPLAIN " + sql, scope=RunScope.ALL).future.result(30)
    (result,) = run.results
    assert result.status is StatementStatus.OK and result.output is OutputKind.PLAN
    rows = worker.submit(lambda h, t: h.execute("SELECT * FROM ex").rows).future.result(30)
    assert rows == ((1,),)  # la tabla no cambió
