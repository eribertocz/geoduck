# SPDX-License-Identifier: GPL-2.0-or-later
"""Pestaña de consulta de Workspace Pro (G9 · E4; workspace-pro-spec §5; AT-WSP-005).

PyQGIS real con una sesión real de DuckDB: ejecutar la sentencia actual, la selección o todo; resultados por
sentencia; mensajes con la línea del error e «Ir»; base de la consulta; cancelar; abrir y guardar `.sql` (un
cuaderno de G7 como una consulta); autoguardado; preguntar al cerrar; copia de recuperación; exportar; y
GeoDuck sin DuckDB iniciado.
"""

from __future__ import annotations

import contextlib
import gc
import os
from pathlib import Path

import pytest
from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtWidgets import QPushButton

from geoduck.app.coordinator import SessionCoordinator
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.i18n import tr
from geoduck.domain.notebook import Cell, Notebook
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from geoduck.plugin import make_memory_engine
from geoduck.ui.dispatcher import QtDispatcher
from geoduck.ui.notebook_store import RecoveryStore
from geoduck.ui.pro.places import QUERY, Place
from geoduck.ui.pro.query_page import MESSAGES, RESULT, QueryPage
from geoduck.ui.pro.workspace import ProWorkspace
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

_CREATED: list = []


class Store(dict):
    def value(self, key, defaultValue=None):  # noqa: N803
        return self.get(key, defaultValue)

    def setValue(self, key, value):
        self[key] = value


@pytest.fixture(autouse=True)
def recovery_dir(tmp_path, monkeypatch):
    """La copia de recuperación en una carpeta de la prueba, nunca en el perfil de QGIS."""
    folder = tmp_path / "recuperacion"
    monkeypatch.setenv("GEODUCK_RECOVERY_DIR", str(folder))
    yield folder
    while _CREATED:
        widget = _CREATED.pop()
        with contextlib.suppress(RuntimeError):
            widget.detach_coordinator()
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


@pytest.fixture
def coordinator(qgis_app):
    dispatcher = QtDispatcher()
    coordinator = SessionCoordinator(make_memory_engine, dispatcher)
    coordinator.start_memory_session()
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    yield coordinator
    coordinator.shutdown(10)
    dispatcher.close()


def workspace(coordinator, *, paths=(), confirm="discard", store=None):
    answers = list(paths)
    ws = ProWorkspace(
        coordinator,
        lambda: None,
        store if store is not None else Store(),
        ask_path=lambda _title, _name, _pattern: answers.pop(0) if answers else "",
        confirm_close=lambda _name: confirm,
    )
    _CREATED.append(ws)
    ws.resize(1300, 800)
    ws.show()
    return ws


def new_query(ws, sql=""):
    ws.new_query()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(page, QueryPage)
    page.editor.setText(sql)
    return page


def done(coordinator, page):
    return page.run is None and coordinator.state is SessionState.READY


def test_run_runs_the_statement_under_the_cursor_and_shows_its_rows(coordinator):
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno;\nSELECT range AS n FROM range(5);")
    page.editor.setCursorPosition(1, 3)
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert len(page.results) == 1
    assert [c.name for c in page.model.columns] == ["n"]
    assert page.model.rowCount() == 5
    assert page.view.current == RESULT and not page.result_tabs.isVisible()
    assert page.range_label.text().startswith(tr("Rows {} of {}").format("1–5", "5") + " · ")


def test_all_shows_one_result_tab_per_statement_with_rows(coordinator):
    ws = workspace(coordinator)
    page = new_query(ws, "CREATE TABLE t AS SELECT 1 AS a;\nSELECT * FROM t;\nSELECT 2 AS b, 3 AS c;")
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and len(page.results) == 3)
    assert page.result_tabs.isVisible() and page.result_tabs.count() == 2
    assert [c.name for c in page.model.columns] == ["b", "c"]  # la última, elegida
    page.result_tabs.setCurrentIndex(0)
    assert [c.name for c in page.model.columns] == ["a"]
    page.view.buttons[MESSAGES].click()
    assert len(page._log) == 3 and all(ok for ok, _ in page._log)


def test_selection_runs_only_the_selection(coordinator):
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno, 2 AS dos")
    page.editor.setSelection(0, 0, 0, 15)  # «SELECT 1 AS uno»
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert [c.name for c in page.model.columns] == ["uno"]


def test_an_error_shows_messages_with_its_line_and_go_moves_the_cursor(coordinator):
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1;\nSELECT no_existe FROM range(1);\nSELECT 3;")
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.view.current == MESSAGES
    assert [ok for ok, _ in page._log] == [True, False]
    assert "no_existe" in page._log[1][1]
    texts = [w.text() for w in page.messages.widget().findChildren(type(page.summary))]
    assert any(tr("Line {0} · near «{1}»").format(2, "no_existe") in t for t in texts)
    # «columna N» confunde: solo línea y palabra (#139)
    assert not any(tr("line {}, column {}").format(2, 8) in t for t in texts)
    # la tarjeta del error (#145): título, lugar y «Ir»
    [card] = page.cards
    assert card.title.text() == tr("The column «{}» does not exist").format("no_existe")
    card.go_button.click()
    assert page.editor.getCursorPosition() == (1, 7)
    summary = tr("{} OK · {} with error").format(1, 1) + " · " + tr("{} not run").format(1)
    assert page.summary.text() == summary


def test_the_query_runs_in_its_database(coordinator, tmp_path):
    coordinator.attach_database(
        AttachRequest(str(tmp_path / "db.duckdb"), AccessMode.READ_WRITE, OpenAction.CREATE_NEW, "db")
    )
    assert wait_for(lambda: coordinator.catalog is not None and coordinator.catalog.get("db") is not None)
    ws = workspace(coordinator)
    page = new_query(ws, "CREATE TABLE en_db AS SELECT 1 AS x;")
    assert wait_for(lambda: page.base.findData("db") >= 0)
    page.base.setCurrentIndex(page.base.findData("db"))
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert wait_for(
        lambda: any(o.database == "db" and o.name == "en_db" for o in coordinator.catalog.objects)
    )


def test_cancel_stops_a_long_query(coordinator):
    from qgis.PyQt.QtTest import QTest

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT count(*) FROM range(100000000000) a;")
    page.run_button.click()
    # #143, punto 1: pasados 0,3 s, el pato en el lago, «Ejecutando… N s» y ■ Cancelar · Esc en la barra del
    # resultado, sin copiar, exportar ni cargar
    assert wait_for(lambda: page.running.isVisibleTo(page) and page.stop_button.isEnabled())
    assert page.lake.progress is None and page.lake.isVisibleTo(page)  # nada de un lado a otro
    assert page.elapsed_label.text().startswith(tr("Running… {} s").format("")[:5])
    assert page.stop_button.text() == tr("Cancel · Esc")
    assert not page.export_button.isVisibleTo(page) and not page.run_button.isEnabled()
    assert not page.copy_button.isVisibleTo(page)
    QTest.keyClick(page.editor, Qt.Key.Key_Escape)  # Esc cancela mientras corre
    assert wait_for(lambda: done(coordinator, page), 30)
    assert page._log and page._log[0] == (False, tr("Cancelled"))
    assert not page.running.isVisibleTo(page) and not page._escape.isEnabled()
    assert page.export_button.isVisibleTo(page)


def _ctrl_enter(page, *, shift=False):
    """Ctrl+Enter (o Ctrl+Shift+Enter) tecleado en el editor, como lo haría el usuario."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest

    modifiers = Qt.KeyboardModifier.ControlModifier
    if shift:
        modifiers |= Qt.KeyboardModifier.ShiftModifier
    page.editor.setFocus()
    QTest.keyClick(page.editor, Qt.Key.Key_Return, modifiers)


def test_ctrl_enter_runs_even_with_the_completion_list_open(coordinator):
    """#139: con la lista de autocompletado abierta, Ctrl+Enter la cierra y ejecuta (no escribe nada)."""
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT range AS n FROM ra")
    page.editor.setCursorPosition(0, 25)
    page.editor.showUserList(1, ["range", "rank"])
    assert page.editor.isListActive()
    _ctrl_enter(page)
    assert not page.editor.isListActive()
    assert page.editor.text() == "SELECT range AS n FROM ra"
    assert wait_for(lambda: done(coordinator, page) and page.results)


def test_ctrl_enter_wins_over_another_shortcut_with_the_same_keys(coordinator):
    """#139: otro atajo con Ctrl+Enter (de QGIS o de otro complemento) lo dejaría ambiguo y sin efecto; el
    editor toma la tecla antes."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QKeySequence
    from qgis.PyQt.QtWidgets import QShortcut

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno;")
    other = QShortcut(QKeySequence("Ctrl+Return"), ws)
    other.setContext(Qt.ShortcutContext.ApplicationShortcut)
    hits = []
    other.activated.connect(lambda: hits.append(1))
    other.activatedAmbiguously.connect(lambda: hits.append(2))
    _ctrl_enter(page)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert hits == []
    _ctrl_enter(page, shift=True)  # Ctrl+Shift+Enter: todo
    assert wait_for(lambda: done(coordinator, page) and page.results)


def test_run_never_fails_silently(coordinator):
    """#139: si no puede ejecutar (otra consulta en curso), lo dice."""
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT count(*) FROM range(100000000000) a;")
    notices = []
    page.said.connect(notices.append)  # #177: en su pestaña
    page.run_button.click()
    assert wait_for(page.stop_button.isEnabled)
    _ctrl_enter(page)
    assert notices == [tr("A query is already running · «Cancel» stops it")]
    other = new_query(ws, "SELECT 1;")
    other.said.connect(notices.append)  # #177: en su pestaña
    _ctrl_enter(other)
    assert notices[-1] == tr(
        "GeoDuck is finishing another task (loading, exporting or importing): run it when it ends"
    )
    page.stop_button.click()
    assert wait_for(lambda: done(coordinator, page), 30)


def test_a_syntax_error_opens_messages_and_marks_the_editor(coordinator):
    """#139: un error de sintaxis (DuckDB no deja correr nada) abre «Mensajes», marca la línea y la palabra
    en el editor y deja un enlace que lleva al error; al editar, las marcas se van."""
    from geoduck.ui.pro import editor as pro_editor

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno;")
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.view.current == RESULT
    page.editor.setText("SELECT range AS zona\nFROM range(3)\nGROUP zona;")
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and page._log)
    assert page.view.current == MESSAGES
    marks = page.editor.markersAtLine(2)
    assert marks & (1 << pro_editor.ERROR_MARK) and marks & (1 << pro_editor.ERROR_LINE)
    assert page.error_link.isVisibleTo(page)
    assert tr("Error on line {0}, near «{1}»").format(3, "zona") in page.error_link.text()
    position = page.editor.text().rindex("zona")
    assert "syntax error" in page.editor.status.message_at(position)
    page.editor.setCursorPosition(0, 0)
    page.error_link.linkActivated.emit("#")
    assert page.editor.getCursorPosition() == (2, 6)
    page.editor.insert(" ")
    assert not page.editor.status.shown
    assert not page.error_link.isVisibleTo(page)


def test_each_statement_gets_its_mark(coordinator):
    """#139: ✓ la que corrió, ✕ la del error, – la que no llegó a correr."""
    from geoduck.ui.pro import editor as pro_editor

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1;\n\nSELECT no_existe FROM range(1);\n\nSELECT 3;")
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.editor.markersAtLine(0) & (1 << pro_editor.OK_MARK)
    assert page.editor.markersAtLine(2) & (1 << pro_editor.ERROR_MARK)
    assert page.editor.markersAtLine(4) & (1 << pro_editor.SKIPPED_MARK)
    assert tr("Error on line {0}, near «{1}»").format(3, "no_existe") in page.error_link.text()


def test_after_loading_the_keyboard_goes_back_to_the_editor(coordinator):
    """#139: tras «Cargar en QGIS» el teclado vuelve al editor y Ctrl+Enter sigue funcionando."""
    from qgis.PyQt.QtWidgets import QApplication

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno;")
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    loads = []
    page._loader = lambda *args, **kwargs: loads.append(args)
    page.grid.setFocus()
    page.load_in_qgis("copy")
    assert loads and QApplication.focusWidget() is page.editor


def test_save_as_autosave_and_reopen(coordinator, tmp_path):
    path = tmp_path / "consumo.sql"
    store = Store()
    ws = workspace(coordinator, paths=[str(tmp_path / "consumo")], store=store)
    page = new_query(ws, "SELECT 42;")
    assert page.modified
    assert page.save()
    assert path.read_text(encoding="utf-8") == "SELECT 42;\n"  # con salto final (#146, punto 30)
    assert ws.tabs.current == Place(QUERY, "consumo.sql", path=str(path))
    assert ws.tabs.bar.tabText(ws.tabs.bar.currentIndex()) == "consumo.sql"
    assert [p.name for p in ws.places.recents] == ["consumo.sql"]
    page.editor.setText("SELECT 43;")
    index = ws.tabs.bar.currentIndex()
    assert ws.tabs.bar.tabText(index) == "consumo.sql" and ws.tabs.is_modified(index)  # el ● ámbar
    assert wait_for(lambda: path.read_text(encoding="utf-8") == "SELECT 43;", 5)  # autoguardado
    again = workspace(coordinator, store=store)  # «reinicio»: la consulta guardada vuelve con su SQL
    restored = again.tabs.page(0)
    assert isinstance(restored, QueryPage) and restored.editor.text() == "SELECT 43;"
    assert not restored.modified


def test_a_g7_notebook_opens_as_one_query(coordinator, tmp_path):
    from geoduck.domain.notebook_file import dumps

    path = tmp_path / "cuaderno.sql"
    notebook = Notebook("cuaderno", [Cell(sql="SELECT 1;", database="memory"), Cell(sql="SELECT 2;")])
    path.write_text(dumps(notebook), encoding="utf-8")
    ws = workspace(coordinator, paths=[str(path)])
    QCoreApplication.processEvents()
    ws.open_query_file()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(page, QueryPage)
    assert page.editor.text() == f"-- {tr('database')}: memory\nSELECT 1;\n\nSELECT 2;\n"
    assert page.database == "memory"


def test_closing_an_unsaved_query_asks(coordinator):
    keep = workspace(coordinator, confirm="cancel")
    new_query(keep, "SELECT 1;")
    keep.tabs.close_current()
    assert len(keep.tabs) == 1
    drop = workspace(coordinator, confirm="discard")
    new_query(drop, "SELECT 1;")
    drop.tabs.close_current()
    assert len(drop.tabs) == 0
    empty = workspace(coordinator, confirm="cancel")
    new_query(empty, "")
    empty.tabs.close_current()  # una consulta vacía se cierra sin preguntar
    assert len(empty.tabs) == 0


def test_the_recovery_copy_brings_back_queries_after_a_crash(coordinator, recovery_dir):
    crashed = RecoveryStore(Path(recovery_dir))
    crashed.save([Notebook("Consulta 7", [Cell(sql="SELECT 7;", database="memory")])])
    crashed._lock.unlock()  # su QGIS «se cerró de golpe»: la carpeta queda sin dueño
    ws = workspace(coordinator)
    toast = ws.recovery.toast
    assert toast is not None and toast.isVisible()
    toast.actions[0].click()  # «Recuperar»
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(page, QueryPage)
    assert page.editor.text() == "SELECT 7;" and page.database == "memory"
    assert ws.tabs.is_modified(ws.tabs.bar.currentIndex())
    assert not crashed.folder.exists()
    page.editor.setText("SELECT 8;")
    ws.recovery.save()
    own = ws.recovery.store.folder
    assert own is not None and "SELECT 8;" in "".join(p.read_text() for p in own.glob("*.sql"))
    ws.detach_coordinator()
    assert not own.exists()  # al cerrar bien, la copia se borra


def test_export_writes_the_full_query(coordinator, tmp_path):
    target = tmp_path / "salida.csv"
    ws = workspace(coordinator, paths=[str(target)])
    page = new_query(ws, "SELECT range AS n FROM range(5000);")
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.export_button.isEnabled()
    next(a for a in page.export_menu.actions() if a.data() == "csv").trigger()
    assert wait_for(lambda: target.exists() and coordinator.state is SessionState.READY, 20)
    assert len(target.read_text().splitlines()) == 5001  # entera, no la vista previa
    # la línea de tiempo (#148): Consulta → DuckDB escribe el archivo → Archivo, terminada con ✓
    from geoduck.ui.pro.timeline import TimelineWindow

    windows = ws.findChildren(TimelineWindow)
    assert wait_for(
        lambda: windows and windows[-1].view.title.text() == tr("Exported: {0}").format("salida.csv")
    )
    view = windows[-1].view
    [row] = view.rows
    assert [v.title.text() for v in row.views] == [tr("Query"), tr("GeoDuck writes the file"), tr("File")]
    assert all(v.node.state == "done" for v in row.views)
    assert row.status.text() == "✓ " + tr("{0} rows").format("5 000")
    texts = [b.text() for b in windows[-1].findChildren(QPushButton) if b.isVisible()]
    assert tr("Open folder") in texts and tr("Load in QGIS") in texts and tr("Close") in texts


def test_export_menu_shows_four_formats_and_the_rest_one_step_back(coordinator):
    """Maqueta aprobada (2026-11-07): Parquet, GeoPackage, CSV y FlatGeobuf a la vista; el resto en «Más
    formatos ▸»; nunca SpatiaLite ni SQLite; cada opción dice qué pasará."""
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS n;")
    shown = [a.data() for a in page.export_menu.actions() if a.data()]
    assert shown == ["parquet", "gpkg", "csv", "fgb"]
    more = next(a.menu() for a in page.export_menu.actions() if a.menu() is not None)
    rest = [a.data() for a in more.actions() if a.data()]
    assert rest == ["arrow", "json", "shp", "geojson", "kml", "gdb", "xlsx"]
    assert all(a.toolTip() for a in more.actions() if a.data())


def test_a_gdal_format_asks_before_loading_spatial_and_cancel_exports_nothing(
    coordinator, tmp_path, monkeypatch
):
    from geoduck.ui.pro import load as load_module

    asked = []
    monkeypatch.setattr(load_module, "ASK_SPATIAL", lambda label, installed: asked.append(label) or False)
    target = tmp_path / "salida.gpkg"
    ws = workspace(coordinator, paths=[str(target)])
    page = new_query(ws, "SELECT 1 AS n;")
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    next(a for a in page.export_menu.actions() if a.data() == "gpkg").trigger()
    assert wait_for(lambda: asked, 20)
    assert asked == ["GeoPackage"] and not target.exists()


def test_without_duckdb_everything_is_grey_except_start(qgis_app):
    dispatcher = QtDispatcher()
    idle = SessionCoordinator(make_memory_engine, dispatcher)
    ws = workspace(idle)
    assert ws.start_button.text() == tr("Start GeoDuck") and ws.start_button.isEnabled()
    assert ws.open_button.isEnabled() and ws.create_button.isEnabled()
    for widget in (ws.sidebar.search, ws.sidebar.tree, ws.new_query_button):
        assert not widget.isEnabled()
    # el menú de la sesión sí: sin sesión ofrece «Iniciar DuckDB» (marca, 2026-11-07)
    assert ws.sidebar.session_button.isEnabled() and ws.sidebar.start_action.isVisible()
    assert ws.sidebar.diagnostics_button.isEnabled() and ws.sidebar.about_button.isEnabled()
    assert ws.state_title.text() == tr("GeoDuck is not started")
    idle.shutdown(5)
    dispatcher.close()


def test_run_sql_typed_by_the_user_through_execute_too(coordinator):
    """Ctrl+Enter y Ctrl+Shift+Enter llegan a la consulta aunque el foco esté en el editor."""
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 5 AS cinco;")
    page.editor.setFocus()
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.model.rows == ((5,),)
    assert os.environ["GEODUCK_RECOVERY_DIR"]


def test_a_long_result_has_pages_its_total_and_the_row_detail_like_a_table(coordinator):
    """Propietario (2026-11-06): el resultado de una consulta se maneja como la pestaña de tabla: «Filas 1–100
    de N · tiempo» abajo, ‹ › de 100 filas, el total contado aparte y el detalle de la fila, plegable."""
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT range AS n, 'v' || range AS v FROM range(250);")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    shown = page.model.rowCount()  # #170: las filas que se ven; sin ‹ ›
    assert page.model.row(0) == (0, "v0") and not hasattr(page, "next_button")
    first = tr("Rows {} of {}").format(f"1–{shown}", "250")
    assert wait_for(lambda: page.range_label.text().startswith(first))
    assert page.summary.text() == ""  # el resumen está en el pie
    # el detalle: la fila elegida, con su número real
    assert page.detail.isVisible() and page.detail.title.text() == tr("Row {}").format("1")
    page.go(100)  # desplazarse: repite la consulta con ventana para el bloque que falta
    assert wait_for(lambda: page.model.offset == 100 and page.model.row(0) is not None)
    assert page.model.row(0) == (100, "v100")
    assert page.range_label.text().startswith(tr("Rows {} of {}").split("{}")[0] + "101–")
    page.grid.setCurrentIndex(page.model.index(0, 0))
    assert page.detail.title.text() == tr("Row {}").format("101")
    page.go(10_000)  # más allá del final: la última ventana
    assert wait_for(lambda: page.model.row(page.model.rowCount() - 1) is not None)
    assert page.model.row(page.model.rowCount() - 1) == (249, "v249")
    page.go(100)
    assert wait_for(lambda: page.model.offset == 100)
    # plegar y volver a abrir el detalle
    page.detail_button.setChecked(False)
    assert not page.detail.isVisible()
    page.detail_button.setChecked(True)
    assert page.detail.isVisible()
    buttons = page.detail.findChildren(type(page.detail_button))
    assert not any(b.toolTip() == tr("Hide the row detail") for b in buttons)  # sin ✕: solo el ◫ (#144)
    # «Mensajes» no tiene páginas ni detalle
    page.view.set_current(MESSAGES)
    page._show_view(MESSAGES)
    assert page.range_label.text() == ""


def test_a_short_result_is_not_counted_again_and_a_write_has_no_pages(coordinator):
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT range AS n FROM range(5);")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.range_label.text().startswith(tr("Rows {} of {}").format("1–5", "5"))
    assert not page.data.vbar.isVisible()  # todo cabe: nada que desplazar
    page.editor.setText("CREATE TABLE w AS SELECT range AS n FROM range(300); DELETE FROM w RETURNING n;")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.model.count == 100  # el DELETE … RETURNING muestra solo lo que trajo
    page.go(10_000)  # se recorre, pero nunca se repite para traer más
    shown = page.model.rowCount()
    assert page.model.row(shown - 1) is not None and page.data.model.missing() == []
    expected = tr("Rows {} of more than {}").format(f"{101 - shown}–100", "100")
    assert wait_for(lambda: page.range_label.text().startswith(expected))


def test_one_run_button_marks_what_will_run_and_runs_exactly_that(coordinator):
    """Propietario (2026-11-06): un solo «Ejecutar»; la barra a la izquierda y el botón dicen qué correrá
    (la sentencia del cursor, también en una línea en blanco, igual con DuckDB 1.5 y 2.0); con selección,
    «Ejecutar selección»; «Ejecutar todo» en «⋯» y con Ctrl+Shift+Enter."""
    from geoduck.ui.pro.editor import MARK, PLAY

    ws = workspace(coordinator)
    text = "SELECT 1 AS uno;\n\nSELECT 2 AS dos\nFROM range(1);\n"
    page = new_query(ws, text)
    marked = lambda: [ln for ln in range(page.editor.lines()) if page.editor.markersAtLine(ln) & (1 << MARK)]  # noqa: E731
    page.editor.setCursorPosition(1, 0)  # la línea en blanco entre las dos: la anterior
    page.mark_statement()
    assert marked() == [0] and page.run_button.accessibleName() == tr("Run · line {}").format(1)
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert [c.name for c in page.model.columns] == ["uno"]
    page.editor.setCursorPosition(3, 2)
    page.mark_statement()
    assert marked() == [2, 3] and page.run_button.accessibleName() == tr("Run · line {}").format(3)
    assert tr("Run all ({} statements) · Ctrl+Shift+Enter").format(2) in page.run_button.toolTip()
    assert page.editor.markersAtLine(2) & (1 << PLAY)  # ▶ en el margen, primera línea de la sentencia
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results[0].statement.text.startswith("SELECT 2"))
    assert [c.name for c in page.model.columns] == ["dos"]
    page.editor.setSelection(0, 0, 0, 8)
    page.mark_statement()
    assert marked() == [] and page.run_button.accessibleName() == tr("Run selection")
    assert page.run_all_action.text().startswith(tr("Run all ({} statements)").format(2))
    page.editor.setSelection(0, 0, 0, 0)
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and len(page.results) == 2)


def test_file_is_on_the_tab_right_click_and_run_all_is_in_the_editor_menu(coordinator, tmp_path):
    """#143: una sola idea por zona. El archivo, en el clic derecho de la pestaña; al final de las pestañas,
    «Cerrar todas»; la barra de la consulta solo ejecuta; las filas, en la barra del resultado."""
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno;\nSELECT 2 AS dos;")
    bar = ws.tabs.bar
    ws._tab_menu(bar.tabRect(bar.currentIndex()).center())
    texts = [a.text() for a in ws._last_tab_menu.actions() if not a.isSeparator()]
    assert texts[0] == tr("Save") + "\tCtrl+S"
    assert texts[1] == tr("Save as…") and texts[2].startswith(tr("Open query…"))
    assert texts[3].startswith(tr("Close"))
    ws._last_tab_menu.close()
    assert not hasattr(ws, "file_button")  # sin «⋯»
    assert ws.close_all_button.toolTip() == tr("Close all tabs") and ws.close_all_button.isVisibleTo(ws)
    assert page.run_button.text() == ""  # solo el ícono ▶
    for icon in (page.copy_button, page.export_button, page.load_button):  # junto a las filas, solo íconos
        assert icon.text() == "" and icon.parentWidget() is page.summary.parentWidget()
    assert any(lab.text() == tr("Active database") for lab in page.findChildren(type(page.summary)))
    page.editor.setCursorPosition(0, 2)
    page.mark_statement()
    menu = page._context.build()
    actions = [a for a in menu.actions() if not a.isSeparator()]
    assert actions[0].text().startswith(tr("Run · line {}").format(1))
    assert actions[1] is page.run_all_action
    assert len(actions) > 2  # y debajo, el menú de siempre del editor
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and len(page.results) == 2)


def test_close_all_tabs_and_play_in_the_margin(coordinator):
    """«Cerrar todas las pestañas» al final de la barra; ▶ del margen ejecuta la sentencia de esa línea."""
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno;\n\nSELECT 2 AS dos;")
    page._play_line(2)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert [c.name for c in page.model.columns] == ["dos"]
    page.saved_text = page.editor.text()  # sin cambios: cerrar no pregunta
    new_query(ws, "")
    assert len(ws.tabs) == 2
    ws.close_all_button.click()
    assert len(ws.tabs) == 0 and not ws.close_all_button.isVisibleTo(ws)


# -- #143: consulta por zonas --------------------------------------------------------------------------


def _rename(ws, name):
    """Doble clic en el nombre de la pestaña actual, escribir y Enter (#143, punto 6)."""
    from qgis.PyQt.QtTest import QTest

    ws.tabs.start_rename(ws.tabs.bar.currentIndex())
    editor = ws.tabs.rename_editor
    assert editor is not None and editor.isVisible() and editor.selectedText()
    editor.setText(name)
    QTest.keyClick(editor, Qt.Key.Key_Return)


def test_double_click_renames_a_new_query_and_esc_cancels(coordinator):
    from qgis.PyQt.QtTest import QTest

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1;")
    ws.tabs.bar.tabBarDoubleClicked.emit(ws.tabs.bar.currentIndex())
    assert ws.tabs.rename_editor is not None
    QTest.keyClick(ws.tabs.rename_editor, Qt.Key.Key_Escape)  # Esc: nada cambia
    assert ws.tabs.rename_editor is None and page.place.name == tr("Query {}").format(1)
    _rename(ws, "ventas")
    assert (
        page.place == Place(QUERY, "ventas") and ws.tabs.bar.tabText(ws.tabs.bar.currentIndex()) == "ventas"
    )
    other = new_query(ws, "SELECT 2;")
    _rename(ws, "ventas")  # otra pestaña ya se llama así: no se repite
    assert other.place.name != "ventas"
    assert tr("A tab named «{}» is already open").format("ventas") in ws.notice.text()


def test_renaming_a_saved_query_renames_its_file_and_never_overwrites(coordinator, tmp_path):
    ws = workspace(coordinator, paths=[str(tmp_path / "consumo.sql")])
    page = new_query(ws, "SELECT 42;")
    assert page.save()
    _rename(ws, "ventas")
    assert page.place == Place(QUERY, "ventas.sql", path=str(tmp_path / "ventas.sql"))
    assert (tmp_path / "ventas.sql").read_text(encoding="utf-8") == "SELECT 42;\n"
    assert not (tmp_path / "consumo.sql").exists()
    assert [p.name for p in ws.places.recents] == ["ventas.sql"]
    (tmp_path / "otra.sql").write_text("SELECT 0;", encoding="utf-8")
    assert page.rename("otra") == tr("«{}» already exists in that folder: the query keeps its name").format(
        "otra.sql"
    )
    assert page.place.name == "ventas.sql" and (tmp_path / "otra.sql").read_text() == "SELECT 0;"
    assert page.rename("mal/nombre") and page.place.name == "ventas.sql"


def test_unsaved_changes_show_the_amber_dot_and_close_all_asks(coordinator):
    keep = workspace(coordinator, confirm="cancel")
    new_query(keep, "SELECT 1;")
    new_query(keep, "")
    assert keep.tabs.is_modified(0) and not keep.tabs.is_modified(1)
    assert tr("Unsaved changes") in keep.tabs.bar.tabToolTip(0)
    keep.close_all_button.click()  # la vacía se cierra; la que tiene cambios pregunta y se queda
    assert len(keep.tabs) == 1
    drop = workspace(coordinator, confirm="discard")
    new_query(drop, "SELECT 1;")
    new_query(drop, "SELECT 2;")
    drop.close_all_button.click()
    assert len(drop.tabs) == 0 and not drop.close_all_button.isVisibleTo(drop)


def test_copy_puts_the_rows_in_the_clipboard_with_their_names(coordinator):
    from qgis.PyQt.QtGui import QGuiApplication

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT range AS n, 'a' || range AS t FROM range(3);")
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.model.rowCount() == 3)
    assert page.copy_button.isEnabled() and page.copy_button.toolTip()
    page.copy_button.click()
    assert QGuiApplication.clipboard().text() == "n\tt\n0\ta0\n1\ta1\n2\ta2"


def test_the_margin_play_runs_that_statement(coordinator):
    from geoduck.ui.pro.editor import PLAY

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno;\nSELECT 2 AS dos;")
    page.editor.setCursorPosition(1, 0)
    page.mark_statement()
    assert page.editor.markersAtLine(1) & (1 << PLAY) and not page.editor.markersAtLine(0) & (1 << PLAY)
    page._play_line(0)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert [c.name for c in page.model.columns] == ["uno"]


def test_the_lake_swims_and_rests_with_reduced_motion(qgis_app, monkeypatch):
    from geoduck.ui.pro import widgets
    from geoduck.ui.pro.tokens import LIGHT

    lake = widgets.Lake(LIGHT)
    lake.resize(200, lake.height())
    lake.show()
    assert lake.animated and lake.progress is None
    lake.phase = 0.0
    left = lake.duck_x()
    lake.phase = 1.0
    assert lake.duck_x() > left  # de un lado al otro
    lake.set_progress(0.5)
    assert lake.duck_x() == pytest.approx((13 + 200 - 16) / 2)
    lake.set_progress(2)
    assert lake.progress == 1.0
    lake.hide()
    assert not lake.animated
    monkeypatch.setattr(widgets, "reduced_motion", lambda _w: True)
    lake.show()
    assert not lake.animated  # menos animaciones: el pato queda quieto
    lake.close()


def test_the_run_button_is_a_compact_filled_square(coordinator):
    """Propietario (2026-11-13, opción 1): ▶ lleno, 28 × 28, a la altura del selector de base."""
    from geoduck.ui.pro.query_page import RUN_SIZE

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1;")
    assert page.run_button.size().width() == page.run_button.size().height() == RUN_SIZE == 28
    assert page.run_button.text() == "" and page.run_button.property("pro") == "primary"
    page.set_compact(True)
    assert page.run_button.width() == RUN_SIZE  # igual en el panel acoplado


# -- #145: errores de primer nivel -----------------------------------------------------------------------


def test_an_error_card_fixes_only_the_editor_text_and_copies_the_original(coordinator):
    from qgis.PyQt.QtWidgets import QApplication

    ws = workspace(coordinator)
    page = new_query(ws, "CREATE TABLE lecturas AS SELECT 1.5 AS kwh;\nSELECT kwhh FROM lecturas;")
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    [card] = page.cards
    assert card.title.text() == tr("The column «{}» does not exist").format("kwhh")
    assert card.where.text() == tr("Line {0} · near «{1}»").format(2, "kwhh")
    assert card.explanation.text() == tr("Suggestion: {}.").format("kwh")
    assert not card.original.isVisibleTo(card)  # el mensaje original, plegado
    card.toggle.click()
    assert card.original.isVisibleTo(card) and card.original.text().startswith("Binder Error")
    card.copy_button.click()
    assert QApplication.clipboard().text() == card.card.original
    runs = []
    page.execute = runs.append  # un arreglo nunca ejecuta nada
    card.fix_buttons[0].click()
    assert page.editor.text() == "CREATE TABLE lecturas AS SELECT 1.5 AS kwh;\nSELECT kwh FROM lecturas;"
    assert runs == []
    page.editor.undo()  # se puede deshacer
    assert "kwhh" in page.editor.text()


def test_a_card_does_not_fix_a_text_that_changed_and_loading_spatial_asks_first(coordinator, monkeypatch):
    from geoduck.domain.sql_errors import LOAD_EXTENSION, Fix
    from geoduck.ui.pro import query_page as module

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT kwhh FROM range(1);")
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    [card] = page.cards
    notices = []
    page.said.connect(notices.append)  # #177: en su pestaña
    page.editor.setText("SELECT kwhh FROM range(1); -- cambiado")
    page.apply_fix(card.card.fixes[0], page.run_text)
    assert page.editor.text().endswith("-- cambiado") and notices
    asked = []
    monkeypatch.setattr(module, "ASK_EXTENSION", lambda name: asked.append(name) or False)
    page.apply_fix(Fix(LOAD_EXTENSION, "x", value="spatial"), page.run_text)
    assert asked == ["spatial"]  # sin permiso, nada se instala ni se carga (ADR-0011)


def test_a_syntax_error_is_underlined_while_typing_without_running(coordinator):
    from geoduck.ui.pro import editor as pro_editor

    ws = workspace(coordinator)
    page = new_query(ws, "")
    page.editor.setText("SELECT zona, sum(kwh)\nFROM lecturas\nGROUP zona;")
    assert page._syntax.isActive()
    page.check_syntax()
    assert wait_for(lambda: page.editor.status.shown)
    assert page.editor.markersAtLine(2) & (1 << pro_editor.ERROR_MARK)
    offset = len("SELECT zona, sum(kwh)\nFROM lecturas\nGROUP ")
    assert tr("SQL check · not run yet") in page.editor.status.message_at(offset)
    assert page.results == [] and page.run is None  # no se ejecutó nada
    page.editor.setText("SELECT 1;")  # al escribir, el aviso se va y se vuelve a revisar
    assert not page.editor.status.shown
    page.check_syntax()
    wait_for(lambda: False, 0.3)
    assert not page.editor.status.shown


def test_an_expensive_result_is_saved_once_and_never_run_again(coordinator, monkeypatch):
    """#170 (E2b, performance-spec §8): una consulta cara se guarda una vez en `temp`; desplazarse, ordenar,
    contar y exportar leen de ahí sin repetirla; al volver a ejecutar, el guardado anterior se borra."""
    from geoduck.ui.pro import query_page as module

    monkeypatch.setattr(module, "SAVE_MS", -1)  # «cara» siempre: sin depender del tiempo de la máquina
    reads = []
    original = coordinator.read_rows

    def logged(sql, max_rows, done, **kwargs):
        reads.append(sql)
        return original(sql, max_rows, done, **kwargs)

    monkeypatch.setattr(coordinator, "read_rows", logged)
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT range AS n, 'v' || range AS v FROM range(1000);")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert wait_for(lambda: page.data.browse.database == "temp" and page.data.total == 1000, 10)
    first = page.data.browse.name
    assert first.startswith("geoduck_result_")
    assert wait_for(lambda: page.data.dense)  # se lee por posición (`rowid` seguidos)
    reads.clear()
    page.go(900)
    assert wait_for(lambda: page.model.row(0) == (900, "v900"))
    page.header.sort_requested.emit(0)  # ordenar: DuckDB sobre el resultado guardado
    assert wait_for(lambda: page.data.browse.order == ("n", True) and page.model.row(0) is not None)
    assert reads and not any("range(1000)" in sql for sql in reads)  # nunca la consulta otra vez
    assert "geoduck_result_" in page._result_sql(page.current_result)  # exportar y «Copia», también
    connected = page._result_sql(page.current_result, connected=True)  # «Conectada»: la consulta original
    assert "geoduck_result_" not in connected and "range(1000)" in connected and "ORDER BY" in connected
    page.execute(RunScope.ALL)  # otra ejecución: el guardado anterior se borra
    assert wait_for(lambda: done(coordinator, page) and page.data.browse.name not in ("", first), 10)
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    left = []
    coordinator.read_rows(
        "SELECT count(*) FROM duckdb_tables() WHERE temporary AND table_name LIKE 'geoduck_result_%'",
        1,
        left.append,
    )
    assert wait_for(lambda: left) and left[0].rows == ((1,),)  # solo el de la ejecución nueva
    page.close_page()  # al cerrar la pestaña, también se borra
    left.clear()
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    coordinator.read_rows(
        "SELECT count(*) FROM duckdb_tables() WHERE temporary AND table_name LIKE 'geoduck_result_%'",
        1,
        left.append,
    )
    assert wait_for(lambda: left) and left[0].rows == ((0,),)


def test_a_cheap_result_is_not_saved_and_cancelling_a_save_counts_instead(coordinator, monkeypatch):
    from geoduck.ui.pro import query_page as module

    ws = workspace(coordinator)
    page = new_query(ws, "SELECT range AS n FROM range(1000);")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.data.total == 1000)
    assert page.data.browse.subquery and not page._saves  # barata: se repite con ventana, sin guardar
    monkeypatch.setattr(module, "SAVE_MS", -1)
    started = []
    monkeypatch.setattr(coordinator, "save_result", lambda *a, **k: started.append(a) or 999_999)
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and started)
    assert page.save_status.isVisibleTo(page) and page.save_cancel.isVisibleTo(page)
    assert page.save_status.text().startswith("⟳ " + tr("Preparing…"))
    name = started[0][0]
    from geoduck.domain.errors import OperationCancelledError

    page._saved(page.current_result, name, OperationCancelledError("x"))  # «Cancelar»
    assert not page.save_status.isVisibleTo(page) and not page._saves
    assert page.hint.text() == tr("Saving the result was cancelled: rows are read by running the query again")
    assert wait_for(lambda: page.data.total == 1000)  # se cuenta repitiendo la consulta
