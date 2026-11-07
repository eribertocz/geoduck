# SPDX-License-Identifier: GPL-2.0-or-later
"""Coordinador de sesión: StartSession (memoria y archivo), AttachDatabase, DetachDatabase, CloseSession,
CancelOperation,
invalidación y catálogo.

Vive en el hilo principal. Toda finalización del motor se reenvía al hilo principal mediante el
`Dispatcher` antes de cambiar el estado, de modo que la máquina de estados nunca se toca desde dos hilos.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import replace
from typing import Any

from geoduck.app.events import (
    AppEvent,
    AttachFailed,
    CatalogChanged,
    CatalogUnavailable,
    CloseConfirmationRequired,
    ColumnsListed,
    ColumnsUnavailable,
    DatabaseAttached,
    DatabaseDetached,
    DetachFailed,
    ExportFailed,
    ExportFinished,
    ExportStarted,
    LoadFailed,
    LoadFinished,
    LoadPrepared,
    LoadPrepareFailed,
    LoadProgressed,
    LoadStarted,
    PreviewsInvalidated,
    ScriptFinished,
    ScriptRejected,
    SendFailed,
    SendFinished,
    SendProgressed,
    SendStarted,
    SendUndoFailed,
    SendUndone,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
    SpatialActivated,
    SpatialActivationFailed,
    SpatialChecked,
    StatementFinished,
    TransactionFailed,
    TransactionStateChanged,
    VocabularyChanged,
)
from geoduck.app.ports import Dispatcher, EngineFactory, LayerLoader, LayerSender, LoadTask, SessionEngine
from geoduck.domain.catalog import (
    AttachRequest,
    AttachResult,
    CatalogSnapshot,
    ColumnInfo,
    DetachResult,
    catalog_key,
)
from geoduck.domain.completion import Vocabulary
from geoduck.domain.errors import ErrorCode, GeoDuckError, SessionInvalidatedError, SessionStateError
from geoduck.domain.export import ExportReport, ExportRequest
from geoduck.domain.i18n import tr
from geoduck.domain.importing import ImportedTable, ImportReport, ImportTarget, SendCandidate, SendRequest
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.domain.operations import EngineInfo, StatementOutcome
from geoduck.domain.session import ErrorCause, SessionState, SessionStateMachine
from geoduck.domain.sql import (
    DEFAULT_PREVIEW_LIMIT,
    RunScope,
    ScriptRun,
    SqlStatement,
    StatementResult,
    StatementStatus,
    detach_target,
)
from geoduck.domain.sql_text import load_sql
from geoduck.domain.transaction import CloseChoice, TransactionState

_log = logging.getLogger("geoduck.app")

Listener = Callable[[AppEvent], None]


class SessionCoordinator:
    def __init__(
        self,
        engine_factory: EngineFactory,
        dispatcher: Dispatcher,
        loader: LayerLoader | None = None,
        sender: LayerSender | None = None,
    ) -> None:
        self._factory = engine_factory
        self._loader = loader
        #: «Enviar a DuckDB» (G8); None si QGIS no está disponible.
        self._sender = sender
        self._send_ids = 0
        #: Carga en QGIS en curso (Memoria o Instantánea); la sesión está en BUSY mientras dura.
        self._load: LoadTask | None = None
        self._load_ids = 0
        self._export_ids = 0
        self._prepare_tokens = 0
        self._dispatcher = dispatcher
        self._sm = SessionStateMachine()
        self._sm.subscribe(lambda a, b: self._emit(SessionStateChanged(a, b)))
        self._engine: SessionEngine | None = None
        self._info: EngineInfo | None = None
        self._catalog: CatalogSnapshot | None = None
        #: Cada lectura del catálogo recibe un número; solo se aplica la más reciente.
        self._catalog_generation = 0
        #: Vocabulario de DuckDB (palabras clave y funciones) del catálogo mostrado: `(motor, catálogo, …)`.
        #: Se vuelve a leer tras un cambio de catálogo (p. ej. `LOAD` añade funciones).
        self._vocabulary: tuple[SessionEngine, CatalogSnapshot | None, Vocabulary] | None = None
        self._vocabulary_asked: tuple[SessionEngine, CatalogSnapshot | None] | None = None
        #: Columnas ya leídas del catálogo mostrado: `(catálogo, {(base, esquema, objeto): columnas})`.
        self._columns: tuple[CatalogSnapshot | None, dict[tuple[str, str, str], tuple[ColumnInfo, ...]]] = (
            None,
            {},
        )
        #: Archivo que se adjunta en cuanto la sesión esté lista (StartSession(mode=file)).
        self._pending_attach: AttachRequest | None = None
        #: Último estado transaccional comprobado en DuckDB; `None` sin sesión.
        self._transaction: TransactionState | None = None
        #: Un ROLLBACK de recuperación en curso desde ERROR_RECOVERABLE (no pasa por BUSY).
        self._recovering = False
        #: Cierre pedido por el usuario a la espera de su decisión o de que termine su COMMIT/ROLLBACK.
        self._close_choice: CloseChoice | None = None
        self._awaiting_close_decision = False
        self._close_generation = 0
        #: Época de datos: sube con todo lo que pueda cambiar estructura o datos (decisión del 2026-11-01).
        self._data_epoch = 0
        self._run_ids = 0
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
    def transaction_state(self) -> TransactionState | None:
        """Último estado transaccional comprobado en DuckDB (ADR-0007 punto 6); `None` sin sesión."""
        return self._transaction

    @property
    def dispatcher(self) -> Dispatcher:
        """El que lleva las respuestas al hilo principal (para encadenar trabajo, p. ej. celdas)."""
        return self._dispatcher

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

    @property
    def can_start(self) -> bool:
        """Se puede iniciar una sesión nueva: no hay sesión, o la anterior terminó sin motor vivo.

        Con `ERROR_RECOVERABLE` por una transacción abortada el motor sigue vivo (con su conexión y sus
        bloqueos): primero hay que revertir o cerrar.
        """
        return (
            self._sm.state in (SessionState.DISCONNECTED, SessionState.ERROR_RECOVERABLE)
            and self._engine is None
        )

    def start_memory_session(self) -> None:
        """StartSession(mode=memory): raíz `:memory:` (ADR-0001)."""
        if not self.can_start:
            raise SessionStateError(
                tr("A session cannot be started in state {0}").format(self._sm.state.value)
            )
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
        if not self.can_start:
            raise SessionStateError(
                tr("A session cannot be started in state {0}").format(self._sm.state.value)
            )
        self._pending_attach = request
        self.start_memory_session()  # si el arranque falla, _fail descarta el ATTACH pendiente

    def attach_database(self, request: AttachRequest) -> None:
        """AttachDatabase: «Abrir existente» o «Crear nueva». La sesión pasa por `BUSY`."""
        if self._sm.state is not SessionState.READY or self._engine is None:
            raise SessionStateError(
                tr("A database cannot be attached in state {0}").format(self._sm.state.value)
            )
        engine = self._engine
        self._sm.transition(SessionState.BUSY)
        attaching = engine.attach(request)
        attaching.add_done_callback(lambda fut: self._dispatcher.post(lambda: self._on_attached(engine, fut)))

    def _guard_unsaved(self, action: str, database: str | None = None) -> None:
        """qgis-bridge-spec §5.5: no se desadjunta ni se cierra con capas Conectadas sin guardar."""
        layers = self._loader.unsaved_layers(database) if self._loader is not None else []
        if layers:
            names = ", ".join(f"«{n}»" for n in layers[:3]) + ("…" if len(layers) > 3 else "")
            raise SessionStateError(
                tr("Cannot {0}: {1} has unsaved changes. Save or discard them first.").format(action, names)
            )

    def _detach_guard(self) -> Callable[[SqlStatement], str | None] | None:
        """Veto de un `DETACH` real (tipo del parser de DuckDB) de una base con capas Conectadas sin
        guardar (§5.5). Las bases y capas se leen aquí, en el hilo principal; el veto corre en el motor."""
        blocked = self._loader.unsaved_by_database() if self._loader is not None else {}
        if not blocked:
            return None

        def guard(statement: SqlStatement) -> str | None:
            target = detach_target(statement)
            if target is None:
                return None
            if not target:  # nombre ilegible: se protege todo
                layers = [n for v in blocked.values() for n in v]
            else:
                layers = blocked.get(target.lower(), []) + blocked.get("", [])
            if not layers:
                return None
            names = ", ".join(f"«{n}»" for n in layers[:3]) + ("…" if len(layers) > 3 else "")
            return tr(
                "Nothing was run: DETACH {0} with unsaved {1}. Save or discard those changes first."
            ).format(target or tr("(unknown database)"), names)

        return guard

    def detach_database(self, alias: str) -> None:
        """DetachDatabase: `DETACH` real. La sesión pasa por `DETACHING`.

        Al ejecutarse en el worker serial, nunca se adelanta a una lectura en curso (session-spec §6).
        Rechazado si una capa Conectada de esa base tiene cambios sin guardar.
        """
        if self._sm.state is not SessionState.READY or self._engine is None:
            raise SessionStateError(
                tr("A database cannot be detached in state {0}").format(self._sm.state.value)
            )
        self._guard_unsaved(tr("detach «{0}»").format(alias), alias)
        engine = self._engine
        self._sm.transition(SessionState.DETACHING)
        detaching = engine.detach(alias)
        detaching.add_done_callback(lambda fut: self._dispatcher.post(lambda: self._on_detached(engine, fut)))

    @property
    def data_epoch(self) -> int:
        return self._data_epoch

    def is_stale(self, epoch: int) -> bool:
        """Una vista previa de `epoch` es posiblemente obsoleta si después pudo cambiar algo en la sesión.
        No detecta cambios externos: una vista previa nunca es el estado actual garantizado."""
        return epoch < self._data_epoch

    def execute_sql(
        self,
        text: str,
        scope: RunScope,
        *,
        cursor: int = 0,
        base: int = 0,
        preview_limit: int = DEFAULT_PREVIEW_LIMIT,
        database: str | None = None,
    ) -> int:
        """GD-SQL-001/002/004: ejecuta la sentencia actual, la selección o todo. La sesión pasa por `BUSY`;
        se cancela con `cancel_current_operation`. Devuelve el `run_id`. `database`: base de la celda (G7)."""
        engine = self._require_ready(tr("run SQL"))
        if not text.strip():
            raise SessionStateError(tr("There is no SQL to run"))
        self._run_ids += 1
        run_id = self._run_ids
        self._sm.transition(SessionState.BUSY)

        def on_statement(result: StatementResult) -> None:  # hilo del motor
            self._dispatcher.post(lambda: self._on_statement(engine, run_id, result))

        handle = engine.run_script(
            guard=self._detach_guard(),
            run_id=run_id,
            text=text,
            scope=scope,
            cursor=cursor,
            base=base,
            preview_limit=preview_limit,
            on_statement=on_statement,
            database=database,
        )
        handle.future.add_done_callback(
            lambda fut: self._dispatcher.post(lambda: self._on_script(engine, fut))
        )
        return run_id

    def _on_statement(self, engine: SessionEngine, run_id: int, result: StatementResult) -> None:
        if engine is not self._engine:
            return
        epoch = self._data_epoch
        self._emit(StatementFinished(run_id, result, epoch))
        if result.status is not StatementStatus.SKIPPED and (
            result.statement.may_change_state or result.status is not StatementStatus.OK
        ):
            self._bump_epoch()  # invalidación conservadora: también tras un error o una cancelación

    def _on_script(self, engine: SessionEngine, fut: Future[ScriptRun]) -> None:
        if engine is not self._engine or self._sm.state is not SessionState.BUSY:
            return
        exc = fut.exception()
        if isinstance(exc, SessionInvalidatedError):
            return
        if exc is not None:
            code, message = _describe(exc)
            self._end_failed_operation(exc)
            self._emit(ScriptRejected(code, message))
            return
        run = fut.result()
        if run.last_transaction is not None:
            self._set_transaction(run.last_transaction)
        if self._transaction is TransactionState.ABORTED:
            # ADR-0007 punto 6: con la transacción abortada no se vuelve a READY hasta un ROLLBACK.
            self._sm.transition(SessionState.ERROR_RECOVERABLE, ErrorCause.TRANSACTION_ABORTED)
        else:
            self._sm.transition(SessionState.READY)
        self._emit(ScriptFinished(run))
        changed = any(
            r.status is not StatementStatus.SKIPPED and r.statement.may_change_state for r in run.results
        )
        # G7: el `USE` de la base de una celda cambia la base en uso sin ser una sentencia del usuario
        moved = (
            run.current_database is not None
            and self._catalog is not None
            and catalog_key(run.current_database) != catalog_key(self._catalog.default)
        )
        if (changed or moved) and self.state is SessionState.READY:
            self.refresh_catalog()  # GD-SES-003 (SQL): ATTACH/DETACH/CREATE/DROP se reflejan en el panel

    def mark_data_changed(self) -> None:
        """Un guardado de una capa Conectada cambió datos de la sesión (qgis-bridge-spec §5.4)."""
        self._bump_epoch()

    def _bump_epoch(self) -> None:
        self._data_epoch += 1
        self._emit(PreviewsInvalidated(self._data_epoch))

    def commit_transaction(self) -> None:
        """COMMIT. El motor comprueba antes el estado real y nunca confirma una transacción abortada."""
        engine = self._require_ready(tr("commit the transaction"))
        self._sm.transition(SessionState.BUSY)
        engine.commit().add_done_callback(
            lambda fut: self._dispatcher.post(lambda: self._on_transaction_end(engine, fut, recovering=False))
        )

    def rollback_transaction(self) -> None:
        """ROLLBACK. Desde `READY` pasa por `BUSY`. Es también la recuperación segura de una transacción
        abortada: desde `ERROR_RECOVERABLE` con causa `TRANSACTION_ABORTED`, un ROLLBACK confirmado devuelve
        la sesión a `READY` (ADR-0007 punto 6)."""
        recovering = (
            self._sm.state is SessionState.ERROR_RECOVERABLE
            and self._sm.error_cause is ErrorCause.TRANSACTION_ABORTED
            and self._engine is not None
        )
        if recovering:
            if self._recovering:
                raise SessionStateError(tr("A recovery is already in progress"))
            engine = self._engine
            assert engine is not None
            self._recovering = True
        else:
            engine = self._require_ready(tr("roll back the transaction"))
            self._sm.transition(SessionState.BUSY)
        engine.rollback().add_done_callback(
            lambda fut: self._dispatcher.post(
                lambda: self._on_transaction_end(engine, fut, recovering=recovering)
            )
        )

    def _require_ready(self, action: str) -> SessionEngine:
        if self._sm.state is not SessionState.READY or self._engine is None:
            raise SessionStateError(tr("Cannot {0} in state {1}").format(action, self._sm.state.value))
        return self._engine

    def request_close(self) -> None:
        """Cierre pedido por el usuario (decisión del 2026-11-01).

        Sin transacción abierta, cierra. Con una transacción abierta emite `CloseConfirmationRequired` y
        espera `resolve_close`: COMMIT, ROLLBACK o cancelar el cierre. En `READY` el estado se comprueba en
        DuckDB, no se supone.
        """
        if self._close_choice is not None or self._awaiting_close_decision:
            return  # ya hay un cierre en curso o una pregunta abierta
        self._guard_unsaved(tr("close the session"))
        state = self._sm.state
        engine = self._engine
        if engine is not None and state is SessionState.READY:
            self._close_generation += 1
            generation = self._close_generation
            engine.transaction_state().add_done_callback(
                lambda fut: self._dispatcher.post(lambda: self._on_close_check(engine, generation, fut))
            )
            return
        if engine is not None and self._transaction is not None and self._transaction.is_open:
            # ERROR_RECOVERABLE con la transacción abortada, o una operación en curso (BUSY/DETACHING):
            # COMMIT no es válido.
            self._ask_close(self._transaction, commit_allowed=False)
            return
        self.close_session()

    def resolve_close(self, choice: CloseChoice) -> None:
        """Respuesta del usuario a `CloseConfirmationRequired`."""
        if not self._awaiting_close_decision:
            raise SessionStateError(tr("There is no pending closing decision"))
        state = self._sm.state
        commit_valid = state is SessionState.READY and self._transaction is TransactionState.ACTIVE
        if choice is CloseChoice.COMMIT and self._engine is not None and not commit_valid:
            raise SessionStateError(tr("COMMIT is not valid right now"))  # la pregunta sigue abierta
        self._awaiting_close_decision = False
        if choice is CloseChoice.CANCEL:
            return  # la sesión sigue abierta y la transacción no se toca
        if self._engine is None:
            self.close_session()  # la sesión ya terminó mientras se decidía
            return
        if choice is CloseChoice.COMMIT:
            self._close_choice = choice
            self.commit_transaction()
            return
        if state in (SessionState.BUSY, SessionState.DETACHING):
            self.close_session()  # cancela la operación; cerrar la conexión descarta la transacción
            return
        self._close_choice = choice
        self.rollback_transaction()

    def _on_close_check(self, engine: SessionEngine, generation: int, fut: Future[TransactionState]) -> None:
        if engine is not self._engine or generation != self._close_generation:
            return
        exc = fut.exception()
        if exc is not None:
            self._record_transaction(exc)
            known = self._transaction
            if known is not None and known.is_open:
                self._ask_close(known, commit_allowed=False)
            else:
                self.close_session()  # sin transacción conocida que proteger
            return
        state = fut.result()
        self._set_transaction(state)
        if state is TransactionState.NONE or self._sm.state is not SessionState.READY:
            self.close_session()
            return
        self._ask_close(state, commit_allowed=state is TransactionState.ACTIVE)

    def _ask_close(self, state: TransactionState, *, commit_allowed: bool) -> None:
        self._awaiting_close_decision = True
        self._emit(CloseConfirmationRequired(state, commit_allowed))

    def close_session(self) -> Future[None]:
        """CloseSession(): cancela lo que esté en curso y cierra el motor sin bloquear la UI."""
        state = self._sm.state
        if state is SessionState.DISCONNECTED or state is SessionState.CLOSING:
            done: Future[None] = Future()
            done.set_result(None)
            return done
        engine, self._engine = self._engine, None
        if self._loader is not None and engine is not None:
            self._loader.session_changed(None)  # las capas Conectadas quedan no disponibles
        self._info = None
        self._pending_attach = None
        self._recovering = False
        self._close_choice = None
        self._awaiting_close_decision = False
        self._close_generation += 1
        self._set_transaction(None)
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
            raise SessionStateError(
                tr("The catalog cannot be read in state {0}").format(self._sm.state.value)
            )
        engine = self._engine
        self._catalog_generation += 1
        generation = self._catalog_generation
        reading = engine.read_catalog()
        reading.add_done_callback(
            lambda fut: self._dispatcher.post(lambda: self._on_catalog(engine, generation, fut))
        )

    def list_columns(self, source: tuple[str, str, str]) -> None:
        """Pide las columnas de `source = (base, esquema, objeto)` (session-spec `ListColumns`).

        Con la sesión ocupada, la lectura espera su turno en el worker. La respuesta (`ColumnsListed` o
        `ColumnsUnavailable`) solo se publica si el catálogo mostrado sigue siendo el mismo: tras DDL,
        ATTACH/DETACH o invalidación, una respuesta anterior se descarta.
        """
        engine = self._engine
        if engine is None or self._sm.state not in (SessionState.READY, SessionState.BUSY):
            raise SessionStateError(tr("Columns cannot be read in state {0}").format(self._sm.state.value))
        catalog = self._catalog
        self.vocabulary()  # para citar los nombres hacen falta las palabras clave
        fut = engine.list_columns(*source)
        fut.add_done_callback(
            lambda f: self._dispatcher.post(lambda: self._on_columns(engine, catalog, source, f))
        )

    def known_columns(self) -> dict[tuple[str, str, str], tuple[ColumnInfo, ...]]:
        """Columnas ya leídas del catálogo que se muestra (vacío tras un cambio de catálogo)."""
        catalog, known = self._columns
        return dict(known) if catalog is self._catalog else {}

    def vocabulary(self) -> Vocabulary | None:
        """Vocabulario del catálogo mostrado; si aún no se conoce, lo pide (una vez) y devuelve `None`.
        Al llegar se publica `VocabularyChanged`."""
        engine, catalog = self._engine, self._catalog
        if engine is None:
            return None
        if self._vocabulary is not None and self._vocabulary[:2] == (engine, catalog):
            return self._vocabulary[2]
        if self._vocabulary_asked != (engine, catalog) and self._sm.state in (
            SessionState.READY,
            SessionState.BUSY,
        ):
            self._vocabulary_asked = (engine, catalog)
            fut = engine.vocabulary()
            fut.add_done_callback(
                lambda f: self._dispatcher.post(lambda: self._on_vocabulary(engine, catalog, f))
            )
        return None

    @property
    def reserved_words(self) -> frozenset[str] | None:
        """Palabras clave que obligan a citar, de esta sesión (aunque el catálogo haya cambiado: no cambian
        con él); `None` si aún no se conocen (entonces se cita todo)."""
        if self._vocabulary is None or self._vocabulary[0] is not self._engine:
            return None
        return self._vocabulary[2].reserved

    def _on_vocabulary(
        self, engine: SessionEngine, catalog: CatalogSnapshot | None, fut: Future[Vocabulary]
    ) -> None:
        if engine is not self._engine:
            return
        if fut.exception() is not None:
            self._vocabulary_asked = None  # se reintenta la próxima vez
            return
        self._vocabulary = (engine, catalog, fut.result())
        if catalog is self._catalog:
            self._emit(VocabularyChanged())

    def _on_columns(
        self,
        engine: SessionEngine,
        catalog: CatalogSnapshot | None,
        source: tuple[str, str, str],
        fut: Future[tuple[ColumnInfo, ...]],
    ) -> None:
        if engine is not self._engine or catalog is not self._catalog:
            return  # sesión cerrada o catálogo nuevo: la respuesta ya no corresponde a lo que se ve
        exc = fut.exception()
        if exc is not None:
            code, message = _describe(exc)
            self._emit(ColumnsUnavailable(source, code, message))
            return
        if self._columns[0] is not catalog:
            self._columns = (catalog, {})
        self._columns[1][source] = fut.result()
        self._emit(ColumnsListed(source, fut.result()))

    def cancel_current_operation(self) -> bool:
        if self._load is not None:
            self._load.cancel()
            return True
        return self._engine.cancel_current() if self._engine is not None else False

    # -- carga en QGIS (qgis-bridge-spec, ADR-0012) ----------------------------------------------

    def load_modes(self) -> dict[LoadMode, str | None]:
        """Modalidad → motivo por el que no está disponible (None = disponible)."""
        if self._loader is None:
            return dict.fromkeys(LoadMode, tr("Loading into QGIS is not available"))
        return self._loader.availability()

    def prepare_load(
        self,
        sql: str,
        geometry: str | None = None,
        formats: Mapping[str, Any] | None = None,
        *,
        database: str | None = None,
    ) -> int:
        """Pide el plan de carga (sin leer datos). Responde con `LoadPrepared` o `LoadPrepareFailed`.
        `database`: base donde se ejecutó el resultado de una celda (G7)."""
        engine = self._require_ready(tr("prepare the load"))
        sql = load_sql(sql)  # sin el `;` ni los comentarios finales de la sentencia del editor
        self._prepare_tokens += 1
        token = self._prepare_tokens
        fut = engine.prepare_load(sql, geometry, formats or None, database=database)
        fut.add_done_callback(lambda f: self._dispatcher.post(lambda: self._on_prepared(engine, token, f)))
        return token

    def _on_prepared(self, engine: SessionEngine, token: int, fut: Future[object]) -> None:
        if engine is not self._engine:
            return
        exc = fut.exception()
        if exc is not None:
            code, message = _describe(exc)
            self._emit(LoadPrepareFailed(token, code, message))
            return
        self._emit(LoadPrepared(token, fut.result()))  # type: ignore[arg-type]

    # -- extensión spatial (spatial-spec §10, ADR-0011) ------------------------------------------

    def check_spatial(self) -> None:
        """Estado de `spatial` en la sesión: responde con `SpatialChecked` (no instala ni carga nada)."""
        engine = self._require_ready(tr("query the spatial extension"))
        fut = engine.spatial_state()
        fut.add_done_callback(lambda f: self._dispatcher.post(lambda: self._on_spatial(engine, f, None)))

    def activate_spatial(self, *, install: bool) -> None:
        """Solo tras el consentimiento del usuario: `INSTALL` (si `install`) y `LOAD spatial`, para esta
        sesión. Responde con `SpatialActivated` o `SpatialActivationFailed`."""
        engine = self._require_ready(tr("activate the spatial extension"))
        fut = engine.activate_spatial(install=install)
        fut.add_done_callback(lambda f: self._dispatcher.post(lambda: self._on_spatial(engine, f, True)))

    def _on_spatial(self, engine: SessionEngine, fut: Future[Any], activated: bool | None) -> None:
        if engine is not self._engine:
            return
        exc = fut.exception()
        if exc is not None:
            code, message = _describe(exc)
            self._emit(SpatialActivationFailed(code, message))
            return
        state = fut.result()
        if activated:
            self._emit(SpatialActivated(state.version, state.always_xy))
        else:
            self._emit(SpatialChecked(state.installed, state.loaded))

    def load(self, request: LoadRequest) -> int:
        """Carga en QGIS. Memoria e Instantánea ocupan la sesión (BUSY) hasta publicar o descartar;
        se cancelan con `cancel_current_operation`. Devuelve el id de la carga."""
        engine = self._require_ready(tr("load into QGIS"))
        request = replace(request, sql=load_sql(request.sql))  # ver `load_sql`
        if self._loader is None:
            raise SessionStateError(tr("Loading into QGIS is not available"))
        reason = self.load_modes().get(request.mode)
        if reason is not None:
            raise SessionStateError(reason)
        self._load_ids += 1
        load_id = self._load_ids
        self._sm.transition(SessionState.BUSY)
        self._emit(LoadStarted(load_id, request))
        try:
            self._load = self._loader.start(
                engine,
                request,
                on_progress=lambda rows: self._emit(LoadProgressed(load_id, rows)),
                on_done=lambda result: self._on_load_done(engine, load_id, result),
            )
        except BaseException as exc:
            self._load = None
            if self._sm.state is SessionState.BUSY:
                self._sm.transition(SessionState.READY)
            code, message = _describe(exc)
            self._emit(LoadFailed(load_id, code, message, cancelled=False))
            raise
        return load_id

    def _on_load_done(self, engine: SessionEngine, load_id: int, result: LoadReport | BaseException) -> None:
        self._load = None
        if engine is not self._engine:
            return
        if self._sm.state is SessionState.BUSY:
            self._sm.transition(SessionState.READY)
        if isinstance(result, BaseException):
            code, message = _describe(result)
            self._emit(LoadFailed(load_id, code, message, cancelled=code is ErrorCode.CANCELLED))
            return
        self._emit(LoadFinished(load_id, result))

    # -- «Exportar ▾» (G7 · E3, GD-NB-007) ----------------------------------------------------------

    def export(self, request: ExportRequest) -> int:
        """Exporta la consulta completa de un resultado (solo lectura repetible, como «Cargar en QGIS»).
        La sesión pasa por `BUSY`; se cancela con `cancel_current_operation`. Devuelve el id."""
        engine = self._require_ready(tr("export"))
        request = replace(request, sql=load_sql(request.sql))
        self._export_ids += 1
        export_id = self._export_ids
        self._sm.transition(SessionState.BUSY)
        self._emit(ExportStarted(export_id, request))
        handle = engine.export_query(request)
        handle.future.add_done_callback(
            lambda fut: self._dispatcher.post(lambda: self._on_exported(engine, export_id, fut))
        )
        return export_id

    def _on_exported(self, engine: SessionEngine, export_id: int, fut: Future[ExportReport]) -> None:
        if engine is not self._engine or self._sm.state is not SessionState.BUSY:
            return
        exc = fut.exception()
        if isinstance(exc, SessionInvalidatedError):
            return
        if exc is not None:
            self._end_failed_operation(exc)
            code, message = _describe(exc)
            self._emit(ExportFailed(export_id, code, message, cancelled=code is ErrorCode.CANCELLED))
            return
        self._sm.transition(SessionState.READY)
        self._emit(ExportFinished(export_id, fut.result()))

    # -- «Enviar a DuckDB» (G8, qgis-import-spec) ------------------------------------------------------

    def send_candidates(self, layer_ids: list[str] | None) -> list[SendCandidate]:
        """Las capas para el diálogo (todas las del proyecto si `layer_ids` es None)."""
        if self._sender is None:
            raise SessionStateError(tr("Sending layers to DuckDB is not available"))
        return self._sender.describe(layer_ids)

    def read_import_target(
        self, database: str, schema: str, on_done: Callable[[ImportTarget | BaseException], None]
    ) -> None:
        """Destino para el diálogo (F-120, tablas existentes); `on_done` en el hilo principal."""
        engine = self._require_ready(tr("read the destination"))
        fut = engine.import_target(database, schema)
        fut.add_done_callback(lambda f: self._dispatcher.post(lambda: on_done(f.exception() or f.result())))

    def read_rows(
        self,
        sql: str,
        max_rows: int,
        on_done: Callable[[StatementOutcome | BaseException], None],
        *,
        database: str | None = None,
    ) -> None:
        """Lectura de la pestaña de tabla (G9; workspace-pro-spec §4): una página, el total, una fila o la
        estructura. Solo SQL de solo lectura que construye GeoDuck (`domain.browse`); no pasa por `BUSY` ni
        invalida nada. Se encola en el worker serial; `on_done` llega en el hilo principal."""
        engine = self._require_ready(tr("read the table"))
        handle = engine.query(sql, max_rows=max_rows, priority=False, database=database)
        handle.future.add_done_callback(
            lambda f: self._dispatcher.post(lambda: on_done(f.exception() or f.result()))
        )

    def send_layers(self, request: SendRequest) -> int:
        """Envía capas de QGIS a DuckDB en una transacción (qgis-import-spec §4). La sesión pasa por `BUSY`
        (bloquea `DETACH` y el cierre, §9); se cancela con `cancel_current_operation`. Devuelve el id."""
        engine = self._require_ready(tr("send layers to DuckDB"))
        if self._sender is None:
            raise SessionStateError(tr("Sending layers to DuckDB is not available"))
        self._send_ids += 1
        send_id = self._send_ids
        self._sm.transition(SessionState.BUSY)
        self._emit(SendStarted(send_id, request))
        try:
            self._load = self._sender.start(
                engine,
                request,
                on_progress=lambda rows: self._emit(SendProgressed(send_id, rows)),
                on_done=lambda result: self._on_sent(engine, send_id, result),
            )
        except BaseException as exc:
            self._load = None
            if self._sm.state is SessionState.BUSY:
                self._sm.transition(SessionState.READY)
            code, message = _describe(exc)
            self._emit(SendFailed(send_id, code, message, cancelled=False))
            raise
        return send_id

    def _on_sent(self, engine: SessionEngine, send_id: int, result: ImportReport | BaseException) -> None:
        self._load = None
        if engine is not self._engine or self._sm.state is not SessionState.BUSY:
            return
        if isinstance(result, BaseException):
            if isinstance(result, SessionInvalidatedError):
                return
            self._end_failed_operation(result)
            code, message = _describe(result)
            self._emit(SendFailed(send_id, code, message, cancelled=code is ErrorCode.CANCELLED))
            return
        self._sm.transition(SessionState.READY)
        self._emit(SendFinished(send_id, result))
        self._bump_epoch()  # tablas nuevas o con más filas: vistas previas y capas Conectadas se releen
        self.refresh_catalog()

    def undo_send(self, tables: list[ImportedTable]) -> None:
        """«Deshacer» (§4): `DROP` de las tablas nuevas del envío (`SendUndone` o `SendUndoFailed`)."""
        engine = self._require_ready(tr("undo the send"))
        fut = engine.drop_imported(tables)
        fut.add_done_callback(lambda f: self._dispatcher.post(lambda: self._on_undone(engine, tables, f)))

    def _on_undone(self, engine: SessionEngine, tables: list[ImportedTable], fut: Future[None]) -> None:
        if engine is not self._engine:
            return
        exc = fut.exception()
        if exc is not None:
            self._record_transaction(exc)
            code, message = _describe(exc)
            self._emit(SendUndoFailed(code, message))
            return
        self._emit(SendUndone(tuple(tables)))
        self._bump_epoch()
        if self._sm.state is SessionState.READY:
            self.refresh_catalog()

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
        if self._loader is not None:
            self._loader.session_changed(self._engine)
        self._emit(SessionStarted(self._info))
        self._set_transaction(TransactionState.NONE)  # una conexión nueva empieza en autocommit
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
        if exc is None:
            self._sm.transition(SessionState.READY)
            result = fut.result()
            self._catalog_generation += 1  # cualquier lectura anterior queda superada
            self._catalog = result.catalog
            self._emit(CatalogChanged(result.catalog))
            self._emit(DatabaseAttached(result.database))
            self._bump_epoch()
            return
        code, message = _describe(exc)
        _log.warning("No se adjuntó la base [%s]", code.value)
        usable = self._end_failed_operation(exc)
        self._emit(AttachFailed(code, message))
        if usable:
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

    def _on_detached(self, engine: SessionEngine, fut: Future[DetachResult]) -> None:
        if engine is not self._engine or self._sm.state is not SessionState.DETACHING:
            return  # la sesión se cerró o se invalidó mientras tanto
        exc = fut.exception()
        if isinstance(exc, SessionInvalidatedError):
            return  # la invalidación llega por su propio camino y lleva a ERROR_RECOVERABLE
        if exc is None:
            self._sm.transition(SessionState.READY)
            result = fut.result()
            self._catalog_generation += 1
            self._catalog = result.catalog
            self._emit(CatalogChanged(result.catalog))
            self._emit(DatabaseDetached(result.database))
            self._bump_epoch()
            return
        code, message = _describe(exc)
        _log.warning("No se desadjuntó la base [%s]", code.value)
        usable = self._end_failed_operation(exc)
        self._emit(DetachFailed(code, message))
        if usable:
            self.refresh_catalog()  # la base sigue adjunta: se confirma con DuckDB, no se supone

    def _on_transaction_end(
        self, engine: SessionEngine, fut: Future[TransactionState], *, recovering: bool
    ) -> None:
        expected = SessionState.ERROR_RECOVERABLE if recovering else SessionState.BUSY
        if engine is not self._engine or self._sm.state is not expected:
            return  # la sesión se cerró o se invalidó mientras tanto
        if recovering:
            self._recovering = False
        exc = fut.exception()
        if isinstance(exc, SessionInvalidatedError):
            return  # la invalidación llega por su propio camino
        closing, self._close_choice = self._close_choice, None
        if exc is None:
            self._set_transaction(fut.result())
            if recovering:
                self._sm.resolve_transaction()
            self._sm.transition(SessionState.READY)
            self._bump_epoch()  # COMMIT o ROLLBACK cambian los datos visibles
            if closing is not None:
                self.close_session()  # COMMIT o ROLLBACK confirmados: se completa el cierre pedido
            return
        code, message = _describe(exc)
        _log.warning("COMMIT/ROLLBACK rechazado [%s]", code.value)
        if recovering:
            self._record_transaction(exc)  # sigue en ERROR_RECOVERABLE: la transacción no se resolvió
        else:
            self._end_failed_operation(exc)
        self._emit(TransactionFailed(code, message))
        if closing is not None and self._transaction is not None and self._transaction.is_open:
            # Nunca se cierra tras un COMMIT o ROLLBACK fallido: se vuelve a preguntar con el estado real.
            self._ask_close(
                self._transaction,
                commit_allowed=self._transaction is TransactionState.ACTIVE
                and self._sm.state is SessionState.READY,
            )
        elif closing is not None:
            self.close_session()

    def _end_failed_operation(self, exc: BaseException) -> bool:
        """Cierra una operación fallida (BUSY o DETACHING). Vuelve a `READY` solo si la conexión y la
        transacción siguen utilizables (dictamen C13); con la transacción abortada pasa a
        `ERROR_RECOVERABLE` hasta un ROLLBACK. Devuelve True si la sesión quedó `READY`."""
        self._record_transaction(exc)
        if self._transaction is TransactionState.ABORTED:
            self._sm.transition(SessionState.ERROR_RECOVERABLE, ErrorCause.TRANSACTION_ABORTED)
            return False
        self._sm.transition(SessionState.READY)
        return True

    def _record_transaction(self, exc: BaseException) -> None:
        state = exc.transaction if isinstance(exc, GeoDuckError) else None
        if state is not None:
            self._set_transaction(state)

    def _set_transaction(self, state: TransactionState | None) -> None:
        if state is not self._transaction:
            self._transaction = state
            self._emit(TransactionStateChanged(state))

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
        self._recovering = False
        self._close_choice = None
        self._close_generation += 1
        self._set_transaction(None)
        self._drop_catalog()
        _log.error("Sesión invalidada [%s]: %s", cause.code.value, cause.detail)
        if self._sm.state is SessionState.ERROR_RECOVERABLE:
            self._sm.mark_invalidated()  # p. ej. durante la recuperación de una transacción abortada
        else:
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


def _describe(exc: BaseException) -> tuple[ErrorCode, str]:
    if isinstance(exc, GeoDuckError):
        return exc.code, exc.message
    return ErrorCode.ENGINE_ERROR, f"{type(exc).__name__}: {exc}"
