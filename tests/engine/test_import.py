# SPDX-License-Identifier: GPL-2.0-or-later
"""«Enviar a DuckDB»: lotes en una transacción, contra DuckDB real (G8 · E1; AT-IMP-004, 006, 007).

Los lotes Arrow los produce aquí un hilo de prueba (en E2, una `QgsTask` que lee la capa). Sin `spatial`.
"""

from __future__ import annotations

import json
import threading
import time

import pyarrow as pa
import pytest

from geoduck.domain.channel import BatchChannel, ConsumerGoneError
from geoduck.domain.errors import EngineError, GeoDuckError, OperationCancelledError, TransactionError
from geoduck.domain.importing import WKB_COLUMN, ImportColumn, ImportGeometry, ImportJob, ImportMode
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 60
#: POINT(-68.15 -16.5) en WKB little-endian.
LAPAZ = bytes.fromhex("01010000009a999999990951c000000000008030c0")
COLUMNS = (
    ImportColumn("id", "id", "BIGINT"),
    ImportColumn("nombre", "nombre", "VARCHAR"),
    ImportColumn("alta", "alta", "DATE"),
)
PROJJSON = json.dumps(
    {
        "type": "GeographicCRS",
        "name": "WGS 84 personalizado",
        "datum": {
            "type": "GeodeticReferenceFrame",
            "name": "WGS 84",
            "ellipsoid": {"name": "WGS 84", "semi_major_axis": 6378137, "inverse_flattening": 298.257223563},
        },
        "coordinate_system": {
            "subtype": "ellipsoidal",
            "axis": [
                {"name": "Longitude", "abbreviation": "lon", "direction": "east", "unit": "degree"},
                {"name": "Latitude", "abbreviation": "lat", "direction": "north", "unit": "degree"},
            ],
        },
    }
)


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def sql(worker, text, max_rows=1000):
    return worker.submit(lambda h, t: h.execute(text, max_rows=max_rows)).future.result(TIMEOUT).rows


def batch(start, n, wkb=LAPAZ):
    import datetime as dt

    return pa.record_batch(
        {
            "id": pa.array(range(start, start + n), pa.int64()),
            "nombre": pa.array([f"N{i}" for i in range(start, start + n)]),
            "alta": pa.array([dt.date(2025, 1, 1)] * n, pa.date32()),
            WKB_COLUMN: pa.array([wkb if i % 10 else None for i in range(start, start + n)], pa.binary()),
        }
    )


def job(table, mode=ImportMode.CREATE, crs="EPSG:4326", **kw):
    geometry = ImportGeometry("geom", crs) if crs is not False else None
    return ImportJob(kw.pop("layer", table), table, mode, COLUMNS, geometry, **kw)


def send(worker, jobs, batches, *, delay=0.0, fail_at=None):
    """Produce los lotes en otro hilo; devuelve (resultado o excepción, el productor terminó sin colgarse)."""
    channel = BatchChannel(capacity=2)
    handle = worker.import_batches(jobs, channel)
    done = threading.Event()

    def produce():
        try:
            for k, item in enumerate(batches):
                if fail_at is not None and k == fail_at:
                    channel.fail(RuntimeError("fallo al leer la capa"))
                    return
                channel.put(item)
                time.sleep(delay)
            channel.finish()
        except ConsumerGoneError:
            pass
        finally:
            done.set()

    threading.Thread(target=produce, daemon=True).start()
    try:
        result = handle.future.result(TIMEOUT)
    except BaseException as exc:
        result = exc
    return result, done.wait(TIMEOUT), handle


def test_create_writes_every_batch_with_geometry_and_crs(worker):
    jobs = [job("puntos")]
    report, finished, _ = send(worker, jobs, [(0, batch(0, 50_000)), (0, batch(50_000, 50_000))])
    assert finished and not isinstance(report, BaseException), report
    assert [(t.display, t.rows, t.mode) for t in report.tables] == [
        ("memory.main.puntos", 100_000, ImportMode.CREATE)
    ]
    assert sql(worker, "SELECT count(*), count(geom), min(alta) FROM puntos")[0][:2] == (100_000, 90_000)
    types = dict(
        sql(worker, "SELECT column_name, data_type FROM duckdb_columns() WHERE table_name = 'puntos'")
    )
    assert types == {"id": "BIGINT", "nombre": "VARCHAR", "alta": "DATE", "geom": "GEOMETRY('EPSG:4326')"}
    assert sql(worker, "SELECT ST_AsText(geom) FROM puntos WHERE id = 1")[0][0] == "POINT (-68.15 -16.5)"


def test_custom_crs_as_projjson_and_no_crs(worker):
    report, _, _ = send(
        worker, [job("a", crs=PROJJSON), job("b", crs=None)], [(0, batch(0, 5)), (1, batch(0, 5))]
    )
    assert not isinstance(report, BaseException), report
    types = dict(sql(worker, "SELECT table_name, data_type FROM duckdb_columns() WHERE column_name = 'geom'"))
    assert types["a"].startswith("GEOMETRY('{") and "WGS 84 personalizado" in types["a"]
    assert types["b"] == "GEOMETRY"
    assert report.warnings == ("memory.main.b: la geometría no tiene SRC (la capa no tenía)",)


def test_layer_without_features_still_creates_its_table(worker):
    report, _, _ = send(worker, [job("vacia")], [(0, batch(0, 0))])
    assert not isinstance(report, BaseException), report
    assert sql(worker, "SELECT count(*) FROM vacia") == ((0,),)
    assert [c[0] for c in sql(worker, "DESCRIBE vacia")] == ["id", "nombre", "alta", "geom"]


def test_create_never_overwrites_an_existing_table(worker):
    sql(worker, "CREATE TABLE zonas AS SELECT 1 AS x")
    result, finished, _ = send(worker, [job("zonas")], [(0, batch(0, 10))])
    assert isinstance(result, GeoDuckError) and finished
    assert sql(worker, "SELECT * FROM zonas") == ((1,),)


def test_replace_and_append(worker):
    send(worker, [job("t")], [(0, batch(0, 10))])
    report, _, _ = send(worker, [job("t", ImportMode.APPEND)], [(0, batch(10, 5))])
    assert not isinstance(report, BaseException), report
    assert report.tables[0].rows == 5
    assert sql(worker, "SELECT count(*), max(id) FROM t") == ((15, 14),)
    report, _, _ = send(worker, [job("t", ImportMode.REPLACE)], [(0, batch(100, 3))])
    assert sql(worker, "SELECT count(*), min(id) FROM t") == ((3, 100),)


def test_append_by_name_with_missing_columns(worker):
    sql(worker, "CREATE TABLE t (id BIGINT, nombre VARCHAR, alta DATE, extra INTEGER, geom GEOMETRY)")
    report, _, _ = send(worker, [job("t", ImportMode.APPEND, crs=None)], [(0, batch(0, 4))])
    assert not isinstance(report, BaseException), report
    assert sql(worker, "SELECT count(*), count(extra) FROM t") == ((4, 0),)


def test_temporary_table(worker):
    report, _, _ = send(worker, [job("tmp", temporary=True)], [(0, batch(0, 7))])
    assert not isinstance(report, BaseException), report
    assert report.tables[0].display == "tmp (temporal)"
    assert sql(worker, "SELECT count(*) FROM temp.main.tmp") == ((7,),)


def test_other_database(worker, tmp_path):
    sql(worker, f"ATTACH '{tmp_path / 'otra.duckdb'}' AS otra (STORAGE_VERSION 'v1.5.0')")
    report, _, _ = send(worker, [job("t", database="otra")], [(0, batch(0, 3))])
    assert not isinstance(report, BaseException), report
    assert sql(worker, "SELECT count(*) FROM otra.main.t") == ((3,),)
    assert sql(worker, "SELECT data_type FROM duckdb_columns() WHERE column_name = 'geom'") == (
        ("GEOMETRY('EPSG:4326')",),
    )


def test_old_file_format_cannot_store_the_crs_and_nothing_is_written(worker, tmp_path):
    """F-120: un archivo con formato v1.0.0+ (por defecto en DuckDB 1.5.x) no guarda el SRC."""
    sql(worker, f"ATTACH '{tmp_path / 'vieja.duckdb'}' AS vieja (STORAGE_VERSION 'v1.0.0')")
    result, finished, _ = send(worker, [job("t", database="vieja")], [(0, batch(0, 3))])
    assert isinstance(result, GeoDuckError) and finished
    assert "formato de archivo antiguo" in result.message
    assert sql(worker, "SELECT count(*) FROM duckdb_tables() WHERE database_name = 'vieja'") == ((0,),)
    report, _, _ = send(
        worker, [job("t", database="vieja", crs=None)], [(0, batch(0, 3))]
    )  # sin SRC, elegido
    assert not isinstance(report, BaseException), report
    assert sql(worker, "SELECT count(*) FROM vieja.main.t") == ((3,),)


def test_all_or_nothing_when_the_second_layer_fails(worker):
    sql(worker, "CREATE TABLE previa AS SELECT 1 AS id")
    jobs = [job("primera"), job("previa", ImportMode.REPLACE), job("segunda")]
    bad = batch(0, 3, wkb=b"\x01\x02")  # WKB ilegible: DuckDB lo rechaza
    result, finished, _ = send(worker, jobs, [(0, batch(0, 10)), (1, batch(0, 10)), (2, bad)])
    assert isinstance(result, GeoDuckError) and finished
    tables = {r[0] for r in sql(worker, "SELECT table_name FROM duckdb_tables()")}
    assert "primera" not in tables and "segunda" not in tables
    assert sql(worker, "SELECT * FROM previa") == ((1,),)  # el reemplazo se deshizo


def test_reader_failure_rolls_back(worker):
    result, finished, _ = send(worker, [job("t")], [(0, batch(0, 10)), (0, batch(10, 10))], fail_at=1)
    assert isinstance(result, BaseException) and finished
    assert "t" not in {r[0] for r in sql(worker, "SELECT table_name FROM duckdb_tables()")}


def test_cancel_rolls_back_and_stops_the_producer(worker):
    batches = [(0, batch(i * 10_000, 10_000)) for i in range(200)]
    channel = BatchChannel(capacity=2)
    handle = worker.import_batches([job("t")], channel)
    stopped = threading.Event()

    def produce():
        try:
            for item in batches:
                channel.put(item)
                time.sleep(0.01)
            channel.finish()
        except ConsumerGoneError:
            stopped.set()

    threading.Thread(target=produce, daemon=True).start()
    time.sleep(0.3)
    assert worker.cancel(handle.op_id)
    with pytest.raises(OperationCancelledError):
        handle.future.result(TIMEOUT)
    assert stopped.wait(TIMEOUT)  # el productor deja de leer la capa
    assert "t" not in {r[0] for r in sql(worker, "SELECT table_name FROM duckdb_tables()")}
    assert sql(worker, "SELECT 1") == ((1,),)  # la sesión sigue utilizable


def test_open_user_transaction_is_rejected_and_left_intact(worker):
    sql(worker, "BEGIN")
    sql(worker, "CREATE TABLE del_usuario AS SELECT 1 AS x")
    result, finished, _ = send(worker, [job("t")], [(0, batch(0, 3))])
    assert isinstance(result, TransactionError) and finished
    assert sql(worker, "SELECT * FROM del_usuario") == ((1,),)  # su transacción no se abortó
    sql(worker, "COMMIT")
    assert sql(worker, "SELECT count(*) FROM del_usuario") == ((1,),)


def test_types_are_cast_to_the_planned_duckdb_types(worker):
    columns = (
        ImportColumn("entero", "a", "INTEGER"),
        ImportColumn("lista", "b", "VARCHAR[]"),
        ImportColumn("datos", "c", "JSON"),
        ImportColumn("hora", "d", "TIMESTAMP"),
    )
    import datetime as dt

    data = pa.record_batch(
        {
            "a": pa.array([1, None], pa.int64()),
            "b": pa.array([["x", "y"], None], pa.list_(pa.string())),
            "c": pa.array(['{"k": 1}', None]),
            "d": pa.array([dt.datetime(2025, 5, 1, 10, 30), None], pa.timestamp("us")),
        }
    )
    jobs = [ImportJob("tipos", "tipos", ImportMode.CREATE, columns, None)]
    report, _, _ = send(worker, jobs, [(0, data)])
    assert not isinstance(report, BaseException), report
    types = dict(
        sql(worker, "SELECT column_name, data_type FROM duckdb_columns() WHERE table_name = 'tipos'")
    )
    assert types == {"entero": "INTEGER", "lista": "VARCHAR[]", "datos": "JSON", "hora": "TIMESTAMP"}
    assert sql(worker, "SELECT count(*), count(entero) FROM tipos") == ((2, 1),)


def test_a_layer_that_sent_nothing_is_an_error(worker):
    result, _, _ = send(worker, [job("a"), job("b")], [(0, batch(0, 3))])
    assert isinstance(result, EngineError) and "b" in result.message
    assert not {"a", "b"} & {r[0] for r in sql(worker, "SELECT table_name FROM duckdb_tables()")}
