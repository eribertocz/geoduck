# SPDX-License-Identifier: GPL-2.0-or-later
"""G5/E1: un solo workspace, dos presentaciones (AT-UX-002, 003, 011; ui-ux-spec §8; ADR-0013).

Ventana propia por defecto (hija de QGIS, la X la oculta) y panel acoplado; alternar traslada el mismo
contenido sin tocar la sesión; ocultar o cerrar un shell no cierra la sesión, ni desadjunta, ni revierte.
"""

from __future__ import annotations

import duckdb
import pytest
from qgis.core import QgsProject, QgsSettings
from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtWidgets import QApplication

import geoduck
from geoduck.app.events import LoadFailed, LoadFinished, LoadProgressed, ScriptFinished, StatementFinished
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.session import SessionState
from geoduck.domain.sql import DEFAULT_PREVIEW_LIMIT
from geoduck.ui.workspace import WorkspaceContent
from geoduck.ui.workspace_controller import PREFIX, WorkspaceMode, on_some_screen, read_mode
from tests.qgis.conftest import FakeIface, wait_for
from tests.qgis.test_sql_panel import run

pytestmark = pytest.mark.qgis


def qgis_window(iface):
    """La ventana principal de QGIS está a la vista, como en QGIS real (si no, un panel acoplado nunca
    sería visible)."""
    iface.mainWindow().resize(1200, 800)
    iface.mainWindow().show()
    return iface


@pytest.fixture
def plugin(iface):
    qgis_window(iface)
    p = geoduck.classFactory(iface)
    p.initGui()
    yield p
    p.unload()
    iface.mainWindow().close()
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
    first = geoduck.classFactory(qgis_window(iface))
    first.initGui()
    first.action.trigger()
    first.workspace.window.toggle_button.click()  # «Acoplar a QGIS»
    assert first.workspace.mode is WorkspaceMode.DOCK
    first.unload()

    iface.mainWindow().close()
    second_iface = qgis_window(FakeIface())  # QGIS reiniciado: las preferencias siguen
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
        second_iface.mainWindow().close()
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


# -- E2 ---------------------------------------------------------------------------------------------------


def toggle(ws, times=1):
    for _ in range(times):
        target = WorkspaceMode.DOCK if ws.mode is WorkspaceMode.WINDOW else WorkspaceMode.WINDOW
        assert ws.set_mode(target)
        QCoreApplication.processEvents()


def editor_state(editor):
    first_line = editor.SendScintilla(editor.SCI_GETFIRSTVISIBLELINE)
    return editor.text(), editor.getCursorPosition(), editor.getSelection(), first_line


# -- AT-UX-004: alternar con el editor modificado y resultados abiertos -------------------------------------


def test_toggling_keeps_text_cursor_selection_scroll_results_and_tabs(plugin):
    coordinator = start(plugin)
    content, ws = plugin.content, plugin.workspace
    panel = content.sql_panel
    plugin.action.trigger()
    run(panel, coordinator, "SELECT range AS n FROM range(500);\nSELECT 2 AS b;")
    assert panel.results.count() == 2
    panel.results.setCurrentIndex(0)
    table = panel.results.widget(0).table
    wait_for(lambda: False, 0.2)
    table.verticalScrollBar().setValue(table.verticalScrollBar().maximum() // 2)
    editor = panel.editor
    editor.setText("\n".join(f"SELECT {i} AS linea_{i};" for i in range(200)))
    editor.setSelection(90, 2, 92, 7)
    editor.SendScintilla(editor.SCI_SETFIRSTVISIBLELINE, 80)
    before = editor_state(editor)
    scroll = table.verticalScrollBar().value()
    assert before[3] == 80 and scroll > 0
    events = record(plugin)

    assert content.side_splitter.widget(1) is panel  # ventana: explorador | SQL
    toggle(ws)  # al panel: pestañas Explorador / SQL, con los mismos widgets
    assert content.tabs.indexOf(panel) == 1 and content.tabs.indexOf(content.databases_card) == 0
    assert content.tabs.currentIndex() == 0 and not panel.isVisible()  # solo la pestaña activa
    content.tabs.setCurrentWidget(panel)
    assert editor_state(editor)[:3] == before[:3]
    assert panel.results.count() == 2 and panel.results.currentIndex() == 0
    toggle(ws)  # de vuelta a la ventana
    assert editor_state(editor) == before
    assert panel.results.widget(0).table is table and table.verticalScrollBar().value() == scroll
    assert panel.results.count() == 2 and panel.results.currentIndex() == 0
    assert content.side_splitter.widget(1) is panel
    toggle(ws)
    assert content.tabs.currentWidget() is panel  # la pestaña elegida en el panel se conserva
    assert events == []


# -- AT-UX-005: alternar durante SQL, carga o cancelación -------------------------------------------------


LONG_SQL = "SELECT sum(range) AS s FROM range(3000000000)"
BIG = "SELECT range AS id, ('POINT(' || range || ' 0)')::GEOMETRY AS g FROM range(1500000)"


def test_toggling_during_sql_delivers_exactly_one_result(plugin):
    coordinator = start(plugin)
    panel, ws = plugin.content.sql_panel, plugin.workspace
    plugin.action.trigger()
    events = record(plugin)
    panel.editor.setText(LONG_SQL)
    panel.run_all_button.click()
    assert coordinator.state is SessionState.BUSY
    toggle(ws, 3)
    assert wait_for(lambda: coordinator.state is SessionState.READY and not panel._running, 120)
    wait_for(lambda: False, 0.3)
    assert len([e for e in events if isinstance(e, StatementFinished)]) == 1
    assert len([e for e in events if isinstance(e, ScriptFinished)]) == 1
    assert panel.log.rowCount() == 1 and panel.results.count() == 1


def test_toggling_during_a_load_publishes_exactly_one_layer(plugin):
    coordinator = start(plugin)
    plugin.action.trigger()
    events = record(plugin)
    coordinator.load(LoadRequest(sql=BIG, mode=LoadMode.MEMORY, layer_name="grande", crs_override=""))
    assert wait_for(lambda: any(isinstance(e, LoadProgressed) for e in events), 60)
    toggle(plugin.workspace, 3)
    assert wait_for(lambda: any(isinstance(e, (LoadFinished, LoadFailed)) for e in events), 120)
    assert wait_for(lambda: coordinator.state is SessionState.READY, 60)
    wait_for(lambda: False, 0.3)
    assert len([e for e in events if isinstance(e, LoadFinished)]) == 1
    assert not any(isinstance(e, LoadFailed) for e in events)
    layers = list(QgsProject.instance().mapLayers().values())
    assert [lyr.name() for lyr in layers] == ["grande"] and layers[0].featureCount() == 1_500_000


def test_toggling_during_a_cancellation_delivers_exactly_one_cancellation(plugin):
    coordinator = start(plugin)
    plugin.action.trigger()
    events = record(plugin)
    coordinator.load(LoadRequest(sql=BIG, mode=LoadMode.MEMORY, layer_name="grande", crs_override=""))
    assert wait_for(lambda: any(isinstance(e, LoadProgressed) for e in events), 60)
    assert coordinator.cancel_current_operation()
    toggle(plugin.workspace, 3)
    assert wait_for(lambda: any(isinstance(e, (LoadFinished, LoadFailed)) for e in events), 120)
    assert wait_for(lambda: coordinator.state is SessionState.READY, 60)
    wait_for(lambda: False, 0.3)
    failed = [e for e in events if isinstance(e, LoadFailed)]
    assert len(failed) == 1 and failed[0].cancelled
    assert not any(isinstance(e, LoadFinished) for e in events)
    assert list(QgsProject.instance().mapLayers().values()) == []


# -- AT-UX-010: preferencias restauradas; nunca fuera de pantalla; ajustes corruptos → valores seguros ------


def restart(iface, previous):
    previous.unload()
    iface.mainWindow().close()
    new_iface = qgis_window(FakeIface())
    plugin = geoduck.classFactory(new_iface)
    plugin.initGui()
    return new_iface, plugin


def near(a, b, tolerance=3):
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b, strict=True))


def test_mode_window_dock_area_splitters_tab_and_limit_are_restored(iface):
    first = geoduck.classFactory(qgis_window(iface))
    first.initGui()
    ws, content = first.workspace, first.content
    first.action.trigger()
    ws.window.setGeometry(40, 50, 700, 500)
    wait_for(lambda: False, 0.2)
    saved = ws.window.geometry()  # la que Qt aceptó (respeta el tamaño mínimo del contenido)
    splitter = content.sql_panel.splitter
    wait_for(lambda: False, 0.2)
    splitter.setSizes([100, 250, 50])
    window_sizes = splitter.sizes()
    content.side_splitter.setSizes([220, 480])
    explorer_widths = content.side_splitter.sizes()
    toggle(ws)  # al panel: otro divisor para este modo
    iface.mainWindow().addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, ws.dock)  # el usuario lo mueve
    content.tabs.setCurrentWidget(content.sql_panel)
    wait_for(lambda: False, 0.2)
    splitter.setSizes([60, 240])  # en el panel, editor | resultados (el registro tiene su pestaña, E4)
    dock_sizes = splitter.sizes()
    content.sql_panel.limit_combo.setCurrentIndex(content.sql_panel.limit_combo.findData(1000))
    toggle(ws)
    assert near(splitter.sizes(), window_sizes)  # cada modo, su divisor
    assert near(content.side_splitter.sizes(), explorer_widths)  # ancho del explorador
    toggle(ws)
    assert near(splitter.sizes(), dock_sizes)

    new_iface, second = restart(iface, first)
    try:
        ws2 = second.workspace
        assert ws2.mode is WorkspaceMode.DOCK
        assert new_iface.mainWindow().dockWidgetArea(ws2.dock) == Qt.DockWidgetArea.LeftDockWidgetArea
        second.action.trigger()
        wait_for(lambda: False, 0.2)
        assert second.content.tabs.currentWidget() is second.content.sql_panel
        assert second.content.sql_panel.limit_combo.currentData() == 1000
        restored = second.content.sql_panel.splitter.sizes()  # otra altura: se compara la proporción
        assert abs(restored[0] / sum(restored) - dock_sizes[0] / sum(dock_sizes)) < 0.05
        toggle(ws2)
        assert ws2.window.geometry() == saved
        assert near(second.content.side_splitter.sizes(), explorer_widths, 10)
    finally:
        second.unload()
        new_iface.mainWindow().close()


def test_a_window_saved_on_a_missing_screen_reopens_on_screen(iface):
    first = geoduck.classFactory(qgis_window(iface))
    first.initGui()
    first.action.trigger()
    first.workspace.window.setGeometry(20000, 20000, 700, 500)  # pantalla que ya no existe
    first.action.trigger()  # se oculta y se guarda así
    new_iface, second = restart(iface, first)
    try:
        second.action.trigger()
        assert on_some_screen(second.workspace.window.frameGeometry())
    finally:
        second.unload()
        new_iface.mainWindow().close()


def test_corrupt_settings_give_safe_values(iface):
    settings = QgsSettings()
    for key, value in (
        ("schema", 1),
        ("mode", "dock"),
        ("window/geometry", "basura"),
        ("dock/area", "centro"),
        ("dock/sql_splitter", "a,b,c"),
        ("tab", 99),
        ("preview_limit", 7),
    ):
        settings.setValue(PREFIX + key, value)
    plugin = geoduck.classFactory(qgis_window(iface))
    plugin.initGui()
    try:
        ws = plugin.workspace
        assert ws.mode is WorkspaceMode.DOCK
        assert iface.mainWindow().dockWidgetArea(ws.dock) == Qt.DockWidgetArea.RightDockWidgetArea
        assert plugin.content.sql_panel.limit_combo.currentData() == DEFAULT_PREVIEW_LIMIT
        assert plugin.content.tabs.currentIndex() == 0
        toggle(ws)
        assert on_some_screen(ws.window.frameGeometry())
    finally:
        plugin.unload()
        iface.mainWindow().close()


# -- AT-UX-012: 20 alternancias seguidas ---------------------------------------------------------------------


def test_twenty_toggles_leave_no_double_signals_orphans_or_extra_sessions(plugin, iface):
    coordinator = start(plugin)
    ws, content = plugin.workspace, plugin.content
    engine, listeners = coordinator._engine, len(coordinator._listeners)
    plugin.action.trigger()
    events = record(plugin)
    toggle(ws, 20)
    assert ws.mode is WorkspaceMode.WINDOW and ws.window.isAncestorOf(content)
    contents = [w for w in QApplication.allWidgets() if isinstance(w, WorkspaceContent)]
    mine = [w for w in contents if ws.window.isAncestorOf(w) or ws.dock.isAncestorOf(w)]
    assert mine == [content]  # ni copias
    assert [w for w in contents if w.parent() is None] == []  # ni huérfanos
    assert iface.docks == [] and coordinator._engine is engine
    assert len(coordinator._listeners) == listeners + 1  # + el registro de esta prueba
    assert ws.window.toggle_button.receivers(ws.window.toggle_button.clicked) == 1
    assert ws.dock.toggle_button.receivers(ws.dock.toggle_button.clicked) == 1
    assert events == []
    panel = content.sql_panel
    run(panel, coordinator, "SELECT 1 AS uno")  # una ejecución da exactamente un resultado
    wait_for(lambda: False, 0.3)
    assert len([e for e in events if isinstance(e, StatementFinished)]) == 1
    assert panel.log.rowCount() == 1 and panel.results.count() == 1


# -- AT-UX-014: fallo inyectado durante el traslado --------------------------------------------------------


@pytest.mark.parametrize("step", ["put", "add_dock"])
def test_a_failed_move_leaves_the_previous_shell_working(plugin, iface, monkeypatch, step):
    coordinator = start(plugin)
    ws, content = plugin.workspace, plugin.content
    panel = content.sql_panel
    plugin.action.trigger()
    panel.editor.setText("SELECT 7 AS siete")
    events = record(plugin)

    def fail(*_args):
        raise RuntimeError("fallo inyectado")

    if step == "put":
        monkeypatch.setattr(ws.dock.slot, "put", fail)  # antes de que el contenido llegue al panel
    else:
        monkeypatch.setattr(ws, "_add_dock", fail)  # con el contenido ya en el panel
    assert ws.set_mode(WorkspaceMode.DOCK) is False

    assert ws.mode is WorkspaceMode.WINDOW and ws.window.isVisible() and ws.window.isAncestorOf(content)
    assert ws.dock.isHidden() and not ws.dock.isAncestorOf(content) and iface.docks == []
    assert plugin.action.isChecked()
    assert "No se pudo cambiar la presentación" in content.message_label.text()
    assert "fallo inyectado" in content.message_label.text()
    assert panel.editor.text() == "SELECT 7 AS siete" and coordinator.state is SessionState.READY
    assert events == []  # nada se repitió
    run(panel, coordinator, "SELECT 7 AS siete")  # el shell de origen sigue operativo
    assert panel.results.count() == 1
    monkeypatch.undo()
    assert ws.set_mode(WorkspaceMode.DOCK) and ws.dock.isAncestorOf(content)
