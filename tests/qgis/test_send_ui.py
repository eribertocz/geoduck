# SPDX-License-Identifier: GPL-2.0-or-later
"""«Enviar a DuckDB»: diálogo, puntos de entrada y aviso final (G8 · E3; AT-IMP-001, AT-IMP-002, AT-IMP-006).

QGIS, coordinador, worker DuckDB y barra de mensajes reales; sin `spatial`.
"""

from __future__ import annotations

import pytest
from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QPushButton

import geoduck
from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import SendFailed, SendFinished, SendUndone
from geoduck.domain.importing import Conflict, ImportMode
from geoduck.domain.session import SessionState
from geoduck.engine.worker import SessionWorker
from geoduck.qgis_bridge.importer import LayerSender
from geoduck.qgis_bridge.loader import BridgeLoader
from geoduck.ui.dispatcher import QtDispatcher
from geoduck.ui.send_dialog import OPEN_AFTER_SETTING, SendDialog
from geoduck.ui.send_flow import SendFlow
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

TIMEOUT = 60


def points(name, n=5, *, crs="EPSG:4326", fields="field=id:integer&field=nombre:string"):
    layer = QgsVectorLayer(f"Point?crs={crs}&{fields}", name, "memory")
    feats = []
    for i in range(n):
        f = QgsFeature(layer.fields())
        f.setAttributes([i, f"p{i}"][: len(layer.fields())])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-68 + i, -16)))
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(layer)
    return layer


class Env:
    def __init__(self, iface):
        from qgis.core import QgsSettings

        QgsSettings().setValue(OPEN_AFTER_SETTING, False)
        self.events = []
        self.loader = BridgeLoader()
        self.coordinator = SessionCoordinator(SessionWorker, QtDispatcher(), self.loader, LayerSender())
        self.coordinator.subscribe(self.events.append)
        self.coordinator.start_memory_session()
        assert wait_for(lambda: self.coordinator.state is SessionState.READY, TIMEOUT)
        assert wait_for(lambda: self.coordinator.catalog is not None, TIMEOUT)
        self.engine = self.coordinator._engine
        self.opened = []
        self.bar = iface.messageBar()
        self.flow = SendFlow(self.coordinator, self.bar, iface.window, open_table=self.opened.append)

    def rows(self, text):
        return self.engine.submit(lambda h, t: h.execute(text, max_rows=1000)).future.result(TIMEOUT).rows

    def dialog(self, layer_ids, checked=None) -> SendDialog:
        dialog = self.flow.open(layer_ids, checked)
        assert dialog is not None
        assert wait_for(lambda: dialog._target is not None or dialog._target_error, TIMEOUT)
        return dialog

    def send(self, dialog):
        before = len(self.events)
        self.flow.send(dialog)

        def ended():
            return [e for e in self.events[before:] if isinstance(e, (SendFinished, SendFailed))]

        assert wait_for(lambda: bool(ended()), TIMEOUT)
        assert wait_for(lambda: QgsApplication.taskManager().countActiveTasks() == 0, TIMEOUT)
        assert wait_for(lambda: self.coordinator.state is SessionState.READY, TIMEOUT)
        return ended()[0]

    def close(self):
        self.flow.detach()
        self.coordinator.shutdown()
        self.loader.shutdown()


@pytest.fixture
def env(iface):
    e = Env(iface)
    yield e
    e.close()
    QgsProject.instance().removeAllMapLayers()


def state(dialog, i):
    return dialog.row_state(i)


# -- AT-IMP-002: qué pasará por fila ---------------------------------------------------------------------


def test_new_table_and_send_with_defaults(env):
    layer = points("Zonas de riego")
    dialog = env.dialog([layer.id()])
    assert dialog.names[0].text() == "zonas_de_riego"
    assert state(dialog, 0).kind == "send" and state(dialog, 0).text == "Tabla nueva"
    assert dialog.send_button.isEnabled()
    assert not dialog.only_selected.isVisible() and not dialog.as_view.isVisible()  # solo lo que aplica
    event = env.send(dialog)
    assert isinstance(event, SendFinished), event
    assert env.rows("SELECT count(*) FROM zonas_de_riego") == ((5,),)


def test_existing_table_is_not_sent_by_default(env):
    env.rows("CREATE TABLE zonas AS SELECT 1 AS id")
    layer = points("zonas")
    dialog = env.dialog([layer.id()])
    assert state(dialog, 0).kind == "skip" and "Ya existe" in state(dialog, 0).text
    assert not dialog.conflicts[0].isHidden()
    assert not dialog.send_button.isEnabled()  # nada que enviar: nada se sobrescribe sin elegirlo


def test_replace_append_and_another_name(env):
    env.rows(
        "CREATE TABLE zonas AS SELECT 1 AS id, 'x' AS nombre, "
        "ST_SetCRS('POINT(0 0)'::GEOMETRY, 'EPSG:4326') AS geom"
    )
    layer = points("zonas")
    dialog = env.dialog([layer.id()])
    combo = dialog.conflicts[0]
    combo.setCurrentIndex(combo.findData(Conflict.APPEND))
    assert state(dialog, 0).mode is ImportMode.APPEND, state(dialog, 0).text
    event = env.send(dialog)
    assert isinstance(event, SendFinished), event
    assert env.rows("SELECT count(*) FROM zonas") == ((6,),)
    assert not event.report.tables[0].can_undo

    dialog = env.dialog([layer.id()])
    dialog.conflicts[0].setCurrentIndex(dialog.conflicts[0].findData(Conflict.REPLACE))
    assert state(dialog, 0).mode is ImportMode.REPLACE
    assert "no se puede deshacer" in dialog.summary.text()
    assert isinstance(env.send(dialog), SendFinished)
    assert env.rows("SELECT count(*) FROM zonas") == ((5,),)

    dialog = env.dialog([layer.id()])
    dialog.conflicts[0].setCurrentIndex(dialog.conflicts[0].findData(Conflict.RENAME))
    assert dialog.names[0].text() == "zonas_2" and state(dialog, 0).text == "Tabla nueva"


def test_append_with_incompatible_columns_says_which(env):
    env.rows("CREATE TABLE zonas AS SELECT 'uno' AS id")
    layer = points("zonas")
    dialog = env.dialog([layer.id()])
    dialog.conflicts[0].setCurrentIndex(dialog.conflicts[0].findData(Conflict.APPEND))
    row = state(dialog, 0)
    assert row.kind == "blocked" and "«id»" in row.text
    assert not dialog.send_button.isEnabled()


def test_two_layers_with_the_same_table_name(env):
    a, b = points("a"), points("b")
    dialog = env.dialog([a.id(), b.id()])
    dialog.names[1].setText("A")  # DuckDB no distingue mayúsculas
    assert state(dialog, 0).kind == "blocked" and "otra capa" in state(dialog, 0).text
    assert not dialog.send_button.isEnabled()
    dialog.items[1].setCheckState(0, Qt.CheckState.Unchecked)
    assert state(dialog, 0).kind == "send" and dialog.send_button.isEnabled()


def test_only_selected_appears_with_a_selection(env):
    layer = points("sel", 10)
    layer.selectByIds([1, 2])
    dialog = env.dialog([layer.id()])
    assert dialog.only_selected.isVisibleTo(dialog) and "(2)" in dialog.only_selected.text()
    dialog.only_selected.setChecked(True)
    assert isinstance(env.send(dialog), SendFinished)
    assert env.rows("SELECT count(*) FROM sel") == ((2,),)


def test_temporary_destination(env):
    layer = points("tmp")
    dialog = env.dialog([layer.id()])
    dialog.destination.setCurrentIndex(dialog.destination.count() - 1)
    assert wait_for(lambda: dialog._target is not None, TIMEOUT)
    assert dialog.temporary
    assert isinstance(env.send(dialog), SendFinished)
    assert env.rows("SELECT count(*) FROM temp.main.tmp") == ((5,),)


def test_old_file_format_offers_without_crs(env, tmp_path):
    env.rows(f"ATTACH '{tmp_path / 'viejo.duckdb'}' AS viejo (STORAGE_VERSION 'v1.0.0')")
    env.coordinator.refresh_catalog()
    assert wait_for(
        lambda: env.coordinator.catalog is not None and len(env.coordinator.catalog.databases) == 2, TIMEOUT
    )
    layer = points("capa")
    dialog = env.dialog([layer.id()])
    dialog.destination.setCurrentIndex(dialog.destinations.index(("viejo", "main")))
    assert wait_for(lambda: dialog._target is not None, TIMEOUT)
    assert state(dialog, 0).kind == "blocked"
    assert dialog.without_crs.isVisibleTo(dialog) and dialog.crs_note.isVisibleTo(dialog)
    assert not dialog.send_button.isEnabled()  # nada se escribe hasta que elige (§7, F-120)
    dialog.without_crs.setChecked(True)
    assert state(dialog, 0).kind == "send"
    event = env.send(dialog)
    assert isinstance(event, SendFinished), event
    assert env.rows(
        "SELECT data_type FROM duckdb_columns() WHERE database_name = 'viejo' AND column_name = 'geom'"
    ) == (("GEOMETRY",),)


# -- AT-IMP-001: puntos de entrada ------------------------------------------------------------------------


def test_raster_layer_is_shown_disabled_with_its_reason(env, tmp_path):
    vector = points("v")
    raster = QgsRasterLayer("", "relieve")  # no válida, pero ráster
    QgsProject.instance().addMapLayer(raster, True)
    dialog = env.dialog(None, [vector.id()])
    names = [dialog._candidates[i].name for i in range(len(dialog.items))]
    i = names.index("relieve")
    assert not (dialog.items[i].flags() & Qt.ItemFlag.ItemIsEnabled)
    assert "vectoriales" in state(dialog, i).text
    assert dialog.items[names.index("v")].checkState(0) == Qt.CheckState.Checked


def test_from_the_plus_nothing_is_checked_without_a_selection(env):
    points("a")
    dialog = env.dialog(None, [])
    assert dialog.items[0].checkState(0) == Qt.CheckState.Unchecked
    assert "marca al menos una" in dialog.summary.text()


def test_without_session_it_explains_what_to_do(iface):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    try:
        layer = points("sin sesión")
        iface.selected_layers = (layer,)
        assert plugin.send_flow.open([layer.id()]) is None
        messages = [w.text() for w in iface.messageBar().items()]
        assert any("Inicia una sesión" in t for t in messages)
    finally:
        iface.selected_layers = ()
        plugin.unload()
        QgsProject.instance().removeAllMapLayers()


def test_plugin_registers_the_layer_action_and_the_plus_entry(iface):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    actions = {a.objectName() for a in iface.layer_actions}
    assert "geoduckSendToDuckDB" in actions
    menu = plugin.content.add_button.menu()
    assert any(a.objectName() == "geoduckImportLayers" for a in menu.actions())
    plugin.unload()
    assert "geoduckSendToDuckDB" not in {a.objectName() for a in iface.layer_actions}


# -- aviso final: «Abrir» y «Deshacer» (§4) --------------------------------------------------------------


def _button(bar, name):
    for item in bar.items():
        for button in item.findChildren(QPushButton):
            if button.objectName() == name:
                return button
    return None


def test_open_and_undo_from_the_message_bar(env):
    layer = points("nueva")
    dialog = env.dialog([layer.id()])
    assert isinstance(env.send(dialog), SendFinished)
    open_button = _button(env.bar, "geoduckSendOpen")
    undo = _button(env.bar, "geoduckSendUndo")
    assert open_button is not None and undo is not None
    open_button.click()
    assert [t.name for t in env.opened] == ["nueva"]
    before = len(env.events)
    undo.click()
    assert wait_for(lambda: any(isinstance(e, SendUndone) for e in env.events[before:]), TIMEOUT)
    assert "nueva" not in {r[0] for r in env.rows("SELECT table_name FROM duckdb_tables()")}


def test_failure_says_nothing_changed(env):
    layer = points("t")
    dialog = env.dialog([layer.id()])
    env.rows("CREATE TABLE t AS SELECT 1 AS x")  # aparece después de abrir el diálogo
    event = env.send(dialog)
    assert isinstance(event, SendFailed) and not event.cancelled
    messages = [w.text() for w in env.bar.items()]
    assert any("DuckDB no cambió" in t for t in messages)


# -- «Reproyectar a…» y SRC personalizados (E4; AT-IMP-003, AT-IMP-007) ------------------------------------


def test_reproject_from_the_dialog(env):
    from qgis.core import QgsCoordinateReferenceSystem

    layer = points("geo")
    dialog = env.dialog([layer.id()])
    assert dialog.reproject_row.isVisibleTo(dialog)
    dialog.reproject.setChecked(True)
    dialog.reproject_crs.setCrs(QgsCoordinateReferenceSystem("EPSG:32719"))
    assert dialog.reproject_to == "EPSG:32719"
    assert "EPSG:32719" in dialog.summary.text()
    assert isinstance(env.send(dialog), SendFinished)
    assert env.rows("SELECT DISTINCT typeof(geom) FROM geo") == (("GEOMETRY('EPSG:32719')",),)


def test_reproject_without_source_crs_is_blocked(env):
    from qgis.core import QgsCoordinateReferenceSystem

    layer = QgsVectorLayer("Point?field=id:integer", "sin src", "memory")
    layer.setCrs(QgsCoordinateReferenceSystem())  # la capa en memoria trae EPSG:4326 por defecto
    QgsProject.instance().addMapLayer(layer)
    dialog = env.dialog([layer.id()])
    dialog.reproject.setChecked(True)
    dialog.reproject_crs.setCrs(QgsCoordinateReferenceSystem("EPSG:32719"))
    assert state(dialog, 0).kind == "blocked" and "no tiene SRC" in state(dialog, 0).text


def test_custom_crs_is_announced(env):
    from qgis.core import QgsCoordinateReferenceSystem

    layer = points("propio")
    proj = (
        "+proj=tmerc +lat_0=0 +lon_0=-63.5 +k=0.9996 +x_0=500000 +y_0=10000000 +ellps=WGS84 +units=m +no_defs"
    )
    layer.setCrs(QgsCoordinateReferenceSystem.fromProj(proj))
    dialog = env.dialog([layer.id()])
    warnings = dialog._candidates[0].warnings
    assert any("PROJJSON" in w for w in warnings)
    assert state(dialog, 0).kind == "send"


def test_append_after_reprojecting_compares_the_target_crs(env):
    from qgis.core import QgsCoordinateReferenceSystem

    env.rows(
        "CREATE TABLE utm AS SELECT 1 AS id, 'x' AS nombre, "
        "ST_SetCRS('POINT(0 0)'::GEOMETRY, 'EPSG:32719') AS geom"
    )
    layer = points("utm")
    dialog = env.dialog([layer.id()])
    dialog.conflicts[0].setCurrentIndex(dialog.conflicts[0].findData(Conflict.APPEND))
    assert state(dialog, 0).kind == "blocked"  # la capa está en EPSG:4326
    dialog.reproject.setChecked(True)
    dialog.reproject_crs.setCrs(QgsCoordinateReferenceSystem("EPSG:32719"))
    assert state(dialog, 0).mode is ImportMode.APPEND, state(dialog, 0).text
    assert isinstance(env.send(dialog), SendFinished)
    assert env.rows("SELECT count(*) FROM utm") == ((6,),)


def test_reproject_without_target_crs_cannot_send(env):
    from qgis.core import QgsCoordinateReferenceSystem

    layer = points("geo")
    dialog = env.dialog([layer.id()])
    dialog.reproject.setChecked(True)
    dialog.reproject_crs.setCrs(QgsCoordinateReferenceSystem())
    assert dialog.reproject_to is None
    assert not dialog.send_button.isEnabled() and "SRC de destino" in dialog.summary.text()
