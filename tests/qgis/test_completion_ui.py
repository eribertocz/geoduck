# SPDX-License-Identifier: GPL-2.0-or-later
"""Autocompletado en la pestaña de consulta de Workspace Pro, con la sesión real (AT-SQL-007; sql-editor-spec
§7). Reescrita para la interfaz nueva en G9 · E6: el mismo completador de G6 en el editor nuevo."""

from __future__ import annotations

import pytest
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_query import coordinator, done, new_query, recovery_dir, workspace  # noqa: F401

pytestmark = pytest.mark.qgis

SETUP = (
    'CREATE TABLE zonas (id INTEGER, "Nombre" VARCHAR, "order" INTEGER); '
    "CREATE SCHEMA censo; CREATE TABLE censo.hogares (personas INTEGER);"
)


class Panel:
    """La pestaña de consulta con lo que las pruebas miran: editor, completador y cuántas ejecuciones hubo."""

    def __init__(self, ws, page, session):
        self.ws, self.page, self.coordinator = ws, page, session
        self.editor, self.completer = page.editor, page.completer

    @property
    def runs(self):
        return len(self.ws.history.entries)


def run(panel, text):
    panel.editor.setText(text)
    panel.page.execute(RunScope.ALL)
    assert wait_for(lambda: done(panel.coordinator, panel.page))


@pytest.fixture
def editor(coordinator):  # noqa: F811 - `coordinator` es la fixture
    ws = workspace(coordinator)
    page = new_query(ws)
    panel = Panel(ws, page, coordinator)
    run(panel, SETUP)
    assert wait_for(lambda: "hogares" in str(coordinator.catalog))
    QApplication.setActiveWindow(ws)
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
    panel, session = editor
    rows = panel.runs
    type_text(panel.editor, "SELECT * FROM zo")
    assert wait_for(lambda: listed(panel)[:1] == ["zonas"])
    QTest.keyClick(panel.editor, Qt.Key.Key_Return)
    assert panel.editor.text() == "SELECT * FROM zonas"
    wait_for(lambda: False, 0.3)
    assert panel.runs == rows  # aceptar no ejecuta nada
    assert session.state is SessionState.READY


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
    panel, session = editor
    run(panel, "CREATE TABLE nueva_tabla (x INTEGER)")
    assert wait_for(lambda: "nueva_tabla" in str(session.catalog))
    panel.editor.setText("")
    panel.editor.setFocus()
    type_text(panel.editor, "SELECT * FROM nue")
    assert wait_for(lambda: listed(panel) == ["nueva_tabla"])


def test_it_works_the_same_in_the_panel(editor):
    panel, _coordinator = editor
    panel.ws.set_presentation(wide=False)  # el mismo contenido, presentado como panel
    panel.editor.setText("")
    panel.editor.setFocus()
    wait_for(lambda: False, 0.2)
    type_text(panel.editor, "SELECT * FROM zo")
    assert wait_for(lambda: listed(panel)[:1] == ["zonas"])
