# SPDX-License-Identifier: GPL-2.0-or-later
"""Puertos que la capa de aplicación necesita. Los implementan `engine` y `ui`."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, Protocol

from geoduck.domain.catalog import AttachRequest, AttachResult, CatalogSnapshot, DetachResult
from geoduck.domain.errors import SessionInvalidatedError
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.domain.operations import EngineInfo
from geoduck.domain.sql import RunScope, ScriptRun, StatementResult
from geoduck.domain.transaction import TransactionState


class ScriptHandle(Protocol):
    """Ejecución de un script en curso."""

    @property
    def future(self) -> Future[ScriptRun]: ...


class OperationHandle(Protocol):
    """Operación en curso del motor: id para cancelarla y su resultado."""

    @property
    def op_id(self) -> int: ...

    @property
    def future(self) -> Future[Any]: ...


class SessionEngine(Protocol):
    """Motor de una sesión. Implementación real: `geoduck.engine.worker.SessionWorker`."""

    def start(self) -> Future[EngineInfo]: ...

    def close(self) -> Future[None]: ...

    def cancel_current(self) -> bool: ...

    def read_catalog(self) -> Future[CatalogSnapshot]:
        """Instantánea del catálogo leída de DuckDB (nunca parcial). Falla si la sesión no acepta trabajo."""
        ...

    def attach(self, request: AttachRequest) -> Future[AttachResult]:
        """«Abrir existente» o «Crear nueva». Devuelve la base y el catálogo resultante."""
        ...

    def detach(self, alias: str) -> Future[DetachResult]:
        """DetachDatabase real. Devuelve la base desadjuntada y el catálogo resultante."""
        ...

    def transaction_state(self) -> Future[TransactionState]:
        """Estado transaccional real, comprobado en DuckDB sin modificarlo."""
        ...

    def commit(self) -> Future[TransactionState]:
        """COMMIT de una transacción abierta y utilizable; rechaza una abortada (nunca la envía)."""
        ...

    def rollback(self) -> Future[TransactionState]:
        """ROLLBACK de una transacción abierta o abortada."""
        ...

    def run_script(
        self,
        *,
        run_id: int,
        text: str,
        scope: RunScope,
        cursor: int = 0,
        base: int = 0,
        preview_limit: int = 200,
        on_statement: Callable[[StatementResult], None] | None = None,
    ) -> ScriptHandle:
        """Ejecuta SQL del usuario en una operación serial; `on_statement` llega en el hilo del motor."""
        ...

    def load_query(
        self,
        sql: str,
        *,
        geometry: str | None = None,
        batch_size: int = ...,
        on_plan: Callable[[Any], None],
        on_batch: Callable[[Any], None],
    ) -> OperationHandle:
        """Lectura normalizada por lotes de una consulta repetible para cargarla en QGIS (ADR-0012).

        `on_plan` y `on_batch` llegan en el hilo del motor; el consumidor aplica la contrapresión.
        """
        ...

    def cancel(self, op_id: int) -> bool: ...

    def prepare_load(self, sql: str, geometry: str | None = None) -> Future[Any]:
        """`LoadPlan` de la consulta sin leer datos (qgis-bridge-spec §2)."""
        ...

    def invalidation(self) -> Future[SessionInvalidatedError | None]:
        """Se resuelve una sola vez, al terminar el motor: la causa si se invalidó, `None` si no."""
        ...


EngineFactory = Callable[[], SessionEngine]


class LoadTask(Protocol):
    """Carga en curso en QGIS."""

    def cancel(self) -> None: ...


class LayerLoader(Protocol):
    """Lleva resultados a QGIS en una de las modalidades de ADR-0012. Implementación: `qgis_bridge`.

    `on_progress` y `on_done` se llaman en el hilo principal.
    """

    def availability(self) -> dict[LoadMode, str | None]:
        """Modalidad → motivo por el que no está disponible (None = disponible)."""
        ...

    def start(
        self,
        engine: SessionEngine,
        request: LoadRequest,
        *,
        on_progress: Callable[[int], None],
        on_done: Callable[[LoadReport | BaseException], None],
    ) -> LoadTask: ...


class Dispatcher(Protocol):
    """Ejecuta una función en el hilo principal (el de la UI y de QGIS).

    Las finalizaciones del motor llegan desde el hilo del worker; la capa de aplicación siempre las
    reenvía por aquí antes de tocar su estado o notificar a la UI.
    """

    def post(self, fn: Callable[[], None]) -> None: ...
