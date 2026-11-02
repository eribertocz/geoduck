# SPDX-License-Identifier: GPL-2.0-or-later
"""Cargador de capas: implementación del puerto `LayerLoader` de la aplicación (ADR-0012).

Elige la modalidad y crea la carga correspondiente. Lo instancia la raíz de composición (`plugin.py`);
la aplicación y la UI solo conocen el puerto.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from qgis.core import QgsProject

from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.connected import ConnectedLoad
from geoduck.qgis_bridge.editing import EditSession, is_editable_layer
from geoduck.qgis_bridge.memory import MemoryLoad
from geoduck.qgis_bridge.provider import register_provider
from geoduck.qgis_bridge.snapshot import SnapshotLoad, unavailable_reason
from geoduck.qgis_bridge.vsimem import VsimemRegistry


class BridgeLoader:
    def __init__(self, project: QgsProject | None = None) -> None:
        self._project = project
        self.vsimem = VsimemRegistry(project)
        register_provider()
        #: Capas Conectadas creadas en esta sesión de QGIS (ciclo de vida: E7).
        self.connected: list[str] = []
        #: Lo fija la raíz de composición: avisa a la aplicación de que un guardado cambió datos.
        self.on_data_changed: Callable[[], None] | None = None
        #: Guardado atómico de cada capa Conectada editable del proyecto (§5.4), por id de capa.
        self.edits: dict[str, EditSession] = {}
        self._project_ref = project or QgsProject.instance()
        self._project_ref.layersAdded.connect(self._on_layers_added)
        self._project_ref.layersWillBeRemoved.connect(self._on_layers_removed)

    def availability(self) -> dict[LoadMode, str | None]:
        """Modalidad → motivo por el que no está disponible (None = disponible)."""
        return {
            LoadMode.MEMORY: None,
            LoadMode.SNAPSHOT: unavailable_reason(),
            LoadMode.CONNECTED: None,
        }

    def shutdown(self) -> None:
        """Descarga de GeoDuck: deja de seguir `/vsimem` sin liberar archivos de capas presentes. Las
        capas Conectadas quedan no disponibles (su sesión deja de existir)."""
        self.vsimem.disconnect()
        for signal, slot in (
            (self._project_ref.layersAdded, self._on_layers_added),
            (self._project_ref.layersWillBeRemoved, self._on_layers_removed),
        ):
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(slot)
        for edit in self.edits.values():
            edit.detach()
        self.edits.clear()
        sessions.clear()

    def repaint_connected(self) -> None:
        """Algo pudo cambiar los datos de la sesión: las capas Conectadas se vuelven a dibujar."""
        for layer_id in list(self.connected):
            layer = self._project_ref.mapLayer(layer_id)
            if layer is not None:
                layer.triggerRepaint()

    def _saved(self) -> None:
        if self.on_data_changed is not None:
            self.on_data_changed()

    def _on_layers_added(self, layers: list[Any]) -> None:
        for layer in layers:
            if is_editable_layer(layer) and layer.id() not in self.edits:
                self.edits[layer.id()] = EditSession(layer, self._saved)

    def _on_layers_removed(self, ids: list[str]) -> None:
        for layer_id in ids:
            edit = self.edits.pop(layer_id, None)
            if edit is not None:
                edit.detach()
            if layer_id in self.connected:
                self.connected.remove(layer_id)

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
        task: MemoryLoad | SnapshotLoad | ConnectedLoad
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
        else:
            task = ConnectedLoad(
                engine,
                request,
                on_progress=on_progress,
                on_done=on_done,
                on_layer=lambda layer: self.connected.append(layer.id()),
                project=self._project,
            )
        task.start()
        return task
