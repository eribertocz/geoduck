# SPDX-License-Identifier: GPL-2.0-or-later
"""«Enviar a DuckDB» desde el coordinador, sin QGIS ni DuckDB (G8 · E3; qgis-import-spec §4, §9)."""

from __future__ import annotations

from concurrent.futures import Future

import pytest

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    PreviewsInvalidated,
    SendFailed,
    SendFinished,
    SendProgressed,
    SendStarted,
    SendUndoFailed,
    SendUndone,
)
from geoduck.domain.errors import ErrorCode, GeoDuckError, SessionStateError, TransactionError
from geoduck.domain.importing import (
    ImportedTable,
    ImportMode,
    ImportReport,
    ImportTarget,
    SendItem,
    SendRequest,
)
from geoduck.domain.session import SessionState as S
from tests.unit.test_coordinator import INFO, FakeEngine, QueueDispatcher
from tests.unit.test_coordinator_load import FakeTask

REQ = SendRequest((SendItem("L1", "zonas", ImportMode.CREATE),), "memory", "main", False)
TABLE = ImportedTable(
    "memory.main.zonas", '"memory"."main"."zonas"', ImportMode.CREATE, 3, False, "memory", "main", "zonas"
)


class FakeSender:
    def __init__(self):
        self.tasks = []
        self.progress = None

    def describe(self, layer_ids):
        return [layer_ids]

    def start(self, engine, request, *, on_progress, on_done):
        self.progress = on_progress
        task = FakeTask(on_done)
        task.request, task.engine = request, engine
        self.tasks.append(task)
        return task


class SendingEngine(FakeEngine):
    def __init__(self):
        super().__init__()
        self.targets: list[tuple[str, str, Future]] = []
        self.drops: list[tuple[list, Future]] = []

    def import_target(self, database, schema):
        self.targets.append((database, schema, Future()))
        return self.targets[-1][2]

    def drop_imported(self, tables):
        self.drops.append((tables, Future()))
        return self.drops[-1][1]


@pytest.fixture
def env():
    engines = []

    def factory():
        engines.append(SendingEngine())
        return engines[-1]

    sender = FakeSender()
    dispatcher = QueueDispatcher()
    coordinator = SessionCoordinator(factory, dispatcher, None, sender)
    events = []
    coordinator.subscribe(events.append)
    coordinator.start_memory_session()
    engines[-1].started.set_result(INFO)
    dispatcher.drain()
    assert coordinator.state is S.READY
    return coordinator, dispatcher, engines[-1], events, sender


def test_send_keeps_the_session_busy_then_refreshes_the_catalog(env):
    coordinator, _, engine, events, sender = env
    reads = len(engine.catalog_reads)
    send_id = coordinator.send_layers(REQ)
    assert coordinator.state is S.BUSY  # bloquea DETACH y el cierre (§9)
    sender.progress(10)
    sender.tasks[0].done(ImportReport((TABLE,)))
    assert coordinator.state is S.READY
    kinds = [type(e) for e in events if type(e).__name__.startswith("Send")]
    assert kinds == [SendStarted, SendProgressed, SendFinished]
    assert next(e for e in events if isinstance(e, SendFinished)).send_id == send_id
    assert any(isinstance(e, PreviewsInvalidated) for e in events)
    assert len(engine.catalog_reads) == reads + 1


def test_cancel_reports_cancelled_and_returns_to_ready(env):
    coordinator, _, _, events, sender = env
    coordinator.send_layers(REQ)
    assert coordinator.cancel_current_operation()
    assert sender.tasks[0].cancelled
    failed = next(e for e in events if isinstance(e, SendFailed))
    assert failed.cancelled and failed.code is ErrorCode.CANCELLED
    assert coordinator.state is S.READY


def test_send_requires_a_ready_session(env):
    coordinator, *_ = env
    coordinator.send_layers(REQ)
    with pytest.raises(SessionStateError):
        coordinator.send_layers(REQ)


def test_without_sender_it_is_not_available():
    coordinator = SessionCoordinator(FakeEngine, QueueDispatcher(), None)
    with pytest.raises(SessionStateError):
        coordinator.send_candidates(None)


def test_read_import_target_answers_on_the_main_thread(env):
    coordinator, dispatcher, engine, _, _ = env
    got = []
    coordinator.read_import_target("memory", "main", got.append)
    database, schema, fut = engine.targets[0]
    assert (database, schema) == ("memory", "main")
    fut.set_result(ImportTarget(True))
    assert got == []
    dispatcher.drain()
    assert got == [ImportTarget(True)]


def test_undo_drops_and_refreshes(env):
    coordinator, dispatcher, engine, events, _ = env
    coordinator.undo_send([TABLE])
    tables, fut = engine.drops[0]
    assert tables == [TABLE]
    fut.set_result(None)
    dispatcher.drain()
    assert any(isinstance(e, SendUndone) and e.tables == (TABLE,) for e in events)
    assert engine.catalog_reads  # el catálogo se relee


def test_undo_failure_is_reported(env):
    coordinator, dispatcher, engine, events, _ = env
    coordinator.undo_send([TABLE])
    engine.drops[0][1].set_exception(TransactionError("transacción abierta"))
    dispatcher.drain()
    assert any(isinstance(e, SendUndoFailed) for e in events)
    assert coordinator.state is S.READY


def test_engine_failure_is_reported(env):
    coordinator, _, _, events, sender = env
    coordinator.send_layers(REQ)
    sender.tasks[0].done(GeoDuckError("ya existe"))
    failed = next(e for e in events if isinstance(e, SendFailed))
    assert not failed.cancelled and "ya existe" in failed.message
    assert coordinator.state is S.READY
