# SPDX-License-Identifier: GPL-2.0-or-later
"""Puertos que la capa de aplicación necesita. Los implementan `engine` y `ui`."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from typing import Protocol

from geoduck.domain.catalog import AttachRequest, AttachResult, CatalogSnapshot, DetachResult
from geoduck.domain.errors import SessionInvalidatedError
from geoduck.domain.operations import EngineInfo
from geoduck.domain.sql import RunScope, ScriptRun, StatementResult
from geoduck.domain.transaction import TransactionState


class ScriptHandle(Protocol):
    """Ejecución de un script en curso."""

    @property
    def future(self) -> Future[ScriptRun]: ...


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

    def invalidation(self) -> Future[SessionInvalidatedError | None]:
        """Se resuelve una sola vez, al terminar el motor: la causa si se invalidó, `None` si no."""
        ...


EngineFactory = Callable[[], SessionEngine]


class Dispatcher(Protocol):
    """Ejecuta una función en el hilo principal (el de la UI y de QGIS).

    Las finalizaciones del motor llegan desde el hilo del worker; la capa de aplicación siempre las
    reenvía por aquí antes de tocar su estado o notificar a la UI.
    """

    def post(self, fn: Callable[[], None]) -> None: ...
