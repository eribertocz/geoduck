# SPDX-License-Identifier: GPL-2.0-or-later
"""Arrastrar entre QGIS y GeoDuck en los dos sentidos (G9 · E5; workspace-pro-spec §9; AT-WSP-009).

QGIS, coordinador, worker DuckDB y panel de capas reales; sin `spatial`:

- «Capas de QGIS → DuckDB» en tres pasos (F-131): capas, dónde y progreso capa por capa; cada capa por
  separado; «×» y «Cancelar todo»; en segundo plano, la línea del pie y el aviso con «×» (F-132);
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

from geoduck.domain.i18n import tr
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from geoduck.ui.pro.drag import PLACES_MIME, PlacesDropHandler, layer_ids, places_from, places_mime
from geoduck.ui.pro.places import TABLE, Place
from geoduck.ui.pro.sidebar import DATABASE, ROLE, TARGET
from geoduck.ui.pro.workspace import ProWorkspace
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


def points_table(name):
    from qgis.core import QgsVectorLayer

    layer = QgsVectorLayer("None?field=id:integer", name, "memory")
    QgsProject.instance().addMapLayer(layer)
    return layer


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
        not ws.to_duckdb.running
        and QgsApplication.taskManager().countActiveTasks() == 0
        and coordinator.state is SessionState.READY
    )


def to_step_two(ws):
    """Paso 1 → «Siguiente» → paso 2 con el destino ya leído."""
    flow = ws.to_duckdb
    window = flow.window
    assert window.stack.currentIndex() == 0
    flow.next_button.click()
    assert wait_for(lambda: window.send_dialog is not None and window.send_dialog.target_ready, TIMEOUT)
    flow._sync_add()
    return window.send_dialog


def add_all(ws, coordinator):
    """Paso 2 → «Añadir» → espera a que termine el paso 3."""
    ws.to_duckdb.add_button.click()
    assert wait_for(lambda: ended(coordinator, ws), 60)


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


def test_dropping_on_a_database_opens_the_three_steps_with_that_database(coordinator):
    """Arrastrar → paso 1 con esas capas → paso 2 con la base donde se soltaron → paso 3 (F-131)."""
    ws = workspace(coordinator)
    a, b = points("medidores", 12), points("zonas", 3)
    points("otra", 2)  # en el proyecto, pero no se arrastró
    item = database_item(ws, DB)
    assert tuple(item.data(0, TARGET)) == (DB, "main")
    tree = ws.sidebar.tree
    _model, data = layers_mime([a, b])
    dropped = []
    tree.layers_dropped.connect(lambda ids, target: dropped.append((ids, target)))
    drop(tree, data, tree.visualItemRect(item).center())
    assert dropped == [([b.id(), a.id()], (DB, "main"))]
    window = ws.to_duckdb.window
    assert window.isVisible() and window.stack.currentIndex() == 0
    assert set(window.chosen()) == {a.id(), b.id()} and len(window.rows) == 2  # solo las arrastradas
    dialog = to_step_two(ws)
    assert dialog.destination_value == (DB, "main")
    assert not dialog.tree.isColumnHidden(2)  # «Qué pasará» siempre a la vista
    assert ws.to_duckdb.add_button.text() == tr("Add {0} layers to GeoDuck").format(2)
    add_all(ws, coordinator)
    assert [s["state"] for s in ws.to_duckdb.states] == ["done", "done"]
    assert has_tables(coordinator, {"medidores", "zonas"})
    assert window.isVisible() and window.stack.currentIndex() == 2  # el resumen, en el paso 3
    summary = (
        tr("{0} QGIS layers added to GeoDuck").format(2)
        + " · "
        + tr("Catalog: {0} · Schema: {1}").format(DB, "main")
    )
    assert window.subtitle.text() == tr("Done:") + " " + summary
    assert not ws.progress.isVisible()


def test_each_layer_is_saved_on_its_own_and_one_can_be_removed(coordinator):
    ws = workspace(coordinator)
    layers = [points(name, 5) for name in ("uno", "dos", "tres")]
    ws.send_layers([x.id() for x in layers], (DB, "main"))
    to_step_two(ws)
    ws.to_duckdb.add_button.click()
    ws.to_duckdb.remove(1)  # «×» en una capa que espera: no se copia y las demás siguen
    assert wait_for(lambda: ended(coordinator, ws), 60)
    states = {s["name"]: s["state"] for s in ws.to_duckdb.states}
    assert list(states.values()).count("cancelled") == 1 and list(states.values()).count("done") == 2
    removed = next(name for name, state in states.items() if state == "cancelled")
    coordinator.refresh_catalog()
    assert wait_for(lambda: set(states) - {removed} <= tables_in_db(coordinator), TIMEOUT)
    assert removed not in tables_in_db(coordinator)
    assert tr("{0} cancelled ({1})").format(1, removed) in ws.to_duckdb.done_text()


def test_cancel_all_before_it_starts_adds_nothing(coordinator):
    ws = workspace(coordinator)
    layers = [points(name, 5) for name in ("a1", "a2")]
    ws.send_layers([x.id() for x in layers], (DB, "main"))
    to_step_two(ws)
    ws.to_duckdb.add_button.click()
    ws.to_duckdb.cancel_all()
    assert wait_for(lambda: ended(coordinator, ws), TIMEOUT)
    assert [s["state"] for s in ws.to_duckdb.states] == ["cancelled", "cancelled"]
    coordinator.refresh_catalog()
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    assert not {"a1", "a2"} & tables_in_db(coordinator)


def test_in_the_background_the_footer_brings_it_back_and_the_end_shows_a_closable_notice(coordinator):
    ws = workspace(coordinator)
    layer = points("fondo", 20)
    ws.send_layers([layer.id()], (DB, "main"))
    to_step_two(ws)
    ws.to_duckdb.add_button.click()
    ws.to_duckdb.background.click()  # «Seguir en segundo plano»
    window = ws.to_duckdb.window
    assert not window.isVisible()
    assert tr("Show progress: QGIS layers → GeoDuck") in [e.title for e in ws.palette_entries()]
    assert ws.progress_button.text().startswith("⟳ ")
    ws.progress_button.click()  # la línea del pie vuelve al paso 3
    assert window.isVisible() and window.stack.currentIndex() == 2
    window.hide()
    assert wait_for(lambda: ended(coordinator, ws), 60)
    toast = ws.last_toast
    assert [b.text() for b in toast.actions] == [tr("Open"), tr("Undo")]
    assert not toast.close_button.isHidden()  # F-132: «×» para cerrarlo
    toast.actions[0].click()  # «Abrir»
    assert ws.tabs.page(ws.tabs.bar.currentIndex()).place.name == "fondo"
    ws.to_duckdb.undo()
    assert wait_for(lambda: tr("Undone: {0}").format("")[:6] in ws.notice.text(), TIMEOUT)
    coordinator.refresh_catalog()
    assert wait_for(lambda: "fondo" not in tables_in_db(coordinator), TIMEOUT)


def test_a_layer_that_fails_is_marked_and_the_others_go_on(coordinator):
    ws = workspace(coordinator)
    first, second = points("choca", 3), points("sigue", 3)
    ws.send_layers([first.id(), second.id()], (DB, "main"))
    to_step_two(ws)
    coordinator.execute_sql("CREATE TABLE choca AS SELECT 1 AS x", RunScope.ALL)  # aparece después
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    add_all(ws, coordinator)
    states = {s["name"]: s for s in ws.to_duckdb.states}
    assert states["choca"]["state"] == "failed" and states["choca"]["message"]
    assert states["sigue"]["state"] == "done"
    assert tr("{0} with error ({1})").format(1, "choca") in ws.to_duckdb.done_text()


def test_an_existing_table_is_shown_and_skipped_unless_chosen(coordinator):
    ws = workspace(coordinator)
    layer = points("zonas", 3)
    ws.send_layers([layer.id()], (DB, "main"))
    to_step_two(ws)
    add_all(ws, coordinator)
    ws.send_layers([layer.id()], (DB, "main"))
    dialog = to_step_two(ws)
    assert not dialog.tree.isColumnHidden(2)
    assert dialog.row_state(0).kind == "skip"  # ya existe: no se envía hasta elegir qué hacer
    assert not ws.to_duckdb.add_button.isEnabled()


def test_add_layers_shows_every_layer_grouped_and_an_empty_project_says_so(coordinator):
    ws = workspace(coordinator)
    ws.add_layers()
    window = ws.to_duckdb.window
    assert window.empty.isVisible() and not ws.to_duckdb.next_button.isEnabled()
    window.hide()
    point = points("pozos", 2)
    points_table("clientes")
    ws.add_layers([point.id()])
    groups = [window.tree.topLevelItem(i).text(0) for i in range(window.tree.topLevelItemCount())]
    assert groups == [tr("Points"), "pozos", tr("Tables without geometry"), "clientes"]
    assert window.chosen() == [point.id()]  # las seleccionadas en QGIS, ya marcadas
    assert ws.to_duckdb.count_label.text() == tr("1 layer chosen")


def test_while_adding_another_drop_shows_the_progress(coordinator):
    ws = workspace(coordinator)
    layer = points("ocupada", 5)
    ws.send_layers([layer.id()], (DB, "main"))
    to_step_two(ws)
    ws.to_duckdb.add_button.click()
    ws.send_layers([layer.id()], (DB, "main"))
    assert ws.notice.text() == tr("Finish or cancel these layers to add more.")
    assert ws.to_duckdb.window.stack.currentIndex() == 2
    assert wait_for(lambda: ended(coordinator, ws), 60)


def test_a_database_that_cannot_store_the_crs_says_so_in_step_two(coordinator):
    ws = workspace(coordinator)
    layer = points("medidores", 4)
    ws.send_layers([layer.id()], ("db", "main"))
    dialog = to_step_two(ws)
    # con DuckDB 1.5 la base nueva en archivo no guarda el SRC: «Enviar sin SRC» aparece; con 2.0, no
    if dialog.without_crs.isVisibleTo(dialog):
        assert not ws.to_duckdb.add_button.isEnabled()


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
    assert to_step_two(ws).destination_value == (DB, "main")


def test_a_layer_dropped_on_the_editor_is_copied_never_moved(coordinator):
    """Observación del propietario (2026-11-06): soltar una capa en el editor la borraba de QGIS (el editor
    aceptaba «mover»). Ahora el editor no la toma; GeoDuck abre «Añadir» y la acción es siempre «copiar»."""
    from qgis.PyQt.QtGui import QDragEnterEvent

    ws = workspace(coordinator)
    ws.new_query()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    page.editor.setText("SELECT 1;")
    layer = points("puntos", 4)
    _model, data = layers_mime([layer])
    viewport = page.editor.viewport()
    pos = QPoint(20, 10)
    # el panel de capas de QGIS propone «mover» (Mayús fuerza esa propuesta aquí, como en Windows)
    buttons, keys = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier
    actions = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    enter = QDragEnterEvent(pos, actions, data, buttons, keys)
    assert enter.proposedAction() == Qt.DropAction.MoveAction
    QCoreApplication.sendEvent(viewport, enter)
    assert (
        enter.isAccepted() and enter.dropAction() == Qt.DropAction.CopyAction
    )  # lo aceptó GeoDuck, copiando
    event = QDropEvent(QPointF(pos), actions, data, buttons, keys)
    QCoreApplication.sendEvent(viewport, event)
    assert event.isAccepted() and event.dropAction() == Qt.DropAction.CopyAction
    assert page.editor.text() == "SELECT 1;"  # el editor no pegó nada
    assert ws.to_duckdb.window is not None and ws.to_duckdb.window.isVisible()  # «Añadir», paso 2
    assert QgsProject.instance().mapLayer(layer.id()) is not None


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


def test_dragging_tables_shows_the_duck_and_the_target_database_is_the_lake(coordinator):
    """Marca (propietario, 2026-11-07, «como arrastrar un pato al lago»): al arrastrar tablas se ve el pato
    con cuántas lleva; la base donde se soltarán capas de QGIS se pinta de azul claro, con el pato."""
    from qgis.PyQt.QtGui import QColor

    from geoduck.ui.pro.drag import drag_pixmap

    one, three = drag_pixmap(1), drag_pixmap(3)
    assert not one.isNull() and one.width() == three.width()
    image = three.toImage()
    assert image.pixelColor(48, 9).alpha() > 0  # el globito con el «3»
    assert one.toImage().pixelColor(48, 9).alpha() == 0  # una sola: sin globito
    ws = workspace(coordinator)
    tree = ws.sidebar.tree
    base = next(
        tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if (tree.topLevelItem(i).data(0, ROLE) or ("",))[0] == DATABASE and tree.topLevelItem(i).text(0) == DB
    )
    tree.drop_item = base
    rect = tree.visualItemRect(base)
    shot = tree.viewport().grab().toImage()
    lake = QColor(ws.colors.accent_soft)
    assert shot.pixelColor(rect.left() + 4, rect.center().y()) == lake
    tree.drop_item = None


def test_a_connected_layer_from_memory_goes_to_a_file_database_inside_duckdb(coordinator):
    """#140 (E4b): una capa Conectada de la base «memory» enviada a una base en archivo se copia dentro de
    DuckDB (`CREATE TABLE … AS SELECT`), sin pasar las entidades por QGIS: el puente lo dice."""
    from geoduck.domain.importing import PATH_CONNECTED

    coordinator.execute_sql(
        # sin geometría: una base nueva en archivo con DuckDB 1.5 no guarda el SRC (F-120) y el paso 2 lo
        # preguntaría; el camino (dentro de DuckDB) es el mismo
        "CREATE TABLE pozos AS SELECT range AS id, 'pozo ' || range AS nombre FROM range(1000);",
        RunScope.ALL,
    )
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    ws = workspace(coordinator)
    handler = PlacesDropHandler(lambda: ws)
    handler.show_menu(ws, [Place(TABLE, "pozos", DB, "main")], QPoint(200, 200))
    [connected] = [a for a in handler.menu.actions() if a.text() == tr("Connected")]
    connected.trigger()

    def layer():
        return next((x for x in QgsProject.instance().mapLayers().values() if x.name() == "pozos"), None)

    assert wait_for(lambda: layer() is not None and coordinator.state is SessionState.READY, TIMEOUT)
    assert layer().providerType() == "geoduck"
    ws.send_layers([layer().id()], ("db", "main"))
    flow = ws.to_duckdb
    assert flow._candidates[0].path == PATH_CONNECTED
    to_step_two(ws)
    add_all(ws, coordinator)
    assert flow.states[0]["state"] == "done"
    assert flow.traces[0].bridge
    rows = []
    coordinator.read_rows("SELECT count(*) FROM db.main.pozos", 1, rows.append)
    assert wait_for(lambda: rows, TIMEOUT)
    assert rows[0].rows[0][0] in (1000, "1000")
