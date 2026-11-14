# SPDX-License-Identifier: GPL-2.0-or-later
"""PyQGIS real en modo headless (QT_QPA_PLATFORM=offscreen)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qgis_core = pytest.importorskip("qgis.core")

from qgis.PyQt.QtCore import QCoreApplication  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow  # noqa: E402

_APP = None


@pytest.fixture(autouse=True)
def recovery_folder(qgis_app, tmp_path, monkeypatch):
    """Cada prueba, su carpeta de copias de recuperación de cuadernos (ADR-0014): nunca la del perfil, y
    ninguna copia de otra prueba aparece como «QGIS se cerró mal». Con `qgis_app` primero (F-129): un
    `QgsSettings` creado antes que la aplicación deja a QGIS 3.34 sin la autoridad de los SRC."""
    folder = tmp_path / "recuperacion"
    monkeypatch.setenv("GEODUCK_RECOVERY_DIR", str(folder))
    settings = qgis_core.QgsSettings()
    settings.remove("geoduck/notebooks/open")  # ni cuadernos guardados de otra prueba al iniciar
    settings.remove("geoduck/notebooks/active")
    return folder


@pytest.fixture(scope="session")
def qgis_app():
    global _APP  # noqa: PLW0603
    if _APP is None:
        _APP = qgis_core.QgsApplication([], True)
        _APP.initQgis()
        # QGIS en español (G6 · E4): GeoDuck carga su catálogo .qm, como un usuario con QGIS en español
        settings = qgis_core.QgsSettings()
        settings.setValue("locale/overrideFlag", True)
        settings.setValue("locale/userLocale", "es_ES")
    yield _APP
    # Como QGIS al cerrarse: sin exitQgis(), las conexiones GDAL del pool (p. ej. GeoPackage en /vsimem
    # de la Instantánea) se destruyen tras finalizar GDAL y QGIS 4.2 termina con un fallo de segmentación.
    qgis_core.QgsProject.instance().removeAllMapLayers()
    settings = qgis_core.QgsSettings()
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    _APP.exitQgis()


def wait_for(predicate, timeout=20.0):
    """Procesa eventos del hilo principal hasta que `predicate()` sea verdadero."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeIface:
    """Subconjunto de QgisInterface usado por GeoDuck."""

    def __init__(self):
        self.window = QMainWindow()
        self.docks = []
        self.menu = []
        self.toolbar = []

    def mainWindow(self):
        return self.window

    def addDockWidget(self, area, dock):
        self.window.addDockWidget(area, dock)
        self.docks.append(dock)

    def removeDockWidget(self, dock):
        self.window.removeDockWidget(dock)
        self.docks.remove(dock)

    def addPluginToDatabaseMenu(self, name, action):
        self.menu.append((name, action))

    def removePluginDatabaseMenu(self, name, action):
        self.menu.remove((name, action))

    def addDatabaseToolBarIcon(self, action):
        self.toolbar.append(action)

    def removeDatabaseToolBarIcon(self, action):
        self.toolbar.remove(action)

    # Acciones del menú de capa (G4: «Diagnosticar geometrías…»)
    layer_actions: dict
    active_layer = None

    def addCustomActionForLayerType(self, action, menu, layer_type, all_layers):
        self.layer_actions = getattr(self, "layer_actions", {})
        self.layer_actions[action] = []

    def addCustomActionForLayer(self, action, layer):
        self.layer_actions[action].append(layer.id())

    def removeCustomActionForLayerType(self, action):
        return self.layer_actions.pop(action, None) is not None

    def activeLayer(self):
        return self.active_layer

    def messageBar(self):
        """Barra de mensajes real de QGIS (G8: progreso y aviso de «Enviar a DuckDB»)."""
        if not hasattr(self, "bar"):
            from qgis.gui import QgsMessageBar

            self.bar = QgsMessageBar(self.window)
        return self.bar

    #: Capas elegidas en el panel de capas (lo que devolvería `layerTreeView().selectedLayers()`).
    selected_layers: tuple = ()

    def layerTreeView(self):
        iface = self

        class _View:
            def selectedLayers(self):
                return list(iface.selected_layers)

        return _View()

    def setActiveLayer(self, layer):
        self.active_layer = layer
        return True

    def mapCanvas(self):
        if not hasattr(self, "canvas"):
            from qgis.gui import QgsMapCanvas

            self.canvas = QgsMapCanvas(self.window)
            self.canvas.resize(400, 300)  # como el lienzo de QGIS: con tamaño, el zoom tiene extensión
        return self.canvas

    def registerCustomDropHandler(self, handler):
        self.drop_handlers = [*getattr(self, "drop_handlers", []), handler]

    def unregisterCustomDropHandler(self, handler):
        self.drop_handlers = [h for h in getattr(self, "drop_handlers", []) if h is not handler]


def reset_workspace_settings():
    """Preferencias de presentación como en una instalación limpia: las de G5 y las de Workspace Pro (G9),
    y los cuadernos abiertos de G7."""
    settings = qgis_core.QgsSettings()
    for group in ("geoduck/workspace", "geoduck/pro", "geoduck/notebooks/open", "geoduck/notebooks/active"):
        settings.remove(group)


@pytest.fixture
def iface(qgis_app):
    reset_workspace_settings()
    yield FakeIface()
    reset_workspace_settings()
