# SPDX-License-Identifier: GPL-2.0-or-later
"""Estructura de Workspace Pro (G9 · E2; workspace-pro-spec §3, §6, §8, §11; AT-WSP-002, 006, 008).

PyQGIS real con una sesión real de DuckDB: estados de la sesión, barra lateral (bases, recientes, favoritos,
filtro), pestañas, Ctrl+K y ventana ↔ panel. Las preferencias van a un diccionario, nunca al perfil.
"""

from __future__ import annotations

import contextlib
import gc
import time

import pytest
from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QPushButton, QShortcut

from geoduck.app.coordinator import SessionCoordinator
from geoduck.domain.i18n import tr
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from geoduck.plugin import make_memory_engine
from geoduck.ui.dispatcher import QtDispatcher
from geoduck.ui.pro.places import PREFIX, QUERY, TABLE, Place
from geoduck.ui.pro.shell import Mode, ProController
from geoduck.ui.pro.sidebar import PLACE, ROLE, SECTION
from geoduck.ui.pro.workspace import STATE, TABS, WELCOME, ProWorkspace
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis


class Store(dict):
    def value(self, key, defaultValue=None):  # noqa: N803
        return self.get(key, defaultValue)

    def setValue(self, key, value):
        self[key] = value


#: Workspaces creados en la prueba: se borran al final en el hilo principal. Si los recogiera el recolector
#: de ciclos de Python, podría hacerlo en el hilo del motor, y Qt falla al destruir widgets fuera de su hilo.
_CREATED: list = []


@pytest.fixture(autouse=True)
def delete_widgets_in_the_main_thread():
    yield
    while _CREATED:
        widget = _CREATED.pop()
        with contextlib.suppress(RuntimeError):  # ya borrado (p. ej. con su ventana)
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


@pytest.fixture
def coordinator(qgis_app):
    dispatcher = QtDispatcher()
    coordinator = SessionCoordinator(make_memory_engine, dispatcher)
    yield coordinator
    coordinator.shutdown(10)
    dispatcher.close()


def ready(coordinator):
    return coordinator.state is SessionState.READY and coordinator.catalog is not None


def start(coordinator):
    coordinator.start_memory_session()
    assert wait_for(lambda: ready(coordinator))


def run(coordinator, sql, expect=None):
    coordinator.execute_sql(sql, RunScope.ALL)
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    if expect is not None:
        assert wait_for(lambda: expect(coordinator.catalog))


def has(name):
    return lambda catalog: any(o.name == name for o in catalog.objects)


def workspace(coordinator, store=None):
    ws = ProWorkspace(coordinator, lambda: None, store if store is not None else Store())
    _CREATED.append(ws)
    ws.resize(1200, 800)
    ws.show()
    return ws


def table(name, database="memory"):
    return Place(TABLE, name, database, "main")


def item_of(ws, name):
    """La fila de `name` en «Bases» (la última que aparece: recientes y favoritos van antes)."""
    found = []

    def visit(item):
        data = item.data(0, ROLE)
        if data and data[0] == PLACE and data[1].name == name:
            found.append(item)
        for i in range(item.childCount()):
            visit(item.child(i))

    for i in range(ws.sidebar.tree.topLevelItemCount()):
        visit(ws.sidebar.tree.topLevelItem(i))
    return found[-1]


def shortcut(ws, keys):
    return next(s for s in ws.findChildren(QShortcut) if s.key().toString() == keys)


def test_without_session_it_offers_to_start_and_then_welcomes(coordinator):
    ws = workspace(coordinator)
    assert ws.body.currentIndex() == STATE
    assert ws.start_button.isVisible() and ws.start_button.isEnabled()
    assert ws.sidebar.status.text() == tr("Not started")
    ws.start_button.click()
    assert wait_for(lambda: ready(coordinator))
    assert wait_for(lambda: ws.body.currentIndex() == WELCOME)
    assert ws.sidebar.title.text().startswith("DuckDB ")
    assert ws.sidebar.status.text() == tr("Ready") + " · " + tr("in memory")
    assert ws.status()[1].startswith(tr("Ready") + " · DuckDB ")


def test_the_sidebar_lists_databases_schemas_tables_views_and_temporaries(coordinator):
    start(coordinator)
    ws = workspace(coordinator)
    run(
        coordinator,
        "CREATE TABLE consumidores(x INT); CREATE VIEW v_consumo AS SELECT 1; CREATE SCHEMA ventas;"
        " CREATE TABLE ventas.facturas(x INT); CREATE TEMP TABLE temporal(x INT);",
        has("facturas"),
    )
    places = {(p.kind, p.schema, p.name) for p in ws.sidebar.visible_places()}
    assert ("table", "main", "consumidores") in places
    assert ("table", "ventas", "facturas") in places
    assert ("table", "main", "temporal") in places
    views = item_of(ws, "v_consumo")
    assert views.parent().text(0) == tr("Views") + " (1)"
    assert not views.parent().isExpanded()  # las vistas, plegadas hasta que se abren


def test_double_click_opens_a_tab_once_and_ctrl_w_closes_it(coordinator):
    start(coordinator)
    store = Store()
    ws = workspace(coordinator, store)
    run(coordinator, "CREATE TABLE consumidores(x INT); CREATE TABLE lecturas(x INT);", has("lecturas"))
    tree = ws.sidebar.tree
    for _ in range(2):
        tree.itemActivated.emit(item_of(ws, "consumidores"), 0)
    assert [p.name for p in ws.tabs.places()] == ["consumidores"]
    assert ws.body.currentIndex() == TABS
    assert [p.name for p in ws.places.recents] == ["consumidores"]  # solo ordena Ctrl+K
    ws.sidebar.render(coordinator.catalog)
    sections = [tree.topLevelItem(i).data(0, ROLE) for i in range(tree.topLevelItemCount())]
    assert (SECTION, "recent") not in [tuple(s) for s in sections if s]  # sin «Recientes» (2026-11-06)
    tree.itemActivated.emit(item_of(ws, "lecturas"), 0)
    assert ws.tabs.current.name == "lecturas"
    shortcut(ws, "Ctrl+W").activated.emit()
    assert [p.name for p in ws.tabs.places()] == ["consumidores"]
    shortcut(ws, "Ctrl+W").activated.emit()
    assert len(ws.tabs) == 0 and ws.body.currentIndex() == WELCOME


def test_new_queries_are_numbered_and_tabs_come_back_after_a_restart(coordinator):
    start(coordinator)
    store = Store()
    ws = workspace(coordinator, store)
    run(coordinator, "CREATE TABLE a(x INT); CREATE TABLE b(x INT);", has("b"))
    ws.new_query_button.click()
    ws.new_query_button.click()
    assert [p.name for p in ws.tabs.places()] == [tr("Query {}").format(1), tr("Query {}").format(2)]
    ws.open_place(table("a"))
    ws.open_place(table("b"))
    ws.tabs.bar.setCurrentIndex(2)  # «a»
    again = workspace(coordinator, store)
    assert [p.name for p in again.tabs.places()] == ["a", "b"]  # las consultas sin guardar, no
    assert again.tabs.current.name == "a"


def test_the_filter_finds_letters_in_order_and_enter_opens_the_first(coordinator):
    start(coordinator)
    ws = workspace(coordinator)
    run(coordinator, "CREATE TABLE consumidores(x INT); CREATE TABLE zonas(x INT);", has("zonas"))
    ws.sidebar.search.edit.setText("CNSM")
    assert [p.name for p in ws.sidebar.visible_places()] == ["consumidores"]
    QTest.keyClick(ws.sidebar.search.edit, Qt.Key.Key_Return)
    assert ws.tabs.current.name == "consumidores"
    ws.sidebar.search.edit.clear()
    assert {"consumidores", "zonas"} <= {p.name for p in ws.sidebar.visible_places()}


def test_favorites_survive_a_restart_and_a_dropped_table_is_dimmed_with_its_reason(coordinator):
    start(coordinator)
    store = Store()
    ws = workspace(coordinator, store)
    run(coordinator, "CREATE TABLE consumidores(x INT);", has("consumidores"))
    ws.toggle_favorite(table("consumidores"))
    assert ws.places.is_favorite(table("consumidores"))
    run(coordinator, "DROP TABLE consumidores;", lambda c: not has("consumidores")(c))
    again = workspace(coordinator, store)  # «reinicio»: otro workspace con las mismas opciones
    favorite = again.sidebar.tree.topLevelItem(1)
    assert favorite.text(0) == "consumidores"
    assert favorite.foreground(0).color() == QColor(again.colors.null)
    assert tr("It is no longer in the database") in favorite.toolTip(0)
    again.open_place(table("consumidores"))
    assert len(again.tabs) == 0
    assert tr("It is no longer in the database") in again.notice.text()
    assert "consumidores" in store[PREFIX + "favorites"]  # solo el nombre


def test_ctrl_k_finds_without_accents_opens_with_enter_and_closes_with_esc(coordinator):
    start(coordinator)
    ws = workspace(coordinator)
    run(coordinator, "CREATE TABLE lecturas(x INT); CREATE TABLE niño(x INT);", has("niño"))
    shortcut(ws, "Ctrl+K").activated.emit()
    palette = ws.command_palette
    assert palette.isVisible()
    QTest.keyClicks(palette.edit, "nino")
    assert palette.shown[0].title == "niño"
    QTest.keyClick(palette.edit, Qt.Key.Key_Return)
    assert not palette.isVisible()
    assert ws.tabs.current.name == "niño"
    ws.open_palette()
    QTest.keyClicks(palette.edit, "lctr")
    assert palette.shown[0].title == "lecturas"
    QTest.keyClick(palette.edit, Qt.Key.Key_Escape)
    assert not palette.isVisible()
    assert ws.tabs.current.name == "niño"
    ws.open_palette()
    titles = [e.title for e in palette.shown]
    assert titles[0] == "niño"  # sin texto: primero las pestañas abiertas
    assert tr("New query") in titles


def test_ctrl_k_with_a_thousand_objects_answers_under_50_ms_per_key(coordinator):
    start(coordinator)
    ws = workspace(coordinator)
    sql = " ".join(f"CREATE TABLE tabla_{i:04d}_consumo(x INT);" for i in range(1000))
    run(coordinator, sql, lambda c: len(c.objects) >= 1000)
    ws.open_palette()
    worst = 0.0
    for text in ("t", "ta", "tab", "tabla_09", "tabla_099", "cnsm", "xyz"):
        begin = time.perf_counter()
        ws.command_palette.refresh(text)
        worst = max(worst, time.perf_counter() - begin)
    assert worst < 0.05, worst
    ws.command_palette.refresh("tabla_0999")
    assert ws.command_palette.shown[0].title == "tabla_0999_consumo"


def test_window_and_panel_share_the_same_tabs_and_the_sidebar_choice_is_remembered(coordinator, iface):
    start(coordinator)
    run(coordinator, "CREATE TABLE a(x INT);", has("a"))
    iface.mainWindow().resize(1200, 800)
    iface.mainWindow().show()
    store = Store()
    ws = ProWorkspace(coordinator, lambda: None, store)
    controller = ProController(iface, ws, store)
    controller.set_visible(True)
    ws.open_place(table("a"))
    ws.new_query()
    assert controller.window.isVisible() and ws.sidebar.isVisible()
    ws.dock_button.click()
    assert controller.mode is Mode.DOCK and controller.dock.isVisible()
    assert not controller.window.isVisible()
    assert ws.parent() is controller.dock.slot
    assert [p.kind for p in ws.tabs.places()] == [TABLE, QUERY]  # nada se pierde
    assert not ws.sidebar.isVisible() and not ws.dock_button.isVisible()
    assert controller.dock.header.status.text() == ws.status()[1]
    assert controller.dock.header.minimumSizeHint().width() < 360  # el estado se recorta: cabe estrecho
    controller.dock.header.window_button.click()
    assert controller.mode is Mode.WINDOW and controller.window.isVisible()
    assert ws.parent() is controller.window.slot and ws.sidebar.isVisible()
    shortcut(ws, "Ctrl+B").activated.emit()
    assert not ws.sidebar.isVisible() and str(store[PREFIX + "sidebar"]) == "0"
    assert coordinator.state is SessionState.READY  # cambiar la presentación no toca la sesión
    controller.unload()
    again = ProWorkspace(coordinator, lambda: None, store)
    controller = ProController(iface, again, store)
    controller.set_visible(True)
    assert not again.sidebar.isVisible()  # Ctrl+B se recuerda
    controller.unload()


def test_the_style_stays_inside_geoduck_and_every_icon_button_has_a_name(coordinator):
    before = QApplication.instance().styleSheet()
    ws = workspace(coordinator)
    assert QApplication.instance().styleSheet() == before
    for widget in ws.findChildren(QPushButton):
        if not widget.text():
            assert widget.accessibleName() and widget.toolTip(), widget.objectName()
