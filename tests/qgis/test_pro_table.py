# SPDX-License-Identifier: GPL-2.0-or-later
"""Pestaña de tabla de Workspace Pro (G9 · E3; workspace-pro-spec §4; AT-WSP-003, 004, 012 parcial).

PyQGIS real con una sesión real de DuckDB: páginas de 100 filas, orden, chips, búsqueda, «Ver SQL», detalle de
fila, «Estructura», copiar, y que la tabla se relee cuando el SQL del usuario cambia los datos.
"""

from __future__ import annotations

import contextlib
import gc
import time

import pytest
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtWidgets import QApplication

from geoduck.app.coordinator import SessionCoordinator
from geoduck.domain.browse import GT, LT, PAGE, Filter
from geoduck.domain.i18n import tr
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from geoduck.plugin import make_memory_engine
from geoduck.ui.dispatcher import QtDispatcher
from geoduck.ui.pro.places import QUERY, TABLE, VIEW, Place
from geoduck.ui.pro.table_page import GRID, TablePage
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
def delete_widgets_in_the_main_thread():
    """Los workspaces se borran en el hilo principal: el recolector de Python puede correr en el del motor."""
    yield
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


def run(coordinator, sql):
    coordinator.execute_sql(sql, RunScope.ALL)
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    wait_for(lambda: False, 0.2)


def scalar(coordinator, sql):
    answers = []
    coordinator.read_rows(sql, 1, answers.append)
    assert wait_for(lambda: answers)
    return answers[0].rows[0][0]


def open_table(coordinator, name, kind=TABLE):
    ws = ProWorkspace(coordinator, lambda: None, Store())
    _CREATED.append(ws)
    ws.resize(1300, 800)
    ws.show()
    ws.open_place(Place(kind, name, "memory", "main"))
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(page, TablePage)
    return ws, page


def loaded(page):
    return page.body.currentIndex() == GRID and page.model.rowCount() > 0


def counted(page):
    return page.total is not None


@pytest.fixture
def consumidores(coordinator):
    run(
        coordinator,
        "CREATE TABLE consumidores AS SELECT range AS id, "
        "CASE WHEN range % 10 = 0 THEN NULL ELSE 'Cliente ' || range END AS nombre, "
        "(range % 500) * 1.5 AS kwh FROM range(1000000);",
    )
    return coordinator


def test_a_million_rows_first_page_quickly_then_the_total(consumidores):
    begin = time.perf_counter()
    _ws, page = open_table(consumidores, "consumidores")
    assert wait_for(lambda: loaded(page))
    elapsed = time.perf_counter() - begin
    assert elapsed < 2.0, elapsed  # objetivo §13: < 0,5 s en la máquina de referencia (se mide en E7)
    assert page.model.rowCount() == PAGE
    assert wait_for(lambda: counted(page))
    assert page.total == 1_000_000
    assert page.range_label.text() == tr("Rows {} of {}").format("1–100", "1 000 000")
    assert [c.name for c in page.model.columns] == ["id", "nombre", "kwh"]
    assert page.model.headerData(0, 2) == "1"  # número de fila (vertical)


def test_sort_filters_search_and_pages_match_sql(consumidores):
    _ws, page = open_table(consumidores, "consumidores")
    assert wait_for(lambda: loaded(page))
    page.header.sort_requested.emit(2)  # ⇅ de kwh (#144): ascendente
    assert wait_for(lambda: loaded(page) and page.browse.order == ("kwh", True))
    page.header.sort_requested.emit(2)  # descendente
    assert wait_for(lambda: loaded(page) and page.model.rows[0][2] == 748.5)
    assert page.browse.order == ("kwh", False)
    page.add_filter(Filter("kwh", GT, "700"))
    page.add_filter(Filter("id", LT, "200000"))
    assert page.chips.count() == 2
    expected = scalar(consumidores, "SELECT count(*) FROM consumidores WHERE kwh > 700 AND id < 200000")
    assert wait_for(lambda: page.total == expected)
    page.search.edit.setText("cliente 19")
    page.search.edit.returnPressed.emit()
    expected = scalar(
        consumidores,
        "SELECT count(*) FROM consumidores WHERE kwh > 700 AND id < 200000 AND nombre ILIKE '%cliente 19%'",
    )
    assert wait_for(lambda: page.total == expected and loaded(page))
    first = page.model.rows[0][0]
    page.next_button.click()
    assert wait_for(lambda: page.offset == PAGE and loaded(page) and page.model.rows[0][0] != first)
    assert page.range_label.text().startswith(tr("Rows {} of {}").split("{}")[0] + "101–200")
    page.prev_button.click()
    assert wait_for(lambda: page.offset == 0 and page.model.rows[0][0] == first)
    page.remove_filter(0)
    assert page.chips.count() == 1 and page.browse.filters == (Filter("id", LT, "200000"),)


def test_a_filter_box_adds_a_chip_and_no_rows_offers_to_clear(consumidores):
    """#144: la casilla bajo el encabezado filtra (contiene) con su chip; sin filas, «Quitar filtros»."""
    _ws, page = open_table(consumidores, "consumidores")
    assert wait_for(lambda: loaded(page))
    assert page.header.filters_visible and page.header.boxes["nombre"].isVisibleTo(page)
    page.header.boxes["nombre"].setText("no existe")
    page.header.boxes["nombre"].returnPressed.emit()
    assert wait_for(lambda: page.browse.boxes == (("nombre", "no existe"),))
    assert page.chips.count() == 1
    assert wait_for(lambda: page.message.text() == tr("No rows match these filters."))
    assert page.clear_button.isVisible()
    page.clear_button.click()
    assert wait_for(lambda: loaded(page))
    assert not page.browse.filtered and page.header.boxes["nombre"].text() == ""


def test_view_sql_opens_the_equivalent_query(consumidores):
    ws, page = open_table(consumidores, "consumidores")
    assert wait_for(lambda: loaded(page))
    page.add_filter(Filter("kwh", GT, "700"))
    page.sql_button.click()
    query = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert ws.tabs.current.kind == QUERY
    assert query.editor.text() == page.browse.display_sql()
    assert "WHERE \"kwh\" > '700'" in query.editor.text()


def test_row_detail_shows_full_values_and_a_geometry_summary(coordinator):
    long_text = "x" * 3000
    run(
        coordinator,
        f"CREATE TABLE lugares AS SELECT 1 AS id, '{long_text}' AS nota, NULL::VARCHAR AS vacio, "
        "'POLYGON((0 0, 1 0, 1 1, 0 0))'::GEOMETRY AS geom;",
    )
    _ws, page = open_table(coordinator, "lugares")
    assert wait_for(lambda: loaded(page))
    assert page.detail.isVisible()
    assert wait_for(lambda: dict(page.detail.fields).get("geom", "").startswith("POLYGON"))
    fields = dict(page.detail.fields)
    assert fields["nota"] == long_text  # completo (la grilla lo abrevia)
    assert page.model.data(page.model.index(0, 1)).endswith("…")
    assert fields["vacio"] == "NULL"
    assert fields["geom"] == " · ".join(["POLYGON", tr("no CRS"), tr("{} vertices").format(4)])
    page.detail_button.setChecked(False)
    assert not page.detail.isVisible()


def test_structure_of_a_table_and_a_view(coordinator):
    run(
        coordinator,
        "CREATE TABLE claves (id INTEGER PRIMARY KEY, codigo VARCHAR UNIQUE, x DOUBLE NOT NULL);"
        " INSERT INTO claves VALUES (1, 'a', 1.0), (2, 'b', 2.0);"
        " CREATE VIEW v_claves AS SELECT id FROM claves;",
    )
    _ws, page = open_table(coordinator, "claves")
    assert wait_for(lambda: loaded(page) and counted(page))
    page.mode.buttons[1].click()
    table = page.structure.table
    assert wait_for(lambda: table.rowCount() == 3 and page.structure.create.toPlainText())
    rows = [[table.item(r, c).text() for c in range(4)] for r in range(3)]
    assert rows[0] == ["id", "INTEGER", tr("no"), tr("primary")]
    assert rows[1][3] == tr("unique")
    assert rows[2][2] == tr("no")
    assert page.structure.create.toPlainText().startswith("CREATE TABLE claves")
    assert tr("{} rows").format(2) in page.structure.summary.text()
    assert not page.search.isVisible()
    _ws2, view = open_table(coordinator, "v_claves", VIEW)
    assert wait_for(lambda: loaded(view))
    view.mode.buttons[1].click()
    assert wait_for(lambda: "SELECT id FROM claves" in view.structure.create.toPlainText())


def test_ctrl_c_copies_the_selected_rows_as_text(coordinator):
    run(coordinator, "CREATE TABLE dos AS SELECT * FROM (VALUES (1, 'a'), (2, NULL)) t(n, s);")
    _ws, page = open_table(coordinator, "dos")
    assert wait_for(lambda: loaded(page))
    page.grid.selectAll()
    page.copy_selection()
    assert QApplication.clipboard().text() == "1\ta\n2\t"


def test_user_sql_that_changes_data_reloads_the_page(coordinator):
    run(coordinator, "CREATE TABLE cambia AS SELECT 1 AS n;")
    _ws, page = open_table(coordinator, "cambia")
    assert wait_for(lambda: loaded(page) and page.total == 1)
    run(coordinator, "INSERT INTO cambia VALUES (2), (3);")
    assert wait_for(lambda: page.total == 3 and page.model.rowCount() == 3)


def test_a_dropped_table_says_so_and_a_closed_tab_stops_listening(coordinator):
    run(coordinator, "CREATE TABLE efimera AS SELECT 1 AS n;")
    ws, page = open_table(coordinator, "efimera")
    assert wait_for(lambda: loaded(page))
    run(coordinator, "DROP TABLE efimera;")
    assert wait_for(lambda: page.body.currentIndex() != GRID)
    assert page.retry_button.isVisible()
    ws.tabs.close_current()
    assert page._closed
    run(coordinator, "CREATE TABLE efimera AS SELECT 1 AS n;")  # nada llega a la pestaña cerrada
