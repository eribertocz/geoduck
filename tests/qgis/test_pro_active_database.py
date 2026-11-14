# SPDX-License-Identifier: GPL-2.0-or-later
"""Una sola base activa; cerrar y adjuntar bases en memoria (#168; maqueta `bases`).
PyQGIS real con una sesión real de DuckDB."""

from __future__ import annotations

import pytest
from qgis.PyQt.QtWidgets import QAbstractButton, QApplication, QMenu

from geoduck.domain.i18n import tr
from geoduck.domain.session import SessionState
from geoduck.ui.pro.sidebar import ACTIVE, META
from geoduck.ui.pro.workspace import ProWorkspace
from tests.qgis import test_pro_workspace as base
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_workspace import _CREATED, Store, ready, run, start

pytestmark = pytest.mark.qgis

#: Las fixtures de `test_pro_workspace`: la sesión real y el borrado de widgets en el hilo principal.
coordinator = base.coordinator
delete_widgets_in_the_main_thread = base.delete_widgets_in_the_main_thread


def workspace(coordinator, **kwargs):
    ws = ProWorkspace(coordinator, lambda: None, Store(), **kwargs)
    _CREATED.append(ws)
    ws.resize(1200, 800)
    ws.show()
    return ws


def bases(ws):
    tree = ws.sidebar.tree
    return {
        tree.topLevelItem(i).text(0): tree.topLevelItem(i)
        for i in range(tree.topLevelItemCount())
        if tree.topLevelItem(i).data(0, META) is not None
    }


def active_in_tree(ws):
    return [name for name, item in bases(ws).items() if item.data(0, ACTIVE)]


def menu_for(ws, item):
    ws.sidebar.tree.setCurrentItem(item)
    before = set(QApplication.topLevelWidgets())
    ws.sidebar._context_menu(ws.sidebar.tree.visualItemRect(item).center())
    menus = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMenu) and w not in before]
    return menus[-1]


def actions(menu):
    return {a.text(): a for a in menu.actions() if a.text()}


def settle(coordinator):
    assert wait_for(lambda: ready(coordinator))
    QApplication.processEvents()


def test_one_active_database_is_shown_the_same_in_the_explorer_and_in_the_editor(coordinator):
    start(coordinator)
    ws = workspace(coordinator, ask_alias=lambda proposed: "borrador")
    ws.new_memory_database()
    assert wait_for(lambda: coordinator.catalog.get("borrador") is not None)
    settle(coordinator)
    assert active_in_tree(ws) == ["memory"]
    assert bases(ws)["memory"].data(0, META) == tr("active")
    ws.new_query()
    one = ws.tabs.page(ws.tabs.bar.currentIndex())
    ws.new_query()
    two = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert one.database == two.database == "memory"
    assert one.runs_in_label.text() == tr("Active database")
    one.base.setCurrentIndex(one.base.findData("borrador"))
    one.base.activated.emit(one.base.currentIndex())  # el usuario la elige en el desplegable
    assert wait_for(lambda: coordinator.catalog.default == "borrador")
    settle(coordinator)
    assert active_in_tree(ws) == ["borrador"]  # una sola verdad: el explorador la sigue
    assert one.database == two.database == "borrador"  # y todas las pestañas
    assert ws.sidebar.current_target() == ("borrador", "main")  # lo nuevo va a la activa
    menu = menu_for(ws, bases(ws)["memory"])
    actions(menu)[tr("Use as active database")].trigger()
    assert wait_for(lambda: coordinator.catalog.default == "memory")
    menu.close()


def test_the_active_or_last_database_cannot_be_closed_and_says_why(coordinator):
    start(coordinator)
    ws = workspace(coordinator)
    settle(coordinator)
    menu = menu_for(ws, bases(ws)["memory"])
    close = actions(menu)[tr("Close database")]
    assert not close.isEnabled()
    assert close.toolTip() == tr("Cannot be closed. {0}").format(
        tr("It is the active database: make another database active first.")
    )
    assert tr("Use as active database") not in actions(menu)  # ya es la activa
    menu.close()


def test_the_starting_memory_database_closes_when_another_is_active(coordinator):
    """La «memory» del inicio se cierra si no es la activa y queda otra; con tablas, pide confirmar."""
    start(coordinator)
    run(coordinator, "CREATE TABLE t AS SELECT 1 AS x;")
    asked = []
    answers = [False, True]
    ws = workspace(
        coordinator,
        ask_alias=lambda proposed: proposed,
        ask_lose=lambda name, count: asked.append((name, count)) or answers.pop(0),
    )
    ws.new_memory_database()
    assert wait_for(lambda: coordinator.catalog.get("memory_2") is not None)  # alias propuesto
    settle(coordinator)
    ws.activate_database("memory_2")
    assert wait_for(lambda: coordinator.catalog.default == "memory_2")
    settle(coordinator)
    assert actions(menu_for(ws, bases(ws)["memory"]))[tr("Close database")].isEnabled()
    ws.detach("memory")  # «Cancelar»: no se pierde nada
    assert asked == [("memory", 1)] and coordinator.catalog.get("memory") is not None
    ws.detach("memory")  # «Cerrar y perder 1 tabla»
    assert wait_for(lambda: ready(coordinator) and coordinator.catalog.get("memory") is None)
    settle(coordinator)
    assert list(bases(ws)) == ["memory_2"] and active_in_tree(ws) == ["memory_2"]
    assert coordinator.state is SessionState.READY


def test_a_saved_query_with_another_database_offers_it_without_changing_it(coordinator):
    start(coordinator)
    ws = workspace(coordinator, ask_alias=lambda proposed: "censo")
    ws.new_memory_database()
    assert wait_for(lambda: coordinator.catalog.get("censo") is not None)
    settle(coordinator)
    ws.open_recovered("guardada", "SELECT 1;", "censo", None)
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert page.saved_database == "censo" and page.database == "memory"  # no se cambió sola
    texts = [b.text() for b in ws.last_toast.findChildren(QAbstractButton)]
    assert tr("Activate «{0}»").format("censo") in texts


def test_query_notices_stay_in_their_tab_and_app_notices_clear_themselves(coordinator, monkeypatch):
    """#177: lo de una consulta, en su pestaña; el pie, solo la aplicación (información 6 s; error con ✕)."""
    from geoduck.ui.pro import workspace as module

    monkeypatch.setattr(module, "NOTICE_MS", 50)
    start(coordinator)
    ws = workspace(coordinator)
    ws.new_query()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    ws.notify("")
    from geoduck.domain.sql import RunScope

    page.execute(RunScope.ALL)  # sin SQL
    assert page.hint.text() == tr("There is no SQL to run") and ws.notice.text() == ""
    ws.notify("Base «x» abierta")
    assert wait_for(lambda: ws.notice.text() == "")  # la información se borra sola
    ws.notify("Falló", error=True)
    QApplication.processEvents()
    assert ws.notice_close.isVisibleTo(ws)
    wait_for(lambda: False, 0.2)
    assert ws.notice.text() == "Falló"  # el error se queda
    ws.notice_close.click()
    assert ws.notice.text() == "" and not ws.notice_close.isVisibleTo(ws)
