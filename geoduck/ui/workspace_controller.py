# SPDX-License-Identifier: GPL-2.0-or-later
"""Un solo workspace, dos presentaciones (ui-ux-spec §8, ADR-0013).

`WorkspaceController` es dueño del único `WorkspaceContent` y de los dos shells (ventana propia y panel
acoplado). Solo uno es visible. Alternar traslada el contenido de un shell a otro en el hilo GUI, sin
recrearlo: la sesión, el worker, el editor y los resultados son los mismos. Ocultar o cerrar un shell no
toca la sesión.

Preferencias en `QgsSettings` bajo `geoduck/workspace/`, con versión de esquema. En E1 solo el modo;
valores desconocidos o de un esquema más nuevo → ventana propia (valor seguro).
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QWidget

from geoduck.ui.shells import DockShell, WindowShell

PREFIX = "geoduck/workspace/"
SCHEMA = 1


class WorkspaceMode(Enum):
    WINDOW = "window"  # por defecto (§8)
    DOCK = "dock"


def read_mode(settings: QgsSettings) -> WorkspaceMode:
    schema = settings.value(PREFIX + "schema", None)
    value = settings.value(PREFIX + "mode", None)
    try:
        if schema is None or int(schema) > SCHEMA:
            return WorkspaceMode.WINDOW
        return WorkspaceMode(value)
    except (TypeError, ValueError):
        return WorkspaceMode.WINDOW


def save_mode(settings: QgsSettings, mode: WorkspaceMode) -> None:
    settings.setValue(PREFIX + "schema", SCHEMA)
    settings.setValue(PREFIX + "mode", mode.value)


class WorkspaceController(QObject):
    """Muestra, oculta y alterna la presentación del workspace. Nunca ejecuta SQL ni toca la sesión."""

    #: Visibilidad del shell actual (para el botón de GeoDuck de la barra de herramientas).
    shown_changed = pyqtSignal(bool)

    def __init__(self, iface: Any, content: QWidget, settings: QgsSettings | None = None) -> None:
        super().__init__()
        self.iface = iface
        self.content = content
        self._settings = settings or QgsSettings()
        main = iface.mainWindow()
        self.window = WindowShell(main)
        self.dock = DockShell(main)
        self.window.hide()
        self.dock.hide()
        self._dock_added = False
        self._switching = False
        self.mode = read_mode(self._settings)
        self._shell(self.mode).slot.put(content)
        if self.mode is WorkspaceMode.DOCK:
            self._add_dock()
        self.window.toggle_button.clicked.connect(lambda: self.set_mode(WorkspaceMode.DOCK))
        self.dock.toggle_button.clicked.connect(lambda: self.set_mode(WorkspaceMode.WINDOW))
        self.window.shown_changed.connect(self._on_shell_shown)
        self.dock.shown_changed.connect(self._on_shell_shown)

    def _shell(self, mode: WorkspaceMode) -> WindowShell | DockShell:
        return self.window if mode is WorkspaceMode.WINDOW else self.dock

    @property
    def shell(self) -> WindowShell | DockShell:
        """Shell de la presentación actual."""
        return self._shell(self.mode)

    def is_visible(self) -> bool:
        return self.shell.isVisible()

    def set_visible(self, visible: bool) -> None:
        shell = self.shell
        if not visible:
            shell.hide()
            return
        if shell is self.dock:
            self._add_dock()
        shell.show()
        shell.raise_()
        shell.activateWindow()

    def set_mode(self, mode: WorkspaceMode) -> None:
        """Traslada el contenido al otro shell y lo muestra; el de origen se oculta. Solo presentación."""
        if mode is self.mode:
            return
        source, target = self.shell, self._shell(mode)
        self._switching = True
        try:
            source.slot.take(self.content)
            target.slot.put(self.content)
            self.mode = mode
            if target is self.dock:
                self._add_dock()
            target.show()
            target.raise_()
            target.activateWindow()
            source.hide()
            if source is self.dock:
                self._remove_dock()
        finally:
            self._switching = False
        save_mode(self._settings, mode)
        self.shown_changed.emit(self.is_visible())

    def _on_shell_shown(self, _visible: bool) -> None:
        if not self._switching:
            self.shown_changed.emit(self.is_visible())

    def _add_dock(self) -> None:
        if not self._dock_added:
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self._dock_added = True

    def _remove_dock(self) -> None:
        if self._dock_added:
            self.iface.removeDockWidget(self.dock)
            self._dock_added = False

    def unload(self) -> None:
        """Al descargar GeoDuck. El cierre de la sesión lo hace antes el complemento (cierre seguro)."""
        self._switching = True
        self.window.hide()
        self._remove_dock()
        self.dock.hide()
        self.window.deleteLater()
        self.dock.deleteLater()
