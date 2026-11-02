# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL del panel con PyQGIS y DuckDB reales (G2; AT-SQL-001..005, GD-SES-003 SQL)."""

import duckdb
import pytest

import geoduck
from geoduck.domain.session import ErrorCause, SessionState
from geoduck.domain.sql import RunScope
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis


@pytest.fixture
def session(iface):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    coordinator = plugin.coordinator
    plugin.dock.start_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    yield plugin, plugin.dock.sql_panel, coordinator
    plugin.unload()


def run(panel, coordinator, text, scope=RunScope.ALL):
    panel.editor.setText(text)
    {RunScope.ALL: panel.run_all_button, RunScope.CURRENT: panel.run_current_button}[scope].click()
    assert wait_for(lambda: coordinator.state is not SessionState.BUSY and not panel._running)


def tabs(panel):
    return [panel.results.tabText(i) for i in range(1, panel.results.count())]


def log(panel):
    return [tuple(panel.log.item(r, c).text() for c in (1, 2, 3)) for r in range(panel.log.rowCount())]


def test_script_with_create_and_two_selects(session):
    """Gate de G2 (sql-editor-spec §8): tres registros, dos pestañas de datos."""
    _plugin, panel, coordinator = session
    run(
        panel,
        coordinator,
        "CREATE TABLE productos AS SELECT 1 AS id, 'Medidor' AS nombre;\n"
        "SELECT * FROM productos;\nSELECT COUNT(*) AS n FROM productos;",
    )
    assert log(panel) == [("1", "CREATE", "OK"), ("2", "SELECT", "OK"), ("3", "SELECT", "OK")]
    assert tabs(panel) == ["2 · SELECT", "3 · SELECT"]
    first = panel.results.widget(1)
    assert first.table.item(0, 1).text() == "Medidor"
    assert first.caption.text().startswith("Vista previa")
    assert wait_for(lambda: any("productos" in o.name for o in coordinator.catalog.objects))  # explorador


def test_attach_in_sql_is_reflected_in_the_explorer(session, tmp_path):
    _plugin, panel, coordinator = session
    path = str(tmp_path / "b.duckdb")
    duckdb.connect(path).close()
    run(panel, coordinator, f"ATTACH '{path}' AS b;")
    assert wait_for(lambda: coordinator.catalog.get("b") is not None)
    run(panel, coordinator, "DETACH b;")
    assert wait_for(lambda: coordinator.catalog.get("b") is None)


def test_error_marks_the_line_and_stops(session):
    plugin, panel, coordinator = session
    run(panel, coordinator, "SELECT 1;\nSELECT * FROM nada;\nCREATE TABLE nunca(x INT);")
    assert [s for _n, _t, s in log(panel)] == ["OK", "Error", "No ejecutada"]
    assert panel.editor.getCursorPosition()[0] == 1  # el cursor va a la línea del error
    assert "nada" in plugin.dock.message_label.text()


def test_current_statement_only(session):
    _plugin, panel, coordinator = session
    panel.editor.setText("CREATE TABLE a(x INT);\nINSERT INTO a VALUES (1);")
    panel.editor.setCursorPosition(0, 3)
    panel.run_current_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY and not panel._running)
    assert log(panel) == [("1", "CREATE", "OK")]


def test_previous_preview_is_marked_possibly_stale(session):
    _plugin, panel, coordinator = session
    run(panel, coordinator, "CREATE TABLE a AS SELECT 1 AS x; SELECT * FROM a; INSERT INTO a VALUES (2);")
    view = panel.results.widget(1)
    assert view.caption.text().startswith("Posiblemente obsoleta")


def test_preview_is_bounded_by_the_selected_limit(session):
    _plugin, panel, coordinator = session
    panel.limit_combo.setCurrentIndex(panel.limit_combo.findData(50))
    run(panel, coordinator, "SELECT range FROM range(100000);")
    view = panel.results.widget(1)
    assert view.table.rowCount() == 50 and "hay más filas" in view.caption.text()


def test_aborted_transaction_shows_rollback_and_recovers(session):
    plugin, panel, coordinator = session
    run(panel, coordinator, "CREATE TABLE u(a INT PRIMARY KEY); INSERT INTO u VALUES (1);")
    run(panel, coordinator, "BEGIN; INSERT INTO u VALUES (1);")
    assert coordinator.state is SessionState.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
    dock = plugin.dock
    assert not dock.rollback_button.isHidden() and not panel.run_all_button.isEnabled()
    dock.rollback_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    assert dock.rollback_button.isHidden() and panel.run_all_button.isEnabled()
