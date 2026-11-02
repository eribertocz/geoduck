# SPDX-License-Identifier: GPL-2.0-or-later
"""G5/E3: explorador, resultados y teclado del workspace (AT-UX-006, 007, 013; ui-ux-spec §8).

Explorador con grupos, acceso por base y búsqueda sobre la instantánea del catálogo (sin leer filas);
resultados con el tipo de cada columna y `NULL` distinto de la cadena vacía; atajos solo dentro de
GeoDuck; en un panel estrecho se compactan etiquetas sin quitar acciones.
"""

from __future__ import annotations

import duckdb
import pytest
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QAbstractButton, QApplication, QLineEdit

from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.session import SessionState
from tests.qgis.conftest import wait_for
from tests.qgis.test_explorer import tree
from tests.qgis.test_sql_panel import run
from tests.qgis.test_workspace import WorkspaceMode, plugin, qgis_window, record, start, toggle  # noqa: F401

pytestmark = pytest.mark.qgis


@pytest.fixture
def files(tmp_path):
    db = str(tmp_path / "db.duckdb")
    con = duckdb.connect(db)
    con.execute(
        "CREATE TABLE consumidores AS SELECT 1 AS id; CREATE TABLE medidores AS SELECT 1 AS id; "
        "CREATE VIEW v_consumidores AS SELECT * FROM consumidores"
    )
    con.close()
    ventas = str(tmp_path / "ventas.duckdb")
    con = duckdb.connect(ventas)
    con.execute("CREATE SCHEMA cierre; CREATE TABLE cierre.mensual AS SELECT 1 AS mes")
    con.close()
    return db, ventas


def attach_all(plugin, files):  # noqa: F811 - `plugin` es la fixture
    coordinator = start(plugin)
    db, ventas = files
    for path, access, alias in ((db, AccessMode.READ_WRITE, "db"), (ventas, AccessMode.READ_ONLY, "ventas")):
        coordinator.attach_database(AttachRequest(path, access, OpenAction.OPEN_EXISTING, alias))
        assert wait_for(
            lambda a=alias: coordinator.state is SessionState.READY and coordinator.catalog.get(a) is not None
        )
    run(plugin.content.sql_panel, coordinator, "CREATE TEMP TABLE borrador AS SELECT 1 AS x")
    assert wait_for(lambda: bool(coordinator.catalog.temporaries))
    return coordinator


# -- AT-UX-006: explorador con varias bases, vistas y temporales; búsqueda ---------------------------------


def test_explorer_groups_objects_and_shows_the_access_of_each_database(plugin, files):  # noqa: F811
    coordinator = attach_all(plugin, files)
    shown = tree(plugin.content.explorer)
    root = f"{coordinator.catalog.root} · raíz, en uso"
    assert shown[root] == {"main": {"Tablas temporales (1)": {"borrador": {}}}}
    assert shown["db · lectura y escritura"] == {
        "main": {"Tablas (2)": {"consumidores": {}, "medidores": {}}, "Vistas (1)": {"v_consumidores": {}}}
    }
    assert shown["ventas · solo lectura"] == {"cierre": {"Tablas (1)": {"mensual": {}}}, "main": {}}


def test_search_filters_and_keeps_the_groups_without_reading_rows(plugin, files):  # noqa: F811
    coordinator = attach_all(plugin, files)
    content = plugin.content
    events = record(plugin)
    content.search_edit.setText("CONSUM")  # sin distinguir mayúsculas
    assert tree(content.explorer) == {
        "db · lectura y escritura": {
            "main": {"Tablas (2)": {"consumidores": {}}, "Vistas (1)": {"v_consumidores": {}}}
        }
    }
    content.search_edit.setText("ventas")  # una base: todo su contenido
    assert tree(content.explorer) == {
        "ventas · solo lectura": {"cierre": {"Tablas (1)": {"mensual": {}}}, "main": {}}
    }
    content.search_edit.setText("cierre")  # un esquema: su camino y su contenido
    assert tree(content.explorer) == {"ventas · solo lectura": {"cierre": {"Tablas (1)": {"mensual": {}}}}}
    content.search_edit.setText("no existe")
    assert tree(content.explorer) == {}
    assert events == []  # buscar no consulta DuckDB ni cambia la sesión
    content.search_edit.setText("medid")
    coordinator.refresh_catalog()  # el filtro sigue tras releer el catálogo
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    wait_for(lambda: False, 0.3)
    assert tree(content.explorer) == {"db · lectura y escritura": {"main": {"Tablas (2)": {"medidores": {}}}}}
    content.search_edit.clear()
    assert len(tree(content.explorer)) == 3


def test_double_click_loads_by_the_object_name(plugin, files):  # noqa: F811
    attach_all(plugin, files)
    explorer = plugin.content.explorer
    asked = []
    explorer.load_requested.connect(lambda sql, name, source: asked.append((sql, name, source)))
    item = explorer.findItems("consumidores", Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)[0]
    explorer._double_clicked(item)
    assert asked == [
        ('SELECT * FROM "db"."main"."consumidores"', "consumidores", ("db", "main", "consumidores", "table"))
    ]


# -- AT-UX-007: resultados con tipos, NULL, cadena vacía y límite -------------------------------------------


def test_results_show_each_column_type_and_tell_null_from_empty(plugin):  # noqa: F811
    coordinator = start(plugin)
    panel = plugin.content.sql_panel
    run(
        panel,
        coordinator,
        "SELECT 1::INTEGER AS n, 'x' AS t, NULL::VARCHAR AS nulo, '' AS vacio, 'NULL' AS texto, "
        "DATE '2026-11-02' AS d",
    )
    table = panel.results.widget(0).table
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    assert headers == ["# n", "Aa t", "Aa nulo", "Aa vacio", "Aa texto", "d"]
    tips = [table.horizontalHeaderItem(c).toolTip() for c in range(table.columnCount())]
    assert tips == ["INTEGER", "VARCHAR", "VARCHAR", "VARCHAR", "VARCHAR", "DATE"]
    nulo, vacio, texto = table.item(0, 2), table.item(0, 3), table.item(0, 4)
    assert nulo.text() == "NULL" and nulo.font().italic() and "sin valor" in nulo.toolTip()
    assert vacio.text() == "" and not vacio.font().italic() and vacio.toolTip() == "Cadena vacía"
    assert texto.text() == "NULL" and not texto.font().italic() and texto.toolTip() == ""  # el texto 'NULL'


@pytest.mark.parametrize(("rows", "more"), [(49, False), (50, False), (51, True)])
def test_there_is_more_only_when_rows_exceed_the_limit(plugin, rows, more):  # noqa: F811
    coordinator = start(plugin)
    panel = plugin.content.sql_panel
    panel.limit_combo.setCurrentIndex(panel.limit_combo.findData(50))
    run(panel, coordinator, f"SELECT range AS n FROM range({rows})")
    view = panel.results.widget(0)
    assert view.table.rowCount() == min(rows, 50)
    assert ("hay más" in view.caption.text()) is more


# -- AT-UX-013: teclado, panel estrecho, DPI y tema --------------------------------------------------------


def test_shortcuts_run_only_with_the_focus_inside_geoduck(plugin, iface):  # noqa: F811
    coordinator = start(plugin)
    content, ws = plugin.content, plugin.workspace
    panel = content.sql_panel
    plugin.action.trigger()
    toggle(ws)  # panel acoplado: comparte ventana con el resto de QGIS
    content.tabs.setCurrentWidget(panel)
    assert all(s.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut for s in panel.shortcuts)
    other = QLineEdit(iface.mainWindow())  # p. ej. la consola de Python de QGIS
    iface.mainWindow().setCentralWidget(other)
    QApplication.setActiveWindow(iface.mainWindow())
    panel.editor.setText("SELECT 1 AS uno")
    other.setFocus()
    wait_for(lambda: False, 0.2)
    QTest.keyClick(other, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    wait_for(lambda: False, 0.5)
    assert panel.log.rowCount() == 0  # fuera de GeoDuck, Ctrl+Intro no ejecuta nada
    panel.editor.setFocus()
    wait_for(lambda: False, 0.2)
    QTest.keyClick(panel.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert wait_for(lambda: panel.log.rowCount() == 1 and coordinator.state is SessionState.READY)


def test_a_narrow_panel_compacts_labels_but_keeps_every_action(plugin):  # noqa: F811
    start(plugin)
    content, ws = plugin.content, plugin.workspace
    panel = content.sql_panel
    plugin.action.trigger()
    toggle(ws)
    content.tabs.setCurrentWidget(panel)
    ws.dock.setFloating(True)
    ws.dock.resize(320, 700)
    assert wait_for(lambda: panel.compact)  # al ancho mínimo del panel no caben las etiquetas
    for button in panel.action_buttons:
        assert (
            button.isVisibleTo(content) and button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        assert button.toolTip() and button.accessibleName()
        right = button.mapTo(panel, button.rect().topRight()).x()
        assert 0 <= right <= panel.width()  # dentro del panel: alcanzable
    assert panel.limit_combo.isVisibleTo(content)
    ws.dock.resize(700, 700)
    assert wait_for(lambda: not panel.compact)
    assert panel.run_all_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon


def test_every_action_is_reachable_with_the_keyboard(plugin):  # noqa: F811
    start(plugin)
    content = plugin.content
    plugin.action.trigger()
    buttons = [b for b in content.findChildren(QAbstractButton) if b.isVisibleTo(content)]
    assert buttons
    unreachable = [b.text() or b.toolTip() for b in buttons if not b.focusPolicy() & Qt.FocusPolicy.TabFocus]
    assert unreachable == []
    assert content.search_edit.focusPolicy() & Qt.FocusPolicy.TabFocus
