# SPDX-License-Identifier: GPL-2.0-or-later
"""Lectura normalizada por lotes para cargar en QGIS (G3/E1; GD-BRD-002, GD-BRD-007; ADR-0012).

DuckDB real, matriz 1.5.0 / 1.5.x / 2.x.
"""

from __future__ import annotations

import datetime as dt
import threading

import pyarrow as pa
import pytest

from geoduck.domain.channel import BatchChannel, ConsumerGoneError
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.operations import ReadOutcome
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def run(worker, sql):
    return worker.submit(lambda h, t: h.execute(sql, max_rows=1000)).future.result(TIMEOUT)


def load(worker, sql, **kw):
    """Carga completa: devuelve (plan, tabla Arrow, resumen)."""
    plans, batches = [], []
    handle = worker.load_query(sql, on_plan=plans.append, on_batch=batches.append, **kw)
    outcome = handle.future.result(TIMEOUT)
    table = pa.Table.from_batches(batches) if batches else None
    return outcome.plan, table, outcome.summary


TYPES_SQL = """
SELECT
  1::HUGEINT * 170141183460469231731687303715884105727 AS hi,
  18446744073709551615::UBIGINT AS ub,
  4294967295::UINTEGER AS ui,
  1234567.89::DECIMAL(9,2) AS d9,
  '1234567890123456789012345678.0123456789'::DECIMAL(38,10) AS d38,
  'b'::ENUM('a','b') AS en,
  '550e8400-e29b-41d4-a716-446655440000'::UUID AS uu,
  TIME '12:34:56' AS tm,
  INTERVAL 3 DAY AS iv,
  TIMESTAMP_NS '2026-11-01 12:34:56.123456789' AS tns,
  TIMESTAMPTZ '2026-11-01 12:34:56+02' AS tz,
  [1, 2, 3] AS li,
  {'x': 1, 'y': 'z'} AS st,
  MAP {'k': 1} AS mp,
  '101'::BIT AS bi,
  'ñandú 🦆' AS txt,
  NULL::INTEGER AS nul,
  'NaN'::DOUBLE AS nan,
  DATE '2026-11-01' AS fecha,
  '\\xAA\\xBB'::BLOB AS blo
"""


def test_every_type_follows_section_7(worker):
    plan, table, summary = load(worker, TYPES_SQL)
    assert summary.outcome is ReadOutcome.EXHAUSTED
    row = table.to_pylist()[0]
    assert row["hi"] == "170141183460469231731687303715884105727"
    assert row["ub"] == "18446744073709551615"
    assert row["ui"] == 4294967295
    assert table.schema.field("ui").type == pa.int64()
    assert row["d9"] == pytest.approx(1234567.89)
    assert table.schema.field("d9").type == pa.float64()
    assert row["d38"] == "1234567890123456789012345678.0123456789"
    assert row["en"] == "b"
    assert row["uu"] == "550e8400-e29b-41d4-a716-446655440000"
    assert row["tm"] == "12:34:56"
    assert row["iv"] == "3 days"
    assert table.schema.field("tns").type == pa.timestamp("us")
    assert row["tz"].astimezone(dt.timezone.utc) == dt.datetime(
        2026, 11, 1, 10, 34, 56, tzinfo=dt.timezone.utc
    )
    assert row["li"] == "[1,2,3]"
    assert row["st"] == '{"x":1,"y":"z"}'
    assert row["mp"] == '{"k":1}'
    assert row["bi"] == "101"
    assert row["txt"] == "ñandú 🦆"
    assert row["nul"] is None
    assert row["nan"] != row["nan"]
    assert row["fecha"] == dt.date(2026, 11, 1)
    assert row["blo"] == b"\xaa\xbb"
    warned = {w.split("»")[0].lstrip("«") for w in plan.warnings}
    assert warned == {"hi", "ub", "d38", "tm", "iv", "tns", "li", "st", "mp", "bi"}


def test_geometry_travels_as_geoarrow_with_crs(worker):
    plan, table, _ = load(
        worker,
        "SELECT range AS id, ('POINT(' || range || ' 1)')::GEOMETRY('OGC:CRS84') AS g, "
        "'POINT(0 0)'::GEOMETRY AS otra FROM range(10)",
        geometry="g",
    )
    assert table.schema.names == ["id", "g"]
    meta = table.schema.field("g").metadata
    assert meta[b"ARROW:extension:name"] == b"geoarrow.wkb"
    assert b"CRS84" in meta[b"ARROW:extension:metadata"]
    assert any("«otra»" in w for w in plan.warnings)


def test_several_geometries_without_a_choice_fail_before_reading(worker):
    with pytest.raises(GeoDuckError, match="varias columnas de geometría"):
        load(worker, "SELECT 'POINT(0 0)'::GEOMETRY AS a, 'POINT(1 1)'::GEOMETRY AS b")


def test_multibatch_read_keeps_every_row(worker):
    _, table, summary = load(worker, "SELECT range AS id FROM range(100000)", batch_size=8192)
    assert summary.rows == table.num_rows == 100000
    assert summary.batches >= 12
    assert table.column("id").to_pylist() == list(range(100000))


def test_describe_does_not_execute_the_query(worker):
    run(worker, "CREATE SEQUENCE s START 1")
    plans: list = []
    handle = worker.load_query("SELECT nextval('s') AS v", on_plan=plans.append, on_batch=lambda b: None)
    handle.future.result(TIMEOUT)
    # una lectura completa avanza la secuencia una vez (la lectura), no dos (DESCRIBE no ejecuta)
    assert run(worker, "SELECT currval('s')").rows[0][0] == 1


def test_dml_is_never_executed(worker):
    run(worker, "CREATE TABLE t (a INTEGER)")
    with pytest.raises(Exception):  # noqa: B017 - el parser de DuckDB lo rechaza
        load(worker, "INSERT INTO t VALUES (1) RETURNING a")
    assert run(worker, "SELECT count(*) FROM t").rows[0][0] == 0


def test_cancel_stops_the_read_and_frees_the_worker(worker):
    seen = threading.Event()
    handle_box = {}

    def on_batch(_b):
        seen.set()

    handle = worker.load_query(
        "SELECT range AS id FROM range(50000000)", batch_size=1024, on_plan=lambda p: None, on_batch=on_batch
    )
    handle_box["h"] = handle
    assert seen.wait(TIMEOUT)
    worker.cancel(handle.op_id)
    outcome = handle.future.result(TIMEOUT)
    assert outcome.summary.outcome is ReadOutcome.CANCELLED
    assert run(worker, "SELECT 42").rows[0][0] == 42


def test_consumer_abandon_stops_the_producer(worker):
    channel = BatchChannel(capacity=1)
    handle = worker.load_query(
        "SELECT range AS id FROM range(5000000)",
        batch_size=1024,
        on_plan=lambda p: None,
        on_batch=channel.put,
    )
    ok, _ = channel.get(timeout=TIMEOUT)
    assert ok
    channel.abandon()
    with pytest.raises(ConsumerGoneError):
        handle.future.result(TIMEOUT)
    assert run(worker, "SELECT 1").rows[0][0] == 1


def test_registered_arrow_and_execute_many(worker):
    run(worker, "CREATE TABLE t (id BIGINT PRIMARY KEY, n VARCHAR)")
    run(worker, "INSERT INTO t VALUES (1, 'a'), (2, 'b')")
    data = pa.table({"id": [1, 2], "n": ["A", "B"]})

    def op(h, _t):
        with h.registered("__upd", data):
            h.execute("UPDATE t SET n = u.n FROM __upd u WHERE t.id = u.id")
        h.execute_many("INSERT INTO t VALUES (?, ?)", [(3, "c"), (4, "d")])
        return h.execute("SELECT id, n FROM t ORDER BY id").rows

    rows = worker.submit(op).future.result(TIMEOUT)
    assert rows == ((1, "A"), (2, "B"), (3, "c"), (4, "d"))
    # la vista registrada no queda en la sesión
    with pytest.raises(Exception):  # noqa: B017
        run(worker, "SELECT * FROM __upd")


def test_geometry_preview_works_in_every_version(worker):
    """DuckDB 1.5.0 no convierte GEOMETRY a Python: la vista previa lo describe sin fallar (G3/E4)."""
    from geoduck.domain.sql import RunScope, StatementStatus

    run = worker.run_script(
        run_id=1,
        text="SELECT 1 AS id, 'POINT(1 2)'::GEOMETRY('OGC:CRS84') AS g, "
        "'POLYGON Z((0 0 0, 1 0 0, 1 1 0, 0 0 0))'::GEOMETRY AS p, NULL::GEOMETRY AS n",
        scope=RunScope.ALL,
    ).future.result(TIMEOUT)
    result = run.results[0]
    assert result.status is StatementStatus.OK
    assert result.preview.rows[0] == (1, "POINT · 21 B", "POLYGON Z · 109 B", None)
