# SPDX-License-Identifier: GPL-2.0-or-later
"""El complemento con la interfaz nueva (G9 · E6; workspace-pro-spec §12, §15; AT-WSP-002, 010, 011).

GeoDuck real (`classFactory` + `initGui`) con PyQGIS y DuckDB reales: ventana y panel con la misma sesión,
preferencias y cuadernos de la interfaz anterior, «Historial», «Revertir» de una transacción abortada,
«Ver en el mapa», el menú de capa y el «+» de «Enviar a DuckDB», el arrastre al mapa, el panel estrecho y
los diálogos que siguen en uso (abrir o crear base, «Acerca de»).
"""

from __future__ import annotations

import json

import pytest
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsSettings, QgsVectorLayer
from qgis.PyQt.QtWidgets import QLabel

import geoduck
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.i18n import tr
from geoduck.domain.notebook import Cell, Notebook
from geoduck.domain.session import ErrorCause, SessionState
from geoduck.domain.sql import RunScope, StatementStatus
from geoduck.ui.pro.drag import PlacesDropHandler
from geoduck.ui.pro.history import ERROR, HistoryPage
from geoduck.ui.pro.load import COPY
from geoduck.ui.pro.query_page import QueryPage
from geoduck.ui.pro.shell import Mode
from geoduck.ui.pro.workspace import ProWorkspace
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

TIMEOUT = 30
RO, RW = AccessMode.READ_ONLY, AccessMode.READ_WRITE


@pytest.fixture
def plugin(iface, tmp_path, monkeypatch):
    monkeypatch.setenv("GEODUCK_RECOVERY_DIR", str(tmp_path / "recuperacion"))
    loaded = []

    def make():
        item = geoduck.classFactory(iface)
        item.initGui()
        loaded.append(item)
        return item

    yield make
    for item in loaded:
        if item.coordinator is not None:
            item.unload()
    QgsProject.instance().removeAllMapLayers()


def start(item):
    item.content.start_button.click()
    assert wait_for(lambda: item.coordinator.state is SessionState.READY and item.coordinator.catalog)
    return item.coordinator


def run(coordinator, sql):
    coordinator.execute_sql(sql, RunScope.ALL)
    assert wait_for(lambda: coordinator.state is not SessionState.BUSY, TIMEOUT)


def points(name, n=3):
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", name, "memory")
    feats = []
    for i in range(n):
        feature = QgsFeature(layer.fields())
        feature.setAttributes([i])
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-68 + i, -16)))
        feats.append(feature)
    layer.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(layer)
    return layer


# -- el complemento usa la interfaz nueva -----------------------------------------------------------------


def test_the_plugin_opens_workspace_pro_in_its_own_window_and_registers_the_map_drop(plugin, iface):
    item = plugin()
    assert isinstance(item.content, ProWorkspace)
    assert item.workspace.window.isHidden()  # nada se abre solo al iniciar QGIS
    item.action.trigger()
    assert item.workspace.window.isVisible() and item.action.isChecked()
    assert [type(h) for h in iface.drop_handlers] == [PlacesDropHandler]
    item.unload()
    assert iface.drop_handlers == [] and iface.docks == []


def test_window_and_panel_share_the_session_hiding_never_closes_it_and_the_mode_is_remembered(plugin, iface):
    item = plugin()
    coordinator = start(item)
    engine = coordinator._engine
    item.workspace.set_visible(True)
    item.workspace.set_mode(Mode.DOCK)
    assert not item.workspace.dock.isHidden() and item.workspace.window.isHidden()
    assert iface.docks == [item.workspace.dock]
    item.workspace.set_visible(False)
    assert coordinator.state is SessionState.READY and coordinator._engine is engine
    item.workspace.set_mode(Mode.WINDOW)
    assert coordinator._engine is engine and item.content.parentWidget() is not None
    item.workspace.set_mode(Mode.DOCK)
    item.unload()
    again = plugin()
    assert again.workspace.mode is Mode.DOCK


def test_corrupt_presentation_settings_fall_back_to_the_window(plugin):
    settings = QgsSettings()
    settings.setValue("geoduck/pro/mode", "flotante")
    settings.setValue("geoduck/pro/window/geometry", "no es una geometría")
    item = plugin()
    assert item.workspace.mode is Mode.WINDOW
    item.action.trigger()
    assert item.workspace.window.isVisible()


def test_updating_keeps_presentation_and_open_notebooks_come_back_as_queries(plugin, tmp_path):
    """AT-WSP-011: desde 0.9.0a1, con un cuaderno guardado abierto y el panel acoplado a la izquierda."""
    from geoduck.domain.notebook_file import dumps

    notebook = tmp_path / "consumo.sql"
    notebook.write_text(
        dumps(Notebook("consumo", [Cell(sql="SELECT 1 AS uno;", database="memory"), Cell(sql="SELECT 2;")])),
        encoding="utf-8",
    )
    settings = QgsSettings()
    settings.setValue("geoduck/workspace/schema", 1)
    settings.setValue("geoduck/workspace/mode", "dock")
    settings.setValue("geoduck/workspace/dock/area", "left")
    settings.setValue("geoduck/workspace/sidebar_open", 0)
    missing = str(tmp_path / "ya_no_existe.sql")
    settings.setValue("geoduck/notebooks/open", json.dumps([missing, str(notebook)]))
    settings.setValue("geoduck/notebooks/active", str(notebook))
    item = plugin()
    assert item.workspace.mode is Mode.DOCK
    assert settings.value("geoduck/pro/dock/area") == "left"
    assert not item.content.sidebar_open
    start(item)
    tabs = item.content.tabs
    assert len(tabs) == 1  # el que ya no existe no vuelve
    page = tabs.page(0)
    assert isinstance(page, QueryPage) and page.place.path == str(notebook)
    assert "SELECT 1 AS uno;" in page.editor.text() and page.database == "memory"
    assert settings.value("geoduck/notebooks/open") is not None  # no se borra nada de la versión anterior


# -- «Historial» ---------------------------------------------------------------------------------------


def test_the_history_lists_what_ran_filters_errors_and_opens_without_running(plugin):
    item = plugin()
    coordinator = start(item)
    ws = item.content
    run(coordinator, "CREATE TABLE t AS SELECT 1 AS x; SELECT * FROM t;")
    run(coordinator, "SELECT * FROM no_existe;")
    assert [e.status for e in ws.history.entries] == [
        StatementStatus.OK,
        StatementStatus.OK,
        StatementStatus.FAILED,
    ]
    titles = [e.title for e in ws.palette_entries()]
    assert tr("Execution history") in titles
    ws.open_history()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(page, HistoryPage)
    assert page.table.rowCount() == 3 and tr("{0} with error").format(1) in page.counts.text()
    page.filter.set_current(ERROR)
    page.set_filter(ERROR)
    assert [page.table.isRowHidden(r) for r in range(3)] == [True, True, False]
    run(coordinator, "SELECT 42 AS n;")  # llega con la pestaña abierta
    assert page.table.rowCount() == 4 and page.table.isRowHidden(3)
    page.open_row(0)
    query = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(query, QueryPage)
    assert query.editor.text().rstrip(";") == "CREATE TABLE t AS SELECT 1 AS x"  # 1.5 sin «;», 2.0 con él
    wait_for(lambda: False, 0.3)
    assert len(ws.history.entries) == 4  # abrir no ejecuta
    keys = [k for k in QgsSettings().allKeys() if k.startswith("geoduck/")]
    assert not any("history" in k for k in keys)  # solo en memoria


# -- «Revertir» de una transacción abortada -----------------------------------------------------------------


def test_an_aborted_transaction_offers_roll_back_and_the_session_recovers(plugin):
    item = plugin()
    coordinator = start(item)
    ws = item.content
    # una clave repetida aborta la transacción con DuckDB 1.5 y 2.0 (un error de catálogo, solo con 2.0)
    run(coordinator, "CREATE TABLE u (x INTEGER PRIMARY KEY); BEGIN; INSERT INTO u VALUES (1), (1);")
    assert coordinator.state is SessionState.ERROR_RECOVERABLE
    assert coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
    toast = ws.aborted_toast
    assert toast is not None and not toast.isHidden() and toast.seconds == 0  # no se va solo
    assert tr("Roll back transaction") in [e.title for e in ws.palette_entries()]
    [rollback] = toast.actions
    assert rollback.text() == tr("Roll back")
    rollback.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY, TIMEOUT)
    assert ws.aborted_toast is None
    assert tr("Roll back transaction") not in [e.title for e in ws.palette_entries()]


# -- «Ver en el mapa» ---------------------------------------------------------------------------------------


def test_view_on_map_after_loading_selects_zooms_and_minimizes_the_window(plugin, iface):
    item = plugin()
    coordinator = start(item)
    item.action.trigger()
    run(
        coordinator,
        "CREATE TABLE pozos AS SELECT range AS id,"
        " ('POINT (' || (-68 - range) || ' -16)')::GEOMETRY('OGC:CRS84') AS geom FROM range(3);",
    )
    ws = item.content
    ws.loader.start('SELECT * FROM "pozos"', "pozos", COPY)
    assert wait_for(lambda: ws.loader.last_report is not None and coordinator.state is SessionState.READY, 60)
    toast = ws.last_toast
    assert toast is not None and [b.text() for b in toast.actions] == [tr("View on map")]
    toast.actions[0].click()
    layer = QgsProject.instance().mapLayer(ws.loader.last_report.layer_id)
    assert iface.active_layer is layer
    extent = iface.mapCanvas().extent()
    assert extent.xMinimum() <= -70 and extent.xMaximum() >= -68
    assert item.workspace.window.isMinimized()


def _big_copy(plugin, monkeypatch, answer):
    from geoduck.qgis_bridge import snapshot
    from geoduck.ui.pro import load

    asked = []
    monkeypatch.setattr(snapshot, "available_memory", lambda: 40 * 1024**2)  # presupuesto: 20 MB
    monkeypatch.setattr(load, "ASK_CONNECTED", lambda name, message: asked.append((name, message)) or answer)
    item = plugin()
    coordinator = start(item)
    run(
        coordinator,
        "CREATE TABLE enorme AS SELECT range AS id, repeat('x', 200) AS texto,"
        " ('POINT (' || (range % 90) || ' -16)')::GEOMETRY('OGC:CRS84') AS geom FROM range(2000000);",
    )
    ws = item.content
    before = set(QgsProject.instance().mapLayers())
    source = ("memory", "main", "enorme")
    ws.loader.start('SELECT * FROM "enorme"', "enorme", COPY, source=source, rows=2_000_000)
    return ws, coordinator, asked, before


def test_a_copy_that_does_not_fit_offers_connected_and_loads_it(plugin, monkeypatch):
    """#172: la Copia no cabe → «Cancelar» o «Cargar como Conectada»; la segunda la carga Conectada."""
    from geoduck.domain.load import LoadMode

    ws, coordinator, asked, _before = _big_copy(plugin, monkeypatch, True)
    assert wait_for(lambda: ws.loader.last_report and coordinator.state is SessionState.READY, 120)
    assert [name for name, _ in asked] == ["enorme"] and "40 MB" in asked[0][1]
    report = ws.loader.last_report
    assert report.mode is LoadMode.CONNECTED
    layer = QgsProject.instance().mapLayer(report.layer_id)
    assert layer is not None and layer.featureCount() == 2_000_000


def test_cancelling_a_copy_that_does_not_fit_loads_nothing(plugin, monkeypatch):
    ws, coordinator, asked, before = _big_copy(plugin, monkeypatch, False)
    assert wait_for(lambda: asked and coordinator.state is SessionState.READY, 120)
    assert ws.loader.last_report is None
    assert set(QgsProject.instance().mapLayers()) == before


# -- «Enviar a DuckDB» desde QGIS -----------------------------------------------------------------------


def test_the_layer_menu_opens_step_one_with_the_selected_layers(plugin, iface):
    item = plugin()
    start(item)
    layer = points("medidores")
    points("otra")
    iface.selected_layers = (layer,)
    try:
        assert item.send_action.action.text() == tr("Send to GeoDuck…")
        item.send_action.action.trigger()
        ws = item.content
        assert item.workspace.is_visible()
        window = ws.to_duckdb.window
        assert window.stack.currentIndex() == 0 and list(window.rows) == [layer.id()]
    finally:
        iface.selected_layers = ()


def test_the_plus_entry_opens_step_one_with_every_layer(plugin, iface):
    item = plugin()
    start(item)
    layer, other = points("zonas"), points("otra")
    iface.selected_layers = (layer,)
    try:
        assert item.content.sidebar.send_action.text() == tr("Add QGIS layers to GeoDuck…")
        item.content.sidebar.send_action.trigger()
        window = item.content.to_duckdb.window
        assert set(window.rows) == {layer.id(), other.id()}
        assert window.chosen() == [layer.id()]  # las seleccionadas en QGIS, ya marcadas
    finally:
        iface.selected_layers = ()


# -- panel estrecho y teclado (AT-WSP-010) ----------------------------------------------------------------


def test_a_narrow_panel_keeps_every_action_within_reach(plugin):
    item = plugin()
    start(item)
    item.workspace.set_visible(True)
    item.workspace.set_mode(Mode.DOCK)
    ws = item.content
    ws.resize(300, 600)
    header = item.workspace.dock.header
    assert not header.isHidden()
    titles = {e.title for e in ws.palette_entries()}
    for action in (
        tr("New query"),
        tr("Open query…"),
        tr("Execution history"),
        tr("Open database…"),
        tr("Create database…"),
        tr("Add QGIS layers to GeoDuck…"),
        tr("Refresh databases"),
        tr("Open in a window"),
        tr("Environment diagnostics"),
    ):
        assert action in titles


def test_the_panel_is_compact_down_to_340_px_and_the_explorer_opens_on_top(plugin):
    """Propietario (2026-11-07): el panel baja a 340 px sin que nada se monte; las mismas opciones, con
    ícono y tooltip donde no cabe el texto (▶ sin «Ejecutar»); el explorador se abre encima y se cierra al
    elegir una tabla o con Esc."""
    from geoduck.ui.pro.places import TABLE, Place
    from geoduck.ui.pro.table_page import TablePage

    item = plugin()
    start(item)
    coordinator = item.coordinator
    coordinator.execute_sql("CREATE TABLE puntos AS SELECT range AS id FROM range(150);", RunScope.ALL)
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    assert wait_for(lambda: any(o.name == "puntos" for o in coordinator.catalog.objects))
    item.workspace.set_visible(True)
    item.workspace.set_mode(Mode.DOCK)
    ws = item.content
    ws.open_place(Place(TABLE, "puntos", "memory", "main"))
    table = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(table, TablePage)
    ws.new_query()
    query = ws.tabs.page(ws.tabs.bar.currentIndex())
    query.editor.setText("SELECT 1;")
    query.mark_statement()
    assert ws.compact and table.compact and query.compact
    assert query.run_button.text() == "" and query.run_button.accessibleName() == tr("Run · line {}").format(
        1
    )
    assert tr("Run · line {}").format(1) in query.run_button.toolTip()
    assert query.load_button.text() == "" and not query.runs_in_label.isVisibleTo(query)
    assert not query.detail_button.isChecked() and not table.detail_button.isChecked()
    assert table.structure_button.isVisibleTo(table) and not table.mode.isVisibleTo(table)
    table.structure_button.setChecked(True)
    assert table.views.currentIndex() == 1
    table.structure_button.setChecked(False)
    assert table.views.currentIndex() == 0
    for page in (query, table):  # medido con el panel visible: 338 px (capturas en docs/evidence/g9/panel)
        assert page.minimumSizeHint().width() <= 340, page.minimumSizeHint().width()
    # el explorador: encima, sin la fila de la sesión (la lleva la cabecera del panel)
    assert ws.sidebar_button.isVisibleTo(ws) and ws.sidebar.isHidden()
    ws.toggle_sidebar()
    assert not ws.sidebar.isHidden() and ws.sidebar.geometry().x() == 0
    assert not ws.sidebar.session_head.isVisibleTo(ws.sidebar)
    ws.sidebar.open_requested.emit(Place(TABLE, "puntos", "memory", "main"))
    assert ws.sidebar.isHidden()  # elegida la tabla, se cierra
    ws.toggle_sidebar()
    assert not ws.sidebar.isHidden()
    ws.set_overlay_open(False)
    # de vuelta a la ventana: todo con texto y la barra lateral en su sitio
    item.workspace.set_mode(Mode.WINDOW)
    ws.window().resize(1300, 800)  # #147: compacto si la página no cabe, no solo por debajo de 640 px
    from qgis.PyQt.QtWidgets import QApplication

    QApplication.processEvents()
    query.mark_statement()
    assert not ws.compact and query.runs_in_label.isVisibleTo(query)
    assert table.mode.isVisibleTo(table) and not table.structure_button.isVisibleTo(table)


def test_right_click_on_one_or_more_tables_loads_them_with_the_same_menu(plugin):
    """Propietario (2026-11-06): clic derecho en una o varias tablas (Ctrl/Mayús) › «Cargar en QGIS ▸», el
    mismo menú que al soltarlas en el mapa; con una sola, también «Más opciones…»."""
    from geoduck.ui.pro.sidebar import PLACE, ROLE

    item = plugin()
    start(item)
    coordinator = item.coordinator
    coordinator.execute_sql(
        "CREATE TABLE a AS SELECT 1 AS x; CREATE TABLE b AS SELECT 2 AS x; CREATE TABLE c AS SELECT 3 AS x;",
        RunScope.ALL,
    )
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    assert wait_for(lambda: any(o.name == "c" for o in coordinator.catalog.objects))
    item.workspace.set_visible(True)
    ws = item.content
    tree = ws.sidebar.tree
    items = {}

    def walk(parent):
        for i in range(parent.childCount()):
            child = parent.child(i)
            data = child.data(0, ROLE)
            if data and data[0] == PLACE:
                items[data[1].name] = child
            walk(child)

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    assert tree.selectionMode() == tree.SelectionMode.ExtendedSelection
    items["a"].setSelected(True)
    items["c"].setSelected(True)
    assert [p.name for p in ws.sidebar.selected_places()] == ["a", "c"]
    picked = []
    ws.loader.start_many = lambda jobs, kind, **_: picked.append(([j["name"] for j in jobs], kind))
    menu = ws._load_menu_for(ws, ws.sidebar.selected_places())
    copy = next(a for a in menu.actions() if a.text() == tr("Copy (mode)"))
    copy.trigger()
    assert picked == [(["a", "c"], COPY)]
    single = ws._load_menu_for(ws, [ws.sidebar.selected_places()[0]])
    assert tr("More options…") in [a.text() for a in single.actions()]


# -- diálogos que siguen en uso ----------------------------------------------------------------------------


def test_attach_dialog_builds_requests(qgis_app, tmp_path):
    from geoduck.ui.attach_dialog import READ_ONLY_HELP, READ_WRITE_HELP, AttachDialog

    dialog = AttachDialog(OpenAction.CREATE_NEW)
    assert dialog.windowTitle() == "Crear base"
    assert not dialog.readonly_check.isVisibleTo(dialog)  # «Crear»: sin acceso que elegir, siempre RW
    assert not dialog.ok_button.isEnabled()  # sin archivo no se puede crear
    dialog.path_edit.setText(str(tmp_path / "nueva.duckdb"))
    assert dialog.ok_button.isEnabled() and dialog.alias_edit.placeholderText() == "nueva"
    request = dialog.build_request()
    assert request.access is RW and request.action is OpenAction.CREATE_NEW and request.alias is None
    existing = tmp_path / "ya.duckdb"
    existing.write_bytes(b"")
    dialog.path_edit.setText(str(existing))
    assert not dialog.ok_button.isEnabled() and "no lo sobrescribe" in dialog.path_hint.text()

    dialog = AttachDialog(OpenAction.OPEN_EXISTING)
    assert dialog.windowTitle() == "Abrir base"
    assert dialog.readonly_check.isChecked() and dialog.access is RO  # por defecto, solo lectura
    assert dialog.access_help.text() == tr(READ_ONLY_HELP)
    dialog.readonly_check.setChecked(False)
    assert dialog.access is RW and dialog.access_help.text() == tr(READ_WRITE_HELP)
    dialog.readonly_check.setChecked(True)
    dialog.path_edit.setText(str(tmp_path / "no_existe.duckdb"))
    assert not dialog.ok_button.isEnabled() and dialog.path_hint.text() == "No se encuentra el archivo."
    dialog.path_edit.setText("")
    dialog._accept()
    assert dialog.request is None and not dialog.error_label.isHidden()  # sigue abierto con el error
    dialog.path_edit.setText("/datos/x.duckdb")
    assert dialog.alias_edit.placeholderText() == "x"  # el alias por defecto, a la vista
    dialog.alias_edit.setText("Mi base")
    dialog._accept()
    assert dialog.request == AttachRequest("/datos/x.duckdb", RO, OpenAction.OPEN_EXISTING, "Mi base")


def test_about_shows_version_license_links_and_components(plugin):
    from geoduck import __version__
    from geoduck.ui.about_dialog import AboutDialog, version_text

    item = plugin()
    coordinator = start(item)
    dialog = AboutDialog(item.content._report, coordinator.engine_info, item.content)
    texts = " ".join(w.text() for w in dialog.findChildren(QLabel))
    assert __version__ in texts and "GPL-2.0-or-later" in dialog.links.text()
    assert "github.com/eribertocz/geoduck" in dialog.links.text() and dialog.links.openExternalLinks()
    assert coordinator.engine_info.duckdb_version in texts
    assert "@" not in texts  # ningún correo
    assert item.about_action.text() == "Acerca de GeoDuck…"
    assert version_text() == f"Versión {__version__} · Alpha"
    footer = " ".join(w.text() for w in item.content.sidebar.findChildren(QLabel))
    assert f"v{__version__}" in footer


def test_the_brand_logo_says_the_session_state_and_its_menu_shows_only_what_applies(plugin):
    """Marca (propietario, 2026-11-07): el logo con un puntito dice el estado y abre el menú de la sesión;
    sin sesión, «Iniciar DuckDB» y nunca un «Iniciar» en gris con sesión; el botón de QGIS lleva el puntito;
    «Acerca de» con la raya ámbar y el botón azul."""
    from geoduck.ui.about_dialog import AboutDialog
    from geoduck.ui.pro.widgets import LogoBar, logo_icon

    item = plugin()
    ws = item.content
    side = ws.sidebar
    assert side.dot.logo and side.dot.state == "off"
    assert side.start_action.isVisible() and not side.close_action.isVisible()
    start(item)
    assert wait_for(lambda: side.dot.state == "ok")
    assert not side.start_action.isVisible() and side.close_action.isVisible()
    assert not logo_icon("ok").isNull() and not logo_icon("off").isNull()
    dialog = AboutDialog(ws._report, item.coordinator.engine_info, ws)
    notes = [w for w in dialog.findChildren(QLabel) if w.property("geoduck") == "note"]
    assert len(notes) == 1
    bar = LogoBar(ws.colors)
    bar.setRange(0, 0)
    bar.resize(160, 20)
    bar.grab()  # sin avance conocido: se dibuja y anima sin fallar
    bar.setRange(0, 10)
    bar.setValue(5)
    assert not bar.grab().isNull()
