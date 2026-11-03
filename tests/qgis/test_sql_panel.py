# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL del panel con PyQGIS y DuckDB reales (G2; AT-SQL-001..005, GD-SES-003 SQL) y su interfaz:
divisor redimensionable, nombres descriptivos, jerarquía, navegación y «Acerca de»."""

import duckdb
import pytest
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QLabel, QSplitter

import geoduck
from geoduck.domain.session import ErrorCause, SessionState
from geoduck.domain.sql import RunScope
from geoduck.ui import theme
from geoduck.ui.sql_panel import LOG_MESSAGE, LOG_NAME, LOG_STATUS
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis


@pytest.fixture
def session(iface):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    coordinator = plugin.coordinator
    plugin.content.start_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    yield plugin, plugin.content.sql_panel, coordinator
    plugin.unload()


def run(panel, coordinator, text, scope=RunScope.ALL):
    panel.editor.setText(text)
    {RunScope.ALL: panel.run_all_button, RunScope.CURRENT: panel.run_current_button}[scope].click()
    assert wait_for(lambda: coordinator.state is not SessionState.BUSY and not panel._running)


def tabs(panel):
    return [panel.results.tabText(i) for i in range(panel.results.count())]


def log(panel):
    """(resultado, estado) de cada fila del registro (G5: hora · nombre · estado · duración · mensaje)."""
    return [
        tuple(panel.log.item(r, c).text() for c in (LOG_NAME, LOG_STATUS))
        for r in range(panel.log.rowCount())
    ]


# -- funcionamiento (G2) ------------------------------------------------------------------------------


def test_script_with_create_and_two_selects(session):
    """Gate de G2 (sql-editor-spec §8): tres registros y dos pestañas con nombres descriptivos."""
    _plugin, panel, coordinator = session
    run(
        panel,
        coordinator,
        "CREATE TABLE productos AS SELECT 1 AS id, 'Medidor' AS nombre;\n"
        "SELECT * FROM productos;\nSELECT COUNT(*) AS n FROM productos;",
    )
    assert log(panel) == [
        ("Crear productos", "OK"),
        ("Productos", "OK"),
        ("Total productos", "OK"),
    ]
    assert tabs(panel) == [
        "Productos (1 fila)",
        "Total productos (1 fila)",
    ]  # nombre (filas), como la maqueta
    first = panel.results.widget(0)
    assert first.table.item(0, 1).text() == "Medidor"
    assert first.caption.text().startswith("Vista previa") and not first.stale
    assert wait_for(lambda: any("productos" in o.name for o in coordinator.catalog.objects))


def test_attach_in_sql_is_reflected_in_the_explorer(session, tmp_path):
    _plugin, panel, coordinator = session
    path = str(tmp_path / "b.duckdb")
    duckdb.connect(path).close()
    run(panel, coordinator, f"ATTACH '{path}' AS b;")
    assert wait_for(lambda: coordinator.catalog.get("b") is not None)
    assert log(panel)[-1] == ("Adjuntar b", "OK")
    run(panel, coordinator, "DETACH b;")
    assert wait_for(lambda: coordinator.catalog.get("b") is None)


def test_error_marks_the_line_and_stops(session):
    plugin, panel, coordinator = session
    run(panel, coordinator, "SELECT 1;\nSELECT * FROM nada;\nCREATE TABLE nunca(x INT);")
    assert [s for _n, s in log(panel)] == ["OK", "Error", "No ejecutada"]
    assert panel.editor.getCursorPosition()[0] == 1  # el cursor va a la línea del error
    error = panel.log.item(1, LOG_MESSAGE)
    assert error.foreground().color().name() == theme.palette_for(panel).error.lower()  # el error, en rojo
    assert tabs(panel)[-1] == "Error · sentencia 2"  # y su pestaña (inventario V28)
    assert "nada" in plugin.content.message_label.text()


def test_current_statement_only(session):
    _plugin, panel, coordinator = session
    panel.editor.setText("CREATE TABLE a(x INT);\nINSERT INTO a VALUES (1);")
    panel.editor.setCursorPosition(0, 3)
    panel.run_current_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY and not panel._running)
    assert log(panel) == [("Crear a", "OK")]


def test_previous_preview_is_marked_possibly_stale(session):
    _plugin, panel, coordinator = session
    run(panel, coordinator, "CREATE TABLE a AS SELECT 1 AS x; SELECT * FROM a; INSERT INTO a VALUES (2);")
    view = panel.results.widget(0)
    assert view.stale and not view.stale_label.isHidden()


def test_preview_is_bounded_by_the_selected_limit(session):
    _plugin, panel, coordinator = session
    panel.limit_combo.setCurrentIndex(panel.limit_combo.findData(50))
    run(panel, coordinator, "SELECT range FROM range(100000);")
    view = panel.results.widget(0)
    assert view.table.rowCount() == 50 and "hay más" in tabs(panel)[0]
    assert view.caption.text() == "Vista previa"  # siempre etiquetada (sql-editor-spec §1)


def test_aborted_transaction_shows_rollback_and_recovers(session):
    plugin, panel, coordinator = session
    run(panel, coordinator, "CREATE TABLE u(a INT PRIMARY KEY); INSERT INTO u VALUES (1);")
    run(panel, coordinator, "BEGIN; INSERT INTO u VALUES (1);")
    assert coordinator.state is SessionState.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
    dock = plugin.content
    assert not dock.rollback_button.isHidden() and not panel.run_all_button.isEnabled()
    dock.rollback_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    assert dock.rollback_button.isHidden() and panel.run_all_button.isEnabled()


# -- interfaz: divisor, nombres, jerarquía y navegación ---------------------------------------------


def test_editor_results_and_log_are_in_a_resizable_splitter(session):
    """G7: cada celda lleva su editor y su resultado; el divisor separa las celdas del registro."""
    plugin, panel, _coordinator = session
    splitter = panel.splitter
    assert isinstance(splitter, QSplitter) and splitter.orientation() == Qt.Orientation.Vertical
    assert splitter.count() == 2  # celdas (editor + resultado) | registro
    assert splitter.isAncestorOf(panel.editor)
    assert splitter.isAncestorOf(panel.results_stack) and splitter.isAncestorOf(panel.log)
    assert panel.cell.isAncestorOf(panel.editor) and panel.cell.isAncestorOf(panel.results_stack)
    assert not splitter.isCollapsible(0) and splitter.isCollapsible(1)  # el registro sí se puede plegar
    plugin.content.resize(460, 900)
    plugin.content.show()
    plugin.content.tabs.setCurrentWidget(panel)
    splitter.setSizes([500, 300])
    first = splitter.sizes()[0]
    splitter.setSizes([300, 500])
    assert splitter.sizes()[0] < first  # el usuario ajusta la altura de las celdas


def test_explicit_names_from_comments_and_empty_state(session):
    _plugin, panel, coordinator = session
    assert panel.results_stack.currentWidget() is panel.empty_results
    run(
        panel,
        coordinator,
        "CREATE TABLE v AS SELECT 1 AS x;\n-- Ventas del mes\nSELECT * FROM v;\nSELECT 2 AS total;",
    )
    assert tabs(panel) == ["Ventas del mes (1 fila)", "Total (1 fila)"]
    assert "SELECT * FROM v" in panel.results.tabToolTip(0)
    assert panel.results_stack.currentWidget() is panel.results


def test_log_double_click_selects_the_statement(session):
    _plugin, panel, coordinator = session
    run(panel, coordinator, "CREATE TABLE a(x INT);\nSELECT * FROM a;")
    panel.log.cellDoubleClicked.emit(1, 0)
    assert panel.editor.selectedText().strip().rstrip(";") == "SELECT * FROM a"


def test_numbers_are_right_aligned_and_nulls_marked(session):
    _plugin, panel, coordinator = session
    run(panel, coordinator, "SELECT 1 AS n, NULL AS vacio, 'x' AS t;")
    table = panel.results.widget(0).table
    assert table.item(0, 0).textAlignment() & int(Qt.AlignmentFlag.AlignRight)
    assert table.item(0, 1).text() == "NULL" and table.item(0, 1).font().italic()
    assert not table.item(0, 2).textAlignment() & int(Qt.AlignmentFlag.AlignRight)
    assert table.horizontalHeaderItem(0).toolTip() == "INTEGER"


def test_about_dialog_shows_version_license_links_and_components(session):
    from geoduck import __version__
    from geoduck.ui.about_dialog import AboutDialog

    plugin, _panel, coordinator = session
    dialog = AboutDialog(plugin.content._report, coordinator.engine_info, plugin.content)
    texts = " ".join(w.text() for w in dialog.findChildren(QLabel))
    assert __version__ in texts and "GPL-2.0-or-later" in dialog.links.text()
    assert "github.com/eribertocz/geoduck" in dialog.links.text() and dialog.links.openExternalLinks()
    assert coordinator.engine_info.duckdb_version in texts
    assert "@" not in texts  # ningún correo
    assert plugin.about_action.text() == "Acerca de GeoDuck…"


def test_displayed_version_is_the_real_package_version(session):
    from geoduck import __version__
    from geoduck.ui.about_dialog import version_text

    plugin, _panel, _coordinator = session
    assert plugin.content.version_label.text() == f"v{__version__} · Alpha"
    assert version_text() == f"Versión {__version__} · Alpha"
