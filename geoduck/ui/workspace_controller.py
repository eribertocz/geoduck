# SPDX-License-Identifier: GPL-2.0-or-later
"""Un solo workspace, dos presentaciones (ui-ux-spec §8, ADR-0013).

`WorkspaceController` es dueño del único `WorkspaceContent` y de los dos shells (ventana propia y panel
acoplado). Solo uno es visible. Alternar traslada el contenido de un shell a otro en el hilo GUI, sin
recrearlo: la sesión, el worker, el editor, los resultados y las tareas en curso son los mismos. Ocultar o
cerrar un shell no toca la sesión. Si el traslado falla, el contenido vuelve al shell de origen, que sigue
operativo, y se informa (AT-UX-014).

Preferencias en `QgsSettings` bajo `geoduck/workspace/` (esquema 1): modo, geometría de la ventana, zona del
panel, divisor editor/resultados/registro por modo, ancho del explorador (ventana), pestaña activa (panel) y
límite de vista previa. Nunca filas,
SQL ni estado de DuckDB. Cada valor se valida al leerlo; uno ausente, corrupto o de un esquema más nuevo
usa el valor seguro.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QByteArray, QObject, QRect, Qt, pyqtSignal
from qgis.PyQt.QtGui import QGuiApplication

from geoduck.domain.sql import DEFAULT_PREVIEW_LIMIT, PREVIEW_LIMITS
from geoduck.ui.i18n import tr
from geoduck.ui.shells import WINDOW_SIZE, DockShell, WindowShell
from geoduck.ui.workspace import WorkspaceContent

PREFIX = "geoduck/workspace/"
SCHEMA = 1
#: Parte mínima de la ventana que debe quedar dentro de una pantalla para darla por visible.
MIN_VISIBLE = (120, 60)


class WorkspaceMode(Enum):
    WINDOW = "window"  # por defecto (§8)
    DOCK = "dock"


# -- preferencias (cada lectura valida y, si no sirve, devuelve el valor seguro) ----------------------------


def _schema_ok(settings: QgsSettings) -> bool:
    schema = settings.value(PREFIX + "schema", None)
    try:
        return schema is not None and int(schema) <= SCHEMA
    except (TypeError, ValueError):
        return False


def read_mode(settings: QgsSettings) -> WorkspaceMode:
    if not _schema_ok(settings):
        return WorkspaceMode.WINDOW
    try:
        return WorkspaceMode(settings.value(PREFIX + "mode", None))
    except ValueError:
        return WorkspaceMode.WINDOW


def read_dock_area(settings: QgsSettings) -> Qt.DockWidgetArea:
    value = settings.value(PREFIX + "dock/area", None) if _schema_ok(settings) else None
    if value == "left":
        return Qt.DockWidgetArea.LeftDockWidgetArea
    if value == "top":
        return Qt.DockWidgetArea.TopDockWidgetArea
    if value == "bottom":
        return Qt.DockWidgetArea.BottomDockWidgetArea
    return Qt.DockWidgetArea.RightDockWidgetArea


def dock_area_name(area: Qt.DockWidgetArea) -> str | None:
    if area == Qt.DockWidgetArea.LeftDockWidgetArea:
        return "left"
    if area == Qt.DockWidgetArea.RightDockWidgetArea:
        return "right"
    if area == Qt.DockWidgetArea.TopDockWidgetArea:
        return "top"
    if area == Qt.DockWidgetArea.BottomDockWidgetArea:
        return "bottom"
    return None  # flotante o sin zona: no se guarda


def read_sizes(settings: QgsSettings, mode: WorkspaceMode, name: str, count: int) -> list[int] | None:
    """Tamaños de un divisor guardados para un modo: `count` enteros no negativos, alguno positivo."""
    text = settings.value(PREFIX + mode.value + "/" + name, None) if _schema_ok(settings) else None
    if not isinstance(text, str):
        return None
    try:
        sizes = [int(part) for part in text.split(",")]
    except ValueError:
        return None
    if len(sizes) != count or min(sizes) < 0 or max(sizes) == 0:
        return None
    return sizes


def read_int(settings: QgsSettings, key: str, allowed: list[int], default: int) -> int:
    value = settings.value(PREFIX + key, None) if _schema_ok(settings) else None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number in allowed else default


def read_window_geometry(settings: QgsSettings) -> QByteArray | None:
    value = settings.value(PREFIX + "window/geometry", None) if _schema_ok(settings) else None
    if isinstance(value, (bytes, bytearray)):
        value = QByteArray(bytes(value))
    return value if isinstance(value, QByteArray) and not value.isEmpty() else None


def on_some_screen(rect: QRect) -> bool:
    """La ventana se ve al menos en parte (MIN_VISIBLE) en alguna pantalla conectada."""
    for screen in QGuiApplication.screens():
        inside = screen.availableGeometry().intersected(rect)
        if inside.width() >= MIN_VISIBLE[0] and inside.height() >= MIN_VISIBLE[1]:
            return True
    return False


class WorkspaceController(QObject):
    """Muestra, oculta y alterna la presentación del workspace. Nunca ejecuta SQL ni toca la sesión."""

    #: Visibilidad del shell actual (para el botón de GeoDuck de la barra de herramientas).
    shown_changed = pyqtSignal(bool)

    def __init__(self, iface: Any, content: WorkspaceContent, settings: QgsSettings | None = None) -> None:
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
        self._restore_window_geometry()
        self._restore_limit()
        self._shell(self.mode).slot.put(content)
        content.set_presentation(wide=self.mode is WorkspaceMode.WINDOW)
        self._apply_sizes(self.mode)
        if self.mode is WorkspaceMode.DOCK:
            self._add_dock()
        # Conexiones una sola vez, aquí: alternar nunca conecta nada (señales idempotentes, AT-UX-012)
        self.window.toggle_button.clicked.connect(lambda: self.set_mode(WorkspaceMode.DOCK))
        self.dock.toggle_button.clicked.connect(lambda: self.set_mode(WorkspaceMode.WINDOW))
        self.window.shown_changed.connect(self._on_shell_shown)
        self.dock.shown_changed.connect(self._on_shell_shown)
        self.dock.dockLocationChanged.connect(self._save_dock_area)
        content.tabs.currentChanged.connect(self._save_tab)
        content.sql_panel.limit_combo.currentIndexChanged.connect(self._save_limit)

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
        if shell is self.window:
            self._keep_window_on_screen()
        else:
            self._add_dock()
        shell.show()
        shell.raise_()
        shell.activateWindow()

    # -- alternancia --------------------------------------------------------------------------------

    def set_mode(self, mode: WorkspaceMode) -> bool:
        """Traslada el contenido al otro shell y lo muestra; el de origen se oculta. Solo presentación.

        Devuelve False si el traslado falló: el contenido vuelve al shell de origen, que sigue visible.
        """
        if mode is self.mode:
            return True
        source, target = self.shell, self._shell(mode)
        old_mode = self.mode
        self._save_sizes(old_mode)
        self._save_window_geometry()
        self._switching = True
        moved = False
        try:
            source.slot.take(self.content)
            target.slot.put(self.content)
            moved = True
            self.content.set_presentation(wide=target is self.window)
            if target is self.dock:
                self._add_dock()
            else:
                self._keep_window_on_screen()
            self._apply_sizes(mode)
            target.show()
            target.raise_()
            target.activateWindow()
        except Exception as exc:  # cualquier fallo de Qt durante el traslado: se revierte y se informa
            self._revert(source, target, moved)
            self._switching = False
            message = tr("No se pudo cambiar la presentación; GeoDuck sigue aquí.")
            self.content.show_text(f"{message} ({exc})")
            self.shown_changed.emit(self.is_visible())
            return False
        self.mode = mode
        source.hide()
        if source is self.dock:
            self._remove_dock()
        self._switching = False
        save_mode(self._settings, mode)
        self.shown_changed.emit(self.is_visible())
        return True

    def _revert(self, source: WindowShell | DockShell, target: WindowShell | DockShell, moved: bool) -> None:
        """El contenido vuelve al shell de origen, que queda visible y operativo (AT-UX-014)."""
        if moved:
            target.slot.take(self.content)
        target.hide()
        if target is self.dock:
            self._remove_dock()
        source.slot.put(self.content)  # `put` del origen: el mismo contenido, nunca otro
        self.content.set_presentation(wide=source is self.window)
        self._apply_sizes(self.mode)
        source.show()

    def _on_shell_shown(self, visible: bool) -> None:
        if self._switching:
            return
        if not visible:
            self._save_sizes(self.mode)
            if self.shell is self.window:
                self._save_window_geometry()
        self.shown_changed.emit(self.is_visible())

    def _add_dock(self) -> None:
        if not self._dock_added:
            self.iface.addDockWidget(read_dock_area(self._settings), self.dock)
            self._dock_added = True

    def _remove_dock(self) -> None:
        if self._dock_added:
            self.iface.removeDockWidget(self.dock)
            self._dock_added = False

    # -- preferencias --------------------------------------------------------------------------------

    def _restore_limit(self) -> None:
        combo = self.content.sql_panel.limit_combo
        limit = read_int(self._settings, "preview_limit", list(PREVIEW_LIMITS), DEFAULT_PREVIEW_LIMIT)
        combo.setCurrentIndex(combo.findData(limit))

    def _apply_sizes(self, mode: WorkspaceMode) -> None:
        """Divisores y pestaña guardados para el modo (cada modo, los suyos)."""
        splitter = self.content.sql_panel.splitter
        sizes = read_sizes(self._settings, mode, "sql_splitter", splitter.count())
        if sizes is not None:
            splitter.setSizes(sizes)
        if mode is WorkspaceMode.WINDOW:
            side = self.content.side_splitter
            widths = read_sizes(self._settings, mode, "explorer_splitter", side.count())
            if widths is not None:
                side.setSizes(widths)
        else:
            tabs = self.content.tabs
            tab = read_int(self._settings, "tab", list(range(tabs.count())), -1)
            if tab >= 0:
                tabs.setCurrentIndex(tab)

    def _save_sizes(self, mode: WorkspaceMode) -> None:
        sizes = self.content.sql_panel.splitter.sizes()
        if sizes and max(sizes) > 0:  # un divisor nunca mostrado da ceros: no se guarda
            self._write(mode.value + "/sql_splitter", ",".join(str(s) for s in sizes))
        if mode is WorkspaceMode.WINDOW:
            widths = self.content.side_splitter.sizes()
            if widths and max(widths) > 0:
                self._write(mode.value + "/explorer_splitter", ",".join(str(w) for w in widths))

    def _save_tab(self, index: int) -> None:
        # Solo la pestaña que elige el usuario en el panel; rehacer las pestañas al alternar no cuenta
        if not self._switching and self.mode is WorkspaceMode.DOCK and index >= 0:
            self._write("tab", index)

    def _save_limit(self, _index: int) -> None:
        self._write("preview_limit", int(self.content.sql_panel.limit_combo.currentData()))

    def _save_dock_area(self, area: Qt.DockWidgetArea) -> None:
        name = dock_area_name(area)
        if name is not None:
            self._write("dock/area", name)

    def _restore_window_geometry(self) -> None:
        geometry = read_window_geometry(self._settings)
        if geometry is None or not self.window.restoreGeometry(geometry):
            self.window.resize(*WINDOW_SIZE)
            self._center_window()
        self._keep_window_on_screen()

    def _save_window_geometry(self) -> None:
        if self.window.isVisible():
            self._write("window/geometry", self.window.saveGeometry())

    def _keep_window_on_screen(self) -> None:
        """Nunca fuera de pantalla: si su pantalla ya no está, tamaño por defecto y centrada (AT-UX-010)."""
        if not on_some_screen(self.window.frameGeometry()):
            self.window.resize(*WINDOW_SIZE)
            self._center_window()

    def _center_window(self) -> None:
        main = self.iface.mainWindow()
        screen = main.screen() if main is not None and main.screen() is not None else None
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width = min(self.window.width(), area.width())
        height = min(self.window.height(), area.height())
        self.window.resize(width, height)
        self.window.move(area.x() + (area.width() - width) // 2, area.y() + (area.height() - height) // 2)

    def _write(self, key: str, value: object) -> None:
        self._settings.setValue(PREFIX + "schema", SCHEMA)
        self._settings.setValue(PREFIX + key, value)

    def unload(self) -> None:
        """Al descargar GeoDuck. El cierre de la sesión lo hace antes el complemento (cierre seguro)."""
        self._save_sizes(self.mode)
        self._save_window_geometry()
        self._switching = True
        self.window.hide()
        self._remove_dock()
        self.dock.hide()
        self.window.deleteLater()
        self.dock.deleteLater()


def save_mode(settings: QgsSettings, mode: WorkspaceMode) -> None:
    settings.setValue(PREFIX + "schema", SCHEMA)
    settings.setValue(PREFIX + "mode", mode.value)
