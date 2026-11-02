# SPDX-License-Identifier: GPL-2.0-or-later
"""Explorador y controles del panel (G1 paso 8; GD-SES-002..004, GD-CAT-001, AT-CAT-001), con PyQGIS y
DuckDB reales. Los diálogos se sustituyen por respuestas fijas; el resto es el panel real.
"""

import subprocess
import sys

import duckdb
import pytest

import geoduck
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.session import SessionState
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

RO, RW = AccessMode.READ_ONLY, AccessMode.READ_WRITE


class Requests:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.actions = []

    def __call__(self, action, parent):
        self.actions.append(action)
        return self.answers.pop(0)


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "datos de Año.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE SCHEMA ventas; CREATE TABLE ventas.t AS SELECT 1 AS x; CREATE VIEW ventas.v AS SELECT 1 AS x"
    )
    con.close()
    return str(path)


def make_plugin(iface, requests):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    plugin.dock._ask_attach_request = requests
    return plugin, plugin.dock, plugin.coordinator


def tree(explorer):
    """Texto de los nodos: {base: {esquema: [objetos]}}."""
    out = {}
    for i in range(explorer.topLevelItemCount()):
        top = explorer.topLevelItem(i)
        out[top.text(0)] = {
            top.child(j).text(0): [top.child(j).child(k).text(0) for k in range(top.child(j).childCount())]
            for j in range(top.childCount())
        }
    return out


def ready(coordinator):
    return wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)


def test_open_existing_without_session_starts_a_file_session_and_shows_the_catalog(iface, db_file):
    requests = Requests(AttachRequest(db_file, RO, OpenAction.OPEN_EXISTING, "Ventas"))
    plugin, dock, coordinator = make_plugin(iface, requests)
    assert (
        dock.open_button.isEnabled() and dock.create_button.isEnabled() and not dock.detach_button.isEnabled()
    )
    dock.open_button.click()
    assert ready(coordinator)
    shown = tree(dock.explorer)
    root = coordinator.catalog.root
    assert shown[f"{root} · raíz, en uso"] == {"main": []}
    assert shown["Ventas · solo lectura"] == {"main": [], "ventas": ["t (tabla)", "v (vista)"]}
    assert dock.explorer.selected_database() == "Ventas"  # la base recién abierta queda seleccionada
    assert dock.detach_button.isEnabled()
    dock.explorer.select_database(root)
    assert not dock.detach_button.isEnabled()  # la raíz no se desadjunta
    plugin.unload()


def test_create_new_and_detach_release_the_file(iface, tmp_path):
    path = str(tmp_path / "nueva.duckdb")
    requests = Requests(AttachRequest(path, RW, OpenAction.CREATE_NEW, "nueva"))
    plugin, dock, coordinator = make_plugin(iface, requests)
    dock.start_button.click()
    assert ready(coordinator)
    dock.create_button.click()
    assert wait_for(lambda: coordinator.catalog is not None and coordinator.catalog.get("nueva") is not None)
    assert requests.actions == [OpenAction.CREATE_NEW]
    dock.explorer.select_database("nueva")
    assert dock.detach_button.isEnabled()
    dock.detach_button.click()
    assert wait_for(
        lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("nueva") is None
    )
    assert all("nueva" not in name for name in tree(dock.explorer))
    code = f"import duckdb;duckdb.connect({path!r}).close()"
    assert subprocess.run([sys.executable, "-c", code], check=False, timeout=30).returncode == 0
    plugin.unload()


def test_failed_open_shows_the_error_and_keeps_the_catalog(iface, tmp_path):
    missing = str(tmp_path / "no_existe.duckdb")
    requests = Requests(AttachRequest(missing, RW, OpenAction.OPEN_EXISTING))
    plugin, dock, coordinator = make_plugin(iface, requests)
    dock.start_button.click()
    assert ready(coordinator)
    before = tree(dock.explorer)
    dock.open_button.click()
    assert wait_for(lambda: "DB_NOT_FOUND" in dock.message_label.text())
    assert coordinator.state is SessionState.READY and tree(dock.explorer) == before
    import os

    assert not os.path.exists(missing)  # nunca se crea
    plugin.unload()


def test_cancelled_dialog_does_nothing(iface):
    requests = Requests(None)
    plugin, dock, coordinator = make_plugin(iface, requests)
    dock.open_button.click()
    assert coordinator.state is SessionState.DISCONNECTED and coordinator._engine is None
    plugin.unload()


def test_closing_clears_the_explorer_and_disables_detach(iface, db_file):
    requests = Requests(AttachRequest(db_file, RO, OpenAction.OPEN_EXISTING, "d"))
    plugin, dock, coordinator = make_plugin(iface, requests)
    dock.open_button.click()
    assert ready(coordinator)
    dock.close_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.DISCONNECTED)
    assert dock.explorer.topLevelItemCount() == 0 and not dock.detach_button.isEnabled()
    plugin.unload()


def test_temporaries_are_listed_separately(iface):
    plugin, dock, coordinator = make_plugin(iface, Requests())
    dock.start_button.click()
    assert ready(coordinator)
    coordinator._engine.submit(lambda h, t: h.execute("CREATE TEMP TABLE tmp(a INT)")).future.result(30)
    coordinator.refresh_catalog()
    assert wait_for(lambda: "Temporales de la sesión" in tree(dock.explorer))
    assert tree(dock.explorer)["Temporales de la sesión"] == {"tmp (tabla)": []}
    plugin.unload()


# -- diálogo -----------------------------------------------------------------------------------------


def test_attach_dialog_builds_requests(qgis_app):
    from geoduck.ui.attach_dialog import AttachDialog

    dialog = AttachDialog(OpenAction.CREATE_NEW)
    assert not dialog.access_combo.isEnabled()  # «Crear nueva» solo en RW
    dialog.path_edit.setText("/datos/nueva.duckdb")
    request = dialog.build_request()
    assert request.access is RW and request.action is OpenAction.CREATE_NEW and request.alias is None

    dialog = AttachDialog(OpenAction.OPEN_EXISTING)
    assert dialog.access_combo.currentData() is RO  # por defecto, solo lectura
    dialog.path_edit.setText("")
    dialog._accept()
    assert dialog.request is None and not dialog.error_label.isHidden()  # sigue abierto con el error
    dialog.path_edit.setText("/datos/x.duckdb")
    dialog.alias_edit.setText("Mi base")
    dialog._accept()
    assert dialog.request == AttachRequest("/datos/x.duckdb", RO, OpenAction.OPEN_EXISTING, "Mi base")
