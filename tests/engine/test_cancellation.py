# SPDX-License-Identifier: GPL-2.0-or-later
"""Cancelación (ADR-0007). Un éxito nunca se reporta tras cancelar."""

from __future__ import annotations

import threading
import time

import duckdb
import pytest

from geoduck.domain.errors import OperationCancelledError
from geoduck.domain.operations import ReadOutcome
from geoduck.engine.compat import EngineCapabilities
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30
LONG_QUERY = "SELECT count(*) FROM range(5000000000) t(a) WHERE a % 7 = 3"
CAPS = EngineCapabilities.for_version(duckdb.__version__)
needs_verified_interrupt = pytest.mark.skipif(
    not CAPS.interrupt_verified,
    reason=f"interrupt() no verificado para DuckDB {duckdb.__version__} (ADR-0007)",
)


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def wait_until_running(worker, handle, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if handle.future.running():
            time.sleep(0.3)  # deja que DuckDB entre en la ejecución
            return
        time.sleep(0.01)
    raise AssertionError("la operación no empezó")


@needs_verified_interrupt
def test_interrupt_stops_long_execute_and_session_recovers(worker):
    handle = worker.submit(lambda h, t: h.execute(LONG_QUERY))
    wait_until_running(worker, handle)
    started = time.monotonic()
    assert worker.cancel(handle.op_id)
    with pytest.raises(OperationCancelledError):
        handle.future.result(TIMEOUT)
    assert time.monotonic() - started < 5
    assert worker.submit(lambda h, t: h.execute("SELECT 1")).future.result(TIMEOUT).rows == ((1,),)


@needs_verified_interrupt
def test_interrupt_during_arrow_read_is_never_complete(worker):
    def op(h, token):
        return h.read_arrow(
            "SELECT a FROM range(5000000000) t(a) WHERE a % 3 = 0",
            batch_size=8192,
            on_batch=lambda b: None,
            token=token,
        )

    handle = worker.submit(op)
    wait_until_running(worker, handle)
    worker.cancel(handle.op_id)
    summary = handle.future.result(TIMEOUT)
    assert summary.outcome is ReadOutcome.CANCELLED
    assert not summary.completed
    assert worker.submit(lambda h, t: h.reader_open).future.result(TIMEOUT) is False


def test_cooperative_cancel_between_batches(worker):
    """Siempre disponible, incluso sin interrupt verificado."""
    seen = []

    def op(h, token):
        def consume(batch):
            seen.append(batch.num_rows)
            if len(seen) == 3:
                token.cancel()

        return h.read_arrow("SELECT range FROM range(100000)", batch_size=1000, on_batch=consume, token=token)

    summary = worker.submit(op).future.result(TIMEOUT)
    assert summary.outcome is ReadOutcome.CANCELLED
    assert summary.rows == 3000 and not summary.completed


def test_cancel_queued_operation_never_runs(worker):
    gate = threading.Event()
    blocker = worker.submit(lambda h, t: gate.wait(TIMEOUT))
    ran = []
    queued = worker.submit(lambda h, t: ran.append(True))
    assert worker.cancel(queued.op_id)
    gate.set()
    blocker.future.result(TIMEOUT)
    with pytest.raises(OperationCancelledError):
        queued.future.result(TIMEOUT)
    assert ran == []


def test_cancel_unknown_operation_returns_false(worker):
    assert worker.cancel(999_999) is False


def test_unverified_version_does_not_call_interrupt():
    """ADR-0007 §1: fuera del conjunto verificado no se llama a interrupt()."""

    class FakeCon:
        interrupted = False

        def interrupt(self):
            self.interrupted = True

    w = SessionWorker()
    fake = FakeCon()
    w._con = fake
    w._caps = EngineCapabilities.for_version("9.9.9")

    class Job:
        op_id = 1

        class token:  # noqa: N801
            @staticmethod
            def cancel():
                pass

    w._current = Job()
    with w._lock:
        w._interrupt_current_locked()
    assert fake.interrupted is False
    w._caps = EngineCapabilities.for_version("2.0.0")
    with w._lock:
        w._interrupt_current_locked()
    assert fake.interrupted is True
