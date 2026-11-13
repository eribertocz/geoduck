# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL moderno (#146, puntos 17, 29 y 30; workspace-pro-spec §5): PyQGIS real con una sesión real de
DuckDB, con el teclado y el ratón como los usa una persona (QTest)."""

from __future__ import annotations

import pytest
from qgis.PyQt.QtCore import QPoint, QPointF, Qt
from qgis.PyQt.QtGui import QWheelEvent
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.i18n import tr
from geoduck.domain.sql import RunScope
from geoduck.ui.pro import editor_tools
from tests.qgis import test_pro_query as base
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_query import done, new_query, workspace

pytestmark = pytest.mark.qgis

#: Las fixtures de la pestaña de consulta: una sesión lista y la copia de recuperación aparte.
coordinator = base.coordinator
recovery_dir = base.recovery_dir

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier
_SCI_POINTXFROMPOSITION = 2164
_SCI_POINTYFROMPOSITION = 2165
_SCI_GETSELECTIONS = 2570
_SCI_CALLTIPACTIVE = 2202


@pytest.fixture
def page(coordinator, monkeypatch):
    settings: dict = {}

    class Settings:
        def value(self, key, default=None):
            return settings.get(key, default)

        def setValue(self, key, value):
            settings[key] = value

    monkeypatch.setattr(editor_tools, "QSettings", Settings)  # nunca las opciones reales del usuario
    ws = workspace(coordinator)
    query = new_query(ws)
    query.ws = ws
    query.editor.setFocus()
    QApplication.processEvents()
    return query


def keys(page, text):
    from qgis.PyQt.QtTest import QTest

    QTest.keyClicks(page.editor, text)


def key(page, code, modifiers=Qt.KeyboardModifier.NoModifier, widget=None):
    from qgis.PyQt.QtTest import QTest

    QTest.keyClick(widget or page.editor, code, modifiers)


def point_of(editor, line, index):
    position = editor.positionFromLineIndex(line, index)
    return QPoint(
        editor.SendScintilla(_SCI_POINTXFROMPOSITION, 0, position) + 2,
        editor.SendScintilla(_SCI_POINTYFROMPOSITION, 0, position) + 4,
    )


def test_pairs_close_skip_wrap_and_delete_together(page):
    editor = page.editor
    keys(page, "SELECT count(")
    assert editor.text() == "SELECT count()" and editor.getCursorPosition() == (0, 13)
    keys(page, "*)")
    assert editor.text() == "SELECT count(*)" and editor.getCursorPosition() == (0, 15)  # saltó el cierre
    keys(page, " WHERE a = '")
    assert editor.text().endswith("''")
    key(page, Qt.Key.Key_Backspace)  # el par vacío se borra entero
    assert editor.text() == "SELECT count(*) WHERE a = "
    keys(page, "'x(")  # dentro de un texto no se cierra nada
    assert editor.text() == "SELECT count(*) WHERE a = 'x(''"[:-1]
    editor.setText("SELECT zona FROM t")
    editor.setSelection(0, 7, 0, 11)
    keys(page, "(")
    assert editor.text() == "SELECT (zona) FROM t" and editor.selectedText() == "zona"
    key(page, Qt.Key.Key_Z, CTRL)
    assert editor.text() == "SELECT zona FROM t"  # un solo paso de deshacer


def test_enter_indents_inside_parentheses_and_keeps_the_indentation(page):
    editor = page.editor
    editor.setText("WITH t AS ()")
    editor.setCursorPosition(0, 11)
    key(page, Qt.Key.Key_Return)
    assert editor.text() == "WITH t AS (\n    \n)" and editor.getCursorPosition() == (1, 4)
    keys(page, "SELECT 1,")
    key(page, Qt.Key.Key_Return)
    assert editor.text().split("\n")[2] == "    " and editor.getCursorPosition() == (2, 4)
    key(page, Qt.Key.Key_Backspace)  # en la sangría, Retroceso quita 4 espacios
    assert editor.getCursorPosition() == (2, 0)
    editor.setText("    CASE")
    editor.setCursorPosition(0, 8)
    key(page, Qt.Key.Key_Return)
    keys(page, "WHEN 1 THEN 2")
    key(page, Qt.Key.Key_Return)
    keys(page, "END")
    assert editor.text().split("\n") == ["    CASE", "        WHEN 1 THEN 2", "    END"]  # END baja un nivel


def test_tab_expands_snippets_and_indents_with_spaces(page):
    editor = page.editor
    keys(page, "sel")
    key(page, Qt.Key.Key_Tab)
    assert editor.text() == "SELECT *\nFROM ;" and editor.getCursorPosition() == (1, 5)
    editor.setText("x")
    editor.setCursorPosition(0, 0)
    key(page, Qt.Key.Key_Tab)
    assert editor.text() == "    x"  # 4 espacios, nunca un tabulador


def test_line_tools_comment_move_duplicate_delete_and_case(page):
    editor = page.editor
    editor.setText("SELECT a,\n    b\nFROM t")
    editor.setSelection(0, 0, 1, 5)
    key(page, Qt.Key.Key_Slash, CTRL)
    assert editor.text() == "-- SELECT a,\n--     b\nFROM t"
    key(page, Qt.Key.Key_Slash, CTRL)
    assert editor.text() == "SELECT a,\n    b\nFROM t"
    editor.setCursorPosition(2, 0)
    key(page, Qt.Key.Key_Up, ALT)
    assert editor.text().split("\n") == ["SELECT a,", "FROM t", "    b"]
    key(page, Qt.Key.Key_Z, CTRL)
    editor.setCursorPosition(0, 2)
    key(page, Qt.Key.Key_Down, SHIFT | ALT)
    assert editor.text().split("\n")[:2] == ["SELECT a,", "SELECT a,"] and editor.getCursorPosition() == (
        1,
        2,
    )
    key(page, Qt.Key.Key_K, CTRL | SHIFT)
    assert editor.text() == "SELECT a,\n    b\nFROM t"
    editor.setCursorPosition(2, 6)
    key(page, Qt.Key.Key_U, CTRL | SHIFT)
    assert editor.text().endswith("FROM T")
    key(page, Qt.Key.Key_U, CTRL | SHIFT)
    assert editor.text().endswith("FROM t")


def test_format_is_one_undo_step(page):
    editor = page.editor
    editor.setText("select zona, count(*) from lecturas where kwh > 1 and zona = 'a' group by zona")
    key(page, Qt.Key.Key_F, SHIFT | ALT)
    assert editor.text() == (
        "SELECT zona,\n    count(*)\nFROM lecturas\nWHERE kwh > 1\n    AND zona = 'a'\nGROUP BY zona\n"
    )
    key(page, Qt.Key.Key_Z, CTRL)
    assert editor.text().startswith("select zona, count(*)")


def test_ctrl_d_adds_the_next_occurrence_and_typing_writes_in_all(page):
    editor = page.editor
    editor.setText("SELECT kwh, kwh * 2 AS doble FROM t WHERE kwh > 0")
    editor.setCursorPosition(0, 8)
    key(page, Qt.Key.Key_D, CTRL)
    assert editor.selectedText() == "kwh"
    key(page, Qt.Key.Key_D, CTRL)
    key(page, Qt.Key.Key_D, CTRL)
    assert editor.SendScintilla(_SCI_GETSELECTIONS) == 3
    keys(page, "energia")
    assert editor.text() == "SELECT energia, energia * 2 AS doble FROM t WHERE energia > 0"


def test_alt_click_adds_a_cursor(page):
    from qgis.PyQt.QtTest import QTest

    editor = page.editor
    editor.setText("SELECT a\nSELECT b")
    editor.setCursorPosition(0, 8)
    QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, ALT, point_of(editor, 1, 8))
    assert editor.SendScintilla(_SCI_GETSELECTIONS) == 2
    keys(page, "x")
    assert editor.text() == "SELECT ax\nSELECT bx"


def test_find_bar_counts_moves_and_replaces(page):
    editor = page.editor
    bar = page.find_bar
    editor.setText("SELECT zona FROM t;\nSELECT Zona, zonas FROM u;")
    editor.setSelection(0, 7, 0, 11)
    key(page, Qt.Key.Key_F, CTRL)
    assert bar.isVisible() and bar.find_edit.text() == "zona" and bar.find_edit.hasFocus()
    assert bar.count.text() == tr("{0} of {1}").format(1, 3)
    key(page, Qt.Key.Key_Return, widget=bar.find_edit)
    assert bar.count.text() == tr("{0} of {1}").format(2, 3) and editor.getSelection()[0] == 1
    bar.word_button.setChecked(True)
    assert len(bar.matches) == 2
    bar.case_button.setChecked(True)
    assert len(bar.matches) == 1
    bar.case_button.setChecked(False)
    bar.regex_button.setChecked(True)
    bar.find_edit.setText("zonas?")
    assert len(bar.matches) == 3 and not bar.find_edit.property("invalid")
    bar.find_edit.setText("zona(")
    assert bar.count.text() == tr("Invalid")
    key(page, Qt.Key.Key_Escape, widget=bar.find_edit)
    assert not bar.isVisible() and editor.hasFocus()
    key(page, Qt.Key.Key_H, CTRL)
    assert bar.replace_edit.isVisible()
    bar.regex_button.setChecked(False)
    bar.word_button.setChecked(True)
    bar.find_edit.setText("zona")
    bar.replace_edit.setText("barrio")
    bar.replace_all()
    assert editor.text() == "SELECT barrio FROM t;\nSELECT barrio, zonas FROM u;"
    key(page, Qt.Key.Key_Z, CTRL)  # todo de una vez, con un solo deshacer
    assert editor.text() == "SELECT zona FROM t;\nSELECT Zona, zonas FROM u;"


def test_find_in_the_selection_and_go_to_line(page):
    editor = page.editor
    bar = page.find_bar
    editor.setText("a = 1\na = 2\na = 3\na = 4")
    editor.setSelection(1, 0, 3, 0)
    key(page, Qt.Key.Key_F, CTRL)
    assert bar.selection_button.isChecked()  # varias líneas elegidas: se busca dentro
    bar.find_edit.setText("a")
    assert len(bar.matches) == 2
    bar.close_bar()
    key(page, Qt.Key.Key_G, CTRL)
    assert bar.isVisible() and not bar.count.isVisible()
    keys(page, "")
    bar.find_edit.setText("3")
    key(page, Qt.Key.Key_Return, widget=bar.find_edit)
    assert editor.getCursorPosition() == (2, 0) and not bar.isVisible()


def test_wrap_scroll_width_and_shift_wheel(page):
    editor = page.editor
    tools = page.tools
    editor.setText("SELECT " + ", ".join(f"columna_{i}" for i in range(80)) + "\nFROM t")
    tools.measure()
    bar = editor.horizontalScrollBar()
    assert bar.maximum() > 0
    point = QPointF(40, 10)
    event = QWheelEvent(
        point, QPointF(editor.viewport().mapToGlobal(QPoint(40, 10))), QPoint(), QPoint(0, -120),
        Qt.MouseButton.NoButton, SHIFT, Qt.ScrollPhase.NoScrollPhase, False,
    )  # fmt: skip
    QApplication.sendEvent(editor.viewport(), event)
    assert bar.value() > 0  # Shift+rueda: a lo ancho
    key(page, Qt.Key.Key_Z, ALT)
    assert tools.wrap
    key(page, Qt.Key.Key_Z, ALT)
    assert not tools.wrap


def test_save_removes_trailing_spaces_and_adds_the_final_newline(coordinator, page, tmp_path):
    path = tmp_path / "limpia.sql"
    page._ask_path = lambda *_a: str(path)
    page.editor.setText("SELECT 1   \nFROM t\t")
    assert page.save()
    assert path.read_text(encoding="utf-8") == "SELECT 1\nFROM t\n"
    assert page.editor.text() == "SELECT 1\nFROM t\n" and not page.modified


def test_keywords_in_upper_case_only_when_chosen(page):
    editor = page.editor
    keys(page, "select 1 ")
    assert editor.text() == "select 1 "  # por defecto, como se escribe
    page.tools.set_upper_keywords(True)
    editor.setText("")
    keys(page, "select 'from' as x from t")
    assert editor.text() == "SELECT 'from' AS x FROM t"


def test_hover_parameters_and_ctrl_click_to_the_explorer(coordinator, page):
    from qgis.PyQt.QtTest import QTest

    editor = page.editor
    editor.setText("CREATE TABLE lecturas AS SELECT 1.5 AS kwh;")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert wait_for(lambda: any(o.name == "lecturas" for o in coordinator.catalog.objects))
    editor.setText("SELECT kwh FROM lecturas")
    coordinator.list_columns(("memory", "main", "lecturas"))
    assert wait_for(lambda: ("memory", "main", "lecturas") in coordinator.known_columns())
    table = page.tools.target(point_of(editor, 0, 18))
    assert table is not None and table.source == ("memory", "main", "lecturas")
    assert "memory.main.lecturas" in page.tools.describe(table)
    column = page.tools.target(point_of(editor, 0, 8))
    assert "DECIMAL" in page.tools.describe(column) or "DOUBLE" in page.tools.describe(column)
    page.ws.sidebar.tree.setCurrentItem(None)
    QTest.mouseClick(editor.viewport(), Qt.MouseButton.LeftButton, CTRL, point_of(editor, 0, 18))
    current = page.ws.sidebar.tree.currentItem()
    assert current is not None and current.text(0) == "lecturas"
    editor.setText("")
    editor.setFocus()
    keys(page, "SELECT round(")
    assert wait_for(lambda: editor.SendScintilla(_SCI_CALLTIPACTIVE))
    assert any(line.startswith("round(") for line in page.tools._signatures["round"])


def test_the_editor_menu_lists_the_tools_with_their_shortcuts(page):
    menu = page._context.build()
    texts = [a.text() for a in menu.actions()]
    for text, shortcut in (
        (tr("Find…"), "Ctrl+F"),
        (tr("Replace…"), "Ctrl+H"),
        (tr("Go to line…"), "Ctrl+G"),
        (tr("Comment or uncomment"), "Ctrl+/"),
        (tr("Format SQL"), "Shift+Alt+F"),
        (tr("Wrap long lines"), "Alt+Z"),
    ):
        assert f"{text}\t{shortcut}" in texts
    menu.close()
