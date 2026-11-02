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


@pytest.mark.parametrize("mode", [LoadMode.MEMORY, LoadMode.SNAPSHOT])
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
    assert layer.providerType() == ("memory" if mode is LoadMode.MEMORY else "ogr")
    assert QgsSettings().value(SETTING) == mode.value
    dialog = AutoDialog.seen[-1]
    assert not dialog.mode_buttons[LoadMode.CONNECTED].isEnabled()  # llega en E5, con motivo visible
    assert "cargada: 500 filas" in plugin.dock.message_label.text()


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
