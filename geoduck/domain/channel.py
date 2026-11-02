# SPDX-License-Identifier: GPL-2.0-or-later
"""Canal acotado productor → consumidor para lotes de una carga (qgis-bridge-spec §6).

El productor (hilo del worker) entrega lotes con contrapresión: como mucho `capacity` en vuelo. Ninguno
de los dos lados puede quedar bloqueado para siempre:

- si el consumidor abandona (cancelación, error, capa descartada), `put` lanza `ConsumerGoneError` y la
  lectura del motor se detiene (F-60);
- si el productor termina o falla, `finish`/`fail` despiertan al consumidor.

Solo biblioteca estándar: lo usan `engine` (productor) y `qgis_bridge` (consumidor) sin importarse.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")

_POLL = 0.05


class ConsumerGoneError(Exception):
    """El consumidor abandonó el canal; el productor debe dejar de leer."""


class _End:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error


class BatchChannel(Generic[T]):
    def __init__(self, capacity: int = 2) -> None:
        if capacity < 1:
            raise ValueError("capacity debe ser ≥ 1")
        self._q: queue.Queue[Any] = queue.Queue(maxsize=capacity)
        self._abandoned = threading.Event()
        self._finished = False

    # -- productor -------------------------------------------------------------------------------

    def put(self, item: T, *, stop: Callable[[], bool] = lambda: False) -> None:
        """Entrega un lote; espera mientras el canal esté lleno. `stop()` corta la espera (cancelación)."""
        while True:
            if self._abandoned.is_set() or stop():
                raise ConsumerGoneError
            try:
                self._q.put(item, timeout=_POLL)
                return
            except queue.Full:
                continue

    def finish(self) -> None:
        self._end(_End())

    def fail(self, error: BaseException) -> None:
        self._end(_End(error))

    def _end(self, marker: _End) -> None:
        if self._finished:
            return
        self._finished = True
        while not self._abandoned.is_set():
            try:
                self._q.put(marker, timeout=_POLL)
                return
            except queue.Full:
                continue

    # -- consumidor ------------------------------------------------------------------------------

    def get(self, timeout: float | None = None) -> tuple[bool, T | None]:
        """`(True, lote)`, `(False, None)` al terminar, o `queue.Empty` si vence `timeout`.

        Si el productor falló, relanza su error.
        """
        item = self._q.get(timeout=timeout)
        if isinstance(item, _End):
            if item.error is not None:
                raise item.error
            return False, None
        return True, item

    def abandon(self) -> None:
        """El consumidor deja de leer: el productor recibe `ConsumerGoneError` en su próximo `put`."""
        self._abandoned.set()
        while True:  # vacía para que el productor no espere sitio
            try:
                self._q.get_nowait()
            except queue.Empty:
                return

    @property
    def abandoned(self) -> bool:
        return self._abandoned.is_set()
