# SPDX-License-Identifier: GPL-2.0-or-later
"""G6 · E1: columnas de tablas y vistas en el explorador (GD-CAT-002, AT-CAT-002; ui-ux-spec §9), con PyQGIS
y DuckDB reales."""

from __future__ import annotations

import pytest
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtTest import QTest

from tests.qgis.conftest import wait_for
from tests.qgis.test_sql_panel import run
from tests.qgis.test_workspace import plugin, qgis_window, start, toggle  # noqa: F401

pytestmark = pytest.mark.qgis

SETUP = (
    'CREATE TABLE zonas (id INTEGER NOT NULL, "Nombre ""oficial""" VARCHAR, "select" INTEGER, '
    "geom GEOMETRY, monto DECIMAL(10,2)); "
    "CREATE VIEW resumen AS SELECT id, monto FROM zonas; "
    "CREATE TEMP TABLE tmp (x DOUBLE);"
)


def find(explorer, name):
    """Primer nodo cuyo texto es `name` (a cualquier profundidad)."""
    stack = [explorer.topLevelItem(i) for i in range(explorer.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item.text(0) == name:
            return item
        stack.extend(item.child(i) for i in range(item.childCount()))
    raise AssertionError(f"{name} no está en el árbol")


def children(item):
    return [item.child(i).text(0) for i in range(item.childCount())]


def expand(explorer, name):
    item = find(explorer, name)
    item.setExpanded(True)
    assert wait_for(lambda: find(explorer, name).child(0).text(0) != "Cargando…")
    return find(explorer, name)


@pytest.fixture
def ready(plugin):  # noqa: F811 - `plugin` es la fixture
    plugin.action.trigger()
    coordinator = start(plugin)
    panel = plugin.content.sql_panel
    run(panel, coordinator, SETUP)
    assert wait_for(lambda: "zonas" in str(coordinator.catalog))
    QCoreApplication.processEvents()
    return plugin, plugin.content.explorer, panel, coordinator


def test_expanding_shows_each_column_with_its_exact_type_and_nulls(ready):
    _plugin, explorer, _panel, _coordinator = ready
    zonas = find(explorer, "zonas")
    assert zonas.childCount() == 0  # nada leído antes de expandir
    zonas = expand(explorer, "zonas")
    assert children(zonas) == [
        "id · INTEGER",
        'Nombre "oficial" · VARCHAR',
        "select · INTEGER",
        "geom · GEOMETRY",
        "monto · DECIMAL(10,2)",
    ]
    assert "Admite NULL: no" in zonas.child(0).toolTip(0)
    assert "Admite NULL: sí" in zonas.child(1).toolTip(0)
    assert not zonas.child(3).icon(0).isNull()  # geometría, por el tipo
    assert zonas.child(4).icon(0).isNull()
    assert children(expand(explorer, "resumen")) == ["id · INTEGER", "monto · DECIMAL(10,2)"]
    assert children(expand(explorer, "tmp")) == ["x · DOUBLE"]


def test_only_one_read_per_expansion_and_none_while_collapsed(ready, monkeypatch):
    _plugin, explorer, _panel, coordinator = ready
    asked = []
    original = coordinator.list_columns
    monkeypatch.setattr(coordinator, "list_columns", lambda s: (asked.append(s), original(s)))
    zonas = expand(explorer, "zonas")
    zonas.setExpanded(False)
    zonas.setExpanded(True)  # ya leídas: no se vuelven a pedir
    QCoreApplication.processEvents()
    assert len(asked) == 1 and asked[0][2] == "zonas"


def test_double_click_inserts_the_name_quoted_only_when_needed(ready):
    gd, explorer, panel, _coordinator = ready
    zonas = expand(explorer, "zonas")
    panel.editor.setText("SELECT  FROM zonas")
    panel.editor.setCursorPosition(0, 7)
    explorer.itemDoubleClicked.emit(zonas.child(0), 0)
    panel.insert_text(", ")
    explorer.itemDoubleClicked.emit(zonas.child(1), 0)
    panel.insert_text(", ")
    explorer.itemDoubleClicked.emit(zonas.child(2), 0)
    assert panel.editor.text() == 'SELECT id, "Nombre ""oficial""", "select" FROM zonas'
    # el SQL resultante es válido: se ejecuta tal cual
    run(panel, gd.coordinator, panel.editor.text())
    assert "OK" in [panel.log.item(r, 2).text() for r in range(panel.log.rowCount())][-1]


def test_double_click_on_a_table_still_loads_and_does_not_toggle_its_columns(ready):
    _plugin, explorer, _panel, _coordinator = ready
    loads = []
    explorer.load_requested.connect(lambda *a: loads.append(a))
    zonas = find(explorer, "zonas")
    explorer.scrollToItem(zonas)
    rect = explorer.visualItemRect(zonas)
    QTest.mouseDClick(explorer.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert loads and loads[0][1] == "zonas"
    assert not find(explorer, "zonas").isExpanded()


def test_only_columns_can_be_dragged_as_text(ready):
    _plugin, explorer, _panel, _coordinator = ready
    zonas = expand(explorer, "zonas")
    data = explorer.mimeData([zonas.child(0), zonas.child(2)])
    assert data is not None and data.text() == 'id, "select"'
    assert explorer.mimeData([zonas]) is None


def test_search_filters_tables_not_columns(ready):
    _plugin, explorer, _panel, _coordinator = ready
    expand(explorer, "zonas")
    explorer.set_filter("monto")  # solo es una columna
    assert find(explorer, "zonas").isHidden()
    explorer.set_filter("zon")
    zonas = find(explorer, "zonas")
    assert not zonas.isHidden() and not zonas.child(4).isHidden()


def test_ddl_refreshes_open_tables_and_nothing_stale_remains(ready):
    _plugin, explorer, panel, coordinator = ready
    expand(explorer, "zonas")
    run(panel, coordinator, "ALTER TABLE zonas ADD COLUMN nueva BOOLEAN; DROP VIEW resumen;")
    assert wait_for(lambda: "nueva · BOOLEAN" in children(find(explorer, "zonas")))
    assert find(explorer, "zonas").isExpanded()
    with pytest.raises(AssertionError):
        find(explorer, "resumen")


def test_a_missing_object_says_so_in_its_node_and_retries_later(ready):
    _plugin, explorer, _panel, coordinator = ready
    # la tabla desaparece sin que el catálogo se relea (directamente en el worker, sin el editor)
    coordinator._engine.submit(lambda h, _t: h.execute("DROP TABLE tmp")).future.result(10)
    tmp = find(explorer, "tmp")
    tmp.setExpanded(True)
    assert wait_for(lambda: children(find(explorer, "tmp")) == ["No se pudieron leer las columnas"])
    assert "ya no existe" in find(explorer, "tmp").child(0).toolTip(0)
    assert coordinator.state.value == "READY"  # la sesión sigue igual


def test_in_the_panel_double_click_goes_to_the_sql_tab(ready):
    gd, explorer, panel, _coordinator = ready
    toggle(gd.workspace)
    gd.content.tabs.setCurrentWidget(gd.content.databases_card)
    zonas = expand(explorer, "zonas")
    panel.editor.setText("")
    explorer.itemDoubleClicked.emit(zonas.child(0), 0)
    assert gd.content.tabs.currentWidget() is panel
    assert panel.editor.text() == "id"
