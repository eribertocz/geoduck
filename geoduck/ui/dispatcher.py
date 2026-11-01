# SPDX-License-Identifier: GPL-2.0-or-later
"""Implementación Qt del puerto `Dispatcher`: ejecuta funciones en el hilo principal."""

from __future__ import annotations

from collections.abc import Callable

from qgis.PyQt.QtCore import QObject, pyqtSignal, pyqtSlot


class QtDispatcher(QObject):
    """Reenvía llamadas al hilo del objeto (el principal) mediante una señal en cola.

    Emitir una señal desde otro hilo hacia un `QObject` del hilo principal hace que Qt la entregue en
    cola en el bucle de eventos principal. Así ninguna finalización del worker toca la UI ni QGIS fuera
    del hilo principal (spec/docs/architecture.md §5).
    """

    _invoke = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._closed = False
        self._invoke.connect(self._run)

    def post(self, fn: Callable[[], None]) -> None:
        if not self._closed:
            self._invoke.emit(fn)

    def close(self) -> None:
        """Deja de aceptar llamadas (descarga del complemento)."""
        self._closed = True

    @pyqtSlot(object)
    def _run(self, fn: Callable[[], None]) -> None:
        if not self._closed:
            fn()
