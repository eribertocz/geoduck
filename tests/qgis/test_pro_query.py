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
from qgis.PyQt.QtCore import QCoreApplication, QEvent

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
    links = [w for w in page.messages.widget().findChildren(type(page.summary)) if "href" in w.text()]
    assert links and tr("line {}, column {}").format(2, 8) in links[0].text()
    links[0].linkActivated.emit("#")
    assert page.editor.getCursorPosition() == (1, 7)
    assert page.summary.text() == tr("{} OK · {} with error").format(1, 1)


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
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT count(*) FROM range(100000000000) a;")
    page.run_button.click()
    assert wait_for(page.cancel_button.isEnabled)
    page.cancel_button.click()
    assert wait_for(lambda: done(coordinator, page), 30)
    assert page._log and page._log[0] == (False, tr("Cancelled"))


def test_save_as_autosave_and_reopen(coordinator, tmp_path):
    path = tmp_path / "consumo.sql"
    store = Store()
    ws = workspace(coordinator, paths=[str(tmp_path / "consumo")], store=store)
    page = new_query(ws, "SELECT 42;")
    assert page.modified
    assert page.save()
    assert path.read_text(encoding="utf-8") == "SELECT 42;"
    assert ws.tabs.current == Place(QUERY, "consumo.sql", path=str(path))
    assert ws.tabs.bar.tabText(ws.tabs.bar.currentIndex()) == "consumo.sql"
    assert [p.name for p in ws.places.recents] == ["consumo.sql"]
    page.editor.setText("SELECT 43;")
    assert ws.tabs.bar.tabText(ws.tabs.bar.currentIndex()) == "consumo.sql •"
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
    assert ws.tabs.bar.tabText(ws.tabs.bar.currentIndex()).endswith("•")
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
    assert ws.start_button.text() == tr("Start DuckDB") and ws.start_button.isEnabled()
    assert ws.open_button.isEnabled() and ws.create_button.isEnabled()
    for widget in (ws.sidebar.search, ws.sidebar.tree, ws.new_query_button):
        assert not widget.isEnabled()
    # el menú de la sesión sí: sin sesión ofrece «Iniciar DuckDB» (marca, 2026-11-07)
    assert ws.sidebar.session_button.isEnabled() and ws.sidebar.start_action.isVisible()
    assert ws.sidebar.diagnostics_button.isEnabled() and ws.sidebar.about_button.isEnabled()
    assert ws.state_title.text() == tr("DuckDB is not started")
    idle.shutdown(5)
    dispatcher.close()


def test_run_sql_typed_by_the_user_through_execute_too(coordinator):
    """Ctrl+Intro y Ctrl+Mayús+Intro llegan a la consulta aunque el foco esté en el editor."""
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
    assert page.model.rowCount() == 100 and page.model.rows[0] == (0, "v0")
    assert wait_for(lambda: page.range_label.text().startswith(tr("Rows {} of {}").format("1–100", "250")))
    assert page.summary.text() == ""  # el resumen está en el pie
    assert not page.prev_button.isEnabled() and page.next_button.isEnabled()
    # el detalle: la fila elegida, con su número real
    assert page.detail.isVisible() and page.detail.title.text() == tr("Row {}").format("1")
    page.next_button.click()
    assert wait_for(lambda: page.model.offset == 100)
    assert page.model.rows[0] == (100, "v100")
    assert page.range_label.text().startswith(tr("Rows {} of {}").format("101–200", "250"))
    assert page.detail.title.text() == tr("Row {}").format("101")
    page.next_button.click()
    assert wait_for(lambda: page.model.offset == 200)
    assert page.model.rowCount() == 50 and not page.next_button.isEnabled()
    page.prev_button.click()
    assert wait_for(lambda: page.model.offset == 100)
    # plegar y volver a abrir el detalle
    page.detail_button.setChecked(False)
    assert not page.detail.isVisible()
    page.detail_button.setChecked(True)
    assert page.detail.isVisible()
    page.detail.closed.emit()
    assert not page.detail_button.isChecked() and not page.detail.isVisible()
    # «Mensajes» no tiene páginas ni detalle
    page.view.set_current(MESSAGES)
    page._show_view(MESSAGES)
    assert page.range_label.text() == "" and not page.next_button.isEnabled()


def test_a_short_result_is_not_counted_again_and_a_write_has_no_pages(coordinator):
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT range AS n FROM range(5);")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.range_label.text().startswith(tr("Rows {} of {}").format("1–5", "5"))
    assert not page.prev_button.isEnabled() and not page.next_button.isEnabled()
    page.editor.setText("CREATE TABLE w AS SELECT range AS n FROM range(300); DELETE FROM w RETURNING n;")
    page.execute(RunScope.ALL)
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert page.model.rowCount() == 100  # el DELETE … RETURNING muestra su primera página
    assert not page.next_button.isEnabled()  # y nunca se repite para pasar de página
    assert page.range_label.text().startswith(tr("Rows {} of more than {}").format("1–100", "100"))


def test_one_run_button_marks_what_will_run_and_runs_exactly_that(coordinator):
    """Propietario (2026-11-06): un solo «Ejecutar»; la barra a la izquierda y el botón dicen qué correrá
    (la sentencia del cursor, también en una línea en blanco, igual con DuckDB 1.5 y 2.0); con selección,
    «Ejecutar selección»; «Ejecutar todo» en «⋯» y con Ctrl+Mayús+Intro."""
    from geoduck.ui.pro.editor import MARK

    ws = workspace(coordinator)
    text = "SELECT 1 AS uno;\n\nSELECT 2 AS dos\nFROM range(1);\n"
    page = new_query(ws, text)
    marked = lambda: [ln for ln in range(page.editor.lines()) if page.editor.markersAtLine(ln) & (1 << MARK)]  # noqa: E731
    page.editor.setCursorPosition(1, 0)  # la línea en blanco entre las dos: la anterior
    page.mark_statement()
    assert marked() == [0] and page.run_button.text() == tr("Run · line {}").format(1)
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results)
    assert [c.name for c in page.model.columns] == ["uno"]
    page.editor.setCursorPosition(3, 2)
    page.mark_statement()
    assert marked() == [2, 3] and page.run_button.text() == tr("Run · line {}").format(3)
    assert tr("Ctrl+Shift+Enter: runs all ({} statements)").format(2) in page.run_button.toolTip()
    page.run_button.click()
    assert wait_for(lambda: done(coordinator, page) and page.results[0].statement.text.startswith("SELECT 2"))
    assert [c.name for c in page.model.columns] == ["dos"]
    page.editor.setSelection(0, 0, 0, 8)
    page.mark_statement()
    assert marked() == [] and page.run_button.text() == tr("Run selection")
    assert page.run_all_action.text().startswith(tr("Run all ({} statements)").format(2))
    page.editor.setSelection(0, 0, 0, 0)
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and len(page.results) == 2)


def test_open_and_save_are_by_the_tabs_and_run_all_is_in_the_editor_menu(coordinator, tmp_path):
    """Propietario (2026-11-06): el archivo arriba (el «⋯» junto a las pestañas), la ejecución en la barra de
    la consulta («Se ejecuta en»), y «Ejecutar todo» en el clic derecho del editor."""
    ws = workspace(coordinator)
    page = new_query(ws, "SELECT 1 AS uno;\nSELECT 2 AS dos;")
    ws._fill_file_menu()
    texts = [a.text() for a in ws.file_menu.actions() if not a.isSeparator()]
    assert texts[0].startswith(tr("Open query…"))
    assert texts[1].startswith(tr("Save «{}»").format(page.place.name))
    assert all(a.isEnabled() for a in ws.file_menu.actions())
    assert not hasattr(page, "file_button")  # la barra de la consulta ya no tiene «⋯»
    assert any(lab.text() == tr("Runs in") for lab in page.findChildren(type(page.summary)))
    page.editor.setCursorPosition(0, 2)
    page.mark_statement()
    menu = page._context.build()
    actions = [a for a in menu.actions() if not a.isSeparator()]
    assert actions[0].text().startswith(tr("Run · line {}").format(1))
    assert actions[1] is page.run_all_action
    assert len(actions) > 2  # y debajo, el menú de siempre del editor
    page.run_all_action.trigger()
    assert wait_for(lambda: done(coordinator, page) and len(page.results) == 2)
