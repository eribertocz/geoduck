# SPDX-License-Identifier: GPL-2.0-or-later
"""«Cargar en QGIS ▾» y «Guardar las copias junto al proyecto» de Workspace Pro (G9 · E4b;
workspace-pro-spec §7; AT-WSP-007).

PyQGIS real con una sesión real de DuckDB: «Copia» (la rápida o, si GDAL no la permite, la de memoria) y
«Conectada» desde la pestaña de tabla y desde un resultado; el SRC solo se pregunta si falta; varias
geometrías; exportar con filtros; y las copias guardadas junto al proyecto, que sobreviven a reabrirlo.
"""

from __future__ import annotations

import contextlib
import gc

import pytest
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication, QEvent

from geoduck.domain.browse import GT, Filter
from geoduck.domain.i18n import tr
from geoduck.domain.load import LoadMode
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from geoduck.qgis_bridge import copies as copies_module
from geoduck.qgis_bridge.copies import is_copy, target_for
from geoduck.ui.pro.load import CONNECTED, COPY, copy_mode
from geoduck.ui.pro.places import TABLE, Place
from geoduck.ui.pro.query_page import QueryPage
from geoduck.ui.pro.table_page import GRID, TablePage
from geoduck.ui.pro.workspace import ProWorkspace
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

_CREATED: list = []


class Store(dict):
    def value(self, key, defaultValue=None):  # noqa: N803
        return self.get(key, defaultValue)

    def setValue(self, key, value):
        self[key] = value


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("GEODUCK_RECOVERY_DIR", str(tmp_path / "recuperacion"))
    yield
    while _CREATED:
        widget = _CREATED.pop()
        with contextlib.suppress(RuntimeError):
            widget.detach_coordinator()
            widget.close()
            widget.deleteLater()
    QgsProject.instance().clear()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


@pytest.fixture
def coordinator(qgis_app, iface):
    from geoduck.plugin import GeoDuckPlugin

    plugin = GeoDuckPlugin(iface)  # el coordinador del complemento, con su cargador de capas
    plugin.initGui()
    # el GeoDuck del complemento también escucha el guardado del proyecto (con su ventana modal): aquí
    # solo pregunta el workspace de cada prueba
    plugin.content.project_copies.detach()
    coordinator = plugin.coordinator
    coordinator.start_memory_session()
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    coordinator.execute_sql(
        "CREATE TABLE puntos AS SELECT range AS id, range * 2.5 AS kwh,"
        " ('POINT (' || range || ' ' || range || ')')::GEOMETRY('OGC:CRS84') AS geom FROM range(50);"
        " CREATE TABLE sin_src AS SELECT 1 AS id, 'POINT (1 2)'::GEOMETRY AS geom;"
        " CREATE TABLE dos AS SELECT 1 AS id, 'POINT (1 2)'::GEOMETRY('OGC:CRS84') AS a,"
        " 'LINESTRING (0 0, 1 1)'::GEOMETRY('OGC:CRS84') AS b;",
        RunScope.ALL,
    )
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    assert wait_for(lambda: any(o.name == "dos" for o in coordinator.catalog.objects))
    yield coordinator
    plugin.unload()


def workspace(coordinator, *, crs=None, save=True, paths=()):
    asked: list = []
    answers = list(paths)

    def ask_crs(columns, _parent):
        asked.append(columns)
        return crs

    ws = ProWorkspace(
        coordinator,
        lambda: None,
        Store(),
        ask_crs=ask_crs,
        ask_save_copies=lambda layers, target, _p: asked.append(("save", [x.name() for x in layers])) or save,
        ask_path=lambda *_a: answers.pop(0) if answers else "",
        copies_bridge=copies_module,
    )
    ws.asked = asked
    _CREATED.append(ws)
    ws.resize(1300, 800)
    ws.show()
    return ws


def open_table(ws, name):
    ws.open_place(Place(TABLE, name, "memory", "main"))
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(page, TablePage)
    assert wait_for(lambda: page.body.currentIndex() == GRID and page.model.rowCount() > 0)
    return page


def layers_named(name):
    return [layer for layer in QgsProject.instance().mapLayers().values() if layer.name().startswith(name)]


def test_copy_is_the_fast_one_unless_gdal_cannot():
    assert copy_mode({LoadMode.SNAPSHOT: None}) is LoadMode.SNAPSHOT
    assert copy_mode({LoadMode.SNAPSHOT: "GDAL sin WriteArrow"}) is LoadMode.MEMORY


def test_copy_from_the_table_tab_loads_it_with_its_crs_and_without_questions(coordinator):
    ws = workspace(coordinator)
    page = open_table(ws, "puntos")
    page.load_in_qgis(COPY)
    assert wait_for(lambda: layers_named("puntos") and coordinator.state is SessionState.READY, 30)
    layer = layers_named("puntos")[0]
    assert layer.featureCount() == 50
    assert layer.crs().authid() == "OGC:CRS84"
    assert is_copy(layer)
    expected = copy_mode(coordinator.load_modes())
    assert ws.loader.last_report.mode is expected
    assert ws.asked == []  # tenía SRC: nada que preguntar
    assert tr("Copy (mode)") in ws.notice.text()


def test_connected_from_the_table_is_the_table_itself_and_with_filters_only_those_rows(coordinator):
    ws = workspace(coordinator)
    page = open_table(ws, "puntos")
    page.load_in_qgis(CONNECTED)
    assert wait_for(lambda: layers_named("puntos") and coordinator.state is SessionState.READY, 30)
    whole = layers_named("puntos")[0]
    assert whole.featureCount() == 50 and not is_copy(whole)
    assert ws.loader.last_report.mode is LoadMode.CONNECTED
    QgsProject.instance().removeMapLayer(whole.id())
    page.add_filter(Filter("kwh", GT, "100"))
    assert wait_for(lambda: page.total == 9)
    page.load_in_qgis(COPY)
    assert wait_for(lambda: layers_named("puntos") and coordinator.state is SessionState.READY, 30)
    assert layers_named("puntos")[0].featureCount() == 9


def test_a_missing_crs_is_asked_once_and_cancel_loads_nothing(coordinator):
    ws = workspace(coordinator, crs=None)
    page = open_table(ws, "sin_src")
    page.load_in_qgis(COPY)
    assert wait_for(lambda: ws.asked)
    assert ws.asked == [["geom"]]
    assert not layers_named("sin_src")
    chosen = workspace(coordinator, crs={"geom": "EPSG:32719"})
    page = open_table(chosen, "sin_src")
    page.load_in_qgis(COPY)
    assert wait_for(lambda: layers_named("sin_src") and coordinator.state is SessionState.READY, 30)
    assert layers_named("sin_src")[0].crs().authid() == "EPSG:32719"


def test_two_geometries_load_as_two_layers(coordinator):
    ws = workspace(coordinator)
    page = open_table(ws, "dos")
    page.load_in_qgis(COPY)
    assert wait_for(lambda: len(layers_named("dos")) == 2 and coordinator.state is SessionState.READY, 30)


def test_a_query_result_loads_with_its_title(coordinator):
    ws = workspace(coordinator)
    ws.new_query()
    query = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(query, QueryPage)
    query.editor.setText("SELECT id, geom FROM puntos WHERE id < 10")
    query.run_button.click()
    assert wait_for(lambda: query.run is None and query.results and coordinator.state is SessionState.READY)
    assert query.load_button.isEnabled()
    query.load_in_qgis(COPY)
    assert wait_for(lambda: ws.loader.last_report is not None and coordinator.state is SessionState.READY, 30)
    layer = QgsProject.instance().mapLayer(ws.loader.last_report.layer_id)
    assert layer.featureCount() == 10


def test_export_from_the_table_uses_its_filters(coordinator, tmp_path):
    target = tmp_path / "puntos.csv"
    ws = workspace(coordinator, paths=[str(target)])
    page = open_table(ws, "puntos")
    page.add_filter(Filter("kwh", GT, "100"))
    assert wait_for(lambda: page.total == 9)
    page.export_menu.actions()[0].trigger()
    assert wait_for(lambda: target.exists() and coordinator.state is SessionState.READY, 20)
    assert len(target.read_text().splitlines()) == 10


def test_saving_the_project_offers_to_keep_the_copies_and_they_survive_reopening(coordinator, tmp_path):
    ws = workspace(coordinator, save=True)
    page = open_table(ws, "puntos")
    page.load_in_qgis(COPY)
    assert wait_for(lambda: layers_named("puntos") and coordinator.state is SessionState.READY, 30)
    project = QgsProject.instance()
    path = tmp_path / "proyecto.qgz"
    assert project.write(str(path))
    assert wait_for(lambda: ws.asked == [("save", ["puntos"])] and not is_copy(layers_named("puntos")[0]))
    gpkg = target_for(project)
    assert gpkg == tmp_path / "proyecto_geoduck.gpkg" and gpkg.exists()
    layer = layers_named("puntos")[0]
    assert layer.providerType() == "ogr" and str(gpkg) in layer.source() and not is_copy(layer)
    assert tr("Copies saved in {}").format(gpkg.name) == ws.notice.text()
    project.clear()
    assert project.read(str(path))
    reopened = layers_named("puntos")[0]
    assert isinstance(reopened, QgsVectorLayer) and reopened.isValid() and reopened.featureCount() == 50


def test_no_thanks_is_not_asked_again_and_reopening_explains_the_lost_copies(coordinator, tmp_path):
    ws = workspace(coordinator, save=False)
    page = open_table(ws, "puntos")
    page.load_in_qgis(COPY)
    assert wait_for(lambda: layers_named("puntos") and coordinator.state is SessionState.READY, 30)
    project = QgsProject.instance()
    path = tmp_path / "proyecto.qgz"
    assert project.write(str(path))
    assert wait_for(lambda: ws.asked)
    assert project.write(str(path))
    wait_for(lambda: False, 0.3)
    assert ws.asked == [("save", ["puntos"])]  # una sola vez
    assert not (tmp_path / "proyecto_geoduck.gpkg").exists()
    project.clear()
    assert project.read(str(path))
    assert wait_for(lambda: "«puntos»" in ws.notice.text())
