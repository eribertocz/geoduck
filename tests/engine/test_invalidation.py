# SPDX-License-Identifier: GPL-2.0-or-later
"""Invalidación de sesión contra DuckDB real (C13 §4 bis, ADR-0007 §3; issue #31).

INV-1 una sola notificación con `SESSION_INVALIDATED`; INV-2 lo pendiente falla y la lectura Arrow en
curso nunca es completa; INV-3 nada posterior llega a DuckDB; INV-5 un cierre pedido no es invalidación.
INV-4 (sin retorno a READY, sesión nueva) se prueba en `tests/unit/test_coordinator.py`.
"""

from __future__ import annotations

import threading
import time

import duckdb
import pytest

from geoduck.domain.errors import ErrorCode, GeoDuckError, SessionClosedError, SessionInvalidatedError
from geoduck.domain.operations import ReadOutcome
from geoduck.engine.compat import EngineCapabilities
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30
LONG_READ = "SELECT a FROM range(5000000000) t(a) WHERE a % 3 = 0"
LONG_QUERY = "SELECT count(*) FROM range(5000000000) t(a) WHERE a % 7 = 3"
CAPS = EngineCapabilities.for_version(duckdb.__version__)
needs_verified_interrupt = pytest.mark.skipif(
    not CAPS.interrupt_verified,
    reason=f"interrupt() no verificado para DuckDB {duckdb.__version__} (ADR-0007)",
)


@pytest.fixture
def unresponsive(monkeypatch):
    """Simula una conexión que no responde a `SELECT 1` tras la interrupción (ADR-0007 §3)."""
    monkeypatch.setattr(SessionWorker, "_connection_responds", staticmethod(lambda handle: False))


def wait_running(handle, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if handle.future.running():
            time.sleep(0.3)
            return
        time.sleep(0.01)
    raise AssertionError("la operación no empezó")


def started_worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    return w


def observe_order(worker):
    """Registra, en el momento de la notificación, si ya no queda camino hacia la conexión."""
    seen = {}

    def on_done(fut):
        seen["cause"] = fut.result()
        try:
            worker.submit(lambda h, t: None)
            seen["submit_rejected"] = False
        except SessionClosedError:
            seen["submit_rejected"] = True
        seen["connection_released"] = worker._con is None

    worker.invalidation().add_done_callback(on_done)
    return seen


@needs_verified_interrupt
def test_inv1_inv2_inv3_unresponsive_connection_after_interrupt(unresponsive):
    w = started_worker()
    seen = observe_order(w)
    ran = []

    def read(h, token):
        return h.read_arrow(LONG_READ, batch_size=8192, on_batch=lambda b: None, token=token)

    reading = w.submit(read)
    queued = [w.submit(lambda h, t, i=i: ran.append(i)) for i in range(3)]
    wait_running(reading)
    w.cancel(reading.op_id)

    cause = w.invalidation().result(TIMEOUT)
    # INV-1: una sola causa, con su código estable
    assert isinstance(cause, SessionInvalidatedError)
    assert cause.code is ErrorCode.SESSION_INVALIDATED
    assert cause.detail == "unresponsive_after_interrupt"
    # Orden: la notificación llega cuando ya no se acepta trabajo y la conexión está liberada
    assert seen["submit_rejected"] and seen["connection_released"]
    # INV-2: la lectura en curso nunca es completa; lo pendiente falla y nunca se ejecuta
    summary = reading.future.result(TIMEOUT)
    assert summary.outcome is ReadOutcome.CANCELLED and not summary.completed
    for handle in queued:
        with pytest.raises(SessionInvalidatedError):
            handle.future.result(TIMEOUT)
    assert ran == []
    # INV-3: lo posterior se rechaza antes de llegar a DuckDB
    called = []
    with pytest.raises(SessionInvalidatedError) as rejected:
        w.submit(lambda h, t: called.append(True))
    assert isinstance(rejected.value, SessionClosedError)
    assert called == []
    w.close().result(TIMEOUT)
    assert w.invalidation().result() is cause  # el resultado no cambia: una sola notificación


def test_fatal_engine_error_invalidates_the_session():
    w = started_worker()
    seen = observe_order(w)

    def boom(h, t):
        raise duckdb.FatalException("FATAL Error: simulado")

    failing = w.submit(boom)
    with pytest.raises(SessionInvalidatedError):
        failing.future.result(TIMEOUT)
    cause = w.invalidation().result(TIMEOUT)
    assert cause is not None and "simulado" in cause.detail
    assert seen["submit_rejected"] and seen["connection_released"]
    with pytest.raises(SessionInvalidatedError):
        w.submit(lambda h, t: None)


def test_worker_loop_failure_invalidates_even_when_idle(monkeypatch):
    def broken_loop(self, handle):
        raise RuntimeError("fallo del bucle")

    monkeypatch.setattr(SessionWorker, "_loop", broken_loop)
    w = started_worker()
    cause = w.invalidation().result(TIMEOUT)
    assert cause is not None and cause.detail == "RuntimeError"
    with pytest.raises(SessionInvalidatedError):
        w.submit(lambda h, t: None)


def test_inv5_requested_close_is_not_an_invalidation():
    w = started_worker()
    assert w.submit(lambda h, t: h.execute("SELECT 1").rows).future.result(TIMEOUT) == ((1,),)
    w.close().result(TIMEOUT)
    assert w.invalidation().result(TIMEOUT) is None
    with pytest.raises(SessionClosedError) as rejected:
        w.submit(lambda h, t: None)
    assert not isinstance(rejected.value, SessionInvalidatedError)


@needs_verified_interrupt
def test_inv5_close_during_unresponsive_interrupt_is_not_an_invalidation(unresponsive):
    w = started_worker()
    running = w.submit(lambda h, t: h.execute(LONG_QUERY))
    queued = w.submit(lambda h, t: None)
    wait_running(running)
    w.close().result(TIMEOUT)
    assert w.invalidation().result(TIMEOUT) is None
    with pytest.raises(SessionClosedError) as rejected:
        queued.future.result(TIMEOUT)
    assert not isinstance(rejected.value, SessionInvalidatedError)


def test_failed_start_resolves_invalidation_with_none(monkeypatch):
    monkeypatch.setattr(duckdb, "connect", lambda **kw: (_ for _ in ()).throw(duckdb.IOException("x")))
    w = SessionWorker()
    with pytest.raises(GeoDuckError):
        w.start().result(TIMEOUT)
    assert w.invalidation().result(TIMEOUT) is None


def test_invalidation_resolves_after_thread_cleanup():
    w = started_worker()
    released = threading.Event()
    w.invalidation().add_done_callback(lambda f: released.set())
    w.close().result(TIMEOUT)
    assert released.wait(TIMEOUT)


def test_fatal_error_wrapped_by_an_operation_still_invalidates():
    """Regresión: una operación que envuelve el FatalException no puede ocultarlo."""
    w = started_worker()

    def wrapped(h, t):
        try:
            raise duckdb.FatalException("FATAL Error: simulado")
        except duckdb.Error as exc:
            raise GeoDuckError("error clasificado") from exc

    failing = w.submit(wrapped)
    with pytest.raises(SessionInvalidatedError):
        failing.future.result(TIMEOUT)
    cause = w.invalidation().result(TIMEOUT)
    assert cause is not None and "simulado" in cause.detail
