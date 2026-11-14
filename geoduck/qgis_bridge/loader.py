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
from geoduck.domain.i18n import tr
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.connected import ConnectedLoad
from geoduck.qgis_bridge.editing import EditSession, is_editable_layer
from geoduck.qgis_bridge.memory import MemoryLoad
from geoduck.qgis_bridge.multi import MultiLoad
from geoduck.qgis_bridge.provider import KEY, register_provider
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

    def unsaved_layers(self, database: str | None = None) -> list[str]:
        """Capas Conectadas editables con cambios sin guardar, de `database` o de cualquier base."""
        out = []
        for edit in self.edits.values():
            layer = edit.layer
            if not (layer.isEditable() and layer.isModified()):
                continue
            db = edit.provider.database
            if database is None or (db is not None and db.lower() == database.lower()):
                out.append(layer.name())
        return out

    def unsaved_by_database(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for edit in self.edits.values():
            layer = edit.layer
            if layer.isEditable() and layer.isModified():
                out.setdefault((edit.provider.database or "").lower(), []).append(layer.name())
        return out

    def layers_reading(self, database: str) -> list[str]:
        """Capas Conectadas que leen de `database`: su base de origen o la base donde se ejecutó la consulta
        (`usedb`). Cerrar esa base las dejaría sin datos (#168)."""
        wanted = database.lower()
        out = []
        for layer_id in self.connected:
            layer = self._project_ref.mapLayer(layer_id)
            provider = layer.dataProvider() if layer is not None else None
            if provider is None:
                continue
            bases = {(getattr(provider, attr, None) or "").lower() for attr in ("database", "use_database")}
            if wanted in bases:
                out.append(layer.name())
        return out

    def session_changed(self, engine: Any | None) -> None:
        """Sesión nueva o cerrada (§5.5): las capas de bases adjuntas usan la activa; las demás solo la
        suya, que deja de existir al cerrarse."""
        previous = sessions.current()
        if previous is not None and previous is not engine:
            sessions.forget(previous)
        sessions.set_current(engine)
        self.repaint_connected()

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
            if getattr(layer, "providerType", lambda: "")() == KEY and layer.id() not in self.connected:
                self.connected.append(layer.id())  # también las de un proyecto que se vuelve a abrir
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
        if request.reproject_to and request.mode is LoadMode.CONNECTED:
            raise GeoDuckError(
                tr("The Connected layer is not reprojected: QGIS does it on the fly (spatial-spec §4)"),
                code=ErrorCode.INVALID_ARGUMENT,
            )
        requests = request.split()

        def factory(req: LoadRequest, project: Any, progress: Callable[[int], None], done: Any) -> Any:
            return self._task(engine, req, project, progress, done)

        task: Any
        if len(requests) == 1:
            task = factory(requests[0], self._project, on_progress, on_done)
        else:  # una capa por columna geométrica, publicadas juntas (spatial-spec §7)
            task = MultiLoad(
                requests,
                factory,
                on_progress=on_progress,
                on_done=on_done,
                project=self._project,
                registry=self.vsimem,
            )
        task.start()
        return task

    def _task(
        self,
        engine: Any,
        request: LoadRequest,
        project: Any,
        on_progress: Callable[[int], None],
        on_done: Callable[[LoadReport | BaseException], None],
    ) -> Any:
        if request.mode is LoadMode.MEMORY:
            return MemoryLoad(engine, request, on_progress=on_progress, on_done=on_done, project=project)
        if request.mode is LoadMode.SNAPSHOT:
            return SnapshotLoad(
                engine,
                request,
                on_progress=on_progress,
                on_done=on_done,
                registry=self.vsimem,
                project=project,
            )
        return ConnectedLoad(engine, request, on_progress=on_progress, on_done=on_done, project=project)
