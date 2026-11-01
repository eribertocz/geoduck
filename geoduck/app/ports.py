# SPDX-License-Identifier: GPL-2.0-or-later
"""Puertos que la capa de aplicación necesita. Los implementan `engine` y `ui`."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from typing import Protocol

from geoduck.domain.errors import SessionInvalidatedError
from geoduck.domain.operations import EngineInfo


class SessionEngine(Protocol):
    """Motor de una sesión. Implementación real: `geoduck.engine.worker.SessionWorker`."""

    def start(self) -> Future[EngineInfo]: ...

    def close(self) -> Future[None]: ...

    def cancel_current(self) -> bool: ...

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
