# SPDX-License-Identifier: GPL-2.0-or-later
"""Ventana propia y panel acoplado de Workspace Pro (workspace-pro-spec §3; GD-WSP-002; AT-WSP-002; ADR-0013).

Un solo `ProWorkspace`, dos presentaciones: «Acoplar a QGIS» / «Ventana» lo traslada de una a otra sin
recrearlo (las pestañas, la sesión y lo que esté en curso siguen igual). Cerrar u ocultar nunca cierra la
sesión. Se recuerdan en `QgsSettings` bajo `geoduck/pro/` solo preferencias de presentación: el modo, la
geometría de la ventana, la zona del panel y si la barra lateral está abierta (Ctrl+B).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QByteArray, Qt, pyqtSignal
from qgis.PyQt.QtGui import QCloseEvent, QGuiApplication, QHideEvent, QIcon, QShowEvent
from qgis.PyQt.QtWidgets import QDockWidget, QFrame, QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from geoduck.ui.i18n import tr
from geoduck.ui.pro import style
from geoduck.ui.pro.places import PREFIX
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS
from geoduck.ui.pro.widgets import ElidedLabel, StatusDot, button, icon_button, label
from geoduck.ui.pro.workspace import ProWorkspace

WINDOW_SIZE = (1280, 800)
ICON = str(Path(__file__).resolve().parents[2] / "resources" / "icon.svg")


class Mode(Enum):
    WINDOW = "window"  # por defecto
    DOCK = "dock"


class _Slot(QWidget):
    """El lugar del contenido en un shell. `addWidget` cambia el padre en un solo paso: el contenido nunca
    queda suelto."""

    def __init__(self) -> None:
        super().__init__()
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)

    def put(self, content: QWidget) -> None:
        self.box.addWidget(content, 1)
        content.show()

    def take(self, content: QWidget) -> None:
        self.box.removeWidget(content)


class ProWindow(QMainWindow):
    """Ventana propia, hija de la de QGIS (queda encima y se minimiza con ella). La X solo la oculta."""

    shown_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setObjectName("GeoDuckProWindow")
        self.setWindowTitle(tr("GeoDuck"))
        self.setWindowIcon(QIcon(ICON))
        self.slot = _Slot()
        self.setCentralWidget(self.slot)
        self.resize(*WINDOW_SIZE)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API de Qt
        event.accept()  # sin WA_DeleteOnClose: solo se oculta; la sesión sigue

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not event.spontaneous():
            self.shown_changed.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        super().hideEvent(event)
        if not event.spontaneous():
            self.shown_changed.emit(False)


class DockHeader(QFrame):
    """Cabecera del panel acoplado (maqueta `3-panel`): sesión, búsqueda (Ctrl+K), «Ventana» y ocultar.
    Es la barra de título del panel: se arrastra para moverlo, como cualquier panel de QGIS."""

    def __init__(self, workspace: ProWorkspace) -> None:
        super().__init__()
        colors = style.apply(self)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        top = QFrame()
        top.setProperty("pro", "head")
        top.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top.setFixedHeight(44)
        row = QHBoxLayout(top)
        row.setContentsMargins(12, 0, 6, 0)
        row.setSpacing(8)
        self.dot = StatusDot(colors)
        row.addWidget(self.dot)
        name = label(tr("GeoDuck"))
        name.setFont(ui_font(bold=True))
        row.addWidget(name)
        self.status = ElidedLabel("", "muted")
        self.status.setFont(ui_font(METRICS.font_small))
        row.addWidget(self.status, 1)
        self.window_button = button(
            tr("Window"),
            icon="window",
            tooltip=tr("Shows GeoDuck in its own window, with the same session"),
            colors=colors,
        )
        self.window_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        row.addWidget(self.window_button)
        self.hide_button = icon_button("close", tr("Hide the panel (the session stays open)"), colors)
        row.addWidget(self.hide_button)
        box.addWidget(top)
        search_row = QFrame()
        search_row.setProperty("pro", "rule-bottom")
        inner = QHBoxLayout(search_row)
        inner.setContentsMargins(10, 8, 10, 8)
        self.search_button = button(
            tr("Open a table…"),
            icon="search",
            tooltip=tr("Go to a table or run an action (Ctrl+K)"),
            colors=colors,
        )
        self.search_button.setProperty("pro", "search-button")
        self.search_button.clicked.connect(workspace.open_palette)
        inner.addWidget(self.search_button, 1)
        box.addWidget(search_row)
        workspace.status_changed.connect(self.set_status)
        self.set_status(*workspace.status())

    def set_status(self, dot: str, text: str) -> None:
        self.dot.set_state(dot)
        self.status.setText(text)


class ProDock(QDockWidget):
    """Panel acoplado a QGIS con la cabecera de GeoDuck como barra de título."""

    shown_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None, workspace: ProWorkspace) -> None:
        super().__init__(tr("GeoDuck"), parent)
        self.setObjectName("GeoDuckProDock")
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.header = DockHeader(workspace)
        self.header.hide_button.clicked.connect(self.close)
        self.setTitleBarWidget(self.header)
        self.slot = _Slot()
        self.setWidget(self.slot)
        self.visibilityChanged.connect(self.shown_changed)


class ProController:
    """Muestra, oculta y alterna la presentación del workspace. Nunca toca la sesión."""

    def __init__(self, iface: Any, workspace: ProWorkspace, settings: QgsSettings | None = None) -> None:
        self.iface = iface
        self.workspace = workspace
        self._settings = settings if settings is not None else QgsSettings()
        main = iface.mainWindow()
        self.window = ProWindow(main)
        self.dock = ProDock(main, workspace)
        self.window.hide()
        self.dock.hide()
        self._dock_added = False
        mode = self._settings.value(PREFIX + "mode", Mode.WINDOW.value)
        self.mode = Mode.DOCK if mode == Mode.DOCK.value else Mode.WINDOW
        geometry = self._settings.value(PREFIX + "window/geometry", None)
        if isinstance(geometry, (bytes, bytearray)):
            geometry = QByteArray(bytes(geometry))
        if not isinstance(geometry, QByteArray) or not self.window.restoreGeometry(geometry):
            self._center_window()
        workspace.set_sidebar_open(str(self._settings.value(PREFIX + "sidebar", "1")) != "0")
        self._shell(self.mode).slot.put(workspace)
        workspace.set_presentation(wide=self.mode is Mode.WINDOW)
        if self.mode is Mode.DOCK:
            self._add_dock()
        workspace.presentation_requested.connect(
            lambda wide: self.set_mode(Mode.WINDOW if wide else Mode.DOCK)
        )
        self.dock.header.window_button.clicked.connect(lambda: self.set_mode(Mode.WINDOW))
        workspace.sidebar_changed.connect(
            lambda open_: self._settings.setValue(PREFIX + "sidebar", int(open_))
        )
        self.dock.dockLocationChanged.connect(self._save_dock_area)

    def _shell(self, mode: Mode) -> ProWindow | ProDock:
        return self.window if mode is Mode.WINDOW else self.dock

    @property
    def shell(self) -> ProWindow | ProDock:
        return self._shell(self.mode)

    def is_visible(self) -> bool:
        return self.shell.isVisible()

    def set_visible(self, visible: bool) -> None:
        shell = self.shell
        if shell is self.window and self.window.isMinimized():
            self.window.showNormal()
        if not visible:
            shell.hide()
            return
        if shell is self.dock:
            self._add_dock()
        shell.show()
        shell.raise_()
        shell.activateWindow()

    def set_mode(self, mode: Mode) -> None:
        """Traslada el contenido al otro shell y lo muestra; el de origen se oculta (AT-WSP-002)."""
        if mode is self.mode:
            return
        source, target = self.shell, self._shell(mode)
        self._save_window_geometry()
        source.slot.take(self.workspace)
        target.slot.put(self.workspace)
        self.workspace.set_presentation(wide=target is self.window)
        if target is self.dock:
            self._add_dock()
        target.show()
        target.raise_()
        target.activateWindow()
        source.hide()
        if source is self.dock:
            self._remove_dock()
        self.mode = mode
        self._settings.setValue(PREFIX + "mode", mode.value)

    def _add_dock(self) -> None:
        if not self._dock_added:
            area = Qt.DockWidgetArea.RightDockWidgetArea
            if self._settings.value(PREFIX + "dock/area", "right") == "left":
                area = Qt.DockWidgetArea.LeftDockWidgetArea
            self.iface.addDockWidget(area, self.dock)
            self._dock_added = True

    def _remove_dock(self) -> None:
        if self._dock_added:
            self.iface.removeDockWidget(self.dock)
            self._dock_added = False

    def _save_dock_area(self, area: Qt.DockWidgetArea) -> None:
        if area == Qt.DockWidgetArea.LeftDockWidgetArea:
            self._settings.setValue(PREFIX + "dock/area", "left")
        elif area == Qt.DockWidgetArea.RightDockWidgetArea:
            self._settings.setValue(PREFIX + "dock/area", "right")

    def _save_window_geometry(self) -> None:
        if self.window.isVisible():
            self._settings.setValue(PREFIX + "window/geometry", self.window.saveGeometry())

    def _center_window(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width, height = min(WINDOW_SIZE[0], area.width()), min(WINDOW_SIZE[1], area.height())
        self.window.resize(width, height)
        self.window.move(area.x() + (area.width() - width) // 2, area.y() + (area.height() - height) // 2)

    def unload(self) -> None:
        self._save_window_geometry()
        self.workspace.detach_coordinator()
        self.window.hide()
        self._remove_dock()
        self.dock.hide()
        self.window.deleteLater()
        self.dock.deleteLater()
