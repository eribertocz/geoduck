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
6. Invalidación (C13 §4 bis): si la conexión deja de ser utilizable, primero se rechaza todo trabajo
   nuevo, se falla lo pendiente y se cierra la conexión; después `invalidation()` se resuelve una sola
   vez con la causa. Un cierre pedido nunca se notifica como invalidación.
7. Al cerrar, también al descargar el complemento o salir de QGIS, una transacción pendiente se revierte
   si es posible y nunca se confirma (decisión del 2026-11-01).
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

import duckdb

from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.catalog import (
    AttachRequest,
    AttachResult,
    CatalogSnapshot,
    ColumnInfo,
    DetachResult,
)
from geoduck.domain.completion import Vocabulary
from geoduck.domain.errors import (
    ActiveResultError,
    EngineError,
    ErrorCode,
    GeoDuckError,
    OperationCancelledError,
    SessionClosedError,
    SessionInvalidatedError,
    UnsupportedEngineError,
    WrongThreadError,
)
from geoduck.domain.export import ExportReport, ExportRequest
from geoduck.domain.i18n import tr
from geoduck.domain.operations import EngineInfo, ReadOutcome, ReadSummary, StatementOutcome
from geoduck.domain.sql import DEFAULT_PREVIEW_LIMIT, RunScope, ScriptRun, SqlStatement
from geoduck.domain.transaction import TransactionState
from geoduck.engine.attach import attach_database
from geoduck.engine.bridge_read import DEFAULT_BATCH, LoadOutcome, load_query, prepare_load
from geoduck.engine.catalog import read_catalog, read_columns, read_vocabulary
from geoduck.engine.compat import MINIMUM, EngineCapabilities, is_interrupt_error
from geoduck.engine.detach import detach_database
from geoduck.engine.export import export_query
from geoduck.engine.spatial import activate_spatial, spatial_state
from geoduck.engine.sql import StatementListener, run_in_database, run_script
from geoduck.engine.transactions import commit, is_aborted_error, probe_transaction, rollback

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
            raise OperationCancelledError(tr("Operation cancelled"))


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
            raise WrongThreadError(tr("The DuckDB connection can only be used from its owner thread"))
        if self._closed:
            raise SessionClosedError(tr("The session is closed"))
        if self._reader_open:
            raise ActiveResultError(
                tr("There is an open Arrow reader in this session; finish or cancel the reading first")
            )

    def extract_statements(self, text: str) -> list[Any]:
        """Divide un script con el parser oficial de DuckDB (sql-editor-spec §2). Pasa por el guardia."""
        self._guard()
        return list(self._con.extract_statements(text))

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
        types = [str(d[1]) for d in description]
        geometry = [i for i, t in enumerate(types) if is_geometry_type(t)]
        if geometry and not self._caps.python_geometry:
            # DuckDB 1.5.0 no convierte GEOMETRY a Python («Unsupported type»): vista previa por Arrow.
            fetched = _arrow_preview(result, max_rows + 1, types)
        else:
            fetched = result.fetchmany(max_rows + 1)
            if geometry:  # misma presentación en todas las versiones: «TIPO · n B»
                fetched = [
                    tuple(describe_wkb(v) if i in geometry else v for i, v in enumerate(row))
                    for row in fetched
                ]
        truncated = len(fetched) > max_rows
        if self._caps.has_complete:
            self._con.complete()
        return StatementOutcome(
            columns=tuple(str(d[0]) for d in description),
            rows=tuple(tuple(r) for r in fetched[:max_rows]),
            truncated=truncated,
            types=tuple(str(d[1]) for d in description),
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
                tr("The statement produces no rows; it cannot be read as Arrow"),
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

    @contextmanager
    def registered(self, name: str, data: Any) -> Iterator[None]:
        """Registra un objeto Arrow como vista temporal durante el bloque (escrituras por lotes, ADR-0012)."""
        self._guard()
        self._con.register(name, data)
        try:
            yield
        finally:
            self._con.unregister(name)

    def execute_many(self, sql: str, rows: Sequence[Sequence[object]]) -> None:
        """Ejecuta una sentencia parametrizada por cada fila (sin resultado)."""
        self._guard()
        self._con.executemany(sql, [list(r) for r in rows])

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
    #: `interrupt()` se llamó durante este trabajo; obliga a verificar la conexión después (ADR-0007 §3),
    #: aunque el trabajo haya absorbido el error (p. ej. una lectura Arrow que devuelve CANCELLED).
    engine_interrupted: bool = False


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
        #: (nivel, orden de llegada, trabajo). Nivel 0: lecturas del mapa (ADR-0012 §5); 1: el resto;
        #: 2: fin del bucle. Dentro de cada nivel se respeta el orden de llegada.
        self._queue: queue.PriorityQueue[tuple[int, int, _Job[Any] | None]] = queue.PriorityQueue()
        self._order = itertools.count()
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending: dict[int, _Job[Any]] = {}
        self._current: _Job[Any] | None = None
        self._con: Any = None  # solo se usa en el hilo del worker; interrupt() es la excepción
        self._caps: EngineCapabilities | None = None
        self._root = ""
        self._accepting = False
        self._close_requested = False
        self._invalidated: SessionInvalidatedError | None = None
        self._thread: threading.Thread | None = None
        self._started: Future[EngineInfo] = Future()
        self._stopped: Future[None] = Future()
        self._invalidation: Future[SessionInvalidatedError | None] = Future()

    # -- ciclo de vida ---------------------------------------------------------------------------

    def start(self) -> Future[EngineInfo]:
        with self._lock:
            if self._thread is not None:
                raise GeoDuckError("The worker has already started", code=ErrorCode.INVALID_TRANSITION)
            self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
            self._thread.start()
        return self._started

    def close(self) -> Future[None]:
        """Cierra sin bloquear: rechaza trabajo nuevo, cancela el pendiente y el actual.

        El `Future` devuelto se completa cuando la conexión ya está cerrada; es lo último que hace el
        hilo, que termina inmediatamente después (use `thread.join()` si necesita esperar al hilo).
        """
        with self._lock:
            self._close_requested = True
            if self._thread is None:
                _resolve(self._invalidation, None)
                _resolve(self._stopped, None)
                return self._stopped
            was_accepting = self._accepting
            self._accepting = False
            for job in self._pending.values():
                job.token.cancel()
            self._interrupt_current_locked()
        if was_accepting or not self._started.done():
            self._queue.put((_STOP, next(self._order), None))
        return self._stopped

    def invalidation(self) -> Future[SessionInvalidatedError | None]:
        """Se resuelve una sola vez cuando el hilo termina, después de cerrar la conexión.

        Resultado: la causa (`SessionInvalidatedError`) si la sesión se invalidó; `None` si terminó por un
        cierre pedido o porque no llegó a arrancar. Nunca se resuelve con una excepción.
        """
        return self._invalidation

    @property
    def capabilities(self) -> EngineCapabilities | None:
        return self._caps

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    # -- operaciones ------------------------------------------------------------------------------

    def read_catalog(self) -> Future[CatalogSnapshot]:
        """Instantánea del catálogo, leída de DuckDB en una sola operación serial."""
        root = self._root
        return self._submit_future(lambda h, _t: read_catalog(h, root))

    def list_columns(self, database: str, schema: str, name: str) -> Future[tuple[ColumnInfo, ...]]:
        """Columnas de una tabla o vista (session-spec `ListColumns`), en una operación serial breve."""
        return self._submit_future(lambda h, _t: read_columns(h, database, schema, name))

    def vocabulary(self) -> Future[Vocabulary]:
        """Palabras clave y funciones de la sesión (`duckdb_keywords()`, `duckdb_functions()`)."""
        return self._submit_future(lambda h, _t: read_vocabulary(h))

    def attach(self, request: AttachRequest) -> Future[AttachResult]:
        """«Abrir existente» o «Crear nueva» (`geoduck.engine.attach`), en una sola operación serial."""
        root = self._root
        return self._submit_future(lambda h, _t: attach_database(h, request, root))

    def spatial_state(self) -> Future[Any]:
        """Estado de `spatial` en la sesión (sin instalar ni cargar nada)."""
        return self._submit_future(lambda h, _t: spatial_state(h))

    def activate_spatial(self, *, install: bool) -> Future[Any]:
        """`INSTALL` (si `install`) y `LOAD spatial`, con consentimiento del usuario (spatial-spec §10)."""
        return self._submit_future(lambda h, _t: activate_spatial(h, install=install))

    def prepare_load(
        self,
        sql: str,
        geometry: str | None = None,
        formats: Mapping[str, Any] | None = None,
        *,
        database: str | None = None,
    ) -> Future[Any]:
        """Plan de carga (columnas normalizadas, geometrías, avisos) sin leer los datos. `database`: base
        donde se ejecutó el resultado (G7); la base en uso no cambia."""
        try:
            return self.submit(
                lambda h, _t: prepare_load(h, sql, geometry, pick_first=True, formats=formats),
                database=database,
            ).future
        except SessionClosedError as exc:
            failed: Future[Any] = Future()
            failed.set_exception(exc)
            return failed

    def load_query(
        self,
        sql: str,
        *,
        geometry: str | None = None,
        formats: Mapping[str, Any] | None = None,
        batch_size: int = DEFAULT_BATCH,
        on_plan: Callable[[Any], None],
        on_batch: Callable[[Any], None],
        database: str | None = None,
    ) -> OperationHandle[LoadOutcome]:
        """Lectura normalizada por lotes de una consulta repetible (qgis-bridge-spec §2).

        `on_plan` y `on_batch` llegan en el hilo del worker; el consumidor aplica la contrapresión.
        `database`: base donde se ejecutó el resultado (G7); la base en uso no cambia.
        """
        return self.submit(
            lambda h, t: load_query(
                h,
                t,
                sql,
                geometry=geometry,
                formats=formats,
                batch_size=batch_size,
                on_plan=on_plan,
                on_batch=on_batch,
            ),
            database=database,
        )

    def export_query(self, request: ExportRequest) -> OperationHandle[ExportReport]:
        """«Exportar ▾» (G7 · E3): `COPY` de la consulta completa, en la base del resultado; cancelable."""
        return self.submit(lambda h, t: export_query(h, t, request), database=request.database)

    def read_table(
        self, sql: str, *, priority: bool = True, database: str | None = None
    ) -> OperationHandle[Any]:
        """Lee entera una consulta acotada (una página de una capa Conectada) como `pyarrow.Table`.

        Quien llama limita la consulta (`LIMIT`); el worker queda libre en cuanto termina la lectura.
        `database`: base del resultado de una celda (G7); la base en uso no cambia.
        """

        def read(handle: ConnectionHandle, token: CancelToken) -> Any:
            batches: list[Any] = []
            summary = handle.read_arrow(sql, batch_size=DEFAULT_BATCH, on_batch=batches.append, token=token)
            if summary.outcome is ReadOutcome.CANCELLED:
                raise OperationCancelledError(tr("Reading cancelled"))
            if summary.outcome is ReadOutcome.FAILED:
                raise EngineError(summary.error)
            return batches

        return self.submit(read, priority=priority, database=database)

    def query(
        self, sql: str, *, max_rows: int = 1000, priority: bool = True, database: str | None = None
    ) -> OperationHandle[StatementOutcome]:
        """Consulta corta de metadatos (columnas, clave, extensión) con prioridad de lectura del mapa."""
        return self.submit(
            lambda h, _t: h.execute(sql, max_rows=max_rows), priority=priority, database=database
        )

    def detach(self, alias: str) -> Future[DetachResult]:
        """DetachDatabase (`geoduck.engine.detach`), en una sola operación serial."""
        root = self._root
        return self._submit_future(lambda h, _t: detach_database(h, alias, root))

    def transaction_state(self) -> Future[TransactionState]:
        """Estado transaccional real, comprobado sin modificarlo."""
        return self._submit_future(lambda h, _t: probe_transaction(h))

    def commit(self) -> Future[TransactionState]:
        """COMMIT solo si hay una transacción abierta y utilizable; nunca de una abortada (F-07)."""
        return self._submit_future(lambda h, _t: commit(h))

    def rollback(self) -> Future[TransactionState]:
        return self._submit_future(lambda h, _t: rollback(h))

    def run_script(
        self,
        *,
        run_id: int,
        text: str,
        scope: RunScope,
        cursor: int = 0,
        base: int = 0,
        preview_limit: int = DEFAULT_PREVIEW_LIMIT,
        on_statement: StatementListener | None = None,
        guard: Callable[[SqlStatement], str | None] | None = None,
        database: str | None = None,
    ) -> OperationHandle[ScriptRun]:
        """Ejecuta SQL del usuario en una sola operación serial (`geoduck.engine.sql`). Se cancela con
        `cancel(handle.op_id)`."""
        return self.submit(
            lambda h, token: run_script(
                h,
                token,
                run_id=run_id,
                text=text,
                scope=scope,
                cursor=cursor,
                base=base,
                preview_limit=preview_limit,
                on_statement=on_statement,
                guard=guard,
                database=database,
            )
        )

    def _submit_future(self, fn: Operation[T]) -> Future[T]:
        """Como `submit`, pero una sesión que no acepta trabajo se entrega como `Future` fallido."""
        try:
            return self.submit(fn).future
        except SessionClosedError as exc:
            failed: Future[T] = Future()
            failed.set_exception(exc)
            return failed

    def submit(
        self, fn: Operation[T], *, priority: bool = False, database: str | None = None
    ) -> OperationHandle[T]:
        """Encola una operación. `priority`: lectura corta del mapa (página de una capa Conectada), que se
        atiende antes que el trabajo en cola sin interrumpir la operación en curso (ADR-0012 §5).
        `database` (G7): la operación corre con esa base en uso y después la base en uso vuelve a la de
        antes (el resultado de una celda se repite en la base donde se ejecutó)."""
        if database is not None:
            inner = fn

            def fn(handle: ConnectionHandle, token: CancelToken) -> T:
                return run_in_database(handle, database, lambda: inner(handle, token))

        with self._lock:
            if not self._accepting:
                if self._invalidated is not None:
                    raise self._invalidated.fresh()
                raise SessionClosedError(tr("The session does not accept operations"))
            job: _Job[T] = _Job(next(self._ids), fn)
            self._pending[job.op_id] = job
            self._queue.put((_PRIORITY if priority else _NORMAL, next(self._order), job))
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
            job.engine_interrupted = True
            self._con.interrupt()

    # -- hilo del worker --------------------------------------------------------------------------

    def _open(self) -> tuple[Any, EngineCapabilities, str]:
        """Abre la conexión en este hilo y lee el nombre real del catálogo raíz."""
        caps = EngineCapabilities.for_version(duckdb.__version__)
        if not caps.supported:
            minimum = ".".join(map(str, MINIMUM))
            raise UnsupportedEngineError(
                tr("DuckDB {0} is not supported; {1} or later is required").format(
                    duckdb.__version__, minimum
                )
            )
        con = duckdb.connect(database=self._database)
        try:
            root = str(con.execute("SELECT current_database()").fetchall()[0][0])
        except BaseException:
            con.close()
            raise
        return con, caps, root

    def _run(self) -> None:
        try:
            con, caps, root = self._open()
        except BaseException as exc:
            self._started.set_exception(_wrap_start_error(exc))
            _resolve(self._invalidation, None)
            self._stopped.set_result(None)
            return

        handle = ConnectionHandle(con, threading.get_ident(), caps)
        with self._lock:
            self._con = con
            self._caps = caps
            self._root = root
            self._accepting = True
        self._started.set_result(
            EngineInfo(
                duckdb_version=duckdb.__version__,
                database=self._database,
                interrupt_enabled=caps.interrupt_verified,
                root_catalog=root,
            )
        )
        cause: SessionInvalidatedError | None = None
        try:
            cause = self._loop(handle)
        except BaseException as exc:  # un fallo del propio bucle: el hilo no puede seguir
            _log.exception("El hilo de la sesión terminó inesperadamente")
            cause = SessionInvalidatedError(
                tr("The session thread ended unexpectedly; the session was invalidated"),
                detail=type(exc).__name__,
            )
        finally:
            if cause is None:
                self._rollback_pending(handle)  # nunca hay COMMIT automático (decisión del 2026-11-01)
            with self._lock:
                if self._close_requested:
                    cause = None  # un cierre pedido nunca se notifica como invalidación (INV-5)
                self._invalidated = cause
                self._accepting = False
                self._con = None
                leftovers = list(self._pending.values())
                self._pending.clear()
            for job in leftovers:
                if not job.future.done():
                    job.future.set_exception(
                        cause.fresh()
                        if cause is not None
                        else SessionClosedError(tr("The session was closed"))
                    )
            handle._close()
            try:
                con.close()
            except Exception:
                _log.warning("No se pudo cerrar la conexión DuckDB", exc_info=True)
            finally:
                _resolve(self._invalidation, cause)
                self._stopped.set_result(None)

    def _loop(self, handle: ConnectionHandle) -> SessionInvalidatedError | None:
        """Ejecuta trabajos hasta un cierre pedido (`None`) o una invalidación (la causa)."""
        while True:
            _level, _order, job = self._queue.get()
            if job is None:
                return None
            if not job.future.set_running_or_notify_cancel():
                self._forget(job)
                continue
            with self._lock:
                self._current = job
            result, failure, fatal, interrupted = self._execute(job, handle)
            with self._lock:
                self._current = None  # ya nada puede interrumpir esta operación (ni la comprobación)
            unusable = None
            if fatal is None and (failure is not None or interrupted or job.engine_interrupted):
                unusable = self._verify_after(handle, failure, interrupted or job.engine_interrupted)
            self._deliver(job, result, failure)
            if fatal is not None:
                _log.error("Error fatal de DuckDB; se invalida la sesión")
                return fatal
            if unusable is not None:
                _log.error("La conexión no es utilizable [%s]; se invalida la sesión", unusable.detail)
                return unusable

    @staticmethod
    def _execute(
        job: _Job[Any], handle: ConnectionHandle
    ) -> tuple[Any, BaseException | None, SessionInvalidatedError | None, bool]:
        """Ejecuta un trabajo. Devuelve (resultado, fallo clasificado, invalidación fatal, interrumpido)."""
        try:
            job.token.raise_if_cancelled()
            return job.fn(handle, job.token), None, None, False
        except BaseException as exc:
            interrupted = is_interrupt_error(exc)
            fatal_cause = _fatal_in_chain(exc)
            if fatal_cause is None:
                return None, _classify(exc, job.token), None, interrupted
            fatal = SessionInvalidatedError(
                tr("DuckDB reported a fatal error; the session was invalidated"),
                detail=_first_line(fatal_cause),
            )
            return None, fatal.fresh(), fatal, interrupted

    def _verify_after(
        self, handle: ConnectionHandle, failure: BaseException | None, interrupted: bool
    ) -> SessionInvalidatedError | None:
        """ADR-0007 §3 y punto 6: tras un fallo o una interrupción, la conexión debe responder y su estado
        transaccional debe ser conocido antes de reutilizarla. Se comprueba antes de entregar el resultado,
        y el estado se adjunta al error. Devuelve la causa de invalidación si no es utilizable."""
        state = self._check_connection(handle)
        if state is None:
            if interrupted:
                return SessionInvalidatedError(
                    tr(
                        "The DuckDB connection does not respond after an interruption; the "
                        "session was invalidated"
                    ),
                    detail="unresponsive_after_interrupt",
                )
            return SessionInvalidatedError(
                tr("The state of the connection could not be checked; the session was invalidated"),
                detail="transaction_state_unknown",
            )
        if isinstance(failure, GeoDuckError):
            failure.transaction = state
        return None

    def _deliver(self, job: _Job[Any], result: Any, failure: BaseException | None) -> None:
        try:
            if failure is not None:
                job.future.set_exception(failure)
            else:
                job.future.set_result(result)
        finally:
            with self._lock:
                self._pending.pop(job.op_id, None)

    def _forget(self, job: _Job[Any]) -> None:
        with self._lock:
            self._pending.pop(job.op_id, None)

    @staticmethod
    def _rollback_pending(handle: ConnectionHandle) -> None:
        """Al cerrar (incluida la descarga del complemento o la salida de QGIS), revierte una transacción
        pendiente cuando es posible. Nunca la confirma. Solo se intenta si la conexión no se invalidó; si no
        se puede, cerrar la conexión la descarta igualmente."""
        try:
            if probe_transaction(handle).is_open:
                handle.execute("ROLLBACK")
                _log.warning("Se revirtió una transacción pendiente al cerrar la sesión")
        except Exception:
            _log.warning("No se pudo revertir la transacción al cerrar; DuckDB la descarta", exc_info=True)

    @staticmethod
    def _check_connection(handle: ConnectionHandle) -> TransactionState | None:
        """Verificación posterior de ADR-0007 §3 y punto 6, en el hilo propietario.

        Devuelve el estado transaccional si la conexión responde (una transacción abortada responde: solo
        admite `ROLLBACK`), o `None` si no responde o el estado no puede determinarse.
        """
        try:
            return probe_transaction(handle)
        except Exception:
            return None


def _fatal_in_chain(exc: BaseException) -> BaseException | None:
    """Busca un `duckdb.FatalException` en la cadena de causas: una operación que envuelve el error
    (p. ej. para clasificarlo) no puede ocultar que la base quedó invalidada."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, duckdb.FatalException):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _resolve(future: Future[Any], value: Any) -> None:
    if not future.done():
        future.set_result(value)


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _classify(exc: BaseException, token: CancelToken) -> BaseException:
    if isinstance(exc, GeoDuckError):
        return exc
    if is_interrupt_error(exc) or (token.cancelled and isinstance(exc, (duckdb.Error, OSError))):
        return OperationCancelledError(tr("Operation cancelled"), detail=type(exc).__name__)
    if isinstance(exc, duckdb.Error) and is_aborted_error(exc):
        return GeoDuckError(
            tr("The transaction is aborted; it can only be rolled back (ROLLBACK)."),
            code=ErrorCode.TRANSACTION_ABORTED,
            detail=type(exc).__name__,
        )
    if isinstance(exc, duckdb.Error):
        return EngineError(_first_line(exc), detail=type(exc).__name__)
    return exc


def _wrap_start_error(exc: BaseException) -> BaseException:
    if isinstance(exc, GeoDuckError):
        return exc
    if isinstance(exc, duckdb.Error):
        return EngineError(
            tr("DuckDB could not start: {0}").format(_first_line(exc)), detail=type(exc).__name__
        )
    return exc


_PRIORITY, _NORMAL, _STOP = 0, 1, 2

_WKB_NAMES = {
    1: "POINT",
    2: "LINESTRING",
    3: "POLYGON",
    4: "MULTIPOINT",
    5: "MULTILINESTRING",
    6: "MULTIPOLYGON",
    7: "GEOMETRYCOLLECTION",
}


def describe_wkb(value: bytes | None) -> str | None:
    """Texto breve para la vista previa: tipo de geometría y tamaño del WKB."""
    if value is None:
        return None
    if len(value) < 5:
        return f"GEOMETRY · {len(value)} B"
    code = int.from_bytes(value[1:5], "little" if value[0] == 1 else "big")
    name = _WKB_NAMES.get(code % 1000, "GEOMETRY")
    suffix = {1: " Z", 2: " M", 3: " ZM"}.get(code // 1000, "")
    return f"{name}{suffix} · {len(value)} B"


def _arrow_preview(result: Any, limit: int, types: list[str]) -> list[tuple[Any, ...]]:
    """Hasta `limit` filas leídas por Arrow; las columnas de geometría se describen como texto."""
    reader = result.fetch_record_batch(limit)  # solo en 1.5.0, donde es la API vigente
    rows: list[tuple[Any, ...]] = []
    try:
        for batch in reader:
            columns = batch.to_pydict()
            values = [
                [describe_wkb(v) for v in col] if is_geometry_type(types[i]) else col
                for i, col in enumerate(columns.values())
            ]
            rows.extend(zip(*values, strict=True))
            if len(rows) >= limit:
                break
    finally:
        reader.close()
    return rows[:limit]
