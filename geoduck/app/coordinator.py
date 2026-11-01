# SPDX-License-Identifier: GPL-2.0-or-later
"""Coordinador de sesión: StartSession (memoria y archivo), AttachDatabase, CloseSession, CancelOperation,
invalidación y catálogo.

Vive en el hilo principal. Toda finalización del motor se reenvía al hilo principal mediante el
`Dispatcher` antes de cambiar el estado, de modo que la máquina de estados nunca se toca desde dos hilos.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout

from geoduck.app.events import (
    AppEvent,
    AttachFailed,
    CatalogChanged,
    CatalogUnavailable,
    DatabaseAttached,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
)
from geoduck.app.ports import Dispatcher, EngineFactory, SessionEngine
from geoduck.domain.catalog import AttachRequest, AttachResult, CatalogSnapshot
from geoduck.domain.errors import ErrorCode, GeoDuckError, SessionInvalidatedError, SessionStateError
from geoduck.domain.operations import EngineInfo
from geoduck.domain.session import ErrorCause, SessionState, SessionStateMachine

_log = logging.getLogger("geoduck.app")

Listener = Callable[[AppEvent], None]


class SessionCoordinator:
    def __init__(self, engine_factory: EngineFactory, dispatcher: Dispatcher) -> None:
        self._factory = engine_factory
        self._dispatcher = dispatcher
        self._sm = SessionStateMachine()
        self._sm.subscribe(lambda a, b: self._emit(SessionStateChanged(a, b)))
        self._engine: SessionEngine | None = None
        self._info: EngineInfo | None = None
        self._catalog: CatalogSnapshot | None = None
        #: Cada lectura del catálogo recibe un número; solo se aplica la más reciente.
        self._catalog_generation = 0
        #: Archivo que se adjunta en cuanto la sesión esté lista (StartSession(mode=file)).
        self._pending_attach: AttachRequest | None = None
        self._listeners: list[Listener] = []

    # -- consulta ----------------------------------------------------------------------------------

    @property
    def state(self) -> SessionState:
        return self._sm.state

    @property
    def error_cause(self) -> ErrorCause | None:
        return self._sm.error_cause

    @property
    def engine_info(self) -> EngineInfo | None:
        return self._info

    @property
    def catalog(self) -> CatalogSnapshot | None:
        """Última instantánea válida del catálogo; `None` si no hay sesión o no se pudo leer."""
        return self._catalog

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    # -- casos de uso ------------------------------------------------------------------------------

    def start_memory_session(self) -> None:
        """StartSession(mode=memory): raíz `:memory:` (ADR-0001)."""
        if self._sm.state not in (SessionState.DISCONNECTED, SessionState.ERROR_RECOVERABLE):
            raise SessionStateError(f"No se puede iniciar una sesión en estado {self._sm.state.value}")
        self._sm.transition(SessionState.CONNECTING)
        try:
            engine = self._factory()
            started = engine.start()
        except Exception as exc:
            self._engine = None
            self._fail(exc)
            return
        self._engine = engine
        started.add_done_callback(lambda fut: self._dispatcher.post(lambda: self._on_started(engine, fut)))

    def start_file_session(self, request: AttachRequest) -> None:
        """StartSession(mode=file): raíz `:memory:` y después el `ATTACH` del archivo (session-spec §2).

        Si el `ATTACH` falla, la sesión queda en memoria, `READY`, y se informa con `AttachFailed`.
        """
        if self._sm.state not in (SessionState.DISCONNECTED, SessionState.ERROR_RECOVERABLE):
            raise SessionStateError(f"No se puede iniciar una sesión en estado {self._sm.state.value}")
        self._pending_attach = request
        self.start_memory_session()  # si el arranque falla, _fail descarta el ATTACH pendiente

    def attach_database(self, request: AttachRequest) -> None:
        """AttachDatabase: «Abrir existente» o «Crear nueva». La sesión pasa por `BUSY`."""
        if self._sm.state is not SessionState.READY or self._engine is None:
            raise SessionStateError(f"No se puede adjuntar una base en estado {self._sm.state.value}")
        engine = self._engine
        self._sm.transition(SessionState.BUSY)
        attaching = engine.attach(request)
        attaching.add_done_callback(lambda fut: self._dispatcher.post(lambda: self._on_attached(engine, fut)))

    def close_session(self) -> Future[None]:
        """CloseSession(): cancela lo que esté en curso y cierra el motor sin bloquear la UI."""
        state = self._sm.state
        if state is SessionState.DISCONNECTED or state is SessionState.CLOSING:
            done: Future[None] = Future()
            done.set_result(None)
            return done
        engine, self._engine = self._engine, None
        self._info = None
        self._pending_attach = None
        self._drop_catalog()
        if engine is None:  # ERROR_RECOVERABLE sin motor vivo
            self._sm.transition(SessionState.DISCONNECTED)
            done = Future()
            done.set_result(None)
            return done
        self._sm.transition(SessionState.CLOSING)
        closed = engine.close()
        closed.add_done_callback(lambda _f: self._dispatcher.post(self._on_closed))
        return closed

    def refresh_catalog(self) -> None:
        """Relee el catálogo de DuckDB. La sesión debe estar `READY`.

        Es una introspección interna y breve, encolada en el worker serial: no cambia el estado de la
        sesión. El resultado se aplica en el hilo principal y solo si sigue siendo la lectura más reciente
        de la misma sesión.
        """
        if self._sm.state is not SessionState.READY or self._engine is None:
            raise SessionStateError(f"No se puede leer el catálogo en estado {self._sm.state.value}")
        engine = self._engine
        self._catalog_generation += 1
        generation = self._catalog_generation
        reading = engine.read_catalog()
        reading.add_done_callback(
            lambda fut: self._dispatcher.post(lambda: self._on_catalog(engine, generation, fut))
        )

    def cancel_current_operation(self) -> bool:
        return self._engine.cancel_current() if self._engine is not None else False

    def shutdown(self, timeout: float = 10.0) -> bool:
        """Cierre bloqueante para la descarga del complemento. Devuelve False si venció el plazo."""
        closing = self.close_session()
        try:
            closing.result(timeout)
        except FutureTimeout:
            _log.warning("El motor no terminó en %.1f s al descargar GeoDuck", timeout)
            return False
        return True

    # -- finalizaciones (hilo principal) -----------------------------------------------------------

    def _on_started(self, engine: SessionEngine, fut: Future[EngineInfo]) -> None:
        if engine is not self._engine or self._sm.state is not SessionState.CONNECTING:
            return  # la sesión se cerró mientras arrancaba
        exc = fut.exception()
        if exc is not None:
            self._engine = None
            self._fail(exc)
            return
        self._info = fut.result()
        self._sm.transition(SessionState.READY)
        self._emit(SessionStarted(self._info))
        engine.invalidation().add_done_callback(
            lambda inv: self._dispatcher.post(lambda: self._on_invalidated(engine, inv))
        )
        pending, self._pending_attach = self._pending_attach, None
        if pending is not None:
            self.attach_database(pending)  # el resultado trae el catálogo
        else:
            self.refresh_catalog()

    def _on_attached(self, engine: SessionEngine, fut: Future[AttachResult]) -> None:
        if engine is not self._engine or self._sm.state is not SessionState.BUSY:
            return  # la sesión se cerró o se invalidó mientras tanto
        exc = fut.exception()
        if isinstance(exc, SessionInvalidatedError):
            return  # la invalidación llega por su propio camino y lleva a ERROR_RECOVERABLE
        self._sm.transition(SessionState.READY)
        if exc is None:
            result = fut.result()
            self._catalog_generation += 1  # cualquier lectura anterior queda superada
            self._catalog = result.catalog
            self._emit(CatalogChanged(result.catalog))
            self._emit(DatabaseAttached(result.database))
            return
        if isinstance(exc, GeoDuckError):
            code, message = exc.code, exc.message
        else:
            code, message = ErrorCode.ENGINE_ERROR, f"{type(exc).__name__}: {exc}"
        _log.warning("No se adjuntó la base [%s]", code.value)
        self._emit(AttachFailed(code, message))
        self.refresh_catalog()  # el catálogo se relee de DuckDB; nunca se supone

    def _on_catalog(self, engine: SessionEngine, generation: int, fut: Future[CatalogSnapshot]) -> None:
        if engine is not self._engine or generation != self._catalog_generation:
            return  # sesión cerrada o lectura superada por otra más reciente
        exc = fut.exception()
        if exc is None:
            self._catalog = fut.result()
            self._emit(CatalogChanged(self._catalog))
            return
        self._catalog = None
        if isinstance(exc, GeoDuckError):
            code, message = exc.code, exc.message
        else:
            code, message = ErrorCode.ENGINE_ERROR, f"{type(exc).__name__}: {exc}"
        _log.warning("No se pudo leer el catálogo [%s]", code.value)
        self._emit(CatalogUnavailable(code, message))

    def _drop_catalog(self) -> None:
        """Sin sesión no hay catálogo: se descarta y se anulan las lecturas en curso."""
        self._catalog_generation += 1
        if self._catalog is not None:
            self._catalog = None
            self._emit(CatalogChanged(None))

    def _on_invalidated(self, engine: SessionEngine, fut: Future[SessionInvalidatedError | None]) -> None:
        """C13 §4 bis: el motor ya rechazó el trabajo nuevo, falló lo pendiente y cerró la conexión."""
        if engine is not self._engine:
            return  # sesión ya cerrada o sustituida: un cierre pedido no es una invalidación (INV-5)
        cause = fut.result()
        if cause is None:
            return
        self._engine = None
        self._info = None
        self._drop_catalog()
        _log.error("Sesión invalidada [%s]: %s", cause.code.value, cause.detail)
        self._sm.transition(SessionState.ERROR_RECOVERABLE, ErrorCause.SESSION_INVALIDATED)
        self._emit(SessionInvalidated(cause.code, cause.message, cause.detail))

    def _on_closed(self) -> None:
        if self._sm.state is SessionState.CLOSING:
            self._sm.transition(SessionState.DISCONNECTED)

    def _fail(self, exc: BaseException) -> None:
        self._pending_attach = None
        if isinstance(exc, GeoDuckError):
            code, message = exc.code, exc.message
        else:
            code, message = ErrorCode.ENGINE_ERROR, f"{type(exc).__name__}: {exc}"
        _log.warning("Fallo de sesión [%s]", code.value)
        self._sm.transition(SessionState.ERROR_RECOVERABLE, ErrorCause.START_FAILED)
        self._emit(SessionFailed(code, message))

    def _emit(self, event: AppEvent) -> None:
        for listener in list(self._listeners):
            listener(event)
