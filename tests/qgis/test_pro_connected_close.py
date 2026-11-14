# SPDX-License-Identifier: GPL-2.0-or-later
"""Cerrar bases y la sesión con capas Conectadas desde la interfaz (#183; maqueta `183-final`)."""

from __future__ import annotations

import duckdb
import pytest
from qgis.core import QgsProject

from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.session import SessionState
from geoduck.ui.pro.load import CONNECTED
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_switch import plugin, run, start  # noqa: F401 - fixture

pytestmark = pytest.mark.qgis

TIMEOUT = 60


def connected(ws, coordinator, sql, name, source):
    ws.loader.start(sql, name, CONNECTED, source=source)
    assert wait_for(
        lambda: ws.loader.last_report is not None and coordinator.state is SessionState.READY, TIMEOUT
    )
    report, ws.loader.last_report = ws.loader.last_report, None
    return QgsProject.instance().mapLayer(report.layer_id)


def file_db(path):
    """Un archivo con GEOMETRY y su SRC: necesita el formato v1.5.0 (DuckDB 1.5 crea v1.0 por defecto)."""
    con = duckdb.connect()
    con.execute(f"ATTACH '{path}' AS f (STORAGE_VERSION 'v1.5.0'); USE f")
    return con


def recorder(ws):
    bars, blocked = [], []
    ws.push_bar = lambda text, level, actions: bars.append((text, [label for label, _ in actions], actions))
    ws._tell_blocked = lambda title, text: blocked.append((title, text))
    return bars, blocked


def test_closing_a_file_database_leaves_its_layers_unavailable_with_open_again(plugin, tmp_path):  # noqa: F811
    path = tmp_path / "catastro.duckdb"
    con = file_db(path)
    con.execute(
        "CREATE TABLE predios AS SELECT range AS id, "
        "('POINT(' || range || ' 0)')::GEOMETRY('OGC:CRS84') AS g FROM range(5)"
    )
    con.close()
    item = plugin()
    coordinator = start(item)
    ws = item.content
    bars, _ = recorder(ws)
    coordinator.attach_database(AttachRequest(str(path), AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING))
    assert wait_for(lambda: coordinator.catalog.get("catastro") is not None, TIMEOUT)
    layer = connected(
        ws,
        coordinator,
        'SELECT * FROM "catastro"."main"."predios"',
        "Predios",
        ("catastro", "main", "predios"),
    )
    ws.detach("catastro")
    assert wait_for(lambda: bars and coordinator.state is SessionState.READY, TIMEOUT)
    text, labels, actions = bars[-1]
    assert "«catastro»" in text and "Predios" in text and labels == ["Abrir de nuevo"]
    assert not layer.isValid()
    actions[0][1]()  # «Abrir de nuevo»
    assert wait_for(lambda: layer.isValid() and coordinator.state is SessionState.READY, TIMEOUT)


def test_a_memory_database_with_layers_is_saved_as_a_file_before_closing(plugin, tmp_path):  # noqa: F811
    item = plugin()
    coordinator = start(item)
    ws = item.content
    run(
        coordinator,
        "ATTACH ':memory:' AS pozos_db; "
        "CREATE TABLE pozos_db.pozos AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY('OGC:CRS84') AS g",
    )
    layer = connected(
        ws, coordinator, 'SELECT * FROM "pozos_db"."main"."pozos"', "Pozos", ("pozos_db", "main", "pozos")
    )
    asked = []
    target = tmp_path / "pozos.duckdb"
    ws._ask_save_memory = lambda name, layers, tables, confirm: (
        asked.append((name, layers, tables, confirm)) or str(target)
    )
    ws.detach("pozos_db")
    assert asked == [("pozos_db", ["Pozos"], 1, True)]
    assert wait_for(lambda: target.exists() and coordinator.state is SessionState.READY, TIMEOUT)
    assert coordinator.catalog.get("pozos_db").path == str(target)
    assert layer.isValid() and sum(1 for _ in layer.getFeatures()) == 1


def test_unsaved_changes_block_closing_with_a_single_button_message(plugin, tmp_path):  # noqa: F811
    path = tmp_path / "catastro.duckdb"
    con = file_db(path)
    con.execute(
        "CREATE TABLE predios (id INTEGER PRIMARY KEY, nombre VARCHAR, g GEOMETRY('OGC:CRS84')); "
        "INSERT INTO predios VALUES (1, 'a', 'POINT(0 0)')"
    )
    con.close()
    item = plugin()
    coordinator = start(item)
    ws = item.content
    _, blocked = recorder(ws)
    coordinator.attach_database(AttachRequest(str(path), AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING))
    assert wait_for(lambda: coordinator.catalog.get("catastro") is not None, TIMEOUT)
    layer = connected(
        ws,
        coordinator,
        'SELECT * FROM "catastro"."main"."predios"',
        "Predios",
        ("catastro", "main", "predios"),
    )
    assert layer.startEditing()
    layer.changeAttributeValue(1, layer.fields().indexOf("nombre"), "b")
    ws.detach("catastro")
    ws.close_session()
    assert [title for title, _ in blocked] == [
        "No se puede cerrar la base «catastro»",
        "No se puede cerrar la sesión",
    ]
    assert all("Predios" in text for _, text in blocked)
    assert coordinator.catalog.get("catastro") is not None and coordinator.state is SessionState.READY
    layer.rollBack()


def test_closing_the_session_tells_which_layers_wait_for_their_database(plugin, tmp_path):  # noqa: F811
    path = tmp_path / "catastro.duckdb"
    con = file_db(path)
    con.execute("CREATE TABLE predios AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY('OGC:CRS84') AS g")
    con.close()
    item = plugin()
    coordinator = start(item)
    ws = item.content
    bars, _ = recorder(ws)
    coordinator.attach_database(AttachRequest(str(path), AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING))
    assert wait_for(lambda: coordinator.catalog.get("catastro") is not None, TIMEOUT)
    connected(
        ws,
        coordinator,
        'SELECT * FROM "catastro"."main"."predios"',
        "Predios",
        ("catastro", "main", "predios"),
    )
    ws.close_session()
    assert wait_for(lambda: coordinator.state is SessionState.DISCONNECTED and bars, TIMEOUT)
    assert bars[-1][0].startswith("Sesión de GeoDuck cerrada. 1 capa quedó no disponible")


def bar_texts(iface):
    from qgis.PyQt.QtWidgets import QPushButton

    out = []
    for item in iface.messageBar().items():
        buttons = [b.text() for b in item.findChildren(QPushButton) if b.text()]
        out.append((item.text(), buttons))
    return out


def test_the_qgis_bar_the_layer_menu_and_reopening_the_project(plugin, iface, tmp_path):  # noqa: F811
    path = tmp_path / "catastro.duckdb"
    con = file_db(path)
    con.execute("CREATE TABLE predios AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY('OGC:CRS84') AS g")
    con.close()
    item = plugin()
    coordinator = start(item)
    ws = item.content
    coordinator.attach_database(AttachRequest(str(path), AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING))
    assert wait_for(lambda: coordinator.catalog.get("catastro") is not None, TIMEOUT)
    layer = connected(
        ws,
        coordinator,
        'SELECT * FROM "catastro"."main"."predios"',
        "Predios",
        ("catastro", "main", "predios"),
    )
    layer_id = layer.id()
    ws.detach("catastro")
    assert wait_for(lambda: coordinator.state is SessionState.READY and not layer.isValid(), TIMEOUT)
    assert any("Abrir de nuevo" in buttons for _, buttons in bar_texts(iface))
    menu = {a.text(): ids for a, ids in iface.layer_actions.items()}
    assert menu.get("Abrir la base «catastro»") == [layer_id]
    project = QgsProject.instance()
    project_path = str(tmp_path / "p.qgz")
    assert project.write(project_path)
    coordinator.close_session().result(TIMEOUT)
    assert wait_for(lambda: coordinator.state is SessionState.DISCONNECTED, TIMEOUT)
    iface.messageBar().clearWidgets()
    assert project.read(project_path)  # GeoDuck se inicia solo y abre la base mientras QGIS lo lee
    reopened = project.mapLayer(layer_id)
    assert reopened is not None and reopened.isValid()
    assert coordinator.state is SessionState.READY and coordinator.catalog.get("catastro") is not None
    assert any(
        "GeoDuck abrió 1 base para este proyecto: catastro.duckdb." in text for text, _ in bar_texts(iface)
    )
    assert "Abrir la base «catastro»" not in {a.text() for a in iface.layer_actions}


def test_saving_a_project_with_layers_on_a_memory_database_warns_after_saving(plugin, iface, tmp_path):  # noqa: F811
    item = plugin()
    coordinator = start(item)
    ws = item.content
    run(coordinator, "CREATE TABLE pozos AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY('OGC:CRS84') AS g")
    connected(ws, coordinator, 'SELECT * FROM "memory"."main"."pozos"', "Pozos", ("memory", "main", "pozos"))
    assert QgsProject.instance().write(str(tmp_path / "p.qgz"))
    texts = bar_texts(iface)
    assert any(
        "«Pozos» usa la base en memoria «memory»" in text and buttons == ["Guardar la base como archivo"]
        for text, buttons in texts
    ), texts
