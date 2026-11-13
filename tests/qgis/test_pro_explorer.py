# SPDX-License-Identifier: GPL-2.0-or-later
"""Explorador y ancho del panel (#147, puntos 20, 21, 23 y 28; maquetas `explorador-lago` y
`explorador-columnas`): PyQGIS real con una sesión real de DuckDB."""

from __future__ import annotations

import pytest
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.i18n import tr
from geoduck.domain.sql import RunScope
from geoduck.ui.pro.places import HISTORY, TABLE, VIEW, Place
from geoduck.ui.pro.sidebar import COLUMN, META, NEW_SECONDS, ROLE
from geoduck.ui.pro.widgets import reduced_motion, relayout
from geoduck.ui.pro.workspace import PINNED_KEY
from tests.qgis import test_pro_query as base
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_query import done, new_query, workspace

pytestmark = pytest.mark.qgis

#: Las fixtures de la pestaña de consulta: una sesión lista y la copia de recuperación aparte.
coordinator = base.coordinator
recovery_dir = base.recovery_dir

PANEL = 320


def _tables(coordinator):
    ws = workspace(coordinator)
    page = new_query(
        ws,
        "CREATE TABLE lecturas AS SELECT range AS id, 'Sur' AS zona, range * 1.5 AS kwh, "
        + ", ".join(f"range AS columna_con_nombre_largo_{i}" for i in range(12))
        + " FROM range(500);\n"
        "CREATE VIEW resumen AS SELECT zona, sum(kwh) AS total FROM lecturas GROUP BY zona;",
    )
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert wait_for(lambda: any(o.name == "resumen" for o in coordinator.catalog.objects))
    return ws


def _fits(ws, what):
    QApplication.processEvents()
    relayout(ws)
    page = ws.tabs.stack.currentWidget() if len(ws.tabs) else ws.body.currentWidget()
    assert ws.minimumSizeHint().width() <= PANEL, what
    assert page.minimumSizeHint().width() <= PANEL, what


def test_the_docked_panel_works_at_320_px_with_every_kind_of_tab(coordinator):
    ws = _tables(coordinator)
    ws.set_presentation(wide=False)
    ws.resize(PANEL, 700)
    _fits(ws, "consulta con resultado")
    query = ws.tabs.stack.currentWidget()
    query.editor.setText("SELECT kwhh FROM lecturas;")
    query.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, query) and query.cards)
    _fits(ws, "consulta con una tarjeta de error")
    for place, what in (
        (Place(TABLE, "lecturas", "memory", "main"), "tabla"),
        (Place(VIEW, "resumen", "memory", "main"), "vista"),
        (Place(HISTORY, "History"), "historial"),
    ):
        ws.open_place(place)
        QApplication.processEvents()
        _fits(ws, what)
    page = ws.tabs.stack.currentWidget()
    ws.open_place(Place(TABLE, "lecturas", "memory", "main"))
    table = ws.tabs.stack.currentWidget()
    assert wait_for(lambda: table.model.rowCount() > 0)
    table.structure_button.setChecked(True)  # la estructura, también
    _fits(ws, "estructura")
    assert page is not None and ws.compact


def test_compact_mode_follows_the_window_and_never_gets_stuck(coordinator):
    ws = _tables(coordinator)
    ws.open_place(Place(TABLE, "lecturas", "memory", "main"))
    ws.resize(1300, 800)
    QApplication.processEvents()
    assert not ws.compact
    ws.resize(600, 800)  # la ventana se puede angostar: su ancho mínimo no lo fija la página
    QApplication.processEvents()
    assert ws.width() == 600 and ws.compact
    ws.resize(1300, 800)
    QApplication.processEvents()
    assert not ws.compact


# -- fijar o flotar (punto 20) -----------------------------------------------------------------------------


def _docked(coordinator, store=None):
    ws = workspace(coordinator, store=store)
    ws.set_presentation(wide=False)
    ws.resize(420, 700)
    QApplication.processEvents()
    return ws


def test_the_pin_keeps_the_explorer_beside_and_is_remembered(coordinator):
    from qgis.PyQt.QtCore import QEvent, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent

    store = base.Store()
    ws = _docked(coordinator, store)
    side = ws.sidebar
    assert side.dock_head.isVisibleTo(side) and not side.session_head.isVisibleTo(side)
    assert ws.floating and not side.pin_button.isChecked()
    ws.toggle_sidebar()
    assert side.isVisible() and ws.layout().indexOf(side) < 0  # flota encima
    side.pin_button.click()
    assert not ws.floating and store[PINNED_KEY] is True
    assert ws.layout().indexOf(side) >= 0 and side.isVisible()  # al lado: el editor se angosta
    click = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )  # fmt: skip
    QApplication.sendEvent(ws.body, click)
    assert side.isVisible()  # fijado no se cierra solo
    again = _docked(coordinator, store)
    assert not again.floating and again.sidebar.pin_button.isChecked()
    again.sidebar.pin_button.click()
    assert again.floating and again.overlay_open and store[PINNED_KEY] is False
    from qgis.PyQt.QtTest import QTest

    QTest.keyClick(again.sidebar.search.edit, Qt.Key.Key_Escape)
    assert not again.overlay_open


# -- arrastrar con el explorador cerrado (punto 20) y el lago (punto 21) -----------------------------------


def _drag(kind, widget, mime, pos):
    from qgis.PyQt.QtCore import QPointF, Qt
    from qgis.PyQt.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

    buttons, keys = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    action = Qt.DropAction.CopyAction
    if kind == "enter":
        event = QDragEnterEvent(pos, action, mime, buttons, keys)
    elif kind == "move":
        event = QDragMoveEvent(pos, action, mime, buttons, keys)
    else:
        event = QDropEvent(QPointF(pos), action, mime, buttons, keys)
    QApplication.sendEvent(widget, event)
    return event


def test_holding_a_drag_over_the_menu_button_opens_the_explorer_and_it_never_closes(coordinator, tmp_path):
    from qgis.PyQt.QtCore import QPoint

    from tests.qgis.test_pro_files import urls_mime
    from tests.qgis.test_pro_send import database_item

    path = tmp_path / "redes.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    ws = _docked(coordinator)
    assert not ws.overlay_open
    enter = _drag("enter", ws.sidebar_button, urls_mime([path]), QPoint(5, 5))
    assert enter.isAccepted() and ws.sidebar_button.property("drop") is True
    assert wait_for(lambda: ws.overlay_open, 3)  # a los ½ s
    assert ws.sidebar.drop_guide.isVisible()  # «Suelta sobre una base…»
    tree = ws.sidebar.tree
    item = database_item(ws, "memory")
    pos = tree.visualItemRect(item).center()
    _drag("enter", tree.viewport(), urls_mime([path]), pos)
    _drag("move", tree.viewport(), urls_mime([path]), pos)
    assert tree.drop_item is item  # el lago
    if not reduced_motion(tree):
        assert tree._wave.state() == tree._wave.State.Running  # ondas en bucle
    _drag("drop", tree.viewport(), urls_mime([path]), pos)
    assert tree.drop_item is None and not ws.sidebar.drop_guide.isVisible()
    assert ws.overlay_open  # mientras se arrastra y al soltar, el explorador no se cierra
    if not reduced_motion(tree):
        assert tree.splash_item is item  # el anillo y el salto del pato


def test_a_new_table_is_highlighted_and_fades(coordinator):
    ws = _tables(coordinator)
    side = ws.sidebar
    side.mark_new([("memory", "main", "lecturas")])
    [item] = side._items_of(("memory", "main", "lecturas"))
    assert side.tree.fresh(item) > 0.5 and item.parent().isExpanded()
    assert wait_for(lambda: side.tree.fresh(item) == 0, NEW_SECONDS + 2)


# -- columnas (punto 23) -------------------------------------------------------------------------------


def _expand(ws, source):
    side = ws.sidebar
    [item] = side._items_of(source)
    item.setExpanded(True)
    assert wait_for(lambda: item.childCount() and item.child(0).data(0, ROLE)[0] == COLUMN)
    return item


def test_columns_load_on_expand_with_icon_type_and_key(coordinator):
    ws = _tables(coordinator)
    page = new_query(
        ws, 'CREATE TABLE clientes (id INTEGER PRIMARY KEY, "Nombre Cliente" VARCHAR, kwh DOUBLE);'
    )
    page.execute(RunScope.ALL)
    assert wait_for(
        lambda: done(coordinator, page) and any(o.name == "clientes" for o in coordinator.catalog.objects)
    )
    item = _expand(ws, ("memory", "main", "clientes"))
    rows = [(item.child(i).text(0), item.child(i).data(0, META)) for i in range(item.childCount())]
    assert rows == [("id", "INTEGER"), ("Nombre Cliente", "VARCHAR"), ("kwh", "DOUBLE")]
    assert tr("primary key") in item.child(0).toolTip(0)
    # doble clic: su nombre en el editor, citado si hace falta
    ws.sidebar.tree.itemActivated.emit(item.child(1), 0)
    assert page.editor.text().endswith('"Nombre Cliente"')
    item.child(0).setSelected(True)
    item.child(2).setSelected(True)
    item.child(1).setSelected(False)
    assert ws.sidebar.column_text(ws.sidebar.tree.selectedItems()) == "id, kwh"
    ws.sidebar.tree.itemActivated.emit(item.child(2), 0)
    assert page.editor.text().endswith('"Nombre Cliente"id, kwh')
    # un ALTER: la tabla abierta se actualiza sola
    page.editor.setText("ALTER TABLE clientes ADD COLUMN fecha DATE;")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page))
    assert wait_for(
        lambda: any(
            it.childCount() == 4 and it.child(3).text(0) == "fecha"
            for it in ws.sidebar._items_of(("memory", "main", "clientes"))
        )
    )


def test_the_search_finds_columns(coordinator):
    ws = _tables(coordinator)
    side = ws.sidebar
    side.search.edit.setText("kwh")
    [item] = side._items_of(("memory", "main", "lecturas"))
    assert wait_for(lambda: not item.isHidden() and item.isExpanded() and item.childCount() > 1)
    shown = [item.child(i).text(0) for i in range(item.childCount()) if not item.child(i).isHidden()]
    assert shown == ["kwh"]
    side.search.edit.setText("")
    assert all(not item.child(i).isHidden() for i in range(item.childCount()))


def test_column_icons_by_type():
    from geoduck.domain.catalog import ColumnInfo
    from geoduck.ui.pro.sidebar import column_icon

    assert column_icon(ColumnInfo("id", "INTEGER", False, True)) == "key"
    assert column_icon(ColumnInfo("g", "GEOMETRY('EPSG:4326')", True)) == "geometry"
    assert [
        column_icon(ColumnInfo("x", t, True)) for t in ("VARCHAR", "DECIMAL(10,2)", "TIMESTAMP", "BOOLEAN")
    ] == [
        "type-text",
        "type-number",
        "type-date",
        "type-bool",
    ]
    assert column_icon(ColumnInfo("s", "STRUCT(a INTEGER)", True)) == "type-other"
