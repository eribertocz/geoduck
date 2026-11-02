# SPDX-License-Identifier: GPL-2.0-or-later
"""Raíz de composición: único lugar que conecta motor, aplicación, infraestructura y UI (ADR-0010).

`duckdb` se importa de forma diferida (dentro de las fábricas) para que el complemento cargue y muestre
el diagnóstico aunque DuckDB o PyArrow falten o no carguen (AT-BOOT-002).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.ports import SessionEngine
from geoduck.domain.diagnostics import DiagnosticReport, SpatialProbe
from geoduck.infra.diagnostics import collect
from geoduck.ui.dispatcher import QtDispatcher
from geoduck.ui.dock import GeoDuckDock
from geoduck.ui.i18n import tr

_log = logging.getLogger("geoduck")

ICON = str(Path(__file__).resolve().parent / "resources" / "icon.svg")
UNLOAD_TIMEOUT_S = 10.0


def make_memory_engine() -> SessionEngine:
    from geoduck.engine.worker import SessionWorker  # noqa: PLC0415 - import diferido intencional

    return SessionWorker(":memory:")


def probe_spatial() -> SpatialProbe:
    from geoduck.engine.probe import probe_spatial as _probe  # noqa: PLC0415

    return _probe()


def run_diagnostics() -> DiagnosticReport:
    return collect(spatial_prober=probe_spatial)


class GeoDuckPlugin:
    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.action: QAction | None = None
        self.about_action: QAction | None = None
        self.dock: GeoDuckDock | None = None
        self.dispatcher: QtDispatcher | None = None
        self.coordinator: SessionCoordinator | None = None

    def initGui(self) -> None:  # noqa: N802 - nombre exigido por QGIS
        self.dispatcher = QtDispatcher()
        self.coordinator = SessionCoordinator(make_memory_engine, self.dispatcher)
        self.dock = GeoDuckDock(self.coordinator, run_diagnostics, self.iface.mainWindow())
        self.dock.hide()
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        self.action = QAction(QIcon(ICON), tr("GeoDuck"), self.iface.mainWindow())
        self.action.setObjectName("geoduckToggleDock")
        self.action.setCheckable(True)
        self.action.setToolTip(tr("Mostrar u ocultar el panel de GeoDuck"))
        self.action.toggled.connect(self.dock.setVisible)
        self.dock.visibilityChanged.connect(self.action.setChecked)
        self.iface.addPluginToDatabaseMenu(tr("&GeoDuck"), self.action)
        self.iface.addDatabaseToolBarIcon(self.action)
        # Convención de QGIS: «Acerca de…» en el menú del complemento (Base de datos › GeoDuck).
        self.about_action = QAction(
            QgsApplication.getThemeIcon("mActionHelpAbout.svg"),
            tr("Acerca de GeoDuck…"),
            self.iface.mainWindow(),
        )
        self.about_action.setObjectName("geoduckAbout")
        self.about_action.triggered.connect(self.dock.show_about)
        self.iface.addPluginToDatabaseMenu(tr("&GeoDuck"), self.about_action)

    def unload(self) -> None:
        if self.coordinator is not None and not self.coordinator.shutdown(UNLOAD_TIMEOUT_S):
            _log.warning("GeoDuck se descargó con el motor aún terminando")
        if self.dispatcher is not None:
            self.dispatcher.close()
        if self.about_action is not None:
            self.iface.removePluginDatabaseMenu(tr("&GeoDuck"), self.about_action)
            self.about_action.deleteLater()
        if self.action is not None:
            self.iface.removePluginDatabaseMenu(tr("&GeoDuck"), self.action)
            self.iface.removeDatabaseToolBarIcon(self.action)
            self.action.deleteLater()
        if self.dock is not None:
            self.dock.detach()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
        if self.dispatcher is not None:
            self.dispatcher.deleteLater()
        self.action = self.about_action = None
        self.dock = self.dispatcher = self.coordinator = None
