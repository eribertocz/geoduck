# SPDX-License-Identifier: GPL-2.0-or-later
"""Session Worker contra DuckDB real (matriz 1.5.0 / 1.5.x / 2.x). ADR-0006, AT-SES-001."""

from __future__ import annotations

import threading
import time

import duckdb
import pytest

from geoduck.domain.errors import (
    ActiveResultError,
    EngineError,
    GeoDuckError,
    SessionClosedError,
    WrongThreadError,
)
from geoduck.domain.operations import ReadOutcome
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def run(worker, fn):
    return worker.submit(fn).future.result(TIMEOUT)


def test_start_reports_engine_and_close_stops_thread():
    w = SessionWorker()
    info = w.start().result(TIMEOUT)
    assert info.duckdb_version == duckdb.__version__
    assert info.database == ":memory:"
    assert w.thread is not None and w.thread.is_alive()
    w.close().result(TIMEOUT)  # la conexión ya está cerrada; el hilo termina justo después
    w.thread.join(TIMEOUT)
    assert not w.thread.is_alive()


def test_at_ses_001_temp_tables_and_sql_in_memory_session(worker):
    """AT-SES-001: sesión :memory: con tablas temporales y SQL funcional."""

    def op(h, _token):
        h.execute("CREATE TEMP TABLE productos AS SELECT 1 AS id, 'Medi;dor' AS nombre")
        h.execute("INSERT INTO productos VALUES (?, ?)", [2, "Válvula"])
        return h.execute("SELECT id, nombre FROM productos ORDER BY id")

    out = run(worker, op)
    assert out.columns == ("id", "nombre")
    assert out.rows == ((1, "Medi;dor"), (2, "Válvula"))
    # el estado de sesión persiste entre operaciones del mismo worker
    again = run(worker, lambda h, t: h.execute("SELECT count(*) FROM productos"))
    assert again.rows == ((2,),)
    db = run(worker, lambda h, t: h.execute("SELECT current_database()"))
    assert db.rows == (("memory",),)


def test_temp_objects_disappear_with_session():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    run(w, lambda h, t: h.execute("CREATE TEMP TABLE t AS SELECT 1"))
    w.close().result(TIMEOUT)
    w2 = SessionWorker()
    w2.start().result(TIMEOUT)
    try:
        with pytest.raises(EngineError):
            run(w2, lambda h, t: h.execute("SELECT * FROM t"))
    finally:
        w2.close().result(TIMEOUT)


def test_execute_is_bounded_and_frees_the_connection(worker):
    out = run(worker, lambda h, t: h.execute("SELECT range FROM range(1000)", max_rows=10))
    assert len(out.rows) == 10 and out.truncated
    # la conexión queda libre para la siguiente operación en 1.5.x y 2.x
    assert run(worker, lambda h, t: h.execute("SELECT 42")).rows == ((42,),)


def test_insert_returning_runs_once(worker):
    """C11: una escritura con RETURNING se ejecuta una sola vez."""

    def op(h, _t):
        h.execute("CREATE TABLE w(i INTEGER)")
        h.execute("INSERT INTO w VALUES (1) RETURNING *")
        return h.execute("SELECT count(*) FROM w")

    assert run(worker, op).rows == ((1,),)


def test_engine_errors_are_typed_and_session_survives(worker):
    with pytest.raises(EngineError) as err:
        run(worker, lambda h, t: h.execute("SELEC 1"))
    assert "syntax error" in err.value.message.lower()
    assert run(worker, lambda h, t: h.execute("SELECT 1")).rows == ((1,),)


def test_connection_cannot_be_used_from_another_thread(worker):
    """ADR-0006 §3: la conexión solo se usa en su hilo propietario."""
    leaked = run(worker, lambda h, t: h)
    with pytest.raises(WrongThreadError):
        leaked.execute("SELECT 1")
    with pytest.raises(WrongThreadError), leaked.arrow_batches("SELECT 1", batch_size=10):
        pass


def test_concurrent_submitters_are_serialized(worker):
    """F-02: en DuckDB 1.5.0 el uso concurrente hace caer el proceso. Aquí 4 hilos × 200 operaciones."""
    errors: list[BaseException] = []
    results: list[int] = []
    lock = threading.Lock()

    def client(k):
        try:
            for i in range(200):
                out = run(worker, lambda h, t, i=i: h.execute(f"SELECT {k * 1000 + i}"))
                with lock:
                    results.append(out.rows[0][0])
        except BaseException as exc:  # pragma: no cover - el test falla abajo
            errors.append(exc)

    threads = [threading.Thread(target=client, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(TIMEOUT * 4)
    assert not errors
    assert sorted(results) == sorted(k * 1000 + i for k in range(4) for i in range(200))


def test_open_reader_rejects_other_statements_and_stays_complete(worker):
    """F-01 / C7: con un lector abierto, otra sentencia se rechaza y el lector no se trunca."""

    def op(h, _t):
        h.execute("CREATE TABLE big AS SELECT range AS i FROM range(100000)")
        with h.arrow_batches("SELECT i FROM big", batch_size=1000) as reader:
            rows = reader.read_next_batch().num_rows
            with pytest.raises(ActiveResultError):
                h.execute("SELECT 1")
            with pytest.raises(ActiveResultError), h.arrow_batches("SELECT 1", batch_size=1):
                pass
            for batch in reader:
                rows += batch.num_rows
        assert not h.reader_open
        return rows

    assert run(worker, op) == 100000


def test_read_arrow_complete_with_exact_counts(worker):
    seen = []

    def op(h, token):
        return h.read_arrow(
            "SELECT range AS i FROM range(50000)",
            batch_size=8192,
            on_batch=lambda b: seen.append(b.num_rows),
            token=token,
        )

    summary = run(worker, op)
    assert summary.completed and summary.outcome is ReadOutcome.EXHAUSTED
    assert summary.rows == 50000 == sum(seen)
    assert summary.batches == len(seen) == 7


def test_consumer_failure_propagates_and_reader_is_closed(worker):
    def failing(_batch):
        raise ValueError("consumidor falló")

    def op(h, token):
        return h.read_arrow("SELECT range FROM range(100000)", batch_size=1000, on_batch=failing, token=token)

    with pytest.raises(ValueError):
        run(worker, op)
    assert run(worker, lambda h, t: (h.reader_open, h.execute("SELECT 7").rows)) == (False, ((7,),))


def test_read_arrow_rejects_non_row_statement(worker):
    def op(h, token):
        return h.read_arrow("CREATE TABLE z(i INT)", batch_size=10, on_batch=lambda b: None, token=token)

    if duckdb.__version__.startswith("1."):
        with pytest.raises(GeoDuckError):
            run(worker, op)
    else:  # en 2.x con.sql() devuelve una relación vacía para DDL; la lectura no tiene filas
        summary = run(worker, op)
        assert summary.rows == 0


def test_submit_after_close_is_rejected():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    w.close().result(TIMEOUT)
    with pytest.raises(SessionClosedError):
        w.submit(lambda h, t: None)


def test_close_is_idempotent_and_safe_before_start():
    w = SessionWorker()
    w.close().result(TIMEOUT)
    w2 = SessionWorker()
    w2.start().result(TIMEOUT)
    f1, f2 = w2.close(), w2.close()
    f1.result(TIMEOUT)
    f2.result(TIMEOUT)


def test_queued_operations_fail_cleanly_when_session_closes():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    gate = threading.Event()
    first = w.submit(lambda h, t: gate.wait(TIMEOUT))
    queued = w.submit(lambda h, t: h.execute("SELECT 1"))
    time.sleep(0.1)
    closing = w.close()
    gate.set()
    closing.result(TIMEOUT)
    first.future.result(TIMEOUT)
    with pytest.raises(Exception) as err:
        queued.future.result(TIMEOUT)
    assert type(err.value).__name__ in {"OperationCancelledError", "SessionClosedError"}
