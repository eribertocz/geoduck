# SPDX-License-Identifier: GPL-2.0-or-later
"""Seguimiento transaccional, COMMIT, ROLLBACK y recuperación segura contra DuckDB real (G1 paso 6,
GD-SES-005, AT-SES-005; ADR-0007 puntos 5 y 6). Matriz 1.5.0 / 1.5.x / 2.x.

En G1 GeoDuck no ejecuta SQL del usuario; las pruebas abren transacciones con SQL directo sobre el worker,
como hará el editor de G2.
"""

from __future__ import annotations

import time

import duckdb
import pytest

from geoduck.domain.errors import ErrorCode, GeoDuckError, OperationCancelledError, TransactionError
from geoduck.domain.transaction import TransactionState as T
from geoduck.engine.compat import EngineCapabilities
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30
LONG_QUERY = "SELECT count(*) FROM range(5000000000) t(a) WHERE a % 7 = 3"
needs_verified_interrupt = pytest.mark.skipif(
    not EngineCapabilities.for_version(duckdb.__version__).interrupt_verified,
    reason=f"interrupt() no verificado para DuckDB {duckdb.__version__} (ADR-0007)",
)


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def run(worker, sql):
    return worker.submit(lambda h, t: h.execute(sql)).future.result(TIMEOUT)


def state(worker):
    return worker.transaction_state().result(TIMEOUT)


def count(worker, table):
    return run(worker, f"SELECT count(*) FROM {table}").rows[0][0]


def tables(worker):
    return {r[0] for r in run(worker, "SELECT table_name FROM duckdb_tables()").rows}


def abort(worker):
    """Deja la transacción abortada en todas las versiones: interrupción dentro de ella (F-32)."""
    long_query = worker.submit(lambda h, t: h.execute(LONG_QUERY))
    deadline = time.monotonic() + 5
    while not long_query.future.running() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.3)
    worker.cancel(long_query.op_id)
    with pytest.raises(OperationCancelledError) as info:
        long_query.future.result(TIMEOUT)
    return info.value


# -- seguimiento ----------------------------------------------------------------------------------


def test_probe_follows_the_real_state_without_changing_it(worker):
    assert state(worker) is T.NONE
    run(worker, "BEGIN")
    assert state(worker) is T.ACTIVE
    run(worker, "CREATE TABLE x AS SELECT 1 AS a")
    assert state(worker) is T.ACTIVE  # comprobar no aborta ni cierra la transacción (F-30)
    run(worker, "COMMIT")
    assert state(worker) is T.NONE and "x" in tables(worker)


@needs_verified_interrupt
def test_cancel_inside_a_transaction_is_reported_as_aborted_not_invalidated(worker):
    """ADR-0007 puntos 5 y 6. Antes, la verificación con SELECT 1 fallaba con la transacción abortada y la
    sesión se invalidaba sin motivo."""
    run(worker, "BEGIN")
    run(worker, "CREATE TABLE x AS SELECT 1 AS a")
    cancelled = abort(worker)
    assert cancelled.transaction is T.ABORTED
    assert not worker.invalidation().done()  # la conexión responde: no hay invalidación
    assert state(worker) is T.ABORTED


def test_error_carries_the_transaction_state(worker):
    run(worker, "BEGIN")
    with pytest.raises(GeoDuckError) as info:
        run(worker, "SELECT * FROM no_existe")
    # 2.0 aborta la transacción con un error de catálogo; 1.5.x no (F-33)
    expected = T.ABORTED if duckdb.__version__.startswith("2.") else T.ACTIVE
    assert info.value.transaction is expected


@needs_verified_interrupt
def test_statements_in_an_aborted_transaction_are_transaction_aborted(worker):
    run(worker, "BEGIN")
    abort(worker)
    with pytest.raises(GeoDuckError) as info:
        run(worker, "SELECT 1")
    assert info.value.code is ErrorCode.TRANSACTION_ABORTED


# -- COMMIT ---------------------------------------------------------------------------------------


def test_commit_persists_and_returns_to_autocommit(worker):
    run(worker, "BEGIN")
    run(worker, "CREATE TABLE x AS SELECT range AS a FROM range(5)")
    assert worker.commit().result(TIMEOUT) is T.NONE
    assert count(worker, "x") == 5 and state(worker) is T.NONE


def test_commit_without_transaction_is_rejected(worker):
    with pytest.raises(TransactionError) as info:
        worker.commit().result(TIMEOUT)
    assert info.value.code is ErrorCode.INVALID_ARGUMENT


@needs_verified_interrupt
def test_commit_of_an_aborted_transaction_is_never_sent(worker):
    """F-07: DuckDB respondería OK al COMMIT y revertiría sin avisar. GeoDuck lo rechaza antes."""
    run(worker, "BEGIN")
    run(worker, "CREATE TABLE x AS SELECT 1 AS a")
    abort(worker)
    with pytest.raises(TransactionError) as info:
        worker.commit().result(TIMEOUT)
    assert info.value.code is ErrorCode.TRANSACTION_ABORTED
    assert state(worker) is T.ABORTED  # sigue abortada: el usuario decide revertir
    assert worker.rollback().result(TIMEOUT) is T.NONE
    assert "x" not in tables(worker)


# -- ROLLBACK ------------------------------------------------------------------------------------


def test_rollback_discards_changes(worker):
    run(worker, "CREATE TABLE x AS SELECT 1 AS a")
    run(worker, "BEGIN")
    run(worker, "INSERT INTO x VALUES (2)")
    run(worker, "CREATE TEMP TABLE tmp AS SELECT 1 AS a")
    assert worker.rollback().result(TIMEOUT) is T.NONE
    assert count(worker, "x") == 1 and "tmp" not in tables(worker)


@needs_verified_interrupt
def test_rollback_recovers_an_aborted_transaction(worker):
    run(worker, "BEGIN")
    abort(worker)
    assert worker.rollback().result(TIMEOUT) is T.NONE
    assert run(worker, "SELECT 42").rows == ((42,),)  # la conexión vuelve a ser utilizable


def test_rollback_without_transaction_is_rejected(worker):
    with pytest.raises(TransactionError) as info:
        worker.rollback().result(TIMEOUT)
    assert info.value.code is ErrorCode.INVALID_ARGUMENT


# -- coherencia de la sesión (GD-SES-005) ----------------------------------------------------------


def test_use_temporaries_and_settings_persist_across_operations(worker, tmp_path):
    path = str(tmp_path / "x.duckdb")
    duckdb.connect(path).close()
    run(worker, f"ATTACH '{path}' AS x")
    run(worker, "USE x")
    run(worker, "CREATE TEMP TABLE t AS SELECT 1 AS a")
    run(worker, "SET threads = 1")
    assert run(worker, "SELECT current_database()").rows == (("x",),)
    assert count(worker, "t") == 1
    assert run(worker, "SELECT current_setting('threads')").rows == ((1,),)
    run(worker, "USE memory")
    run(worker, "DETACH x")


def test_a_new_session_starts_clean():
    first = SessionWorker()
    first.start().result(TIMEOUT)
    run(first, "CREATE TEMP TABLE t AS SELECT 1 AS a")
    run(first, "BEGIN")
    first.close().result(TIMEOUT)
    second = SessionWorker()
    second.start().result(TIMEOUT)
    try:
        assert state(second) is T.NONE and "t" not in tables(second)
    finally:
        second.close().result(TIMEOUT)
