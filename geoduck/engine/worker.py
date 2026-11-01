# SPDX-License-Identifier: GPL-2.0-or-later
"""Session Worker: único propietario de la conexión DuckDB (ADR-0006, ADR-0007).

Invariantes que este módulo garantiza en DuckDB 1.5.x y 2.x por igual:

1. La conexión se crea, se usa y se cierra en un solo hilo (el del worker).
2. Las operaciones se ejecutan en serie, en orden de llegada.
3. Mientras hay un lector Arrow abierto, cualquier otra sentencia se rechaza con `ActiveResultError`
   antes de llegar a DuckDB (DuckDB 1.5.x truncaría el lector sin error: evidencia F-01).
4. Una lectura solo es completa si el lector se agotó (`ReadSummary.completed`).
5. La única llamada a la conexión desde otro hilo es `interrupt()`, dentro de `cancel()`, y solo en
   versiones verificadas (`EngineCapabilities.interrupt_verified`).
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import duckdb

from geoduck.domain.errors import (
    ActiveResultError,
    EngineError,
    ErrorCode,
    GeoDuckError,
    OperationCancelledError,
    SessionClosedError,
    UnsupportedEngineError,
    WrongThreadError,
)
from geoduck.domain.operations import EngineInfo, ReadOutcome, ReadSummary, StatementOutcome
from geoduck.engine.compat import MINIMUM, EngineCapabilities, is_interrupt_error

_log = logging.getLogger("geoduck.engine")

T = TypeVar("T")


class CancelToken:
    """Señal de cancelación cooperativa; se consulta entre lotes y entre sentencias."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelledError("Operación cancelada")


class ConnectionHandle:
    """Única vía de acceso a la conexión. Solo es válida dentro del hilo del worker."""

    def __init__(self, con: Any, owner_ident: int, caps: EngineCapabilities) -> None:
        self._con = con
        self._owner = owner_ident
        self._caps = caps
        self._reader_open = False
        self._closed = False

    @property
    def capabilities(self) -> EngineCapabilities:
        return self._caps

    @property
    def reader_open(self) -> bool:
        return self._reader_open

    def _guard(self) -> None:
        if threading.get_ident() != self._owner:
            raise WrongThreadError("La conexión DuckDB solo puede usarse desde su hilo propietario")
        if self._closed:
            raise SessionClosedError("La sesión está cerrada")
        if self._reader_open:
            raise ActiveResultError(
                "Hay un lector Arrow abierto en esta sesión; termine o cancele la lectura primero"
            )

    def execute(
        self, sql: str, parameters: Sequence[object] | None = None, *, max_rows: int = 200
    ) -> StatementOutcome:
        """Ejecuta una sentencia y devuelve como mucho `max_rows` filas.

        Nunca materializa resultados sin límite (NF-02). Si quedan filas sin leer en DuckDB 2.x, el
        resultado se cierra con `complete()` para no dejar la conexión ocupada.
        """
        self._guard()
        result = self._con.execute(sql) if parameters is None else self._con.execute(sql, parameters)
        description = result.description
        if not description:
            return StatementOutcome()
        fetched = result.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        if self._caps.has_complete:
            self._con.complete()
        return StatementOutcome(
            columns=tuple(str(d[0]) for d in description),
            rows=tuple(tuple(r) for r in fetched[:max_rows]),
            truncated=truncated,
        )

    @contextmanager
    def arrow_batches(self, sql: str, *, batch_size: int) -> Iterator[Any]:
        """Abre un lector Arrow por lotes sobre una relación de lectura construida por GeoDuck.

        El lector se cierra siempre al salir del bloque. Mientras está abierto, la conexión rechaza
        cualquier otra operación (invariante 3).
        """
        self._guard()
        if batch_size <= 0:
            raise GeoDuckError("batch_size debe ser positivo", code=ErrorCode.INVALID_ARGUMENT)
        relation = self._con.sql(sql)
        if relation is None:
            raise GeoDuckError(
                "La sentencia no produce filas; no se puede leer como Arrow",
                code=ErrorCode.INVALID_ARGUMENT,
            )
        reader = relation.to_arrow_reader(batch_size=batch_size)
        self._reader_open = True
        try:
            yield reader
        finally:
            try:
                reader.close()
            finally:
                self._reader_open = False

    def read_arrow(
        self,
        sql: str,
        *,
        batch_size: int,
        on_batch: Callable[[Any], None],
        token: CancelToken,
    ) -> ReadSummary:
        """Lee una relación por lotes, entregando cada `RecordBatch` a `on_batch` en este hilo.

        Devuelve `EXHAUSTED` solo si el lector se agotó sin cancelación (invariante 4). Las excepciones
        de `on_batch` se propagan: un consumidor que falla no puede producir una lectura «completa».
        """
        rows = batches = 0
        try:
            with self.arrow_batches(sql, batch_size=batch_size) as reader:
                for batch in reader:
                    if token.cancelled:
                        return ReadSummary(rows, batches, ReadOutcome.CANCELLED)
                    on_batch(batch)
                    rows += batch.num_rows
                    batches += 1
        except Exception as exc:
            if token.cancelled or is_interrupt_error(exc):
                return ReadSummary(rows, batches, ReadOutcome.CANCELLED, error=type(exc).__name__)
            if isinstance(exc, duckdb.Error):
                return ReadSummary(rows, batches, ReadOutcome.FAILED, error=_first_line(exc))
            raise
        if token.cancelled:
            return ReadSummary(rows, batches, ReadOutcome.CANCELLED)
        return ReadSummary(rows, batches, ReadOutcome.EXHAUSTED)

    def _close(self) -> None:
        self._closed = True


Operation = Callable[[ConnectionHandle, CancelToken], T]


@dataclass
class _Job(Generic[T]):
    op_id: int
    fn: Operation[T]
    future: Future[T] = field(default_factory=Future)
    token: CancelToken = field(default_factory=CancelToken)


@dataclass(frozen=True)
class OperationHandle(Generic[T]):
    op_id: int
    future: Future[T]
    token: CancelToken


class SessionWorker:
    """Hilo propietario de una conexión DuckDB con cola serial de operaciones."""

    def __init__(self, database: str = ":memory:", *, name: str = "geoduck-session") -> None:
        self._database = database
        self._name = name
        self._queue: queue.Queue[_Job[Any] | None] = queue.Queue()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[int, _Job[Any]] = {}
        self._current: _Job[Any] | None = None
        self._con: Any = None  # solo se usa en el hilo del worker; interrupt() es la excepción
        self._caps: EngineCapabilities | None = None
        self._accepting = False
        self._thread: threading.Thread | None = None
        self._started: Future[EngineInfo] = Future()
        self._stopped: Future[None] = Future()

    # -- ciclo de vida ---------------------------------------------------------------------------

    def start(self) -> Future[EngineInfo]:
        with self._lock:
            if self._thread is not None:
                raise GeoDuckError("El worker ya se inició", code=ErrorCode.INVALID_TRANSITION)
            self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
            self._thread.start()
        return self._started

    def close(self) -> Future[None]:
        """Cierra sin bloquear: rechaza trabajo nuevo, cancela el pendiente y el actual.

        El `Future` devuelto se completa cuando el hilo terminó y la conexión está cerrada.
        """
        with self._lock:
            if self._thread is None:
                if not self._stopped.done():
                    self._stopped.set_result(None)
                return self._stopped
            was_accepting = self._accepting
            self._accepting = False
            for job in self._pending.values():
                job.token.cancel()
            self._interrupt_current_locked()
        if was_accepting or not self._started.done():
            self._queue.put(None)
        return self._stopped

    @property
    def capabilities(self) -> EngineCapabilities | None:
        return self._caps

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    # -- operaciones ------------------------------------------------------------------------------

    def submit(self, fn: Operation[T]) -> OperationHandle[T]:
        with self._lock:
            if not self._accepting:
                raise SessionClosedError("La sesión no acepta operaciones")
            job: _Job[T] = _Job(next(self._ids), fn)
            self._pending[job.op_id] = job
            self._queue.put(job)
        return OperationHandle(job.op_id, job.future, job.token)

    def cancel(self, op_id: int) -> bool:
        """Cancela una operación pendiente o en curso. Devuelve False si no existe."""
        with self._lock:
            job = self._pending.get(op_id)
            if job is None:
                return False
            job.token.cancel()
            if self._current is job:
                self._interrupt_current_locked()
            return True

    def cancel_current(self) -> bool:
        with self._lock:
            job = self._current
        return job is not None and self.cancel(job.op_id)

    def _interrupt_current_locked(self) -> None:
        """Excepción controlada de ADR-0007. Debe llamarse con `self._lock` adquirido.

        Con el lock tomado, el worker no puede cambiar de operación, así que la interrupción solo
        alcanza a la operación actual.
        """
        job = self._current
        if job is None or self._con is None or self._caps is None:
            return
        job.token.cancel()
        if self._caps.interrupt_verified:
            self._con.interrupt()

    # -- hilo del worker --------------------------------------------------------------------------

    def _run(self) -> None:
        try:
            caps = EngineCapabilities.for_version(duckdb.__version__)
            if not caps.supported:
                minimum = ".".join(map(str, MINIMUM))
                raise UnsupportedEngineError(
                    f"DuckDB {duckdb.__version__} no es compatible; se requiere {minimum} o superior"
                )
            con = duckdb.connect(database=self._database)
        except BaseException as exc:
            self._started.set_exception(_wrap_start_error(exc))
            self._stopped.set_result(None)
            return

        handle = ConnectionHandle(con, threading.get_ident(), caps)
        with self._lock:
            self._con = con
            self._caps = caps
            self._accepting = True
        self._started.set_result(
            EngineInfo(
                duckdb_version=duckdb.__version__,
                database=self._database,
                interrupt_enabled=caps.interrupt_verified,
            )
        )
        try:
            self._loop(handle)
        finally:
            with self._lock:
                self._accepting = False
                self._con = None
                leftovers = list(self._pending.values())
                self._pending.clear()
            for job in leftovers:
                if not job.future.done():
                    job.future.set_exception(SessionClosedError("La sesión se cerró"))
            handle._close()
            try:
                con.close()
            finally:
                self._stopped.set_result(None)

    def _loop(self, handle: ConnectionHandle) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            if not job.future.set_running_or_notify_cancel():
                self._forget(job)
                continue
            with self._lock:
                self._current = job
            interrupted = False
            try:
                job.token.raise_if_cancelled()
                result = job.fn(handle, job.token)
            except BaseException as exc:
                interrupted = is_interrupt_error(exc)
                job.future.set_exception(_classify(exc, job.token))
            else:
                job.future.set_result(result)
            finally:
                with self._lock:
                    self._current = None
                    self._pending.pop(job.op_id, None)
            if interrupted and not self._connection_responds(handle):
                _log.error("La conexión no responde tras una interrupción; se cierra la sesión")
                return

    def _forget(self, job: _Job[Any]) -> None:
        with self._lock:
            self._pending.pop(job.op_id, None)

    @staticmethod
    def _connection_responds(handle: ConnectionHandle) -> bool:
        """Verificación posterior de ADR-0007 §3, en el hilo propietario."""
        try:
            return handle.execute("SELECT 1").rows == ((1,),)
        except Exception:
            return False


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _classify(exc: BaseException, token: CancelToken) -> BaseException:
    if isinstance(exc, GeoDuckError):
        return exc
    if is_interrupt_error(exc) or (token.cancelled and isinstance(exc, (duckdb.Error, OSError))):
        return OperationCancelledError("Operación cancelada", detail=type(exc).__name__)
    if isinstance(exc, duckdb.Error):
        return EngineError(_first_line(exc), detail=type(exc).__name__)
    return exc


def _wrap_start_error(exc: BaseException) -> BaseException:
    if isinstance(exc, GeoDuckError):
        return exc
    if isinstance(exc, duckdb.Error):
        return EngineError(f"No se pudo iniciar DuckDB: {_first_line(exc)}", detail=type(exc).__name__)
    return exc
