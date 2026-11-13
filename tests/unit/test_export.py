# SPDX-License-Identifier: GPL-2.0-or-later
"""«Exportar ▾» (G7 · E3, AT-NB-011): opciones de `COPY` y coordinador, con dobles (sin DuckDB ni Qt)."""

from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import ExportFailed, ExportFinished, ExportStarted
from geoduck.domain.errors import EngineError, OperationCancelledError, SessionStateError
from geoduck.domain.export import ExportFormat, ExportReport, ExportRequest, copy_options
from geoduck.domain.session import SessionState
from tests.unit.test_coordinator import INFO, FakeEngine, QueueDispatcher

# -- opciones de COPY ---------------------------------------------------------------------------------------


def test_csv_always_with_header_and_no_warnings():
    assert copy_options([("g", "GEOMETRY")], ExportFormat.CSV) == ("FORMAT csv, HEADER", ())


def test_parquet_without_geometry_uses_the_default():
    assert copy_options([("n", "INTEGER")], ExportFormat.PARQUET) == ("FORMAT parquet", ())


def test_parquet_geometry_without_crs_warns_and_never_invents_one():
    options, warnings = copy_options([("n", "INTEGER"), ("geom", "GEOMETRY")], ExportFormat.PARQUET)
    assert options == "FORMAT parquet"
    assert len(warnings) == 1 and "«geom»" in warnings[0] and "OGC:CRS84" in warnings[0]


def test_parquet_geometry_with_crs_is_kept_and_the_others_still_warn():
    columns = [("utm", "GEOMETRY('EPSG:32719')"), ("cruda", "GEOMETRY")]
    options, warnings = copy_options(columns, ExportFormat.PARQUET)
    assert options == "FORMAT parquet, GEOPARQUET_VERSION 'V2'"
    assert len(warnings) == 1 and "«cruda»" in warnings[0]


# -- coordinador --------------------------------------------------------------------------------------------


class ExportingEngine(FakeEngine):
    def __init__(self):
        super().__init__()
        self.exports: list[tuple[ExportRequest, Future]] = []

    def export_query(self, request):
        self.exports.append((request, Future()))
        return SimpleNamespace(op_id=1, future=self.exports[-1][1])


@pytest.fixture
def ready():
    engines: list[ExportingEngine] = []

    def factory():
        engines.append(ExportingEngine())
        return engines[-1]

    dispatcher = QueueDispatcher()
    coordinator = SessionCoordinator(factory, dispatcher)
    events: list = []
    coordinator.subscribe(events.append)
    coordinator.start_memory_session()
    engines[0].started.set_result(INFO)
    dispatcher.drain()
    return coordinator, dispatcher, engines[0], events


REQUEST = ExportRequest("SELECT * FROM t;\n-- comentario", "/tmp/t.csv", ExportFormat.CSV, "db")


def test_export_keeps_the_session_busy_and_reports_the_rows(ready):
    coordinator, dispatcher, engine, events = ready
    export_id = coordinator.export(REQUEST)
    assert coordinator.state is SessionState.BUSY
    ((sent, future),) = engine.exports
    assert sent.sql.strip() == "SELECT * FROM t" and sent.database == "db"  # sin `;` ni comentario final
    assert isinstance(events[-1], ExportStarted) and events[-1].export_id == export_id
    with pytest.raises(SessionStateError):
        coordinator.export(REQUEST)  # una a la vez: la sesión está ocupada
    future.set_result(ExportReport("/tmp/t.csv", ExportFormat.CSV, 1_000_000))
    dispatcher.drain()
    assert coordinator.state is SessionState.READY
    assert events[-1] == ExportFinished(export_id, ExportReport("/tmp/t.csv", ExportFormat.CSV, 1_000_000))


def test_cancel_and_failure_return_to_ready(ready):
    coordinator, dispatcher, engine, events = ready
    coordinator.export(REQUEST)
    assert coordinator.cancel_current_operation() and engine.cancelled
    engine.exports[-1][1].set_exception(OperationCancelledError("cancelada"))
    dispatcher.drain()
    assert coordinator.state is SessionState.READY
    assert isinstance(events[-1], ExportFailed) and events[-1].cancelled

    coordinator.export(REQUEST)
    engine.exports[-1][1].set_exception(EngineError("Catalog Error: t no existe"))
    dispatcher.drain()
    assert coordinator.state is SessionState.READY
    assert (
        isinstance(events[-1], ExportFailed)
        and not events[-1].cancelled
        and "t no existe" in events[-1].message
    )


def test_shapefile_is_written_in_utf8_and_warns_about_long_names():
    """#141: `.cpg` en UTF-8 y aviso de los nombres que GDAL acorta a 10 bytes."""
    options, warnings = copy_options(
        [("id", "INTEGER"), ("región", "VARCHAR"), ("nombre_muy_largo", "VARCHAR"), ("geom", "GEOMETRY")],
        ExportFormat.SHP,
    )
    assert "DRIVER 'ESRI Shapefile'" in options and "ENCODING=UTF-8" in options
    assert len(warnings) == 1 and "«nombre_muy_largo»" in warnings[0] and "región" not in warnings[0]
    assert copy_options([("id", "INTEGER"), ("geom", "GEOMETRY")], ExportFormat.SHP)[1] == ()
