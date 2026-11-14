# SPDX-License-Identifier: GPL-2.0-or-later
"""AT-BOOT-001 y GD-SES-001 a través de la UI, con PyQGIS real (QGIS 3.x/Qt5 y 4.x/Qt6)."""

import importlib
import pkgutil
import threading

import pytest

import geoduck
from geoduck.domain.session import SessionState
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis


def test_every_module_imports(qgis_app):
    """AT-BOOT-001: ningún error de importación en QGIS 3 ni 4."""
    names = [m.name for m in pkgutil.walk_packages(geoduck.__path__, "geoduck.")]
    for name in names:
        importlib.import_module(name)
    assert "geoduck.ui.pro.workspace" in names and "geoduck.engine.worker" in names


def test_init_gui_registers_and_unload_removes(iface):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    assert len(iface.toolbar) == 1
    assert [action.objectName() for _menu, action in iface.menu] == ["geoduckToggleDock", "geoduckAbout"]
    window = plugin.workspace.window
    assert window.isHidden() and plugin.workspace.dock.isHidden()  # nada se abre solo al iniciar QGIS
    plugin.action.trigger()
    assert not window.isHidden() and plugin.action.isChecked()
    plugin.unload()
    assert iface.docks == [] and iface.menu == [] and iface.toolbar == []


def test_start_and_close_memory_session_from_the_dock(iface):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    ws, coordinator = plugin.content, plugin.coordinator
    side = ws.sidebar
    assert ws.start_button.isEnabled()
    assert not side.close_action.isEnabled()

    ws.start_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    assert side.status.text().startswith("Lista")
    assert side.title.text() == "GeoDuck"  # sin la versión de DuckDB: solo en «Acerca de» (#149)
    assert side.close_action.isEnabled()

    worker_thread = plugin.coordinator._engine.thread
    assert worker_thread is not threading.current_thread()

    side.close_action.trigger()
    assert wait_for(lambda: coordinator.state is SessionState.DISCONNECTED)
    assert ws.start_button.isEnabled() and not side.close_action.isEnabled()
    worker_thread.join(5)
    assert not worker_thread.is_alive()
    plugin.unload()


def test_invalidated_session_is_shown_once_and_new_session_recovers(iface):
    """#31 / C13 §4 bis en la UI: aviso visible, solo «Iniciar» y «Cerrar», y sesión nueva funcional."""
    import duckdb

    from geoduck.app.events import SessionInvalidated
    from geoduck.domain.session import ErrorCause

    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    ws, coordinator = plugin.content, plugin.coordinator
    notices = []
    coordinator.subscribe(lambda e: notices.append(e) if isinstance(e, SessionInvalidated) else None)
    ws.start_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    first_engine = coordinator._engine

    def fatal(handle, token):
        raise duckdb.FatalException("FATAL Error: simulado")

    first_engine.submit(fatal)
    assert wait_for(lambda: coordinator.state is SessionState.ERROR_RECOVERABLE)
    assert coordinator.error_cause is ErrorCause.SESSION_INVALIDATED
    assert len(notices) == 1
    assert "Sesión invalidada" in ws.notice.text()
    assert "SESSION_INVALIDATED" in ws.notice.text()
    assert coordinator.can_start and ws.start_button.isEnabled()  # se puede iniciar una sesión nueva

    ws.start()
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    assert coordinator._engine is not first_engine
    ws.close_session()
    assert wait_for(lambda: coordinator.state is SessionState.DISCONNECTED)
    assert len(notices) == 1
    plugin.unload()


def test_unload_with_open_session_stops_the_worker(iface):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    plugin.content.start_button.click()
    assert wait_for(lambda: plugin.coordinator.state is SessionState.READY)
    worker_thread = plugin.coordinator._engine.thread
    plugin.unload()
    # la conexión ya está cerrada cuando unload() vuelve; el hilo termina inmediatamente después
    worker_thread.join(5)
    assert not worker_thread.is_alive()


def test_dispatcher_runs_callbacks_on_main_thread(qgis_app):
    from geoduck.ui.dispatcher import QtDispatcher

    dispatcher = QtDispatcher()
    seen = []
    t = threading.Thread(target=lambda: dispatcher.post(lambda: seen.append(threading.get_ident())))
    t.start()
    t.join()
    assert wait_for(lambda: seen)
    assert seen == [threading.get_ident()]
    dispatcher.close()
    dispatcher.post(lambda: seen.append("tarde"))
    wait_for(lambda: False, timeout=0.2)
    assert seen == [threading.get_ident()]


def test_diagnostics_dialog_shows_and_copies_report(qgis_app):
    from qgis.PyQt.QtGui import QGuiApplication

    from geoduck.plugin import run_diagnostics
    from geoduck.ui.diagnostics_dialog import DiagnosticsDialog

    report = run_diagnostics()
    assert report.by_id("qgis").status.value == "OK"
    dialog = DiagnosticsDialog(report)
    assert "Diagnóstico de GeoDuck" in dialog.text.toPlainText()
    dialog.copy_button.click()
    assert QGuiApplication.clipboard().text() == report.to_text()


def test_broken_environment_disables_start(iface, monkeypatch):
    """AT-BOOT-002 en la UI: sin DuckDB el panel abre, explica y no permite iniciar."""
    from geoduck import plugin as plugin_module
    from geoduck.infra.diagnostics import collect

    def missing_duckdb(name):
        if name in ("duckdb", "pyarrow"):
            raise ImportError(f"No module named {name!r}")
        return importlib.import_module(name)

    monkeypatch.setattr(plugin_module, "run_diagnostics", lambda: collect(import_module=missing_duckdb))
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    ws = plugin.content
    assert not ws.start_button.isEnabled() and not ws.open_button.isEnabled()
    assert ws.state_title.text() == "El entorno no está listo para GeoDuck"
    assert "DuckDB" in ws.state_text.text()
    assert ws.diagnostics_button.isVisibleTo(ws)
    plugin.unload()


def test_unload_rolls_back_a_pending_transaction_and_never_commits(iface, tmp_path):
    """Decisión del 2026-11-01: al descargar GeoDuck o salir de QGIS, revertir lo pendiente; nunca COMMIT."""
    import duckdb

    from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction

    path = str(tmp_path / "datos.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE t AS SELECT 1 AS x")
    con.close()
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    coordinator = plugin.coordinator
    coordinator.start_file_session(AttachRequest(path, AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING, "d"))
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    engine = coordinator._engine
    engine.submit(lambda h, t: h.execute("BEGIN")).future.result(30)
    engine.submit(lambda h, t: h.execute("INSERT INTO d.t VALUES (2)")).future.result(30)
    worker_thread = engine.thread

    plugin.unload()  # sin diálogo: QGIS no permite que un complemento cancele su descarga
    worker_thread.join(10)
    assert not worker_thread.is_alive()
    check = duckdb.connect(path, read_only=True)
    try:
        assert check.execute("SELECT x FROM t ORDER BY x").fetchall() == [(1,)]  # revertida, no confirmada
    finally:
        check.close()
