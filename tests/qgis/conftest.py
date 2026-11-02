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


@pytest.fixture(scope="session")
def qgis_app():
    global _APP  # noqa: PLW0603
    if _APP is None:
        _APP = qgis_core.QgsApplication([], True)
        _APP.initQgis()
    yield _APP
    # Como QGIS al cerrarse: sin exitQgis(), las conexiones GDAL del pool (p. ej. GeoPackage en /vsimem
    # de la Instantánea) se destruyen tras finalizar GDAL y QGIS 4.2 termina con un fallo de segmentación.
    qgis_core.QgsProject.instance().removeAllMapLayers()
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


@pytest.fixture
def iface(qgis_app):
    return FakeIface()
