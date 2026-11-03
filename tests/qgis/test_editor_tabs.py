# SPDX-License-Identifier: GPL-2.0-or-later
"""G6 · E3: pestañas de editor, historial de la sesión en el registro y «Explicar» (AT-SQL-008, 009, 010;
sql-editor-spec §7, ui-ux-spec §9), con PyQGIS y DuckDB reales."""

from __future__ import annotations

import pytest
from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from tests.qgis.conftest import wait_for
from tests.qgis.test_sql_panel import run
from tests.qgis.test_workspace import editor_state, plugin, qgis_window, start, toggle  # noqa: F401

pytestmark = pytest.mark.qgis


@pytest.fixture
def ready(plugin):  # noqa: F811 - `plugin` es la fixture
    plugin.action.trigger()
    coordinator = start(plugin)
    return plugin, plugin.content.sql_panel, coordinator


def names(panel):
    return [panel.editor_tabs.tabText(i) for i in range(panel.editor_tabs.count())]


# -- AT-SQL-008: pestañas -------------------------------------------------------------------------------


def test_each_tab_keeps_its_text_and_only_the_active_one_runs(ready):
    _plugin, panel, coordinator = ready
    first = panel.editor
    run(panel, coordinator, "CREATE TABLE a AS SELECT 1 AS x")
    second = panel.new_editor_tab()
    assert names(panel) == ["Consulta 1", "Consulta 2"] and panel.editor is second
    run(panel, coordinator, "SELECT 42 AS respuesta")
    assert first.text() == "CREATE TABLE a AS SELECT 1 AS x"
    assert second.text() == "SELECT 42 AS respuesta"
    assert panel.current_view().preview.rows == ((42,),)
    panel.editor_tabs.setCurrentWidget(first)
    assert panel.editor is first and coordinator.state is SessionState.READY


def test_tabs_survive_toggling_window_and_panel_with_their_state(ready):
    gd, panel, _coordinator = ready
    panel.editor.setText("SELECT 1;\nSELECT 2;")
    panel.editor.setCursorPosition(1, 3)
    second = panel.new_editor_tab("SELECT 'b'")
    second.setSelection(0, 0, 0, 6)
    before = [editor_state(e) for e in panel.editors()]
    workers = gd.coordinator._engine
    toggle(gd.workspace, 2)
    toggle(gd.workspace)
    assert [editor_state(e) for e in panel.editors()] == before
    assert panel.editor is second and gd.coordinator._engine is workers  # misma sesión


def test_closing_a_tab_with_sql_asks_and_an_empty_one_does_not(ready):
    _plugin, panel, _coordinator = ready
    asked = []
    panel.confirm_close = lambda name: (asked.append(name), False)[1]
    panel.editor.setText("SELECT 1")
    panel.new_editor_tab()  # vacía
    assert panel.close_current_editor_tab() and names(panel) == ["Consulta 1"]
    assert asked == []
    assert not panel.close_editor_tab(0)  # «no» → sigue abierta
    assert asked == ["Consulta 1"] and names(panel) == ["Consulta 1"]
    panel.confirm_close = lambda _name: True
    assert panel.close_editor_tab(0)
    assert panel.editor_tabs.count() == 1 and panel.editor.text() == ""  # siempre queda una


def test_a_tab_cannot_close_while_its_statement_runs(ready):
    _plugin, panel, coordinator = ready
    panel.confirm_close = lambda _name: True
    messages = []
    panel._on_message = messages.append
    panel.editor.setText("SELECT count(*) FROM range(3000000000)")
    panel.execute(RunScope.ALL)
    assert wait_for(lambda: coordinator.state is SessionState.BUSY)
    assert not panel.close_current_editor_tab() and panel.editor_tabs.count() == 1
    assert messages and "ejecutando" in messages[-1]
    panel.cancel_button.click()
    assert wait_for(lambda: coordinator.state is not SessionState.BUSY and not panel._running)
    assert panel.close_current_editor_tab()


def test_ctrl_t_and_ctrl_w_only_with_the_focus_in_geoduck(ready):
    gd, panel, _coordinator = ready
    panel.confirm_close = lambda _name: True
    QApplication.setActiveWindow(gd.workspace.window)
    panel.editor.setFocus()
    wait_for(lambda: False, 0.2)
    QTest.keyClick(panel.editor, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    assert wait_for(lambda: panel.editor_tabs.count() == 2)
    QTest.keyClick(panel.editor, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    assert wait_for(lambda: panel.editor_tabs.count() == 1)


def test_errors_are_shown_in_the_tab_that_ran(ready):
    _plugin, panel, coordinator = ready
    first = panel.editor
    first.setText("SELECT * FROM no_existe")
    panel.execute(RunScope.ALL)
    panel.new_editor_tab("SELECT 1")  # el usuario cambia de pestaña mientras tanto
    assert wait_for(lambda: coordinator.state is not SessionState.BUSY and not panel._running)
    row = panel.log.rowCount() - 1
    panel._select_logged_statement(row, 0)  # doble clic en el registro: vuelve a su pestaña
    assert panel.editor is first and first.hasSelectedText()


# -- AT-SQL-009: historial de la sesión ---------------------------------------------------------------


def test_open_in_editor_copies_the_exact_sql_to_a_new_tab_without_running(ready):
    _plugin, panel, coordinator = ready
    # sin comentarios entre sentencias: DuckDB 1.5 los asigna a la siguiente y 2.0 a la anterior
    script = "CREATE TABLE h AS SELECT 1 AS x;\nSELECT  x   FROM h  WHERE x = 1;"
    run(panel, coordinator, script)
    rows = panel.log.rowCount()
    assert rows == 2
    opened = panel.open_logged_sql(1)
    assert opened is panel.editor and names(panel)[-1] == "Consulta 2"
    assert opened.text() == "SELECT  x   FROM h  WHERE x = 1"  # tal cual, sin el «;» final
    assert panel.logged_sql(0) == "CREATE TABLE h AS SELECT 1 AS x"
    wait_for(lambda: False, 0.3)
    assert panel.log.rowCount() == rows  # no se ejecutó nada


def test_the_log_menu_offers_open_in_editor(ready, monkeypatch):
    _plugin, panel, coordinator = ready
    run(panel, coordinator, "SELECT 7 AS siete")
    shown = []
    monkeypatch.setattr("geoduck.ui.sql_panel.QMenu.exec", lambda menu, *_a: shown.append(menu.actions()))
    rect = panel.log.visualItemRect(panel.log.item(0, 0))
    panel._log_menu(rect.center())
    (actions,) = shown
    assert [a.text() for a in actions] == ["Abrir en el editor"]
    actions[0].trigger()
    assert panel.editor.text() == "SELECT 7 AS siete"


def test_the_history_is_not_written_to_disk(ready):
    _plugin, panel, coordinator = ready
    run(panel, coordinator, "SELECT 'secreto-123' AS clave")
    settings = QgsSettings()
    stored = {k: str(settings.value(k)) for k in settings.allKeys() if k.startswith("geoduck")}
    assert not any("secreto-123" in v for v in stored.values())


# -- AT-SQL-010: «Explicar» ---------------------------------------------------------------------------------


def test_explain_shows_the_plan_and_the_table_does_not_change(ready):
    _plugin, panel, coordinator = ready
    run(panel, coordinator, "CREATE TABLE e AS SELECT 1 AS x")
    panel.editor.setText("SELECT 1 AS antes;\nDELETE FROM e;")
    panel.editor.setCursorPosition(1, 3)  # la sentencia bajo el cursor
    panel.explain_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY and not panel._running)
    view = panel.current_view()
    assert view is not None and view.statement.text == "EXPLAIN DELETE FROM e;"
    assert view.preview is not None and view.preview.rows  # el plan
    assert not view.loadable  # un plan no se carga en QGIS
    run(panel, coordinator, "SELECT count(*) AS n FROM e")
    assert panel.current_view().preview.rows == ((1,),)  # nada se borró


@pytest.mark.parametrize(
    "text", ["CREATE TABLE nunca AS SELECT 1; SELECT 2", "CREATE TABLE nunca AS SELECT 1"]
)
def test_explain_refuses_several_statements_or_other_types_without_running(ready, text):
    _plugin, panel, coordinator = ready
    messages = []
    panel._on_message = messages.append
    rows = panel.log.rowCount()
    panel.editor.setText(text)
    panel.editor.selectAll()
    panel.explain_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY and not panel._running)
    assert messages and "Explicar" in messages[-1]
    assert "nunca" not in str(coordinator.catalog)
    assert panel.log.rowCount() == rows
