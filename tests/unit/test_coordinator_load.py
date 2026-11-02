# SPDX-License-Identifier: GPL-2.0-or-later
"""Carga en QGIS desde el coordinador, sin QGIS ni DuckDB (G3/E2; ADR-0012)."""

from __future__ import annotations

from concurrent.futures import Future

import pytest

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    LoadFailed,
    LoadFinished,
    LoadPrepared,
    LoadPrepareFailed,
    LoadProgressed,
    LoadStarted,
)
from geoduck.domain.bridge_types import build_load_plan
from geoduck.domain.errors import ErrorCode, GeoDuckError, SessionStateError
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.domain.session import SessionState as S
from tests.unit.test_coordinator import INFO, FakeEngine, QueueDispatcher


class FakeTask:
    def __init__(self, done):
        self.done = done
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        self.done(GeoDuckError("Carga cancelada", code=ErrorCode.CANCELLED))


class FakeLoader:
    def __init__(self, fail_start=False):
        self.tasks = []
        self.fail_start = fail_start
        self.progress = None

    def availability(self):
        return {LoadMode.MEMORY: None, LoadMode.SNAPSHOT: "sin GDAL", LoadMode.CONNECTED: None}

    def start(self, engine, request, *, on_progress, on_done):
        if self.fail_start:
            raise GeoDuckError("no se pudo")
        self.progress = on_progress
        task = FakeTask(on_done)
        task.request, task.engine = request, engine
        self.tasks.append(task)
        return task


class PreparingEngine(FakeEngine):
    def __init__(self):
        super().__init__()
        self.prepared = Future()

    def prepare_load(self, sql, geometry=None):
        return self.prepared


@pytest.fixture
def env():
    engines = []

    def factory():
        engines.append(PreparingEngine())
        return engines[-1]

    loader = FakeLoader()
    dispatcher = QueueDispatcher()
    coordinator = SessionCoordinator(factory, dispatcher, loader)
    events = []
    coordinator.subscribe(events.append)
    coordinator.start_memory_session()
    engines[-1].started.set_result(INFO)
    dispatcher.drain()
    assert coordinator.state is S.READY
    return coordinator, dispatcher, engines, events, loader


REQ = LoadRequest(sql="SELECT 1", mode=LoadMode.MEMORY, layer_name="capa")


def test_load_keeps_the_session_busy_until_done(env):
    coordinator, _, engines, events, loader = env
    load_id = coordinator.load(REQ)
    assert coordinator.state is S.BUSY
    assert loader.tasks[0].engine is engines[-1]
    loader.progress(1000)
    loader.tasks[0].done(LoadReport("L1", "capa", LoadMode.MEMORY, 1000))
    assert coordinator.state is S.READY
    assert [type(e) for e in events if type(e).__name__.startswith("Load")] == [
        LoadStarted,
        LoadProgressed,
        LoadFinished,
    ]
    assert next(e for e in events if isinstance(e, LoadFinished)).load_id == load_id


def test_cancel_current_operation_cancels_the_load(env):
    coordinator, _, _, events, loader = env
    coordinator.load(REQ)
    assert coordinator.cancel_current_operation()
    assert loader.tasks[0].cancelled
    failed = next(e for e in events if isinstance(e, LoadFailed))
    assert failed.cancelled
    assert coordinator.state is S.READY


def test_unavailable_mode_is_rejected_with_its_reason(env):
    coordinator, *_ = env
    with pytest.raises(SessionStateError, match="sin GDAL"):
        coordinator.load(LoadRequest(sql="SELECT 1", mode=LoadMode.SNAPSHOT, layer_name="x"))
    assert coordinator.state is S.READY


def test_start_error_returns_to_ready_and_reports(env):
    coordinator, _, _, events, loader = env
    loader.fail_start = True
    with pytest.raises(GeoDuckError):
        coordinator.load(REQ)
    assert coordinator.state is S.READY
    assert any(isinstance(e, LoadFailed) and not e.cancelled for e in events)


def test_load_requires_a_ready_session(env):
    coordinator, *_ = env
    coordinator.load(REQ)
    with pytest.raises(SessionStateError):
        coordinator.load(REQ)


def test_without_loader_every_mode_is_unavailable():
    coordinator = SessionCoordinator(FakeEngine, QueueDispatcher())
    assert all(reason for reason in coordinator.load_modes().values())


def test_prepare_publishes_the_plan_or_the_error(env):
    coordinator, dispatcher, engines, events, _ = env
    token = coordinator.prepare_load("SELECT 1 AS a")
    plan = build_load_plan("SELECT 1 AS a", [("a", "INTEGER")])
    engines[-1].prepared.set_result(plan)
    dispatcher.drain()
    assert LoadPrepared(token, plan) in events
    engines[-1].prepared = Future()
    token2 = coordinator.prepare_load("SELECT x")
    engines[-1].prepared.set_exception(GeoDuckError("Binder Error", code=ErrorCode.ENGINE_ERROR))
    dispatcher.drain()
    assert any(isinstance(e, LoadPrepareFailed) and e.token == token2 for e in events)
    assert coordinator.state is S.READY
