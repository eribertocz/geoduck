# SPDX-License-Identifier: GPL-2.0-or-later
"""G5/E1: un solo workspace, dos presentaciones (AT-UX-002, 003, 011; ui-ux-spec §8; ADR-0013).

Ventana propia por defecto (hija de QGIS, la X la oculta) y panel acoplado; alternar traslada el mismo
contenido sin tocar la sesión; ocultar o cerrar un shell no cierra la sesión, ni desadjunta, ni revierte.
"""

from __future__ import annotations

import duckdb
import pytest
from qgis.core import QgsProject, QgsSettings

import geoduck
from geoduck.app.events import LoadFinished
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.session import SessionState
from geoduck.ui.workspace_controller import PREFIX, WorkspaceMode, read_mode
from tests.qgis.conftest import FakeIface, wait_for
from tests.qgis.test_sql_panel import run

pytestmark = pytest.mark.qgis


@pytest.fixture
def plugin(iface):
    p = geoduck.classFactory(iface)
    p.initGui()
    yield p
    p.unload()
    QgsProject.instance().removeAllMapLayers()


def start(plugin):
    plugin.content.start_button.click()
    coordinator = plugin.coordinator
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    return coordinator


def record(plugin):
    """Eventos de la aplicación desde ahora (tras dejar llegar los pendientes de lo anterior)."""
    wait_for(lambda: False, 0.5)
    events = []
    plugin.coordinator.subscribe(events.append)
    return events


# -- AT-UX-002: ventana propia por defecto; el modo elegido se recuerda ----------------------------------


def test_clean_install_opens_in_its_own_window_child_of_qgis(plugin, iface):
    ws = plugin.workspace
    assert ws.mode is WorkspaceMode.WINDOW
    assert ws.window.isHidden() and ws.dock.isHidden() and iface.docks == []  # nada se abre solo
    plugin.action.trigger()  # botón de GeoDuck de la barra de herramientas
    assert ws.window.isVisible() and plugin.action.isChecked()
    assert ws.window.isWindow() and ws.window.parent() is iface.mainWindow()  # hija de QGIS
    assert ws.window.isAncestorOf(plugin.content)
    plugin.action.trigger()
    assert ws.window.isHidden() and not plugin.action.isChecked()


def test_the_chosen_mode_is_remembered_after_restarting(iface):
    first = geoduck.classFactory(iface)
    first.initGui()
    first.action.trigger()
    first.workspace.window.toggle_button.click()  # «Acoplar a QGIS»
    assert first.workspace.mode is WorkspaceMode.DOCK
    first.unload()

    second_iface = FakeIface()  # QGIS reiniciado: las preferencias siguen
    second = geoduck.classFactory(second_iface)
    second.initGui()
    try:
        ws = second.workspace
        assert ws.mode is WorkspaceMode.DOCK and second_iface.docks == [ws.dock]
        assert ws.dock.isAncestorOf(second.content)
        second.action.trigger()
        assert ws.dock.isVisible() and ws.window.isHidden()
    finally:
        second.unload()
    assert second_iface.docks == []


@pytest.mark.parametrize(
    ("schema", "mode"), [(None, None), (1, "otra cosa"), (99, "dock"), ("x", "dock"), (1, None)]
)
def test_missing_corrupt_or_newer_settings_fall_back_to_the_window(iface, schema, mode):
    settings = QgsSettings()
    for key, value in (("schema", schema), ("mode", mode)):
        if value is None:
            settings.remove(PREFIX + key)
        else:
            settings.setValue(PREFIX + key, value)
    assert read_mode(settings) is WorkspaceMode.WINDOW


# -- AT-UX-003: alternar ida y vuelta conserva sesión, worker y contenido ----------------------------------


def test_round_trip_keeps_the_same_session_worker_and_content(plugin, iface):
    coordinator = start(plugin)
    ws, content = plugin.workspace, plugin.content
    panel, engine = content.sql_panel, coordinator._engine
    run(panel, coordinator, "CREATE TABLE t AS SELECT 1 AS x")
    panel.editor.setText("SELECT 42 AS respuesta")
    results = panel.results.count()
    events = record(plugin)
    plugin.action.trigger()

    ws.window.toggle_button.click()  # ventana → panel
    assert ws.mode is WorkspaceMode.DOCK and iface.docks == [ws.dock]
    assert ws.dock.isVisible() and ws.window.isHidden() and plugin.action.isChecked()
    assert ws.dock.isAncestorOf(content) and not ws.window.isAncestorOf(content)

    ws.dock.toggle_button.click()  # panel → ventana
    assert ws.mode is WorkspaceMode.WINDOW and iface.docks == []
    assert ws.window.isVisible() and ws.dock.isHidden() and ws.window.isAncestorOf(content)

    # Identidad: mismo contenido, mismo editor, misma sesión y mismo worker; nada se ejecutó
    assert plugin.content is content and content.sql_panel is panel
    assert coordinator._engine is engine and engine.thread.is_alive()
    assert coordinator.state is SessionState.READY
    assert panel.editor.text() == "SELECT 42 AS respuesta" and panel.results.count() == results
    assert events == []


# -- AT-UX-011: cerrar u ocultar la ventana o el panel no toca la sesión ------------------------------------


def test_closing_or_hiding_a_shell_never_closes_detaches_or_rolls_back(plugin, iface, tmp_path):
    path = str(tmp_path / "datos.duckdb")
    con = duckdb.connect(path)
    con.execute(
        "CREATE TABLE t AS SELECT range::INTEGER AS id, ('POINT(' || range || ' 0)')::GEOMETRY AS g "
        "FROM range(50)"
    )
    con.close()
    coordinator = start(plugin)
    coordinator.attach_database(AttachRequest(path, AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING, "db"))
    assert wait_for(
        lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("db") is not None
    )
    done = []
    coordinator.subscribe(lambda e: done.append(e) if isinstance(e, LoadFinished) else None)
    coordinator.load(
        LoadRequest(
            sql='SELECT * FROM "db"."main"."t"',
            mode=LoadMode.CONNECTED,
            layer_name="t",
            crs_override="",
            source=("db", "main", "t"),
            source_kind="table",
        )
    )
    assert wait_for(lambda: bool(done) and coordinator.state is SessionState.READY)
    layer = QgsProject.instance().mapLayer(done[0].report.layer_id)
    panel, engine = plugin.content.sql_panel, coordinator._engine
    run(panel, coordinator, "BEGIN; INSERT INTO db.t VALUES (50, 'POINT(50 0)')")  # transacción abierta
    events = record(plugin)
    ws = plugin.workspace

    plugin.action.trigger()
    ws.window.close()  # la X de la ventana
    assert ws.window.isHidden() and not plugin.action.isChecked()
    ws.window.show()
    ws.window.toggle_button.click()
    ws.dock.close()  # la X del panel
    assert ws.dock.isHidden() and not plugin.action.isChecked()
    plugin.action.trigger()
    assert ws.dock.isVisible()
    plugin.action.trigger()  # ocultar con el botón de la barra de herramientas
    assert ws.dock.isHidden()

    assert events == []  # ni cierre, ni DETACH, ni ROLLBACK, ni recarga
    assert coordinator.state is SessionState.READY and coordinator._engine is engine
    assert coordinator.catalog.get("db") is not None
    assert layer.isValid() and not layer.dataProvider().unavailable
    run(panel, coordinator, "COMMIT")  # la transacción seguía abierta
    run(panel, coordinator, "SELECT count(*) AS n FROM db.t")
    assert coordinator.state is SessionState.READY
    assert panel.results.widget(panel.results.count() - 1).table.item(0, 0).text() == "51"
