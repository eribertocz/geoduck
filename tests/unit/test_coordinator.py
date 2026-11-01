# SPDX-License-Identifier: GPL-2.0-or-later
"""Casos de uso de sesión con dobles (sin DuckDB ni Qt)."""

from concurrent.futures import Future

import pytest

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    AttachFailed,
    CatalogChanged,
    CatalogUnavailable,
    DatabaseAttached,
    DatabaseDetached,
    DetachFailed,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
    TransactionFailed,
    TransactionStateChanged,
)
from geoduck.domain.catalog import (
    AccessMode,
    AttachedDatabase,
    AttachRequest,
    AttachResult,
    CatalogSnapshot,
    DetachResult,
    OpenAction,
)
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
from geoduck.domain.transaction import TransactionState as T


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
        self.attaches: list[tuple[AttachRequest, Future]] = []
        self.detaches: list[tuple[str, Future]] = []
        self.commits: list[Future] = []
        self.rollbacks: list[Future] = []
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

    def attach(self, request):
        self.attaches.append((request, Future()))
        return self.attaches[-1][1]

    def detach(self, alias):
        self.detaches.append((alias, Future()))
        return self.detaches[-1][1]

    def commit(self):
        self.commits.append(Future())
        return self.commits[-1]

    def rollback(self):
        self.rollbacks.append(Future())
        return self.rollbacks[-1]

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


# -- Abrir existente / Crear nueva (G1 paso 3) -----------------------------------------------------

REQUEST = AttachRequest("/datos/ventas.duckdb", AccessMode.READ_ONLY, OpenAction.OPEN_EXISTING)
ATTACHED = AttachResult(SALES, WITH_SALES)


def test_attach_goes_busy_then_ready_with_the_new_catalog(env):
    coordinator, dispatcher, engines, events = _ready(env)
    coordinator.attach_database(REQUEST)
    assert coordinator.state is S.BUSY
    with pytest.raises(SessionStateError):
        coordinator.attach_database(REQUEST)  # una operación a la vez
    request, fut = engines[0].attaches[0]
    assert request is REQUEST
    fut.set_result(ATTACHED)
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.catalog is WITH_SALES
    assert [e.database for e in events if isinstance(e, DatabaseAttached)] == [SALES]
    assert states(events)[-2:] == [S.BUSY, S.READY]


@pytest.mark.parametrize("code", [ErrorCode.DB_NOT_FOUND, ErrorCode.DB_LOCKED, ErrorCode.DB_ALIAS_CONFLICT])
def test_attach_failure_keeps_the_session_ready_and_rereads_the_catalog(env, code):
    from geoduck.domain.errors import AttachError

    coordinator, dispatcher, engines, events = _ready(env)
    engines[0].catalog_reads[0].set_result(ONLY_ROOT)
    dispatcher.drain()
    coordinator.attach_database(REQUEST)
    engines[0].attaches[0][1].set_exception(AttachError("No se pudo", code=code))
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.error_cause is None
    failed = [e for e in events if isinstance(e, AttachFailed)]
    assert len(failed) == 1 and failed[0].code is code
    assert len(engines[0].catalog_reads) == 2  # se relee de DuckDB, no se supone


def test_attach_requires_ready(env):
    coordinator, _dispatcher, _engines, _events = env
    with pytest.raises(SessionStateError):
        coordinator.attach_database(REQUEST)


def test_stale_catalog_read_cannot_overwrite_the_attach_result(env):
    coordinator, dispatcher, engines, _events = _ready(env)
    coordinator.attach_database(REQUEST)
    engines[0].attaches[0][1].set_result(ATTACHED)
    dispatcher.drain()
    engines[0].catalog_reads[0].set_result(ONLY_ROOT)  # lectura inicial que llega tarde
    dispatcher.drain()
    assert coordinator.catalog is WITH_SALES


def test_invalidation_during_attach_ends_in_error_recoverable(env):
    coordinator, dispatcher, engines, events = _ready(env)
    coordinator.attach_database(REQUEST)
    engines[0].attaches[0][1].set_exception(CAUSE.fresh())
    dispatcher.drain()
    assert coordinator.state is S.BUSY  # espera a la notificación de invalidación
    engines[0].invalidated.set_result(CAUSE)
    dispatcher.drain()
    assert coordinator.state is S.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.SESSION_INVALIDATED
    assert not any(isinstance(e, AttachFailed) for e in events)


def test_close_during_attach_ignores_the_late_result(env):
    coordinator, dispatcher, engines, events = _ready(env)
    coordinator.attach_database(REQUEST)
    coordinator.close_session()
    engines[0].attaches[0][1].set_result(ATTACHED)
    engines[0].stopped.set_result(None)
    dispatcher.drain()
    assert coordinator.state is S.DISCONNECTED and coordinator.catalog is None
    assert not any(isinstance(e, DatabaseAttached) for e in events)


def test_file_session_attaches_after_start(env):
    coordinator, dispatcher, engines, _events = env
    coordinator.start_file_session(REQUEST)
    assert engines[0].attaches == []  # todavía no: primero la raíz en memoria
    engines[0].started.set_result(INFO)
    dispatcher.drain()
    assert coordinator.state is S.BUSY and engines[0].attaches[0][0] is REQUEST
    assert engines[0].catalog_reads == []  # el ATTACH ya trae el catálogo
    engines[0].attaches[0][1].set_result(ATTACHED)
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.catalog is WITH_SALES


def test_file_session_failed_attach_stays_in_memory(env):
    from geoduck.domain.errors import AttachError

    coordinator, dispatcher, engines, events = env
    coordinator.start_file_session(REQUEST)
    engines[0].started.set_result(INFO)
    dispatcher.drain()
    engines[0].attaches[0][1].set_exception(AttachError("No existe", code=ErrorCode.DB_NOT_FOUND))
    dispatcher.drain()
    assert coordinator.state is S.READY  # sesión en memoria, informada
    assert any(isinstance(e, AttachFailed) and e.code is ErrorCode.DB_NOT_FOUND for e in events)


def test_file_session_failed_start_drops_the_pending_attach(env):
    coordinator, dispatcher, engines, _events = env
    coordinator.start_file_session(REQUEST)
    engines[0].started.set_exception(UnsupportedEngineError("DuckDB 1.4"))
    dispatcher.drain()
    coordinator.start_memory_session()
    engines[1].started.set_result(INFO)
    dispatcher.drain()
    assert engines[1].attaches == [] and len(engines[1].catalog_reads) == 1


def test_file_session_requires_no_active_session(env):
    coordinator, _dispatcher, _engines, _events = _ready(env)
    with pytest.raises(SessionStateError):
        coordinator.start_file_session(REQUEST)


# -- DetachDatabase (G1 pasos 4 y 5) -------------------------------------------------------------

DETACHED = DetachResult(SALES, ONLY_ROOT)


def _ready_with_sales(env):
    coordinator, dispatcher, engines, events = _ready(env)
    engines[0].catalog_reads[0].set_result(WITH_SALES)
    dispatcher.drain()
    return coordinator, dispatcher, engines, events


def test_detach_goes_through_detaching_and_publishes_the_new_catalog(env):
    coordinator, dispatcher, engines, events = _ready_with_sales(env)
    coordinator.detach_database("ventas")
    assert coordinator.state is S.DETACHING
    for blocked in (
        lambda: coordinator.detach_database("ventas"),
        lambda: coordinator.attach_database(REQUEST),
    ):
        with pytest.raises(SessionStateError):
            blocked()
    assert engines[0].detaches[0][0] == "ventas"
    engines[0].detaches[0][1].set_result(DETACHED)
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.catalog is ONLY_ROOT
    assert [e.database for e in events if isinstance(e, DatabaseDetached)] == [SALES]
    assert states(events)[-2:] == [S.DETACHING, S.READY]


@pytest.mark.parametrize(
    "code", [ErrorCode.DETACH_FAILED, ErrorCode.DEFAULT_CATALOG, ErrorCode.ACTIVE_RESULT]
)
def test_failed_detach_keeps_the_database_and_rereads_the_catalog(env, code):
    from geoduck.domain.errors import DetachError

    coordinator, dispatcher, engines, events = _ready_with_sales(env)
    coordinator.detach_database("ventas")
    engines[0].detaches[0][1].set_exception(DetachError("No se pudo", code=code))
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.error_cause is None
    assert len(engines[0].catalog_reads) == 2  # se relee de DuckDB: nunca se supone
    engines[0].catalog_reads[1].set_result(WITH_SALES)
    dispatcher.drain()
    assert coordinator.catalog.get("ventas") is not None  # sigue adjunta
    assert [e.code for e in events if isinstance(e, DetachFailed)] == [code]


def test_detach_requires_ready(env):
    coordinator, _dispatcher, _engines, _events = env
    with pytest.raises(SessionStateError):
        coordinator.detach_database("ventas")


def test_invalidation_during_detach_ends_in_error_recoverable(env):
    coordinator, dispatcher, engines, events = _ready_with_sales(env)
    coordinator.detach_database("ventas")
    engines[0].detaches[0][1].set_exception(CAUSE.fresh())
    dispatcher.drain()
    assert coordinator.state is S.DETACHING
    engines[0].invalidated.set_result(CAUSE)
    dispatcher.drain()
    assert coordinator.state is S.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.SESSION_INVALIDATED
    assert not coordinator._sm.can(S.READY)
    assert not any(isinstance(e, DetachFailed) for e in events)


def test_close_during_detach_ignores_the_late_result(env):
    coordinator, dispatcher, engines, events = _ready_with_sales(env)
    coordinator.detach_database("ventas")
    coordinator.close_session()
    assert coordinator.state is S.CLOSING
    engines[0].detaches[0][1].set_result(DETACHED)
    engines[0].stopped.set_result(None)
    dispatcher.drain()
    assert coordinator.state is S.DISCONNECTED and coordinator.catalog is None
    assert not any(isinstance(e, DatabaseDetached) for e in events)


# -- transacciones (G1 paso 6) ---------------------------------------------------------------------


def failed_with(error_cls, code, transaction, message="falló"):
    exc = error_cls(message, code=code)
    exc.transaction = transaction
    return exc


def tx_states(events):
    return [e.state for e in events if isinstance(e, TransactionStateChanged)]


def test_new_session_starts_in_autocommit_and_close_forgets_it(env):
    coordinator, _dispatcher, _engines, events = _ready(env)
    assert coordinator.transaction_state is T.NONE
    coordinator.close_session()
    assert coordinator.transaction_state is None
    assert tx_states(events) == [T.NONE, None]


def test_commit_goes_busy_and_records_autocommit(env):
    coordinator, dispatcher, engines, _events = _ready(env)
    coordinator._set_transaction(T.ACTIVE)
    coordinator.commit_transaction()
    assert coordinator.state is S.BUSY
    engines[0].commits[0].set_result(T.NONE)
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.transaction_state is T.NONE


def test_commit_of_an_aborted_transaction_is_refused_and_requires_rollback(env):
    from geoduck.domain.errors import TransactionError

    coordinator, dispatcher, engines, events = _ready(env)
    coordinator.commit_transaction()
    engines[0].commits[0].set_exception(
        failed_with(TransactionError, ErrorCode.TRANSACTION_ABORTED, T.ABORTED)
    )
    dispatcher.drain()
    assert coordinator.state is S.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
    assert not coordinator._sm.can(S.READY)  # no vuelve a READY sin ROLLBACK
    assert [e.code for e in events if isinstance(e, TransactionFailed)] == [ErrorCode.TRANSACTION_ABORTED]
    for blocked in (coordinator.commit_transaction, lambda: coordinator.detach_database("x")):
        with pytest.raises(SessionStateError):
            blocked()


def test_rollback_recovers_an_aborted_transaction_back_to_ready(env):
    from geoduck.domain.errors import TransactionError

    coordinator, dispatcher, engines, events = _ready(env)
    coordinator.commit_transaction()
    engines[0].commits[0].set_exception(
        failed_with(TransactionError, ErrorCode.TRANSACTION_ABORTED, T.ABORTED)
    )
    dispatcher.drain()
    coordinator.rollback_transaction()
    assert coordinator.state is S.ERROR_RECOVERABLE  # la recuperación no pasa por BUSY
    with pytest.raises(SessionStateError):
        coordinator.rollback_transaction()  # una sola recuperación a la vez
    engines[0].rollbacks[0].set_result(T.NONE)
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.error_cause is None
    assert coordinator.transaction_state is T.NONE
    assert tx_states(events)[-2:] == [T.ABORTED, T.NONE]


def test_failed_recovery_rollback_stays_in_error_recoverable(env):
    from geoduck.domain.errors import TransactionError

    coordinator, dispatcher, engines, _events = _ready(env)
    coordinator.commit_transaction()
    engines[0].commits[0].set_exception(
        failed_with(TransactionError, ErrorCode.TRANSACTION_ABORTED, T.ABORTED)
    )
    dispatcher.drain()
    coordinator.rollback_transaction()
    engines[0].rollbacks[0].set_exception(failed_with(TransactionError, ErrorCode.ENGINE_ERROR, T.ABORTED))
    dispatcher.drain()
    assert coordinator.state is S.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
    coordinator.rollback_transaction()  # se puede reintentar
    assert len(engines[0].rollbacks) == 2


def test_rollback_from_ready_goes_busy(env):
    coordinator, dispatcher, engines, _events = _ready(env)
    coordinator._set_transaction(T.ACTIVE)
    coordinator.rollback_transaction()
    assert coordinator.state is S.BUSY
    engines[0].rollbacks[0].set_result(T.NONE)
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.transaction_state is T.NONE


def test_operation_failure_with_aborted_transaction_does_not_return_to_ready(env):
    """ADR-0007 punto 6: si la transacción quedó abortada, la sesión no vuelve a READY ni relee nada."""
    from geoduck.domain.errors import DetachError

    coordinator, dispatcher, engines, events = _ready_with_sales(env)
    coordinator.detach_database("ventas")
    engines[0].detaches[0][1].set_exception(failed_with(DetachError, ErrorCode.DETACH_FAILED, T.ABORTED))
    dispatcher.drain()
    assert coordinator.state is S.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
    assert len(engines[0].catalog_reads) == 1  # no se relee el catálogo con la transacción abortada
    assert any(isinstance(e, DetachFailed) for e in events)


def test_operation_failure_with_active_transaction_returns_to_ready_and_tracks_it(env):
    from geoduck.domain.errors import DetachError

    coordinator, dispatcher, engines, _events = _ready_with_sales(env)
    coordinator.detach_database("ventas")
    engines[0].detaches[0][1].set_exception(failed_with(DetachError, ErrorCode.DETACH_FAILED, T.ACTIVE))
    dispatcher.drain()
    assert coordinator.state is S.READY and coordinator.transaction_state is T.ACTIVE


def test_invalidation_during_recovery_ends_invalidated(env):
    from geoduck.domain.errors import TransactionError

    coordinator, dispatcher, engines, _events = _ready(env)
    coordinator.commit_transaction()
    engines[0].commits[0].set_exception(
        failed_with(TransactionError, ErrorCode.TRANSACTION_ABORTED, T.ABORTED)
    )
    dispatcher.drain()
    coordinator.rollback_transaction()
    engines[0].rollbacks[0].set_exception(CAUSE.fresh())
    engines[0].invalidated.set_result(CAUSE)
    dispatcher.drain()
    assert coordinator.error_cause is ErrorCause.SESSION_INVALIDATED
    assert coordinator.transaction_state is None
    with pytest.raises(SessionStateError):
        coordinator.rollback_transaction()


@pytest.mark.parametrize("use_case", ["commit_transaction", "rollback_transaction"])
def test_transaction_use_cases_require_a_session(env, use_case):
    coordinator, _dispatcher, _engines, _events = env
    with pytest.raises(SessionStateError):
        getattr(coordinator, use_case)()
