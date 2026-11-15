# SPDX-License-Identifier: GPL-2.0-or-later
"""«Crear índice espacial…» y «Quitar índice espacial» en el explorador (#154; maqueta `154`).
PyQGIS real con una sesión real de DuckDB y la extensión espacial."""

from __future__ import annotations

import duckdb
import pytest
from qgis.PyQt.QtWidgets import QApplication, QMenu

from geoduck.domain.i18n import tr
from geoduck.domain.session import SessionState
from geoduck.ui.pro.sidebar import ACCENT_META, META, PLACE, ROLE
from geoduck.ui.pro.workspace import ProWorkspace
from tests.qgis import test_pro_workspace as base
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_workspace import _CREATED, Store, run, start

coordinator = base.coordinator
delete_widgets_in_the_main_thread = base.delete_widgets_in_the_main_thread


def _spatial_available() -> bool:
    con = duckdb.connect()
    try:
        con.execute("LOAD spatial")
        return True
    except duckdb.Error:
        return False
    finally:
        con.close()


pytestmark = [
    pytest.mark.qgis,
    pytest.mark.skipif(not _spatial_available(), reason="sin la extensión spatial"),
]


@pytest.fixture(autouse=True)
def with_spatial(monkeypatch):
    monkeypatch.setenv("GEODUCK_SPATIAL", "1")


def workspace(coordinator):
    ws = ProWorkspace(coordinator, lambda: None, Store())
    _CREATED.append(ws)
    ws.resize(1200, 800)
    ws.show()
    return ws


def table_item(ws, name):
    found = []

    def shown():
        item = _find(ws, name)
        found[:] = [item] if item is not None else []
        return bool(found)

    assert wait_for(shown), name
    return found[0]


def _find(ws, name):
    ws.sidebar._fill_all_pending()
    tree = ws.sidebar.tree

    def visit(item):
        data = item.data(0, ROLE)
        if data and data[0] == PLACE and data[1].name == name:
            return item
        for i in range(item.childCount()):
            found = visit(item.child(i))
            if found is not None:
                return found
        return None

    for i in range(tree.topLevelItemCount()):
        found = visit(tree.topLevelItem(i))
        if found is not None:
            return found
    return None


def menu_for(ws, name):
    """El clic derecho de una tabla: el menú se abre cuando llegan sus columnas."""
    item = table_item(ws, name)
    ws.sidebar.tree.setCurrentItem(item)
    before = set(QApplication.topLevelWidgets())
    ws.sidebar._context_menu(ws.sidebar.tree.visualItemRect(item).center())
    new = []

    def opened():
        menus = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu) and w not in before]
        new[:] = [w for w in menus if w.isVisible()]  # el menú del primer clic se descarta sin mostrarse
        return bool(new)

    assert wait_for(opened)
    return new[-1]


def actions(menu):
    return {a.text(): a for a in menu.actions() if a.text()}


def settle(coordinator):
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    QApplication.processEvents()


def test_create_and_remove_a_spatial_index_from_the_explorer(coordinator):
    start(coordinator)
    run(
        coordinator,
        "CREATE TABLE predios (id INTEGER PRIMARY KEY, g GEOMETRY); "
        "INSERT INTO predios SELECT range, ('POINT(' || range || ' 0)')::GEOMETRY FROM range(100); "
        "CREATE TABLE notas (id INTEGER, texto VARCHAR)",
    )
    ws = workspace(coordinator)
    settle(coordinator)
    assert tr("Create spatial index…") not in actions(menu_for(ws, "notas"))
    menu = menu_for(ws, "predios")
    asked = []
    ws._ask_spatial_index = lambda table, database, key: asked.append((table, database, key)) or True
    actions(menu)[tr("Create spatial index…")].trigger()
    menu.close()
    assert asked == [("predios", "memory", True)]
    assert wait_for(lambda: coordinator.catalog.spatial_index("memory", "main", "predios", "g") is not None)
    settle(coordinator)
    done = tr("Spatial index created on «{0}» ({1})").split("(")[0].format("predios")
    assert ws.notice.text().startswith(done)
    item = table_item(ws, "predios")
    assert item.data(0, META) == tr("index") and item.data(0, ACCENT_META)
    menu = menu_for(ws, "predios")
    actions(menu)[tr("Remove spatial index")].trigger()  # sin preguntar
    menu.close()
    assert wait_for(lambda: coordinator.catalog.spatial_index("memory", "main", "predios", "g") is None)
    settle(coordinator)
    assert ws.notice.text() == tr("Spatial index removed from «{0}»").format("predios")
    assert table_item(ws, "predios").data(0, META) is None


def test_cancel_in_the_notice_keeps_the_table_without_index(coordinator):
    start(coordinator)
    run(
        coordinator,
        "CREATE TABLE grande AS SELECT range AS id, "
        "('POINT(' || (range % 1000) || ' ' || (range // 1000) || ')')::GEOMETRY AS g FROM range(5000000)",
    )
    ws = workspace(coordinator)
    settle(coordinator)
    ws._ask_spatial_index = lambda *_: True
    ws.spatial_index(("memory", "main", "grande"), "g")
    assert ws.notice_action.isVisible() and ws.notice_action.text() == tr("Cancel")
    ws.notice_action.click()
    settle(coordinator)
    assert coordinator.catalog.spatial_index("memory", "main", "grande", "g") is None


def test_a_table_without_integer_key_says_its_layers_will_not_use_the_index(coordinator):
    start(coordinator)
    run(coordinator, "CREATE TABLE calles AS SELECT 'a' AS nombre, 'POINT(0 0)'::GEOMETRY AS g")
    ws = workspace(coordinator)
    settle(coordinator)
    asked = []
    ws._ask_spatial_index = lambda table, database, key: asked.append(key) or False
    menu = menu_for(ws, "calles")
    actions(menu)[tr("Create spatial index…")].trigger()
    menu.close()
    assert asked == [False]
    assert coordinator.catalog.spatial_index("memory", "main", "calles", "g") is None


def test_a_read_only_database_shows_the_option_greyed_with_the_reason(coordinator, tmp_path):
    path = tmp_path / "censo.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE zonas AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY AS g")
    con.close()
    start(coordinator)
    run(coordinator, f"ATTACH '{path}' AS censo (READ_ONLY)")
    ws = workspace(coordinator)
    settle(coordinator)
    action = actions(menu_for(ws, "zonas"))[tr("Create spatial index…")]
    assert not action.isEnabled()
    assert action.toolTip() == tr("The database «{0}» is open read-only.").format("censo")
