# SPDX-License-Identifier: GPL-2.0-or-later
"""G6 · E2: autocompletado en el editor real, con la sesión real (AT-SQL-007; sql-editor-spec §7)."""

from __future__ import annotations

import pytest
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.session import SessionState
from tests.qgis.conftest import wait_for
from tests.qgis.test_sql_panel import run
from tests.qgis.test_workspace import plugin, qgis_window, start, toggle  # noqa: F401

pytestmark = pytest.mark.qgis

SETUP = (
    'CREATE TABLE zonas (id INTEGER, "Nombre" VARCHAR, "order" INTEGER); '
    "CREATE SCHEMA censo; CREATE TABLE censo.hogares (personas INTEGER);"
)


@pytest.fixture
def editor(plugin):  # noqa: F811 - `plugin` es la fixture
    plugin.action.trigger()
    coordinator = start(plugin)
    panel = plugin.content.sql_panel
    run(panel, coordinator, SETUP)
    assert wait_for(lambda: "hogares" in str(coordinator.catalog))
    QApplication.setActiveWindow(plugin.workspace.window)
    panel.editor.setText("")
    panel.editor.setFocus()
    wait_for(lambda: False, 0.2)
    return panel, coordinator


def type_text(widget, text):
    for ch in text:
        QTest.keyClicks(widget, ch)


def listed(panel):
    """Etiquetas de la lista abierta (vacía si no hay lista)."""
    completer = panel.completer
    return list(completer._open[1]) if completer.is_open and completer._open else []


def test_the_qgis_keyword_list_is_replaced_by_ours(editor):
    panel, _coordinator = editor
    assert panel.editor.autoCompletionSource() == type(panel.editor).AutoCompletionSource.AcsNone


def test_typing_opens_the_list_and_enter_inserts_without_running(editor):
    panel, coordinator = editor
    rows = panel.log.rowCount()
    type_text(panel.editor, "SELECT * FROM zo")
    assert wait_for(lambda: listed(panel)[:1] == ["zonas"])
    QTest.keyClick(panel.editor, Qt.Key.Key_Return)
    assert panel.editor.text() == "SELECT * FROM zonas"
    wait_for(lambda: False, 0.3)
    assert panel.log.rowCount() == rows  # aceptar no ejecuta nada
    assert coordinator.state is SessionState.READY


def test_after_an_alias_dot_the_columns_arrive_from_the_worker_and_are_quoted(editor):
    panel, _coordinator = editor
    panel.editor.setText(" FROM zonas z")
    panel.editor.setCursorPosition(0, 0)
    type_text(panel.editor, "SELECT z.")
    # las columnas no se conocían: se piden al worker y la lista se abre al llegar
    assert wait_for(lambda: listed(panel) == ["id", "Nombre", "order"])
    QTest.keyClick(panel.editor, Qt.Key.Key_Down)
    QTest.keyClick(panel.editor, Qt.Key.Key_Tab)
    assert panel.editor.text() == 'SELECT z."Nombre" FROM zonas z'


def test_escape_closes_and_ctrl_space_reopens(editor):
    panel, _coordinator = editor
    type_text(panel.editor, "SELECT * FROM censo.")
    assert wait_for(lambda: listed(panel) == ["hogares"])
    QTest.keyClick(panel.editor, Qt.Key.Key_Escape)
    assert not panel.completer.is_open
    QTest.keyClick(panel.editor, Qt.Key.Key_Space, Qt.KeyboardModifier.ControlModifier)
    assert wait_for(lambda: listed(panel) == ["hogares"])


def test_nothing_opens_inside_strings_or_comments(editor):
    panel, _coordinator = editor
    type_text(panel.editor, "SELECT 'zon")
    wait_for(lambda: False, 0.3)
    assert not panel.completer.is_open
    panel.editor.setText("")
    type_text(panel.editor, "-- zon")
    wait_for(lambda: False, 0.3)
    assert not panel.completer.is_open


def test_enter_without_the_list_is_a_new_line(editor):
    panel, _coordinator = editor
    type_text(panel.editor, "SELECT 1")
    QTest.keyClick(panel.editor, Qt.Key.Key_Return)
    assert panel.editor.text() == "SELECT 1\n"


def test_ddl_is_seen_by_the_completion(editor):
    panel, coordinator = editor
    run(panel, coordinator, "CREATE TABLE nueva_tabla (x INTEGER)")
    assert wait_for(lambda: "nueva_tabla" in str(coordinator.catalog))
    panel.editor.setText("")
    panel.editor.setFocus()
    type_text(panel.editor, "SELECT * FROM nue")
    assert wait_for(lambda: listed(panel) == ["nueva_tabla"])


def test_it_works_the_same_in_the_panel(editor, plugin):  # noqa: F811
    panel, _coordinator = editor
    toggle(plugin.workspace)
    plugin.content.tabs.setCurrentWidget(panel)
    QApplication.setActiveWindow(plugin.workspace.dock.window())
    panel.editor.setText("")
    panel.editor.setFocus()
    wait_for(lambda: False, 0.2)
    type_text(panel.editor, "SELECT * FROM zo")
    assert wait_for(lambda: listed(panel)[:1] == ["zonas"])
