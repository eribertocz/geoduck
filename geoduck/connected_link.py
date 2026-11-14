# SPDX-License-Identifier: GPL-2.0-or-later
"""Capas Conectadas y el proyecto de QGIS (#183), en la raíz de composición.

- Avisos en la barra de mensajes de QGIS (no bloquean), con sus botones.
- Al abrir un proyecto, GeoDuck se inicia (si hace falta) y abre las bases de sus capas mientras QGIS lo
  lee, para que lleguen disponibles. Los archivos que faltan los muestra la ventana de QGIS de capas no
  disponibles.
- Al guardar un proyecto con capas sobre una base en memoria, avisa que no podrá reabrirlas.
- Clic derecho en una capa no disponible: «Abrir la base «…»».
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Callable
from typing import Any

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtWidgets import QAction, QPushButton

from geoduck.app.events import CatalogChanged, SessionStateChanged
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.qgis_bridge import sessions
from geoduck.ui.i18n import tr

#: Segundos que se ve un aviso sin botones; con botones se queda hasta cerrarlo.
BAR_SECONDS = 8

_LEVELS = {
    "info": Qgis.MessageLevel.Info,
    "warning": Qgis.MessageLevel.Warning,
    "success": Qgis.MessageLevel.Success,
}


class ConnectedLink:
    def __init__(self, iface: Any, coordinator: Any, loader: Any, content: Any) -> None:
        self._iface = iface
        self._coordinator = coordinator
        self._loader = loader
        self._content = content
        self._project = QgsProject.instance()
        self._reading = False
        self._tried: set[tuple[str, str]] = set()
        self._opened: list[str] = []
        #: (alias, ruta) → acción «Abrir la base «alias»» en el menú de sus capas.
        self._actions: dict[tuple[str, str], QAction] = {}
        content.push_bar = self.push
        sessions.set_resolver(self._resolve)
        self._connections: list[tuple[Any, Callable[..., None]]] = [
            (self._project.cleared, self._start_reading),
            (self._project.readProject, self._end_reading),
            (self._project.projectSaved, self._saved),
        ]
        if hasattr(iface, "newProjectCreated"):
            self._connections.append((iface.newProjectCreated, self._end_reading))
        for signal, slot in self._connections:
            signal.connect(slot)
        self._unsubscribe = coordinator.subscribe(self._on_event)

    def _on_event(self, event: object) -> None:
        if isinstance(event, (CatalogChanged, SessionStateChanged)):
            self.sync_actions()

    # -- barra de mensajes ------------------------------------------------------------------------

    def push(self, text: str, level: str, actions: list[tuple[str, Callable[[], None]]]) -> None:
        bar = self._iface.messageBar()
        item = bar.createMessage(tr("GeoDuck"), text)
        for label, action in actions:
            button = QPushButton(label)

            def clicked(_checked: bool = False, act: Callable[[], None] = action, it: Any = item) -> None:
                bar.popWidget(it)
                act()

            button.clicked.connect(clicked)
            item.layout().addWidget(button)
        bar.pushWidget(item, _LEVELS.get(level, Qgis.MessageLevel.Info), 0 if actions else BAR_SECONDS)

    # -- abrir un proyecto ------------------------------------------------------------------------

    def _start_reading(self) -> None:
        self._reading = True
        self._tried.clear()
        self._opened.clear()

    def _end_reading(self, *_args: Any) -> None:
        if not self._reading:
            return
        self._reading = False
        if self._opened:
            names = ", ".join(self._opened)
            text = (
                tr("GeoDuck opened 1 database for this project: {0}.").format(names)
                if len(self._opened) == 1
                else tr("GeoDuck opened {0} databases for this project: {1}.").format(
                    len(self._opened), names
                )
            )
            self.push(text, "success", [])
        self._opened.clear()

    def _resolve(self, alias: str, path: str) -> bool:
        """Una capa del proyecto que se lee necesita la base `path` como `alias`."""
        key = (alias.lower(), os.path.normcase(path))
        if not self._reading or key in self._tried or not os.path.isfile(path):
            return False
        self._tried.add(key)
        if self._coordinator.open_for_project(path, alias):
            self._opened.append(os.path.basename(path))
            return True
        return False

    # -- guardar un proyecto ----------------------------------------------------------------------

    def _saved(self) -> None:
        for base, layers in self._loader.in_memory().items():
            text = (
                tr(
                    "The layer «{0}» uses the in-memory database «{1}»: the project will not be able to "
                    "reopen it."
                )
                if len(layers) == 1
                else tr(
                    "The layers {0} use the in-memory database «{1}»: the project will not be able to "
                    "reopen them."
                )
            ).format(layers[0] if len(layers) == 1 else ", ".join(layers), base)
            self.push(
                text,
                "warning",
                [(tr("Save the database as a file"), _bind(self._save_and_write, base))],
            )

    def _save_and_write(self, base: str) -> None:
        self._content.save_memory(base, confirm=False, then=self._write)

    def _write(self) -> None:
        self._project.write()

    # -- clic derecho en una capa no disponible ---------------------------------------------------

    def sync_actions(self) -> None:
        """«Abrir la base «alias»» en el menú de cada capa no disponible cuya base es un archivo."""
        wanted = self._loader.to_reopen() if self._loader is not None else {}
        for key in [k for k in self._actions if k not in wanted]:
            self._remove(key)
        if not hasattr(self._iface, "addCustomActionForLayer"):
            return
        for key, layers in wanted.items():
            action = self._actions.get(key)
            if action is None:
                alias, path = key
                action = QAction(tr("Open the database «{0}»").format(alias), self._iface.mainWindow())
                action.triggered.connect(lambda _checked=False, a=alias, p=path: self._reopen(a, p))
                self._iface.addCustomActionForLayerType(action, "", _vector(), False)
                self._actions[key] = action
            for layer in layers:
                self._iface.addCustomActionForLayer(action, layer)

    def _reopen(self, alias: str, path: str) -> None:
        request = AttachRequest(path, AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING, alias=alias)
        self._content.reopen(request)

    def _remove(self, key: tuple[str, str]) -> None:
        action = self._actions.pop(key)
        if hasattr(self._iface, "removeCustomActionForLayerType"):
            self._iface.removeCustomActionForLayerType(action)
        action.deleteLater()

    def unload(self) -> None:
        sessions.set_resolver(None)
        self._content.push_bar = None
        self._unsubscribe()
        for signal, slot in self._connections:
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(slot)
        for key in list(self._actions):
            self._remove(key)


def _vector() -> Any:
    layer_type = getattr(Qgis, "LayerType", None)
    if layer_type is not None:
        return layer_type.Vector
    from qgis.core import QgsMapLayerType  # noqa: PLC0415 - QGIS < 3.30

    return QgsMapLayerType.VectorLayer


def _bind(fn: Callable[[str], None], value: str) -> Callable[[], None]:
    return lambda: fn(value)
