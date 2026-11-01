# SPDX-License-Identifier: GPL-2.0-or-later
"""Casos de uso de sesión con dobles (sin DuckDB ni Qt)."""

from concurrent.futures import Future

import pytest

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import SessionFailed, SessionStarted, SessionStateChanged
from geoduck.domain.errors import ErrorCode, SessionStateError, UnsupportedEngineError
from geoduck.domain.operations import EngineInfo
from geoduck.domain.session import SessionState as S


class QueueDispatcher:
    """Simula el bucle de eventos: las llamadas quedan en cola hasta `drain()`."""

    def __init__(self):
        self.queue = []

    def post(self, fn):
        self.queue.append(fn)

    def drain(self):
        while self.queue:
            self.queue.pop(0)()


class FakeEngine:
    def __init__(self):
        self.started: Future = Future()
        self.stopped: Future = Future()
        self.cancelled = False

    def start(self):
        return self.started

    def close(self):
        return self.stopped

    def cancel_current(self):
        self.cancelled = True
        return True


INFO = EngineInfo("2.0.0", ":memory:", True)


@pytest.fixture
def env():
    engines = []

    def factory():
        engines.append(FakeEngine())
        return engines[-1]

    dispatcher = QueueDispatcher()
    coordinator = SessionCoordinator(factory, dispatcher)
    events = []
    coordinator.subscribe(events.append)
    return coordinator, dispatcher, engines, events


def states(events):
    return [e.current for e in events if isinstance(e, SessionStateChanged)]


def test_start_then_ready_only_after_dispatch(env):
    coordinator, dispatcher, engines, events = env
    coordinator.start_memory_session()
    assert coordinator.state is S.CONNECTING
    engines[0].started.set_result(INFO)  # «hilo del worker»
    assert coordinator.state is S.CONNECTING  # nada cambia fuera del hilo principal
    dispatcher.drain()
    assert coordinator.state is S.READY
    assert coordinator.engine_info == INFO
    assert any(isinstance(e, SessionStarted) for e in events)


def test_start_failure_is_recoverable_and_retry_works(env):
    coordinator, dispatcher, engines, events = env
    coordinator.start_memory_session()
    engines[0].started.set_exception(UnsupportedEngineError("DuckDB 1.4"))
    dispatcher.drain()
    assert coordinator.state is S.ERROR_RECOVERABLE
    failed = [e for e in events if isinstance(e, SessionFailed)]
    assert failed and failed[0].code is ErrorCode.UNSUPPORTED_ENGINE
    coordinator.start_memory_session()
    engines[1].started.set_result(INFO)
    dispatcher.drain()
    assert coordinator.state is S.READY


def test_factory_exception_is_contained(env):
    coordinator, _dispatcher, _engines, events = env
    coordinator._factory = lambda: (_ for _ in ()).throw(ImportError("No module named 'duckdb'"))
    coordinator.start_memory_session()
    assert coordinator.state is S.ERROR_RECOVERABLE
    assert isinstance(events[-1], SessionFailed)
    assert events[-1].code is ErrorCode.ENGINE_ERROR


def test_close_goes_through_closing_to_disconnected(env):
    coordinator, dispatcher, engines, events = env
    coordinator.start_memory_session()
    engines[0].started.set_result(INFO)
    dispatcher.drain()
    closing = coordinator.close_session()
    assert coordinator.state is S.CLOSING
    engines[0].stopped.set_result(None)
    dispatcher.drain()
    assert closing.done() and coordinator.state is S.DISCONNECTED
    assert states(events) == [S.CONNECTING, S.READY, S.CLOSING, S.DISCONNECTED]


def test_close_while_connecting_ignores_late_start(env):
    coordinator, dispatcher, engines, _events = env
    coordinator.start_memory_session()
    coordinator.close_session()
    engines[0].started.set_result(INFO)
    engines[0].stopped.set_result(None)
    dispatcher.drain()
    assert coordinator.state is S.DISCONNECTED
    assert coordinator.engine_info is None


def test_cannot_start_twice(env):
    coordinator, _d, _e, _ev = env
    coordinator.start_memory_session()
    with pytest.raises(SessionStateError):
        coordinator.start_memory_session()


def test_close_without_session_is_noop(env):
    coordinator, _d, _e, events = env
    assert coordinator.close_session().done()
    assert events == []


def test_cancel_delegates_to_engine(env):
    coordinator, _dispatcher, engines, _ev = env
    assert coordinator.cancel_current_operation() is False
    coordinator.start_memory_session()
    assert coordinator.cancel_current_operation() is True
    assert engines[0].cancelled


def test_shutdown_times_out_without_raising(env):
    coordinator, dispatcher, engines, _ev = env
    coordinator.start_memory_session()
    engines[0].started.set_result(INFO)
    dispatcher.drain()
    assert coordinator.shutdown(timeout=0.05) is False
    engines[0].stopped.set_result(None)
    assert coordinator.shutdown(timeout=0.05) is True
