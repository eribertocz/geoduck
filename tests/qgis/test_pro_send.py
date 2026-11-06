# SPDX-License-Identifier: GPL-2.0-or-later
"""Arrastrar entre QGIS y GeoDuck en los dos sentidos (G9 · E5; workspace-pro-spec §9; AT-WSP-009).

QGIS, coordinador, worker DuckDB y panel de capas reales; sin `spatial`:

- capas soltadas sobre una base: sin diálogo si todo es nuevo; con el diálogo (estilo nuevo) si hay algo
  que decidir; progreso en el pie; aviso con «Abrir» y «Deshacer»;
- tablas arrastradas desde la barra lateral y soltadas en el mapa: mini menú Copia / Conectada y un solo
  SRC para todas las que no lo tienen.
"""

from __future__ import annotations

import contextlib
import gc

import pytest
from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsLayerTreeModel,
    QgsPointXY,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QDropEvent
from qgis.PyQt.QtWidgets import QDialog

from geoduck.domain.i18n import tr
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from geoduck.ui.pro.drag import PLACES_MIME, PlacesDropHandler, layer_ids, places_from, places_mime
from geoduck.ui.pro.places import TABLE, Place
from geoduck.ui.pro.sidebar import DATABASE, ROLE, TARGET
from geoduck.ui.pro.workspace import ProWorkspace
from geoduck.ui.send_dialog import SendDialog
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

TIMEOUT = 60
#: Destino de los envíos: la base en memoria guarda el SRC con DuckDB 1.5 y 2.0. (Una base nueva en archivo
#: con DuckDB 1.5 usa el formato antiguo, sin SRC: ahí el diálogo sí se abre, y eso es lo correcto.)
DB = "memory"
_CREATED: list = []


class Store(dict):
    def value(self, key, defaultValue=None):  # noqa: N803
        return self.get(key, defaultValue)

    def setValue(self, key, value):
        self[key] = value


def points(name, n=5, *, crs="EPSG:4326"):
    from qgis.core import QgsVectorLayer

    layer = QgsVectorLayer(f"Point?crs={crs}&field=id:integer", name, "memory")
    feats = []
    for i in range(n):
        feature = QgsFeature(layer.fields())
        feature.setAttributes([i])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-68 + i, -16)))
        feats.append(feature)
    layer.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(layer)
    return layer


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setenv("GEODUCK_RECOVERY_DIR", str(tmp_path / "recuperacion"))
    yield
    while _CREATED:
        widget = _CREATED.pop()
        with contextlib.suppress(RuntimeError):
            if hasattr(widget, "detach_coordinator"):
                widget.detach_coordinator()
            widget.close()
            widget.deleteLater()
    QgsProject.instance().clear()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


@pytest.fixture
def coordinator(qgis_app, iface, tmp_path):
    from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
    from geoduck.plugin import GeoDuckPlugin

    plugin = GeoDuckPlugin(iface)  # el coordinador del complemento: envía y carga en QGIS
    plugin.initGui()
    coordinator = plugin.coordinator
    coordinator.start_memory_session()
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    request = AttachRequest(str(tmp_path / "db.duckdb"), AccessMode.READ_WRITE, OpenAction.CREATE_NEW, "db")
    coordinator.attach_database(request)
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("db"))
    yield coordinator
    plugin.unload()


def workspace(coordinator, *, crs=None):
    asked: list = []

    def ask_crs(columns, _parent):
        asked.append(columns)
        return crs

    ws = ProWorkspace(coordinator, lambda: None, Store(), ask_crs=ask_crs)
    ws.asked = asked
    _CREATED.append(ws)
    ws.resize(1300, 800)
    ws.show()
    return ws


def layers_mime(layers):
    model = QgsLayerTreeModel(QgsProject.instance().layerTreeRoot())
    root = QgsProject.instance().layerTreeRoot()
    indexes = [model.node2index(root.findLayer(layer.id())) for layer in layers]
    return model, model.mimeData(indexes)


def database_item(ws, name):
    tree = ws.sidebar.tree
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        data = item.data(0, ROLE)
        if data and data[0] == DATABASE and item.text(0) == name:
            return item
    raise AssertionError(name)


def drop(tree, data, pos):
    buttons, keys = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    event = QDropEvent(QPointF(pos), Qt.DropAction.CopyAction, data, buttons, keys)
    tree.dropEvent(event)
    return event


def ended(coordinator, ws):
    return (
        ws.quick_send.dialog is None
        and not ws.quick_send._mine
        and QgsApplication.taskManager().countActiveTasks() == 0
        and coordinator.state is SessionState.READY
    )


def tables_in_db(coordinator):
    return {o.name for o in coordinator.catalog.objects_in(DB, "main")}


def has_tables(coordinator, names, *, present=True):
    coordinator.refresh_catalog()
    return wait_for(lambda: (set(names) <= tables_in_db(coordinator)) is present, TIMEOUT)


# -- QGIS → DuckDB ------------------------------------------------------------------------------------


def test_the_layers_panel_format_gives_the_dragged_layer_ids(coordinator):
    a, b = points("a"), points("b")
    _model, data = layers_mime([a, b])
    assert layer_ids(data) == [b.id(), a.id()]  # en el orden del panel: la última añadida, arriba


def test_dropping_on_a_database_sends_without_a_dialog_and_offers_open_and_undo(coordinator):
    ws = workspace(coordinator)
    a, b = points("medidores", 12), points("zonas", 3)
    item = database_item(ws, DB)
    assert tuple(item.data(0, TARGET)) == (DB, "main")
    tree = ws.sidebar.tree
    _model, data = layers_mime([a, b])
    dropped = []
    tree.layers_dropped.connect(lambda ids, target: dropped.append((ids, target)))
    drop(tree, data, tree.visualItemRect(item).center())
    assert dropped == [([b.id(), a.id()], (DB, "main"))]
    assert wait_for(lambda: ws.quick_send.last_report is not None and ended(coordinator, ws), TIMEOUT)
    assert ws.quick_send.asked is False  # todo era nuevo: sin diálogo
    assert has_tables(coordinator, {"medidores", "zonas"})
    assert ws.notice.text().startswith(tr("{0} layers sent to {1}").format(2, DB))
    toast = ws.last_toast
    assert [b.text() for b in toast.actions] == [tr("Open"), tr("Undo")]
    assert not ws.progress.isVisible()
    toast.actions[0].click()  # «Abrir»: la primera tabla, en una pestaña
    assert ws.tabs.page(ws.tabs.bar.currentIndex()).place.name == "zonas"  # la primera del panel
    ws.quick_send.undo([t for t in ws.quick_send.last_report.tables if t.can_undo])
    assert wait_for(lambda: tr("Undone: {0}").format("")[:6] in ws.notice.text(), TIMEOUT)
    assert wait_for(lambda: not {"medidores", "zonas"} & tables_in_db(coordinator), TIMEOUT)


def test_an_existing_table_opens_the_dialog_with_the_new_style(coordinator, monkeypatch):
    ws = workspace(coordinator)
    layer = points("zonas", 3)
    ws.send_layers([layer.id()], (DB, "main"))
    assert wait_for(lambda: ws.quick_send.last_report is not None and ended(coordinator, ws), TIMEOUT)
    shown = []

    def fake_exec(dialog):
        shown.append((dialog.pro, dialog.destination_value, dialog.tree.isColumnHidden(2)))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(SendDialog, "exec", fake_exec)
    ws.quick_send.last_report = None
    ws.send_layers([layer.id()], (DB, "main"))
    assert wait_for(lambda: shown and ended(coordinator, ws), TIMEOUT)
    assert ws.quick_send.asked is True
    # la tabla ya existe: se ve «Qué pasará» y, cancelado, nada se envía
    assert shown == [(True, (DB, "main"), False)]
    assert ws.quick_send.last_report is None


def test_a_selection_is_a_decision_too(coordinator, monkeypatch):
    ws = workspace(coordinator)
    layer = points("medidores", 10)
    layer.selectByIds([1, 2])
    monkeypatch.setattr(SendDialog, "exec", lambda _d: QDialog.DialogCode.Rejected)
    ws.send_layers([layer.id()], (DB, "main"))
    assert wait_for(lambda: ws.quick_send.asked and ended(coordinator, ws), TIMEOUT)


def test_a_database_that_cannot_store_the_crs_is_a_decision(coordinator, monkeypatch):
    ws = workspace(coordinator)
    layer = points("medidores", 4)
    shown = []

    def fake_exec(dialog):
        shown.append(dialog.without_crs.isVisibleTo(dialog))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(SendDialog, "exec", fake_exec)
    ws.send_layers([layer.id()], ("db", "main"))
    assert wait_for(lambda: ended(coordinator, ws) and (shown or ws.quick_send.last_report), TIMEOUT)
    # con DuckDB 1.5 la base nueva en archivo no guarda el SRC: se pregunta, y la razón está a la vista;
    # con 2.0 sí lo guarda: se envía sin diálogo
    assert shown in ([], [True])
    assert ws.quick_send.asked is bool(shown)


def test_dropping_on_empty_space_goes_to_the_current_database(coordinator):
    ws = workspace(coordinator)
    layer = points("puntos", 4)
    tree = ws.sidebar.tree
    tree.setCurrentItem(database_item(ws, DB))
    dropped = []
    tree.layers_dropped.connect(lambda ids, target: dropped.append(target))
    _model, data = layers_mime([layer])
    drop(tree, data, QPoint(tree.viewport().width() // 2, tree.viewport().height() - 4))
    assert dropped == [(DB, "main")]
    assert wait_for(lambda: ws.quick_send.last_report is not None and ended(coordinator, ws), TIMEOUT)
    assert has_tables(coordinator, {"puntos"})


def test_the_dialog_hides_what_will_happen_when_all_is_new_and_folds_the_options(coordinator):
    ws = workspace(coordinator)
    layer = points("nuevos", 2)
    dialog = SendDialog(
        coordinator.send_candidates([layer.id()]),
        coordinator.catalog,
        coordinator.read_import_target,
        ws,
        checked={layer.id()},
        destination=(DB, "main"),
        pro=True,
    )
    _CREATED.append(dialog)
    dialog.show()
    assert wait_for(lambda: dialog.target_ready, TIMEOUT)
    assert dialog.tree.isColumnHidden(2)
    assert not dialog.needs_decision()
    assert dialog.more_button.isVisible() and not dialog.reproject_row.isVisible()
    dialog.more_button.click()
    assert dialog.reproject_row.isVisible()


# -- DuckDB → QGIS ------------------------------------------------------------------------------------


def test_tables_dragged_to_the_map_ask_how_and_ask_the_crs_once(coordinator):
    coordinator.execute_sql(
        "CREATE TABLE con_src AS SELECT 1 AS id, 'POINT (1 2)'::GEOMETRY('OGC:CRS84') AS geom;"
        " CREATE TABLE sin_a AS SELECT 1 AS id, 'POINT (1 2)'::GEOMETRY AS geom;"
        " CREATE TABLE sin_b AS SELECT 2 AS id, 'POINT (3 4)'::GEOMETRY AS geom;",
        RunScope.ALL,
    )
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    ws = workspace(coordinator, crs={"sin_a · geom": "EPSG:32719", "sin_b · geom": "EPSG:32719"})
    places = [Place(TABLE, name, DB, "main") for name in ("con_src", "sin_a", "sin_b")]
    data = places_mime(places)
    assert places_from(data) == places
    handler = PlacesDropHandler(lambda: ws)
    assert handler.canHandleMimeData(data)
    handler.show_menu(ws, places, QPoint(200, 200))
    menu = handler.menu
    assert menu.actions()[0].defaultWidget().text() == tr("{} tables · how to load them?").format(3)
    [copy] = [a for a in menu.actions() if a.text() == tr("Copy (mode)")]
    copy.trigger()

    def loaded():
        names = {layer.name() for layer in QgsProject.instance().mapLayers().values()}
        return {"con_src", "sin_a", "sin_b"} <= names

    assert wait_for(lambda: loaded() and coordinator.state is SessionState.READY, TIMEOUT)
    assert ws.asked == [["sin_a · geom", "sin_b · geom"]]  # una sola ventana, para las dos
    by_name = {layer.name(): layer for layer in QgsProject.instance().mapLayers().values()}
    assert by_name["sin_a"].crs().authid() == "EPSG:32719"
    assert by_name["con_src"].crs().authid() == "OGC:CRS84"


def test_the_sidebar_drags_tables_but_not_queries(coordinator):
    coordinator.execute_sql("CREATE TABLE db.t AS SELECT 1 AS id", RunScope.ALL)
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    assert wait_for(lambda: any(o.name == "t" for o in coordinator.catalog.objects))
    ws = workspace(coordinator)
    tree = ws.sidebar.tree
    found = tree.findItems("t", Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
    data = tree.mimeData(found)
    assert data.hasFormat(PLACES_MIME)
    assert places_from(data) == [Place(TABLE, "t", "db", "main")]
