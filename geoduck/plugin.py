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
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import LoadFinished, PreviewsInvalidated
from geoduck.app.ports import SessionEngine
from geoduck.domain.diagnostics import DiagnosticReport, SpatialProbe
from geoduck.infra.diagnostics import collect
from geoduck.ui.dispatcher import QtDispatcher
from geoduck.ui.i18n import tr
from geoduck.ui.map_view import MapView
from geoduck.ui.workspace import WorkspaceContent
from geoduck.ui.workspace_controller import WorkspaceController

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


def _vector_layer_type() -> Any:
    """Tipo vectorial para las acciones de capa (3.34: `QgsMapLayerType`; 4.x: `Qgis.LayerType`)."""
    from qgis.core import Qgis  # noqa: PLC0415

    layer_type = getattr(Qgis, "LayerType", None)
    if layer_type is not None:
        return layer_type.Vector
    from qgis.core import QgsMapLayerType  # noqa: PLC0415

    return QgsMapLayerType.VectorLayer


class GeometryValidity:
    """«Diagnosticar geometrías…» en el menú de las capas cargadas por GeoDuck (spatial-spec §9, E4).

    Une la tarea de QGIS (`qgis_bridge.validity`) con el diálogo (`ui.validity_dialog`).
    """

    def __init__(self, iface: Any, on_message: Any) -> None:
        from qgis.core import QgsProject  # noqa: PLC0415

        from geoduck.ui.validity_dialog import ValidityDialog  # noqa: PLC0415

        self.iface = iface
        self._on_message = on_message
        self.dialog_factory: Any = ValidityDialog
        self.tasks: list[Any] = []  # referencias vivas mientras corren
        self.action = QAction(tr("Diagnosticar geometrías…"), iface.mainWindow())
        self.action.setObjectName("geoduckDiagnoseGeometries")
        self.action.triggered.connect(self.diagnose_active_layer)
        self._project = QgsProject.instance()
        self._layer_api = hasattr(iface, "addCustomActionForLayerType")
        if self._layer_api:
            iface.addCustomActionForLayerType(self.action, tr("GeoDuck"), _vector_layer_type(), False)
        self._project.layersAdded.connect(self._on_layers_added)

    def register(self, layer_ids: list[str]) -> None:
        """Capas que GeoDuck acaba de cargar: el menú de capa ofrece el diagnóstico."""
        for layer_id in layer_ids:
            layer = self._project.mapLayer(layer_id)
            if layer is not None and self._layer_api:
                self.iface.addCustomActionForLayer(self.action, layer)

    def _on_layers_added(self, layers: list[Any]) -> None:
        from geoduck.qgis_bridge.provider import KEY  # noqa: PLC0415

        self.register([lyr.id() for lyr in layers if getattr(lyr, "providerType", lambda: "")() == KEY])

    def diagnose_active_layer(self) -> None:
        layer = self.iface.activeLayer() if hasattr(self.iface, "activeLayer") else None
        if layer is not None:
            self.diagnose(layer)

    def diagnose(self, layer: Any) -> Any:
        from geoduck.qgis_bridge.validity import DiagnoseTask  # noqa: PLC0415

        layer_id = layer.id()
        task = DiagnoseTask(layer, lambda result: self._diagnosed(layer_id, task, result))
        return self._start(task, tr("Diagnosticando geometrías de «{}»…").format(layer.name()))

    def _start(self, task: Any, message: str) -> Any:
        self.tasks.append(task)
        self._on_message(message)
        QgsApplication.taskManager().addTask(task)
        return task

    def _diagnosed(self, layer_id: str, task: Any, result: Any) -> None:
        if task in self.tasks:
            self.tasks.remove(task)
        layer = self._project.mapLayer(layer_id)
        if isinstance(result, BaseException) or layer is None:
            self._on_message(tr("Diagnóstico no completado: ") + str(getattr(result, "message", result)))
            return
        layer.selectByIds(list(result.selected))
        self._on_message(
            tr("Diagnóstico de «{}»: {} inválidas, {} ilegibles, {} sin geometría, {} vacías").format(
                result.layer_name, result.invalid, result.unreadable, result.null, result.empty
            )
        )
        dialog = self.dialog_factory(
            result, self.iface.mainWindow(), on_repair=lambda: self.repair(layer, result.invalid_fids)
        )
        dialog.exec()

    def repair(self, layer: Any, invalid_fids: tuple[int, ...]) -> Any:
        from geoduck.qgis_bridge.validity import RepairTask  # noqa: PLC0415

        task = RepairTask(layer, invalid_fids, lambda result: self._repaired(task, result))
        return self._start(task, tr("Reparando geometrías de «{}» en una copia…").format(layer.name()))

    def _repaired(self, task: Any, result: Any) -> None:
        if task in self.tasks:
            self.tasks.remove(task)
        if isinstance(result, BaseException):
            self._on_message(tr("Reparación no completada: ") + str(getattr(result, "message", result)))
            return
        self._on_message(result.message())

    def unload(self) -> None:
        import contextlib  # noqa: PLC0415

        with contextlib.suppress(TypeError, RuntimeError):
            self._project.layersAdded.disconnect(self._on_layers_added)
        if self._layer_api:
            self.iface.removeCustomActionForLayerType(self.action)
        self.action.deleteLater()


class GeoDuckPlugin:
    def __init__(self, iface: Any) -> None:
        self.iface = iface
        self.action: QAction | None = None
        self.about_action: QAction | None = None
        self.content: WorkspaceContent | None = None
        self.workspace: WorkspaceController | None = None
        self.dispatcher: QtDispatcher | None = None
        self.coordinator: SessionCoordinator | None = None
        self.loader: Any = None
        self.validity: GeometryValidity | None = None

    def initGui(self) -> None:  # noqa: N802 - nombre exigido por QGIS
        self.dispatcher = QtDispatcher()
        from geoduck.qgis_bridge.loader import BridgeLoader  # noqa: PLC0415 - importa qgis y pyarrow

        self.loader = BridgeLoader()
        self.coordinator = SessionCoordinator(make_memory_engine, self.dispatcher, self.loader)
        self.loader.on_data_changed = self.coordinator.mark_data_changed
        self.coordinator.subscribe(self._on_app_event)
        # Un solo workspace (contenido + controlador) con dos presentaciones (ADR-0013, ui-ux-spec §8)
        self.content = WorkspaceContent(self.coordinator, run_diagnostics)
        self.workspace = WorkspaceController(self.iface, self.content)
        self._map_view = MapView(self.iface)
        self.content.on_view_map = self._view_map  # «Ver en el mapa» (ui-ux-spec §8)

        self.action = QAction(QIcon(ICON), tr("GeoDuck"), self.iface.mainWindow())
        self.action.setObjectName("geoduckToggleDock")  # nombre de G0–G4: conserva atajos del usuario
        self.action.setCheckable(True)
        self.action.setToolTip(tr("Mostrar u ocultar GeoDuck"))
        # `triggered` (clic del usuario), no `toggled`: sincronizar la marca no muestra ni oculta nada
        self.action.triggered.connect(self.workspace.set_visible)
        self.workspace.shown_changed.connect(self.action.setChecked)
        self.iface.addPluginToDatabaseMenu(tr("&GeoDuck"), self.action)
        self.iface.addDatabaseToolBarIcon(self.action)
        # Convención de QGIS: «Acerca de…» en el menú del complemento (Base de datos › GeoDuck).
        self.about_action = QAction(
            QgsApplication.getThemeIcon("mActionHelpAbout.svg"),
            tr("Acerca de GeoDuck…"),
            self.iface.mainWindow(),
        )
        self.about_action.setObjectName("geoduckAbout")
        self.about_action.triggered.connect(self.content.show_about)
        self.iface.addPluginToDatabaseMenu(tr("&GeoDuck"), self.about_action)
        self.validity = GeometryValidity(self.iface, self.content.show_text)

    def _view_map(self, layer_ids: list[str]) -> str | None:
        """Selecciona y hace zoom; en la ventana propia, GeoDuck se minimiza para dejar ver el mapa."""
        from qgis.core import QgsProject  # noqa: PLC0415

        present = any(QgsProject.instance().mapLayer(i) is not None for i in layer_ids)
        message = self._map_view.show(layer_ids)
        if present and self.workspace is not None:  # sin capa que mostrar, GeoDuck no se aparta
            self.workspace.minimize_for_map()
        return message

    def _on_app_event(self, event: object) -> None:
        if isinstance(event, LoadFinished) and self.validity is not None:
            report = event.report
            self.validity.register([i for i, _ in report.layers] or [report.layer_id])
        if isinstance(event, PreviewsInvalidated) and self.loader is not None:
            self.loader.repaint_connected()  # SQL del usuario o un guardado: las capas Conectadas se repintan

    def unload(self) -> None:
        if self.validity is not None:
            self.validity.unload()
            self.validity = None
        if self.coordinator is not None and not self.coordinator.shutdown(UNLOAD_TIMEOUT_S):
            _log.warning("GeoDuck se descargó con el motor aún terminando")
        if self.dispatcher is not None:
            self.dispatcher.close()
        if self.loader is not None:
            self.loader.shutdown()
            self.loader = None
        if self.about_action is not None:
            self.iface.removePluginDatabaseMenu(tr("&GeoDuck"), self.about_action)
            self.about_action.deleteLater()
        if self.action is not None:
            self.iface.removePluginDatabaseMenu(tr("&GeoDuck"), self.action)
            self.iface.removeDatabaseToolBarIcon(self.action)
            self.action.deleteLater()
        if self.content is not None:
            self.content.detach()
        if self.workspace is not None:
            self.workspace.unload()  # borra los shells y, con ellos, el contenido
        if self.dispatcher is not None:
            self.dispatcher.deleteLater()
        self.action = self.about_action = None
        self.content = self.workspace = None
        self.dispatcher = self.coordinator = None
