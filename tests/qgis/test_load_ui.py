# SPDX-License-Identifier: GPL-2.0-or-later
"""«Cargar en QGIS» desde el panel (G3/E4; GD-BRD-012, AT-BRD-012)."""

from __future__ import annotations

from typing import ClassVar

import pytest
from qgis.core import QgsProject, QgsSettings
from qgis.PyQt.QtWidgets import QDialog

import geoduck
from geoduck.domain.load import LoadMode
from geoduck.domain.session import SessionState
from geoduck.ui.load_dialog import SETTING, LoadDialog
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

TIMEOUT = 60


class AutoDialog(LoadDialog):
    """El diálogo real, aceptado sin interacción con la modalidad pedida."""

    choice = LoadMode.MEMORY
    seen: ClassVar[list[LoadDialog]] = []

    def exec(self):
        AutoDialog.seen.append(self)
        self.mode_buttons[AutoDialog.choice].setChecked(True)
        return QDialog.DialogCode.Accepted


@pytest.fixture
def plugin(iface):
    p = geoduck.classFactory(iface)
    p.initGui()
    p.dock.load_flow._dialog_factory = AutoDialog
    p.coordinator.start_memory_session()
    assert wait_for(lambda: p.coordinator.state is SessionState.READY, TIMEOUT)
    yield p
    p.unload()
    QgsProject.instance().removeAllMapLayers()


def run_sql(plugin, sql):
    panel = plugin.dock.sql_panel
    panel.editor.setText(sql)
    from geoduck.domain.sql import RunScope

    panel.execute(RunScope.ALL)
    assert wait_for(lambda: plugin.coordinator.state is SessionState.READY and panel.result_views(), TIMEOUT)
    return panel.result_views()[-1]


@pytest.mark.parametrize("mode", list(LoadMode))
def test_load_button_loads_the_result(plugin, mode):
    AutoDialog.choice = mode
    view = run_sql(
        plugin, "SELECT range AS id, ('POINT(' || range || ' 1)')::GEOMETRY('OGC:CRS84') AS g FROM range(500)"
    )
    assert view.load_button.isEnabled()
    view.load_button.click()
    assert wait_for(
        lambda: any(lyr.name() == view.title for lyr in QgsProject.instance().mapLayers().values()), TIMEOUT
    )
    layer = next(lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() == view.title)
    assert layer.featureCount() == 500
    assert layer.providerType() == {LoadMode.MEMORY: "memory", LoadMode.SNAPSHOT: "ogr"}.get(mode, "geoduck")
    assert QgsSettings().value(SETTING) == mode.value
    dialog = AutoDialog.seen[-1]
    assert all(button.isEnabled() for button in dialog.mode_buttons.values())
    assert (
        "cargada · " in plugin.dock.message_label.text()
        and "· 500 entidades" in plugin.dock.message_label.text()
    )
    assert "Origen: consulta SQL" in plugin.dock.message_label.text()


def test_write_results_cannot_be_loaded(plugin):
    view = run_sql(plugin, "CREATE TABLE t (a INTEGER); INSERT INTO t VALUES (1) RETURNING a")
    assert not view.load_button.isEnabled()


def test_unknown_crs_is_asked(plugin):
    AutoDialog.choice = LoadMode.MEMORY
    AutoDialog.seen.clear()
    view = run_sql(plugin, "SELECT 'POINT(1 2)'::GEOMETRY AS g")
    view.load_button.click()
    assert wait_for(lambda: bool(AutoDialog.seen), TIMEOUT)
    dialog = AutoDialog.seen[-1]
    assert dialog._crs_unknown
    assert dialog.request().crs_override == ""  # sin elegir: continuar sin CRS, con aviso


def test_explorer_loads_a_table_connected_with_its_key(plugin):
    AutoDialog.choice = LoadMode.CONNECTED
    run_sql(
        plugin,
        "CREATE TABLE t (id INTEGER PRIMARY KEY, g GEOMETRY); INSERT INTO t VALUES (7, 'POINT(1 2)'); "
        "SELECT * FROM t",
    )
    plugin.dock.explorer.load_requested.emit(
        'SELECT * FROM "memory"."main"."t"', "t", ("memory", "main", "t")
    )
    assert wait_for(
        lambda: any(lyr.name() == "t" for lyr in QgsProject.instance().mapLayers().values()), TIMEOUT
    )
    layer = next(lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() == "t")
    assert layer.providerType() == "geoduck"
    assert [f.id() for f in layer.getFeatures()] == [7]


def test_double_click_on_a_table_loads_it_like_the_menu(plugin):
    """Issue #67: doble clic sobre una tabla = «Cargar en QGIS…»; sobre una base o esquema, nada."""
    AutoDialog.choice = LoadMode.CONNECTED
    run_sql(plugin, "CREATE TABLE dc (id INTEGER PRIMARY KEY, g GEOMETRY); SELECT * FROM dc")
    explorer = plugin.dock.explorer
    plugin.coordinator.refresh_catalog()

    def find(item):
        if item.text(0).startswith("dc ("):
            return item
        return next((f for i in range(item.childCount()) if (f := find(item.child(i)))), None)

    def table_item():
        tops = [explorer.topLevelItem(i) for i in range(explorer.topLevelItemCount())]
        return next((f for top in tops if (f := find(top))), None)

    assert wait_for(lambda: explorer.loading_enabled and table_item() is not None, TIMEOUT)
    requests = []
    explorer.load_requested.connect(lambda *args: requests.append(args))
    database = explorer.topLevelItem(0)
    explorer.itemDoubleClicked.emit(database, 0)
    assert requests == []
    explorer.itemDoubleClicked.emit(table_item(), 0)
    assert requests == [('SELECT * FROM "memory"."main"."dc"', "dc", ("memory", "main", "dc", "table"))]
    assert wait_for(
        lambda: any(lyr.name() == "dc" for lyr in QgsProject.instance().mapLayers().values()), TIMEOUT
    )
