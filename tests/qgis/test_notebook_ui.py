# SPDX-License-Identifier: GPL-2.0-or-later
"""G7 · E2: celdas del cuaderno en el panel SQL (AT-NB-001, 005, 008; sql-editor-spec §7, ui-ux-spec §10),
con PyQGIS y DuckDB reales."""

from __future__ import annotations

import pytest
from qgis.core import QgsProject, QgsSettings
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.export import ExportFormat
from geoduck.domain.load import LoadMode
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from tests.qgis.conftest import wait_for
from tests.qgis.test_load_ui import AutoDialog
from tests.qgis.test_workspace import plugin, qgis_window, start, toggle  # noqa: F401

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
    assert wait_for(lambda: last.database_combo.property("problem") == "true")  # se ve y avisa
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


# -- AT-NB-011: «Exportar ▾» la consulta completa ---------------------------------------------------------


def test_export_writes_the_whole_query_from_the_base_of_the_cell(ready, tmp_path):
    _plugin, panel, coordinator = ready
    coordinator.execute_sql(
        f"ATTACH '{tmp_path / 'otra.duckdb'}' AS otra; "
        "CREATE TABLE otra.t AS SELECT range AS n FROM range(1000)",
        RunScope.ALL,
    )
    idle(panel, coordinator)
    assert wait_for(lambda: coordinator.catalog.get("otra") is not None)
    cell = panel.cell
    cell.editor.setText("SELECT n FROM t ORDER BY n")
    cell.cell.database = "otra"
    panel.notebook_view.add_cell(1, "SELECT 1").cell.database = "memory"  # cambia la base en uso
    panel.run_all_button.click()
    idle(panel, coordinator)
    assert len(panel._cell_view(cell).preview.rows) == 50  # la vista previa
    asked = []
    panel.choose_export_path = lambda fmt, name: (asked.append((fmt, name)), str(tmp_path / "salida"))[1]
    messages = []
    panel._on_message = messages.append
    assert cell.export_button.isEnabled()
    next(a for a in cell.export_button.menu().actions() if a.objectName() == "geoduckExport_csv").trigger()
    idle(panel, coordinator)
    assert wait_for((tmp_path / "salida.csv").exists)  # se añade la extensión
    lines = (tmp_path / "salida.csv").read_text().splitlines()
    assert lines[0] == "n" and len(lines) == 1001  # todas las filas, no las 200 de la vista previa
    assert asked == [(ExportFormat.CSV, "T.csv")]  # el nombre del resultado, sin «(50+ filas)»
    assert "1000" in messages[-1] and "salida.csv" in messages[-1]


def test_write_results_cannot_be_exported_and_the_cell_script_is_not_repeated(ready, tmp_path):
    _plugin, panel, coordinator = ready
    cell = panel.cell
    cell.editor.setText("CREATE TABLE c(x INT); INSERT INTO c VALUES (1) RETURNING x")
    panel.run_cell(cell)
    idle(panel, coordinator)
    assert not cell.export_button.isEnabled()  # un RETURNING no se repite (GD-SQL-006)
    cell.editor.setText("INSERT INTO c VALUES (2); SELECT x FROM c ORDER BY x")
    panel.run_cell(cell)
    idle(panel, coordinator)
    panel.choose_export_path = lambda *_a: f"{tmp_path}/c.parquet"
    panel.export_cell(cell, ExportFormat.PARQUET)
    idle(panel, coordinator)
    assert wait_for((tmp_path / "c.parquet").exists)
    run = coordinator._engine.query("SELECT count(*) FROM c").future.result(10)
    assert run.rows == ((2,),)  # se exportó la consulta, el INSERT no se repitió


def test_cancel_an_export_leaves_no_file(ready, tmp_path):
    _plugin, panel, coordinator = ready
    cell = panel.cell
    cell.editor.setText("SELECT a.range * b.range AS n FROM range(30000) a, range(30000) b")
    panel.run_cell(cell)
    idle(panel, coordinator)
    messages = []
    panel._on_message = messages.append
    panel.choose_export_path = lambda *_a: f"{tmp_path}/grande.parquet"
    panel.export_cell(cell, ExportFormat.PARQUET)
    assert coordinator.state is SessionState.BUSY and panel.cancel_button.isEnabled()
    wait_for(lambda: False, 0.3)
    panel.cancel_button.click()
    idle(panel, coordinator)
    assert "cancel" in messages[-1].lower()
    assert list(tmp_path.iterdir()) == []  # ni el archivo ni el temporal


# -- AT-NB-007: lista de cuadernos (solo en memoria) ------------------------------------------------------


def test_the_notebook_list_creates_renames_switches_and_closes(ready):
    gd, panel, _coordinator = ready
    notebooks = panel.notebook_list
    assert notebooks.parent() is gd.content.left_column  # ventana: encima de «Bases de datos»
    assert gd.content.left_column.indexOf(gd.content.databases_card) == 1
    assert not panel.editor_tabs.tabBar().isVisible()
    panel.cell.editor.setText("SELECT 'uno'")
    notebooks.new_button.click()
    panel.cell.editor.setText("SELECT 'dos'")
    assert notebooks.names() == ["Consulta 1", "Consulta 2"] and notebooks.list.currentRow() == 1

    notebooks.list.item(0).setText("Ventas")  # como al renombrar con doble clic o F2
    assert notebooks.names() == ["Ventas", "Consulta 2"] and panel.editor_tabs.tabText(0) == "Ventas"
    assert panel.editor_tabs.widget(0).notebook.name == "Ventas"
    notebooks.list.item(1).setText("   ")  # vacío: vuelve el nombre de antes
    assert notebooks.names() == ["Ventas", "Consulta 2"]

    notebooks.list.setCurrentRow(0)  # cambiar de cuaderno conserva el estado de cada uno
    assert panel.editor.text() == "SELECT 'uno'"
    notebooks.list.setCurrentRow(1)
    assert panel.editor.text() == "SELECT 'dos'"

    panel.confirm_close = lambda _name: True
    notebooks._on_close(0)  # Supr o «Cerrar» del menú
    assert notebooks.names() == ["Consulta 2"] and panel.editor.text() == "SELECT 'dos'"
    stored = [k for k in QgsSettings().allKeys() if k.startswith("geoduck")]
    assert not any("Ventas" in str(QgsSettings().value(k)) for k in stored)  # nada en disco


def test_in_the_panel_the_selector_shows_the_same_notebooks(ready):
    gd, panel, _coordinator = ready
    panel.new_editor_tab("SELECT 2")
    toggle(gd.workspace)  # panel acoplado
    selector = panel.notebook_selector
    assert selector.isVisibleTo(panel) and not panel.summary.isVisibleTo(panel)
    combo = selector.combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["Consulta 1", "Consulta 2"]
    combo.setCurrentIndex(0)
    assert panel.editor_tabs.currentIndex() == 0
    selector.new_button.click()
    assert combo.count() == 3 and combo.currentIndex() == 2
    toggle(gd.workspace)  # ventana
    assert not selector.isVisibleTo(panel) and panel.notebook_list.names()[-1] == "Consulta 3"


# -- AT-NB-006: resumen del resultado, sin consultas nuevas -----------------------------------------------


def test_the_summary_shows_rows_columns_and_types_without_querying(ready):
    gd, panel, coordinator = ready
    cell = panel.cell
    cell.editor.setText("SELECT range AS id, 'x' AS nombre FROM range(500)")
    panel.run_cell(cell)
    idle(panel, coordinator)
    summary = panel.summary
    assert summary.isVisibleTo(panel) and summary.line.text() == "50+ filas · 2 columnas"
    assert summary.items() == [("# id", "BIGINT"), ("Aa nombre", "VARCHAR")]
    assert summary.origin.text() == "Celda 1 · memory"
    asked = []
    engine = coordinator._engine
    original = engine.submit
    engine.submit = lambda *a, **k: (asked.append(a), original(*a, **k))[1]
    try:
        other = panel.notebook_view.add_cell(1)  # la celda activa cambia: resumen vacío
        assert summary.columns.topLevelItemCount() == 0
        panel.notebook_view.set_active(cell)
        assert summary.columns.topLevelItemCount() == 2
        toggle(gd.workspace)  # panel: el resumen es la ayuda (ⓘ) del rótulo
        assert cell.status_label.text().endswith(" ⓘ")
        assert cell.status_label.toolTip().splitlines()[:2] == ["50+ filas · 2 columnas", "id · BIGINT"]
        assert other.status_label.toolTip() == ""
    finally:
        engine.submit = original
    assert asked == []  # ninguna consulta nueva
    panel.summary_button.setChecked(False)


# -- AT-NB-009: ventana ↔ panel con varias celdas, resultados y una ejecución en curso ------------------


def test_toggling_keeps_cells_results_and_a_running_cell(ready):
    gd, panel, coordinator = ready
    view = panel.notebook_view
    first = view.cell_widgets()[0]
    first.editor.setText("SELECT 1 AS a")
    second = view.add_cell(1, "SELECT count(*) FROM range(3000000000)")  # larga
    panel.run_cell(first)
    idle(panel, coordinator)
    before = [(w.editor.text(), w.results.count(), w.cell.database) for w in view.cell_widgets()]
    panel.run_cell(second)
    assert wait_for(lambda: coordinator.state is SessionState.BUSY)
    toggle(gd.workspace)
    toggle(gd.workspace)
    assert panel.notebook_view is view
    after = [(w.editor.text(), w.results.count(), w.cell.database) for w in view.cell_widgets()]
    assert after[0] == before[0] and after[1][0] == before[1][0]
    panel.cancel_button.click()
    idle(panel, coordinator)
    assert first.results.count() == 1 and panel._cell_view(first).preview.rows == ((1,),)  # un solo resultado
    assert coordinator.state is SessionState.READY


# -- AT-NB-010: accesibilidad del cuaderno ---------------------------------------------------------------


def test_every_cell_action_has_a_name_help_and_keyboard_focus(ready):
    gd, panel, coordinator = ready
    cell = panel.cell
    cell.editor.setText("SELECT 1 AS a")
    panel.run_cell(cell)
    idle(panel, coordinator)
    widgets = [cell.run_button, cell.database_combo, cell.fold_cell, cell.fold_editor, cell.fold_result]
    widgets += [cell.sheet_button, cell.more_button, cell.copy_button, cell.export_button, cell.load_button]
    widgets += [panel.notebook_view.add_button, panel.notebook_list.new_button, panel.summary_button]
    for widget in widgets:
        name = widget.accessibleName() or (widget.text() if hasattr(widget, "text") else "")
        assert name, widget.objectName() or widget.toolTip()
        assert widget.toolTip(), name
        assert widget.focusPolicy() & Qt.FocusPolicy.TabFocus, name  # se alcanza con el teclado
    toggle(gd.workspace)  # panel: el pie, también accesible
    for widget in (panel.foot_copy, panel.foot_export, panel.foot_load, panel.notebook_selector.combo):
        assert widget.accessibleName() and widget.toolTip()
        assert widget.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert panel.foot_load.isEnabled() and panel.foot_export.isEnabled()
    assert not cell.load_button.isVisibleTo(panel)  # en el panel, los botones van al pie


def test_one_result_has_no_tab_and_a_cell_without_table_has_no_buttons(ready):
    _plugin, panel, coordinator = ready
    cell = panel.cell
    cell.editor.setText("CREATE TABLE sin_tabla(x INT)")
    panel.run_cell(cell)
    idle(panel, coordinator)
    assert not cell.load_button.isVisibleTo(cell) and not cell.export_button.isVisibleTo(cell)
    assert "ms" in cell.status_label.text()
    cell.editor.setText("SELECT 1 AS a")
    panel.run_cell(cell)
    idle(panel, coordinator)
    assert cell.load_button.isVisibleTo(cell) and not cell.results.tabBar().isVisibleTo(cell)
    cell.editor.setText("SELECT 1 AS a; SELECT 2 AS b")
    panel.run_cell(cell)
    idle(panel, coordinator)
    assert cell.results.tabBar().isVisibleTo(cell)  # con varias sentencias, sus pestañas
