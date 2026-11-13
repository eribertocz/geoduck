# SPDX-License-Identifier: GPL-2.0-or-later
"""Resultado y filtros (#144; workspace-pro-spec §4, §5): detalle, selección como en una hoja de cálculo,
Ctrl+C con DuckDB, ⇅, resumen de la columna, filtros (casillas, chips, clic derecho, barra WHERE) en la
tabla y en el resultado de una consulta, y el resultado plegable.

PyQGIS real con una sesión real de DuckDB.
"""

from __future__ import annotations

import pytest
from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QItemSelectionModel, Qt
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.filters import EXCLUDE, FILTER
from geoduck.domain.i18n import tr
from geoduck.ui.pro import grid as grid_module
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_query import (
    done,
    new_query,
    recovery_dir,  # noqa: F401 - borra los workspaces en el hilo principal
    workspace,
)
from tests.qgis.test_pro_table import coordinator, loaded, open_table, run  # noqa: F401

pytestmark = pytest.mark.qgis


@pytest.fixture
def lecturas(coordinator):  # noqa: F811
    run(
        coordinator,
        "CREATE TABLE lecturas AS SELECT range AS id, 'cliente ' || range AS nombre, "
        "CASE range % 3 WHEN 0 THEN 'Sur' WHEN 1 THEN 'Norte' ELSE NULL END AS zona, "
        "(range % 100) * 1.5 AS kwh FROM range(250);",
    )
    return coordinator


def _count(coordinator, sql):  # noqa: F811 - la sesión de la prueba
    answers = []
    coordinator.read_rows(sql, 1, answers.append)
    assert wait_for(lambda: answers)
    return answers[0].rows[0][0]


def test_filter_boxes_chips_and_the_where_bar_keep_the_last_valid_filter(lecturas):
    _ws, page = open_table(lecturas, "lecturas")
    assert wait_for(lambda: loaded(page))
    data = page.data
    data.apply_box("zona", "=Sur")
    expected = _count(lecturas, "SELECT count(*) FROM lecturas WHERE zona = 'Sur'")
    assert wait_for(lambda: page.total == expected and loaded(page))
    assert page.header.boxes["zona"].property("active") is True and page.chips.count() == 1
    assert data.count_label.text() == tr("{0} of {1} rows").format(expected, 250)
    data.apply_box("kwh", "> 50 AND <")  # error: la casilla queda en rojo y sigue el filtro anterior
    assert wait_for(lambda: page.header.boxes["kwh"].property("invalid") is True)
    assert page.browse.box("kwh") == "" and page.total == expected
    data.apply_box("kwh", "> 50 AND < 100")
    both = _count(lecturas, "SELECT count(*) FROM lecturas WHERE zona = 'Sur' AND kwh > 50 AND kwh < 100")
    assert wait_for(lambda: page.total == both)
    assert page.header.boxes["kwh"].property("invalid") is False
    data.where_edit.setText("kwh >> 80")
    data.apply_where()  # DuckDB no la entiende: barra en rojo, mensaje y el último filtro válido
    assert wait_for(lambda: data.where_error.text().startswith("✕ "))
    assert data.where_edit.property("invalid") is True and page.browse.where == ""
    data.where_edit.setText("id % 2 = 0")
    data.apply_where()
    even = _count(
        lecturas, "SELECT count(*) FROM lecturas WHERE zona = 'Sur' AND kwh > 50 AND kwh < 100 AND id % 2 = 0"
    )
    assert wait_for(lambda: page.total == even and page.chips.count() == 3)
    assert data.where_error.text() == ""
    page.chips.itemAt(0).widget().removed.emit()  # quitar el chip de zona vacía su casilla
    assert wait_for(lambda: page.browse.box("zona") == "" and page.header.boxes["zona"].text() == "")
    assert 'WHERE ("kwh" > 50 AND "kwh" < 100)\n  AND (id % 2 = 0)' in page.browse.display_sql()


def test_right_click_filters_or_excludes_the_chosen_cells(lecturas):
    _ws, page = open_table(lecturas, "lecturas")
    assert wait_for(lambda: loaded(page))
    data = page.data
    zona = page.model.columns[2]
    data.grid.setCurrentIndex(page.model.index(0, 2))
    menu = data.cell_menu(data.grid.visualRect(page.model.index(0, 2)).center())
    titles = [a.text() for a in menu.actions() if a.text()]
    assert tr("Filter by this value") in titles and tr("Exclude this value") in titles
    assert not next(a for a in menu.actions() if a.text() == tr("Greater than this value")).isEnabled()
    menu.close()
    data.apply_cells([(zona, "Sur"), (zona, "Norte")], FILTER)  # misma columna: «o»
    expected = _count(lecturas, "SELECT count(*) FROM lecturas WHERE zona IN ('Sur', 'Norte')")
    assert wait_for(lambda: page.total == expected)
    assert page.header.boxes["zona"].text() == "IN ('Sur', 'Norte')"
    data.clear_filters()
    assert wait_for(lambda: not page.browse.filtered and page.total == 250)
    data.apply_cells([(zona, "Sur"), (page.model.columns[0], 0)], EXCLUDE)  # varias columnas: NOT (… y …)
    assert wait_for(lambda: page.total == 249)
    assert len(page.browse.extra) == 1 and page.chips.count() == 1


def test_sort_with_the_header_icon_and_choose_a_whole_column(lecturas):
    _ws, page = open_table(lecturas, "lecturas")
    assert wait_for(lambda: loaded(page))
    header = page.header
    rect = header._sort_rect(3)
    assert header.section_at_sort(rect.center()) == 3
    assert header.section_at_sort(rect.center() - rect.topLeft() + header._sort_rect(0).topLeft()) == 0
    header.sort_requested.emit(3)
    assert wait_for(lambda: page.total == 250 and loaded(page) and page.model.rows[1][3] == 0)
    assert page.grid.selectionModel().selectedIndexes() == []  # ordenar no elige la columna
    page.grid.selectColumn(3)  # clic en el nombre: la columna entera (lógica: todas las filas)
    assert page.data.whole_columns() == [3]
    # el resumen de la columna (#144, punto 11), de DuckDB sobre las 250 filas, no solo la página
    assert wait_for(lambda: page.column_summary.text().startswith("kwh · Σ 16 687.5 · x̄ 66.75"))
    assert tr("max {}").format("148.5") in page.column_summary.text()
    assert tr("nulls {}").format(0) in page.column_summary.text()


def test_ctrl_c_of_whole_columns_is_read_by_duckdb_and_too_many_offers_export(lecturas, monkeypatch):
    _ws, page = open_table(lecturas, "lecturas")
    assert wait_for(lambda: loaded(page) and page.total == 250)
    page.grid.selectColumn(0)
    page.copy_selection()  # 250 filas, más que la página: las lee DuckDB
    assert wait_for(lambda: QApplication.clipboard().text().count("\n") == 249)
    assert QApplication.clipboard().text().split("\n")[:3] == ["0", "1", "2"]
    offered = []
    page.data._offer_export = lambda: offered.append(True)
    monkeypatch.setattr(grid_module, "COPY_LIMIT", 100)
    page.grid.selectionModel().select(
        page.model.index(0, 1),
        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Columns,
    )
    page.copy_selection()  # 2 columnas × 250 filas > 100 valores: avisa y ofrece Exportar
    assert offered == [True]
    page.grid.clearSelection()
    page.grid.selectionModel().select(page.model.index(2, 1), QItemSelectionModel.SelectionFlag.Select)
    page.copy_selection()  # una celda: de la página
    assert QApplication.clipboard().text() == "cliente 2"


def test_the_detail_follows_the_chosen_cell_without_a_close_button(lecturas):
    _ws, page = open_table(lecturas, "lecturas")
    assert wait_for(lambda: loaded(page) and page.detail.isVisible())
    page.grid.setCurrentIndex(page.model.index(4, 2))
    assert page.detail.title.text() == tr("Row {}").format(5)
    page.grid.setFocus()
    from qgis.PyQt.QtTest import QTest

    QTest.keyClick(page.grid, Qt.Key.Key_Down)
    assert page.detail.title.text() == tr("Row {}").format(6)
    assert page.detail_button.isChecked()
    page.detail_button.click()
    assert not page.detail.isVisible() and not page.detail_button.isChecked()


def test_a_query_result_filters_with_duckdb_and_exports_what_is_shown(lecturas):
    ws = workspace(lecturas)
    page = new_query(ws, "SELECT * FROM lecturas;")
    page.run_button.click()
    assert wait_for(lambda: done(lecturas, page) and page.model.rowCount() == 100)
    assert wait_for(lambda: page.data.total == 250)
    assert not page.data.filter_bar.isVisibleTo(page)  # sin filtros, la barra no ocupa sitio
    page.filter_button.click()
    assert page.data.filter_bar.isVisibleTo(page) and page.header.filters_visible
    page.data.apply_box("zona", "=Norte")
    expected = _count(lecturas, "SELECT count(*) FROM lecturas WHERE zona = 'Norte'")
    assert wait_for(lambda: page.data.total == expected)
    assert all(row[2] == "Norte" for row in page.model.rows)
    assert page.range_label.text().startswith(tr("Rows {} of {}").format(f"1–{expected}", expected))
    loads = []
    page._loader = lambda *args, **kwargs: loads.append(args)
    page.load_in_qgis("copy")
    assert "AS geoduck_q" in loads[0][0] and "\"zona\" = 'Norte'" in loads[0][0]
    shown = []
    page.view_sql_requested.connect(shown.append)
    page.data.sql_button.click()
    assert shown and shown[0] == page.data.browse.display_sql()


def test_a_write_with_rows_cannot_be_filtered_again(lecturas):
    ws = workspace(lecturas)
    page = new_query(ws, "CREATE TABLE w AS SELECT range AS n FROM range(5); DELETE FROM w RETURNING n;")
    page.run_all_action.trigger()
    assert wait_for(lambda: done(lecturas, page) and page.results)
    assert not page.filter_button.isEnabled() and not page.data.replayable
    assert not page.header.sortable


def test_the_result_folds_and_the_editor_takes_the_whole_height(lecturas):
    QgsSettings().remove("geoduck/pro/result_height")
    ws = workspace(lecturas)
    page = new_query(ws, "SELECT 1 AS uno;")
    page.run_button.click()
    assert wait_for(lambda: done(lecturas, page) and page.results)
    before = page.split.sizes()
    page.toggle_result()  # ⌄ (o Ctrl+J, o doble clic en la barra)
    assert not page.result_open and not page.result_body.isVisible()
    head = page.result_head.sizeHint().height()
    assert page.split.sizes()[1] <= head and page.split.sizes()[0] > before[0]
    assert page.fold_button.toolTip() == tr("Show the result · Ctrl+J")
    page.run_button.click()  # al ejecutar, se abre solo, con la altura que tenía
    assert page.result_open and page.result_body.isVisible()
    assert abs(page.split.sizes()[1] - before[1]) <= 2
    assert wait_for(lambda: done(lecturas, page))
    from qgis.PyQt.QtCore import QEvent, QPointF
    from qgis.PyQt.QtGui import QMouseEvent

    click = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(page.result_head, click)  # doble clic en la barra
    assert not page.result_open
    page.toggle_result()
    sizes = page.split.sizes()
    page.split.moveSplitter(sum(sizes) - head + 4, 1)  # arrastrar hasta abajo lo pliega
    assert not page.result_open
    page.toggle_result()
    page.split.moveSplitter(sum(sizes) - 300, 1)
    assert int(QgsSettings().value("geoduck/pro/result_height")) == page.split.sizes()[1]
