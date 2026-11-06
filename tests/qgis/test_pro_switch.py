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
from qgis.PyQt.QtWidgets import QDialog, QLabel

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
from geoduck.ui.send_dialog import SendDialog
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


# -- «Enviar a DuckDB» desde QGIS -----------------------------------------------------------------------


def test_the_layer_menu_sends_like_dropping_and_shows_geoduck(plugin, iface):
    item = plugin()
    start(item)
    layer = points("medidores")
    iface.selected_layers = (layer,)
    try:
        item.send_action.action.trigger()
        ws = item.content
        assert item.workspace.is_visible()
        assert wait_for(lambda: ws.quick_send.last_report is not None, TIMEOUT)
        assert ws.quick_send.asked is False  # tabla nueva en la base en memoria: sin diálogo
        assert ws.last_toast is not None
    finally:
        iface.selected_layers = ()


def test_the_plus_entry_always_opens_the_dialog_to_choose(plugin, iface, monkeypatch):
    item = plugin()
    start(item)
    layer = points("zonas")
    iface.selected_layers = (layer,)
    shown = []

    def fake_exec(dialog):
        shown.append(len(dialog.items))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(SendDialog, "exec", fake_exec)
    try:
        item.content.sidebar.send_action.trigger()
        assert wait_for(lambda: shown, TIMEOUT)
        assert item.content.quick_send.asked and item.content.quick_send.last_report is None
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
        tr("Send QGIS layers to DuckDB…"),
        tr("Refresh databases"),
        tr("Open in a window"),
        tr("Environment diagnostics"),
    ):
        assert action in titles


# -- diálogos que siguen en uso ----------------------------------------------------------------------------


def test_attach_dialog_builds_requests(qgis_app, tmp_path):
    from geoduck.ui.attach_dialog import READ_ONLY_HELP, READ_WRITE_HELP, AttachDialog

    dialog = AttachDialog(OpenAction.CREATE_NEW)
    assert dialog.windowTitle() == "Crear base DuckDB"
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
    assert dialog.windowTitle() == "Abrir base DuckDB"
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
