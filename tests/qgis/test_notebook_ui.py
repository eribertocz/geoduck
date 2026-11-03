# SPDX-License-Identifier: GPL-2.0-or-later
"""G7 · E2: celdas del cuaderno en el panel SQL (AT-NB-001, 005, 008; sql-editor-spec §7, ui-ux-spec §10),
con PyQGIS y DuckDB reales."""

from __future__ import annotations

import pytest
from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.load import LoadMode
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from tests.qgis.conftest import wait_for
from tests.qgis.test_load_ui import AutoDialog
from tests.qgis.test_workspace import plugin, qgis_window, start  # noqa: F401

pytestmark = pytest.mark.qgis


@pytest.fixture
def ready(plugin):  # noqa: F811 - `plugin` es la fixture
    plugin.action.trigger()
    coordinator = start(plugin)
    return plugin, plugin.content.sql_panel, coordinator


def idle(panel, coordinator):
    assert wait_for(
        lambda: coordinator.state is not SessionState.BUSY and not panel._running and not panel.runner.running
    )


def sqls(panel):
    return [w.editor.text() for w in panel.notebook_view.cell_widgets()]


# -- AT-NB-001: añadir, mover, plegar, vista de hoja y borrar ----------------------------------------------


def test_cells_are_added_moved_folded_and_deleted(ready):
    _plugin, panel, _coordinator = ready
    view = panel.notebook_view
    view.cell_widgets()[0].editor.setText("SELECT 1")
    view.add_button.click()
    panel.editor.setText("SELECT 2")
    third = view.add_cell(2, "SELECT 3")
    assert sqls(panel) == ["SELECT 1", "SELECT 2", "SELECT 3"] and panel.cell is third
    view.add_cell(1)  # el «+» entre celdas inserta en su sitio
    assert sqls(panel) == ["SELECT 1", "", "SELECT 2", "SELECT 3"]

    # arrastrar la tercera celda al principio (lo que hace soltar ⠿): texto y base viajan con ella
    view._cells.dropped.emit(third.cell.id, 0)
    assert sqls(panel) == ["SELECT 3", "SELECT 1", "", "SELECT 2"]
    view.set_active(third)
    next(s for s in view.shortcuts if s.key().toString() == "Ctrl+Down").activated.emit()  # Ctrl+↓
    assert sqls(panel) == ["SELECT 1", "SELECT 3", "", "SELECT 2"]
    assert view.notebook.cells[1] is third.cell  # el modelo sigue a la vista
    _plugin.content.show()
    third.editor.setFocus()
    QTest.keyClick(
        third.editor, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier
    )  # tecla real, no QScintilla
    assert wait_for(lambda: sqls(panel) == ["SELECT 3", "SELECT 1", "", "SELECT 2"])
    QTest.keyClick(third.editor, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert wait_for(lambda: sqls(panel) == ["SELECT 1", "SELECT 3", "", "SELECT 2"])

    third.fold_editor.setChecked(True)
    assert third.editor.isHidden() and not third.fold_result.isChecked()
    third.fold_cell.setChecked(True)
    assert third.splitter.isHidden() and third.title.text() == "SELECT 3"
    third.fold_cell.setChecked(False)
    third.fold_editor.setChecked(False)
    assert not third.editor.isHidden()

    # vista de hoja (⛶ o Ctrl+E): solo esa celda; otra vez, vuelve la lista
    third.sheet_button.click()
    assert view.sheet is third
    assert [w.isHidden() for w in view.cell_widgets()] == [True, False, True, True]
    view.toggle_sheet(third)
    assert view.sheet is None and not any(w.isHidden() for w in view.cell_widgets())

    # borrar: con SQL pregunta («no» la deja); vacía no pregunta; siempre queda una celda
    asked = []
    view.confirm_delete = lambda w: (asked.append(w), False)[1]
    assert not view.delete_cell(third) and len(view.cell_widgets()) == 4
    assert view.delete_cell(view.cell_widgets()[2]) and asked == [third]
    view.confirm_delete = lambda _w: True
    for widget in list(view.cell_widgets()):
        view.delete_cell(widget)
    assert sqls(panel) == [""]


def test_duplicate_keeps_sql_and_database(ready):
    _plugin, panel, _coordinator = ready
    view = panel.notebook_view
    first = view.cell_widgets()[0]
    menu = first.more_button.menu()  # ⋯, como la DuckDB UI
    assert [(a.text(), a.shortcut().toString()) for a in menu.actions()] == [
        ("Subir celda", "Ctrl+Up"),
        ("Bajar celda", "Ctrl+Down"),
        ("", ""),
        ("Duplicar celda", ""),
        ("Eliminar", ""),
    ]
    first.editor.setText("SELECT 'copia'")
    first.cell.database = "memory"
    view._action(first, "duplicate")
    copy = view.cell_widgets()[1]
    assert copy.editor.text() == "SELECT 'copia'" and copy.cell.database == "memory"
    assert copy.cell.id != first.cell.id and panel.cell is copy and copy.load_button is not None


# -- AT-NB-005: cada celda con su base y su resultado, que se carga en QGIS --------------------------------


def test_each_cell_runs_on_its_database_and_keeps_its_result(ready, tmp_path):
    _plugin, panel, coordinator = ready
    target = tmp_path / "otra.duckdb"
    coordinator.execute_sql(f"ATTACH '{target}' AS otra; CREATE TABLE otra.t AS SELECT 7 AS n", RunScope.ALL)
    idle(panel, coordinator)
    view = panel.notebook_view
    first = view.cell_widgets()[0]
    first.editor.setText("CREATE TABLE memoria AS SELECT 1 AS m")
    second = view.add_cell(1, "SELECT n, (SELECT m FROM memory.memoria) AS m FROM t")
    second.cell.database = "otra"
    view.show_databases(coordinator.catalog, None)
    assert second.database_combo.currentData() == "otra" and first.cell.database == "memory"
    panel.run_all_button.click()  # «Ejecutar»: todas las celdas, en orden
    idle(panel, coordinator)
    assert panel._cell_view(second).preview.rows == ((7, 1),)
    assert first.results.count() == 0 and "ms" in first.status_label.text()  # DDL: sin tabla, con duración
    assert second.results.count() == 1
    assert "1" in second.status_label.text() and not second.result_box.isHidden()
    assert coordinator.catalog.default == "memory"  # la base de una celda no cambia la de la sesión

    # ▶ de la celda: solo esa; su resultado se carga en QGIS desde su propio botón
    view.set_active(first)
    first.editor.setText("SELECT 5 AS cinco")
    first.run_button.click()
    idle(panel, coordinator)
    assert panel._cell_view(first).preview.rows == ((5,),)
    assert panel._cell_view(second).preview.rows == ((7, 1),)  # la otra celda no se tocó
    assert first.load_button.isEnabled()
    before = len(QgsProject.instance().mapLayers())
    _plugin.content.load_flow._dialog_factory = AutoDialog
    first.load_button.click()
    assert wait_for(lambda: len(QgsProject.instance().mapLayers()) == before + 1)
    first.copy_button.click()
    assert QApplication.clipboard().text() == "cinco\n5"


def test_a_failing_cell_stops_the_notebook_and_a_detached_database_is_flagged(ready, tmp_path):
    _plugin, panel, coordinator = ready
    view = panel.notebook_view
    view.cell_widgets()[0].editor.setText("SELECT * FROM no_existe")
    last = view.add_cell(1, "SELECT 'nunca' AS x")
    panel.run_all_button.click()
    idle(panel, coordinator)
    assert last.results.count() == 0  # se detiene en la primera celda con error

    target = tmp_path / "fuera.duckdb"
    coordinator.execute_sql(f"ATTACH '{target}' AS fuera", RunScope.ALL)
    idle(panel, coordinator)
    last.cell.database = "fuera"
    coordinator.execute_sql("DETACH fuera", RunScope.ALL)
    idle(panel, coordinator)
    assert wait_for(lambda: last.database_combo.property("geoduck") == "error")  # se ve y avisa
    assert last.database_combo.currentText().startswith("fuera")
    messages = []
    panel._on_message = messages.append
    last.run_button.click()
    idle(panel, coordinator)
    assert messages and "fuera" in messages[-1] and last.results.count() == 0


# -- AT-NB-008: atajos de la DuckDB UI e historial dentro de una celda -------------------------------------


def shortcut(panel, keys):
    return next(s for s in panel.shortcuts if s.key().toString() == keys)


def test_cell_shortcuts_like_the_duckdb_ui(ready):
    _plugin, panel, coordinator = ready
    assert [a.text() for a in panel.cell.run_menu.actions()] == [
        "Ejecutar celda (Ctrl+Intro)",
        "Ejecutar selección (Ctrl+Mayús+Intro)",
        "Ejecutar celda y avanzar (Mayús+Intro)",
    ]
    cell = panel.cell
    cell.editor.setText("SELECT 1 AS a;\nSELECT 2 AS b;")
    shortcut(panel, "Ctrl+Return").activated.emit()  # la celda entera
    idle(panel, coordinator)
    assert cell.results.count() == 2

    cell.editor.setSelection(1, 0, 1, 13)
    shortcut(panel, "Ctrl+Shift+Return").activated.emit()  # solo la selección
    idle(panel, coordinator)
    assert cell.results.count() == 1 and panel.current_view().preview.rows == ((2,),)

    shortcut(panel, "Shift+Return").activated.emit()  # la celda y pasa a una nueva
    idle(panel, coordinator)
    assert cell.results.count() == 2 and len(panel.notebook_view.cell_widgets()) == 2
    assert panel.cell is not cell and panel.editor.text() == ""
    assert panel.log.rowCount() >= 3  # el historial de la sesión registra lo ejecutado en las celdas


def test_use_in_a_cell_changes_only_that_cell(ready, tmp_path):
    _plugin, panel, coordinator = ready
    target = tmp_path / "usada.duckdb"
    cell = panel.cell
    cell.editor.setText(f"ATTACH '{target}' AS usada; USE usada; CREATE TABLE t AS SELECT 1 AS x")
    panel.run_cell(cell)
    idle(panel, coordinator)
    assert cell.cell.database == "usada" and cell.database_combo.currentData() == "usada"
    other = panel.notebook_view.add_cell(1, "SELECT current_database() AS db")
    assert other.cell.database == "usada"  # una celda nueva hereda la base de la activa


@pytest.mark.parametrize("mode", [LoadMode.MEMORY, LoadMode.SNAPSHOT, LoadMode.CONNECTED])
def test_a_cell_result_loads_from_its_own_base_after_another_cell_changed_it(ready, tmp_path, mode):
    """Una celda en `otra` y la siguiente en `memory`: «Cargar» de la primera repite su consulta en `otra`
    (antes fallaba con «Table t does not exist»), y la base en uso no cambia."""
    gd, panel, coordinator = ready
    if gd.coordinator.load_modes()[mode] is not None:
        pytest.skip(gd.coordinator.load_modes()[mode])
    coordinator.execute_sql(
        f"ATTACH '{tmp_path / 'otra.duckdb'}' AS otra; CREATE TABLE otra.t AS SELECT 7 AS n", RunScope.ALL
    )
    idle(panel, coordinator)
    assert wait_for(lambda: coordinator.catalog.get("otra") is not None)
    view = panel.notebook_view
    first = view.cell_widgets()[0]
    first.editor.setText("SELECT n FROM t")
    first.cell.database = "otra"
    view.add_cell(1, "SELECT 1 AS uno").cell.database = "memory"
    panel.run_all_button.click()
    idle(panel, coordinator)
    assert panel._cell_view(first).database == "otra" and coordinator.catalog.default == "memory"
    messages = []
    gd.content.load_flow._on_message = messages.append
    AutoDialog.choice = mode
    gd.content.load_flow._dialog_factory = AutoDialog
    before = set(QgsProject.instance().mapLayers())
    first.load_button.click()
    assert wait_for(lambda: set(QgsProject.instance().mapLayers()) - before), messages
    idle(panel, coordinator)
    (layer_id,) = set(QgsProject.instance().mapLayers()) - before
    layer = QgsProject.instance().mapLayer(layer_id)
    assert [f["n"] for f in layer.getFeatures()] == [7]  # también Conectada, leyendo en `otra`
    rows = coordinator._engine.query("SELECT current_database()").future.result(10).rows
    assert rows == (("memory",),)  # la base en uso sigue siendo la de la última celda
