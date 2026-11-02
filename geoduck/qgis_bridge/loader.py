# SPDX-License-Identifier: GPL-2.0-or-later
"""Cargador de capas: implementación del puerto `LayerLoader` de la aplicación (ADR-0012).

Elige la modalidad y crea la carga correspondiente. Lo instancia la raíz de composición (`plugin.py`);
la aplicación y la UI solo conocen el puerto.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsProject

from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.qgis_bridge.memory import MemoryLoad
from geoduck.qgis_bridge.snapshot import SnapshotLoad, unavailable_reason
from geoduck.qgis_bridge.vsimem import VsimemRegistry


class BridgeLoader:
    def __init__(self, project: QgsProject | None = None) -> None:
        self._project = project
        self.vsimem = VsimemRegistry(project)

    def availability(self) -> dict[LoadMode, str | None]:
        """Modalidad → motivo por el que no está disponible (None = disponible)."""
        return {
            LoadMode.MEMORY: None,
            LoadMode.SNAPSHOT: unavailable_reason(),
            LoadMode.CONNECTED: "Disponible en una próxima entrega de G3",
        }

    def shutdown(self) -> None:
        """Descarga de GeoDuck: deja de seguir `/vsimem` sin liberar archivos de capas presentes."""
        self.vsimem.disconnect()

    def start(
        self,
        engine: Any,
        request: LoadRequest,
        *,
        on_progress: Callable[[int], None],
        on_done: Callable[[LoadReport | BaseException], None],
    ) -> Any:
        reason = self.availability().get(request.mode)
        if reason is not None:
            raise GeoDuckError(reason, code=ErrorCode.INVALID_ARGUMENT)
        task: MemoryLoad | SnapshotLoad
        if request.mode is LoadMode.MEMORY:
            task = MemoryLoad(
                engine, request, on_progress=on_progress, on_done=on_done, project=self._project
            )
        elif request.mode is LoadMode.SNAPSHOT:
            task = SnapshotLoad(
                engine,
                request,
                on_progress=on_progress,
                on_done=on_done,
                registry=self.vsimem,
                project=self._project,
            )
        else:  # pragma: no cover - la modalidad Conectada llega en E5
            raise GeoDuckError(f"Modalidad no implementada: {request.mode.value}")
        task.start()
        return task
