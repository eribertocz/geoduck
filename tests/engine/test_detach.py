# SPDX-License-Identifier: GPL-2.0-or-later
"""DetachDatabase contra DuckDB real (G1 pasos 4 y 5, GD-SES-004, AT-SES-004). Matriz 1.5.0 / 1.5.x / 2.x.

Efectivo: la base desaparece del catálogo y los datos confirmados quedan en el archivo.
Bloqueo: tras el DETACH, un proceso independiente abre el archivo en lectura y escritura.
Integridad: un DETACH fallido deja la base adjunta y la predeterminada como estaba; nunca se adelanta a
una lectura en curso.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

import duckdb
import pytest

from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.errors import (
    ActiveResultError,
    DetachError,
    ErrorCode,
    GeoDuckError,
    OperationCancelledError,
    SessionClosedError,
    SessionInvalidatedError,
)
from geoduck.domain.transaction import TransactionState
from geoduck.engine import detach as engine_detach
from geoduck.engine.compat import EngineCapabilities
from geoduck.engine.detach import detach_database
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30
RO, RW = AccessMode.READ_ONLY, AccessMode.READ_WRITE


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "datos de Año's.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t AS SELECT range AS x FROM range(1000)")
    con.close()
    return str(path)


def attach(worker, path, access, alias="b"):
    return worker.attach(AttachRequest(path, access, OpenAction.OPEN_EXISTING, alias)).result(TIMEOUT)


def run(worker, sql):
    return worker.submit(lambda h, t: h.execute(sql)).future.result(TIMEOUT)


def catalog(worker):
    return worker.read_catalog().result(TIMEOUT)


def other_process(path, script):
    """Ejecuta `script` con una conexión `c` RW al archivo en un proceso independiente."""
    code = f"import duckdb;c=duckdb.connect({path!r});{script};c.close()"
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=TIMEOUT, check=False
    )
    return done.returncode, done.stdout.strip(), done.stderr


# -- efectivo y liberación del bloqueo --------------------------------------------------------------


@pytest.mark.parametrize("access", [RO, RW])
def test_detach_removes_the_database_and_releases_the_lock(worker, db_file, access):
    attach(worker, db_file, access)
    assert other_process(db_file, "pass")[0] != 0  # bloqueado mientras está adjunta
    result = worker.detach("b").result(TIMEOUT)
    assert result.database.name == "b" and result.database.path == db_file
    assert result.catalog.get("b") is None and catalog(worker).get("b") is None
    rc, out, err = other_process(db_file, "print(c.execute('SELECT count(*) FROM t').fetchone()[0])")
    assert rc == 0, err
    assert out == "1000"


def test_committed_writes_are_in_the_file_after_detach(worker, db_file):
    attach(worker, db_file, RW)
    run(worker, "INSERT INTO b.t SELECT range FROM range(1000, 1500)")
    worker.detach("b").result(TIMEOUT)
    assert not os.path.exists(db_file + ".wal")  # el DETACH hizo checkpoint (F-27)
    rc, out, err = other_process(db_file, "print(c.execute('SELECT count(*) FROM t').fetchone()[0])")
    assert rc == 0, err
    assert out == "1500"


def test_lock_release_allows_reattach_and_external_write(worker, db_file):
    attach(worker, db_file, RW)
    worker.detach("b").result(TIMEOUT)
    assert other_process(db_file, "c.execute('INSERT INTO t VALUES (-1)')")[0] == 0
    attach(worker, db_file, RO)
    assert run(worker, "SELECT count(*) FROM b.t").rows == ((1001,),)


def test_alias_lookup_follows_duckdb_rule(worker, db_file):
    attach(worker, db_file, RO, alias="Ventas")
    assert worker.detach("VENTAS").result(TIMEOUT).database.name == "Ventas"


# -- predeterminada y raíz -------------------------------------------------------------------------


def test_detaching_the_default_switches_to_the_real_root_first(worker, db_file):
    attach(worker, db_file, RO)
    root = catalog(worker).root
    run(worker, "USE b")
    assert catalog(worker).default == "b"
    result = worker.detach("b").result(TIMEOUT)
    assert result.catalog.default == root and catalog(worker).default == root


def test_failed_detach_restores_the_default_and_keeps_the_database(worker, db_file, monkeypatch):
    attach(worker, db_file, RO)
    run(worker, "USE b")

    def fail(handle, sql):
        raise duckdb.BinderException("Binder Error: simulado")

    monkeypatch.setattr(engine_detach, "_execute_detach", fail)
    with pytest.raises(DetachError) as info:
        worker.detach("b").result(TIMEOUT)
    assert info.value.code is ErrorCode.DETACH_FAILED
    snap = catalog(worker)
    assert snap.get("b") is not None and snap.default == "b"  # sin cambio oculto
    assert run(worker, "SELECT count(*) FROM t").rows == ((1000,),)


def test_root_cannot_be_detached(worker):
    root = catalog(worker).root
    with pytest.raises(DetachError) as info:
        worker.detach(root.upper()).result(TIMEOUT)
    assert info.value.code is ErrorCode.DEFAULT_CATALOG
    assert catalog(worker).root == root


def test_detaching_an_unknown_alias_fails_without_touching_duckdb(worker):
    with pytest.raises(DetachError) as info:
        worker.detach("nada").result(TIMEOUT)
    assert info.value.code is ErrorCode.DETACH_FAILED and info.value.detail == "not_attached"


# -- lectores y orden serial -----------------------------------------------------------------------


def test_detach_inside_an_open_reader_is_rejected_before_duckdb(worker, db_file):
    """F-26: en 1.5.x, DuckDB aceptaría el DETACH y el lector daría 0 filas sin error."""
    attach(worker, db_file, RO)
    root = catalog(worker).root

    def op(h, t):
        with h.arrow_batches("SELECT * FROM b.t", batch_size=100):
            return detach_database(h, "b", root)

    with pytest.raises(ActiveResultError):
        worker.submit(op).future.result(TIMEOUT)
    assert catalog(worker).get("b") is not None


def test_detach_waits_for_a_read_in_progress(worker, db_file):
    """session-spec §6: el DETACH no se adelanta a la liberación del lector."""
    attach(worker, db_file, RO)
    gate = threading.Event()
    rows = []

    def read(h, token):
        def consume(batch):
            rows.append(batch.num_rows)
            gate.wait(TIMEOUT)

        return h.read_arrow("SELECT * FROM b.t", batch_size=100, on_batch=consume, token=token)

    reading = worker.submit(read)
    detaching = worker.detach("b")
    assert not detaching.done()
    gate.set()
    summary = reading.future.result(TIMEOUT)
    assert summary.completed and summary.rows == 1000
    assert detaching.result(TIMEOUT).catalog.get("b") is None


# -- transacciones y errores fatales ---------------------------------------------------------------


@pytest.mark.parametrize("work", [False, True])
def test_detach_is_blocked_by_an_open_transaction_in_every_version(worker, db_file, work):
    """Regla obligatoria (dictamen del 2026-11-01). Sin ella, 1.5.0 desadjuntaría con cambios pendientes
    (F-28), y 1.5.6/2.0 rechazarían el DETACH dejando la transacción abortada (F-29)."""
    attach(worker, db_file, RW)
    run(worker, "BEGIN")
    if work:
        run(worker, "INSERT INTO b.t VALUES (-1)")
    with pytest.raises(DetachError) as info:
        worker.detach("b").result(TIMEOUT)
    assert info.value.code is ErrorCode.DETACH_FAILED and info.value.detail == "open_transaction: ACTIVE"
    assert info.value.transaction is TransactionState.ACTIVE  # el DETACH nunca llegó a DuckDB: no se abortó
    run(worker, "COMMIT" if work else "ROLLBACK")
    expected = 1001 if work else 1000
    assert run(worker, "SELECT count(*) FROM b.t").rows == ((expected,),)
    worker.detach("b").result(TIMEOUT)  # sin transacción, se desadjunta


@pytest.mark.skipif(
    not EngineCapabilities.for_version(duckdb.__version__).interrupt_verified,
    reason="la transacción se aborta con interrupt(), no verificado en esta versión (ADR-0007)",
)
def test_detach_is_blocked_by_an_aborted_transaction(worker, db_file):
    attach(worker, db_file, RW)
    run(worker, "BEGIN")
    run(worker, "INSERT INTO b.t VALUES (-1)")
    long_query = worker.submit(
        lambda h, t: h.execute("SELECT count(*) FROM range(5000000000) t(a) WHERE a % 7 = 3")
    )
    _wait_running(long_query)
    worker.cancel(long_query.op_id)  # una interrupción dentro de la transacción la aborta (F-32)
    with pytest.raises(OperationCancelledError):
        long_query.future.result(TIMEOUT)
    with pytest.raises(DetachError) as info:
        worker.detach("b").result(TIMEOUT)
    assert info.value.detail == "open_transaction: ABORTED"
    assert info.value.transaction is TransactionState.ABORTED
    run(worker, "ROLLBACK")
    assert run(worker, "SELECT count(*) FROM b.t").rows == ((1000,),)  # el INSERT no se confirmó


def _wait_running(handle, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if handle.future.running():
            time.sleep(0.3)
            return
        time.sleep(0.01)
    raise AssertionError("la operación no empezó")


def test_fatal_error_during_detach_invalidates_the_session(db_file, monkeypatch):
    def fatal(handle, sql):
        raise duckdb.FatalException("FATAL Error: simulado")

    monkeypatch.setattr(engine_detach, "_execute_detach", fatal)
    w = SessionWorker()
    w.start().result(TIMEOUT)
    attach(w, db_file, RO)
    with pytest.raises(SessionInvalidatedError):
        w.detach("b").result(TIMEOUT)
    assert w.invalidation().result(TIMEOUT) is not None


def test_detach_after_close_fails_without_touching_duckdb(db_file):
    w = SessionWorker()
    w.start().result(TIMEOUT)
    w.close().result(TIMEOUT)
    with pytest.raises(SessionClosedError) as info:
        w.detach("b").result(TIMEOUT)
    assert info.value.code is ErrorCode.SESSION_CLOSED


def test_detach_invalidates_future_reads_of_that_alias(worker, db_file):
    """session-spec §6: «DETACH en UI invalida futuras lecturas de ese alias»; no hay reconexión implícita."""
    attach(worker, db_file, RO)
    assert run(worker, "SELECT count(*) FROM b.t").rows == ((1000,),)
    worker.detach("b").result(TIMEOUT)
    for sql in ("SELECT count(*) FROM b.t", "SELECT count(*) FROM b.main.t"):
        with pytest.raises(GeoDuckError) as info:
            run(worker, sql)
        assert info.value.code is ErrorCode.ENGINE_ERROR
    assert catalog(worker).get("b") is None  # sigue desadjuntada: nada la volvió a adjuntar
