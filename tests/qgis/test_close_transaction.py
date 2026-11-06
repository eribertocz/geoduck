# SPDX-License-Identifier: GPL-2.0-or-later
"""Cierre con una transacción abierta desde GeoDuck («Cerrar DuckDB»; G1 paso 7), con PyQGIS y DuckDB reales.

Decisión del 2026-11-01: COMMIT, ROLLBACK o cancelar el cierre; cancelar no modifica la transacción;
COMMIT deshabilitado si no es válido.
"""

import time

import duckdb
import pytest

import geoduck
from geoduck.app.events import CloseConfirmationRequired
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.session import SessionState
from geoduck.domain.transaction import CloseChoice, TransactionState
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

TIMEOUT = 30


class Chooser:
    """Sustituye al diálogo modal: registra lo que se preguntó y responde lo indicado."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked: list[CloseConfirmationRequired] = []

    def __call__(self, request, parent):
        self.asked.append(request)
        return self.answers.pop(0)


@pytest.fixture
def db_file(tmp_path):
    path = tmp_path / "datos.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t AS SELECT 1 AS x")
    con.close()
    return str(path)


def open_with_transaction(iface, db_file, chooser):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    plugin.content._ask_close = chooser
    coordinator = plugin.coordinator
    coordinator.start_file_session(
        AttachRequest(db_file, AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING, "d")
    )
    assert wait_for(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    engine = coordinator._engine
    engine.submit(lambda h, t: h.execute("BEGIN")).future.result(TIMEOUT)
    engine.submit(lambda h, t: h.execute("INSERT INTO d.t VALUES (2)")).future.result(TIMEOUT)
    return plugin, coordinator, engine


def rows(path):
    con = duckdb.connect(path, read_only=True)
    try:
        return sorted(r[0] for r in con.execute("SELECT x FROM t").fetchall())
    finally:
        con.close()


def test_cancel_keeps_session_and_transaction_then_commit_persists(iface, db_file):
    chooser = Chooser(CloseChoice.CANCEL, CloseChoice.COMMIT)
    plugin, coordinator, engine = open_with_transaction(iface, db_file, chooser)

    plugin.content.sidebar.close_action.trigger()
    assert wait_for(lambda: len(chooser.asked) == 1)
    assert chooser.asked[0] == CloseConfirmationRequired(TransactionState.ACTIVE, commit_allowed=True)
    assert coordinator.state is SessionState.READY
    assert engine.transaction_state().result(TIMEOUT) is TransactionState.ACTIVE  # intacta
    assert engine.submit(lambda h, t: h.execute("SELECT count(*) FROM d.t").rows).future.result(TIMEOUT) == (
        (2,),
    )

    plugin.content.sidebar.close_action.trigger()
    assert wait_for(lambda: coordinator.state is SessionState.DISCONNECTED)
    assert rows(db_file) == [1, 2]  # confirmada antes de cerrar
    plugin.unload()


def test_rollback_discards_and_closes(iface, db_file):
    chooser = Chooser(CloseChoice.ROLLBACK)
    plugin, coordinator, _engine = open_with_transaction(iface, db_file, chooser)
    plugin.content.sidebar.close_action.trigger()
    assert wait_for(lambda: coordinator.state is SessionState.DISCONNECTED)
    assert rows(db_file) == [1]
    plugin.unload()


def test_aborted_transaction_disables_commit_and_rollback_closes(iface, db_file):
    chooser = Chooser(CloseChoice.ROLLBACK)
    plugin, coordinator, engine = open_with_transaction(iface, db_file, chooser)
    long_query = engine.submit(
        lambda h, t: h.execute("SELECT count(*) FROM range(5000000000) t(a) WHERE a % 7 = 3")
    )
    deadline = time.monotonic() + 5
    while not long_query.future.running() and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.3)
    engine.cancel(long_query.op_id)
    assert engine.transaction_state().result(TIMEOUT) is TransactionState.ABORTED

    plugin.content.sidebar.close_action.trigger()
    assert wait_for(lambda: coordinator.state is SessionState.DISCONNECTED)
    assert chooser.asked == [CloseConfirmationRequired(TransactionState.ABORTED, commit_allowed=False)]
    assert rows(db_file) == [1]
    plugin.unload()


def test_without_transaction_close_does_not_ask(iface, db_file):
    chooser = Chooser()
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    plugin.content._ask_close = chooser
    plugin.content.start_button.click()
    assert wait_for(lambda: plugin.coordinator.state is SessionState.READY)
    plugin.content.sidebar.close_action.trigger()
    assert wait_for(lambda: plugin.coordinator.state is SessionState.DISCONNECTED)
    assert chooser.asked == []
    plugin.unload()


@pytest.mark.parametrize("state", [TransactionState.ACTIVE, TransactionState.ABORTED])
def test_dialog_buttons_and_escape_cancels(qgis_app, state):
    from geoduck.ui.close_dialog import CloseTransactionDialog

    dialog = CloseTransactionDialog(
        CloseConfirmationRequired(state, commit_allowed=state is TransactionState.ACTIVE)
    )
    assert dialog.commit_button.isEnabled() is (state is TransactionState.ACTIVE)
    assert dialog.rollback_button.isEnabled() and dialog.cancel_button.isEnabled()
    assert dialog.cancel_button.isDefault()  # la opción por defecto no modifica nada
    dialog.reject()  # Escape o la «X»
    assert dialog.choice is CloseChoice.CANCEL
    dialog = CloseTransactionDialog(CloseConfirmationRequired(state, commit_allowed=True))
    dialog.rollback_button.click()
    assert dialog.choice is CloseChoice.ROLLBACK
