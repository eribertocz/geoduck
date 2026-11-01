# SPDX-License-Identifier: GPL-2.0-or-later
"""Casos de uso de sesión con dobles (sin DuckDB ni Qt)."""

from concurrent.futures import Future

import pytest

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    CatalogChanged,
    CatalogUnavailable,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
)
from geoduck.domain.catalog import AccessMode, AttachedDatabase, CatalogSnapshot
from geoduck.domain.errors import (
    EngineError,
    ErrorCode,
    SessionClosedError,
    SessionInvalidatedError,
    SessionStateError,
    UnsupportedEngineError,
)
from geoduck.domain.operations import EngineInfo
from geoduck.domain.session import ErrorCause
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
        self.invalidated: Future = Future()
        self.catalog_reads: list[Future] = []
        self.cancelled = False

    def start(self):
        return self.started

    def close(self):
        return self.stopped

    def cancel_current(self):
        self.cancelled = True
        return True

    def invalidation(self):
        return self.invalidated

    def read_catalog(self):
        self.catalog_reads.append(Future())
        return self.catalog_reads[-1]


INFO = EngineInfo("2.0.0", ":memory:", True, "memory")


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


# -- invalidación de sesión (C13 §4 bis, #31) ------------------------------------------------------

CAUSE = SessionInvalidatedError("La conexión DuckDB no responde", detail="unresponsive_after_interrupt")


def _ready(env):
    coordinator, dispatcher, engines, events = env
    coordinator.start_memory_session()
    engines[-1].started.set_result(INFO)
    dispatcher.drain()
    assert coordinator.state is S.READY
    return coordinator, dispatcher, engines, events


def test_inv1_invalidation_is_notified_once_with_its_code(env):
    coordinator, dispatcher, engines, events = _ready(env)
    engines[0].invalidated.set_result(CAUSE)
    assert not any(isinstance(e, SessionInvalidated) for e in events)  # solo tras pasar por el hilo principal
    dispatcher.drain()
    notices = [e for e in events if isinstance(e, SessionInvalidated)]
    assert len(notices) == 1
    assert notices[0].code is ErrorCode.SESSION_INVALIDATED
    assert notices[0].detail == "unresponsive_after_interrupt"
    assert coordinator.state is S.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.SESSION_INVALIDATED
    assert coordinator.engine_info is None


def test_inv4_no_return_to_ready_and_new_session_uses_a_new_engine(env):
    coordinator, dispatcher, engines, _events = _ready(env)
    engines[0].invalidated.set_result(CAUSE)
    dispatcher.drain()
    assert not coordinator._sm.can(S.READY)
    with pytest.raises(SessionStateError):
        coordinator._sm.transition(S.READY)
    assert coordinator.cancel_current_operation() is False  # nada llega al motor invalidado
    coordinator.start_memory_session()
    assert len(engines) == 2 and engines[1] is not engines[0]
    engines[1].started.set_result(INFO)
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.error_cause is None


def test_inv4_close_after_invalidation_disconnects_without_touching_the_engine(env):
    coordinator, dispatcher, engines, _events = _ready(env)
    engines[0].invalidated.set_result(CAUSE)
    dispatcher.drain()
    assert coordinator.close_session().done()
    assert coordinator.state is S.DISCONNECTED


def test_inv5_requested_close_is_never_an_invalidation(env):
    coordinator, dispatcher, engines, events = _ready(env)
    coordinator.close_session()
    engines[0].invalidated.set_result(CAUSE)  # incluso si el motor informara una causa tardía
    engines[0].stopped.set_result(None)
    dispatcher.drain()
    assert coordinator.state is S.DISCONNECTED
    assert not any(isinstance(e, SessionInvalidated) for e in events)


def test_normal_engine_end_does_not_notify(env):
    coordinator, dispatcher, engines, events = _ready(env)
    engines[0].invalidated.set_result(None)
    dispatcher.drain()
    assert coordinator.state is S.READY
    assert not any(isinstance(e, SessionInvalidated) for e in events)


def test_late_invalidation_of_a_replaced_engine_is_ignored(env):
    coordinator, dispatcher, engines, events = _ready(env)
    coordinator.close_session()
    engines[0].stopped.set_result(None)
    dispatcher.drain()
    _ready(env)
    engines[0].invalidated.set_result(CAUSE)
    dispatcher.drain()
    assert coordinator.state is S.READY
    assert not any(isinstance(e, SessionInvalidated) for e in events)


def test_start_failure_records_its_cause(env):
    coordinator, dispatcher, engines, _events = env
    coordinator.start_memory_session()
    engines[0].started.set_exception(UnsupportedEngineError("DuckDB 1.4"))
    dispatcher.drain()
    assert coordinator.error_cause is ErrorCause.START_FAILED
    assert not coordinator._sm.can(S.READY)


# -- catálogo (G1 paso 2) ----------------------------------------------------------------------

ROOT = AttachedDatabase("memory", None, AccessMode.READ_WRITE, "duckdb")
SALES = AttachedDatabase("ventas", "/datos/ventas.duckdb", AccessMode.READ_ONLY, "duckdb")
ONLY_ROOT = CatalogSnapshot((ROOT,), root="memory", default="memory")
WITH_SALES = CatalogSnapshot((ROOT, SALES), root="memory", default="memory")


def catalogs(events):
    return [e.catalog for e in events if isinstance(e, CatalogChanged)]


def test_catalog_is_read_once_after_start_without_leaving_ready(env):
    coordinator, dispatcher, engines, events = _ready(env)
    assert len(engines[0].catalog_reads) == 1
    assert coordinator.catalog is None  # todavía no ha llegado
    engines[0].catalog_reads[0].set_result(ONLY_ROOT)
    assert catalogs(events) == []  # solo tras pasar por el hilo principal
    dispatcher.drain()
    assert coordinator.catalog is ONLY_ROOT and catalogs(events) == [ONLY_ROOT]
    assert states(events) == [S.CONNECTING, S.READY]


def test_catalog_failure_discards_previous_snapshot(env):
    coordinator, dispatcher, engines, events = _ready(env)
    engines[0].catalog_reads[0].set_result(ONLY_ROOT)
    dispatcher.drain()
    coordinator.refresh_catalog()
    engines[0].catalog_reads[1].set_exception(EngineError("Catálogo incoherente"))
    dispatcher.drain()
    assert coordinator.catalog is None
    unavailable = [e for e in events if isinstance(e, CatalogUnavailable)]
    assert len(unavailable) == 1 and unavailable[0].code is ErrorCode.ENGINE_ERROR
    assert coordinator.state is S.READY


def test_only_the_latest_catalog_read_is_applied(env):
    coordinator, dispatcher, engines, events = _ready(env)
    coordinator.refresh_catalog()
    first, second = engines[0].catalog_reads
    second.set_result(WITH_SALES)
    first.set_result(ONLY_ROOT)  # llega tarde: superada
    dispatcher.drain()
    assert coordinator.catalog is WITH_SALES and catalogs(events) == [WITH_SALES]


def test_close_drops_catalog_and_ignores_late_read(env):
    coordinator, dispatcher, engines, events = _ready(env)
    engines[0].catalog_reads[0].set_result(ONLY_ROOT)
    dispatcher.drain()
    coordinator.refresh_catalog()
    coordinator.close_session()
    assert coordinator.catalog is None and catalogs(events)[-1] is None
    engines[0].catalog_reads[1].set_result(WITH_SALES)
    engines[0].stopped.set_result(None)
    dispatcher.drain()
    assert coordinator.catalog is None
    assert catalogs(events) == [ONLY_ROOT, None]


def test_invalidation_drops_catalog(env):
    coordinator, dispatcher, engines, events = _ready(env)
    engines[0].catalog_reads[0].set_result(ONLY_ROOT)
    dispatcher.drain()
    engines[0].invalidated.set_result(CAUSE)
    dispatcher.drain()
    assert coordinator.catalog is None and catalogs(events) == [ONLY_ROOT, None]
    with pytest.raises(SessionStateError):
        coordinator.refresh_catalog()


def test_catalog_read_rejected_by_closed_engine_is_reported(env):
    coordinator, dispatcher, engines, events = _ready(env)
    engines[0].catalog_reads[0].set_exception(SessionClosedError("La sesión no acepta operaciones"))
    dispatcher.drain()
    assert coordinator.catalog is None
    assert any(isinstance(e, CatalogUnavailable) and e.code is ErrorCode.SESSION_CLOSED for e in events)


@pytest.mark.parametrize("state", ["DISCONNECTED", "CONNECTING"])
def test_refresh_catalog_requires_ready(env, state):
    coordinator, _dispatcher, _engines, _events = env
    if state == "CONNECTING":
        coordinator.start_memory_session()
    with pytest.raises(SessionStateError):
        coordinator.refresh_catalog()
