# SPDX-License-Identifier: GPL-2.0-or-later
"""«Exportar ▾» contra DuckDB real (G7 · E3, AT-NB-011; GD-NB-007; `geoduck.engine.export`)."""

from __future__ import annotations

import threading
import time

import pytest

from geoduck.domain.errors import GeoDuckError, OperationCancelledError
from geoduck.domain.export import ExportFormat, ExportRequest
from geoduck.domain.sql import RunScope
from geoduck.domain.sql_text import quote_string_literal
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 60
MILLION = "SELECT range AS id, ('POINT(' || range || ' 1)')::GEOMETRY AS g FROM range(1000000)"


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def run_sql(worker, sql):
    return worker.submit(lambda h, t: h.execute(sql, max_rows=10)).future.result(TIMEOUT)


def export(worker, sql, path, fmt, database=None):
    return worker.export_query(ExportRequest(sql, str(path), fmt, database)).future.result(TIMEOUT)


def leftovers(folder):
    return [p.name for p in folder.iterdir() if p.name.startswith(".")]


@pytest.mark.parametrize("fmt", list(ExportFormat))
def test_the_whole_query_is_exported_not_the_preview(worker, tmp_path, fmt):
    target = tmp_path / f"millon{fmt.suffix}"
    report = export(worker, MILLION + ";\n-- fin", target, fmt)  # como la sentencia del editor
    assert report.rows == 1_000_000 and report.path == str(target)
    reader = "read_csv" if fmt is ExportFormat.CSV else "read_parquet"
    rows = run_sql(worker, f"SELECT count(*), max(id) FROM {reader}({quote_string_literal(str(target))})")
    assert rows.rows == ((1_000_000, 999_999),)
    assert leftovers(tmp_path) == []


def test_csv_writes_the_geometry_as_wkt(worker, tmp_path):
    target = tmp_path / "puntos.csv"
    report = export(worker, "SELECT 1 AS id, 'POINT(1 2)'::GEOMETRY AS g", target, ExportFormat.CSV)
    assert target.read_text().splitlines() == ["id,g", "1,POINT (1 2)"] and report.warnings == ()


def test_parquet_without_crs_warns_and_keeps_geoparquet_1(worker, tmp_path):
    target = tmp_path / "sin_src.parquet"
    report = export(worker, "SELECT 'POINT(1 2)'::GEOMETRY AS g", target, ExportFormat.PARQUET)
    assert len(report.warnings) == 1 and "OGC:CRS84" in report.warnings[0] and "«g»" in report.warnings[0]
    meta = run_sql(
        worker,
        f"SELECT decode(value) FROM parquet_kv_metadata({quote_string_literal(str(target))}) "
        "WHERE decode(key) = 'geo'",
    ).rows
    assert '"version":"1.0.0"' in meta[0][0]


def test_parquet_with_crs_keeps_it(worker, tmp_path):
    """La opción por defecto de DuckDB falla con un SRC (no PROJJSON); con V2 el SRC queda en el archivo."""
    target = tmp_path / "con_src.parquet"
    sql = "SELECT ST_SetCRS('POINT(1 2)'::GEOMETRY, 'EPSG:32719') AS g"
    report = export(worker, sql, target, ExportFormat.PARQUET)
    assert report.rows == 1 and report.warnings == ()
    schema = run_sql(
        worker,
        f"SELECT logical_type FROM parquet_schema({quote_string_literal(str(target))}) WHERE name = 'g'",
    ).rows
    assert "EPSG:32719" in str(schema[0][0])


def test_a_failure_leaves_the_previous_file_untouched_and_no_partial(worker, tmp_path):
    target = tmp_path / "previo.csv"
    target.write_text("lo de antes\n")
    with pytest.raises(GeoDuckError):
        export(worker, "SELECT * FROM no_existe", target, ExportFormat.CSV)
    with pytest.raises(GeoDuckError):  # falla a mitad de la escritura
        export(
            worker,
            "SELECT CASE WHEN range > 500000 THEN error('roto') END FROM range(1000000)",
            target,
            ExportFormat.CSV,
        )
    assert target.read_text() == "lo de antes\n" and leftovers(tmp_path) == []


def test_cancel_stops_the_copy_and_leaves_no_partial(worker, tmp_path):
    target = tmp_path / "grande.parquet"
    target.write_bytes(b"previo")
    slow = "SELECT a.range * b.range AS n FROM range(20000) a, range(20000) b"
    handle = worker.export_query(ExportRequest(slow, str(target), ExportFormat.PARQUET))
    threading.Thread(target=lambda: (time.sleep(0.5), worker.cancel(handle.op_id))).start()
    with pytest.raises(OperationCancelledError):
        handle.future.result(TIMEOUT)
    assert target.read_bytes() == b"previo" and leftovers(tmp_path) == []
    assert run_sql(worker, "SELECT 42").rows == ((42,),)  # la sesión sigue utilizable


def test_export_runs_in_the_base_of_the_result_and_keeps_the_base_in_use(worker, tmp_path):
    otra = tmp_path / "otra.duckdb"
    run_sql(worker, f"ATTACH {quote_string_literal(str(otra))} AS otra")
    run_sql(worker, "CREATE TABLE otra.t AS SELECT 7 AS n")
    target = tmp_path / "t.csv"
    assert export(worker, "SELECT n FROM t", target, ExportFormat.CSV, database="otra").rows == 1
    assert target.read_text().splitlines() == ["n", "7"]
    assert run_sql(worker, "SELECT current_database()").rows == (("memory",),)


def test_the_cell_script_is_not_repeated(worker, tmp_path):
    """Solo la consulta de lectura del resultado se repite: el resto de la celda (DML) no."""
    run = worker.run_script(
        run_id=1, text="CREATE TABLE c(x INT); INSERT INTO c VALUES (1); SELECT x FROM c", scope=RunScope.ALL
    ).future.result(TIMEOUT)
    select = run.results[-1].statement
    export(worker, select.text, tmp_path / "c.csv", ExportFormat.CSV)
    assert run_sql(worker, "SELECT count(*) FROM c").rows == ((1,),)  # el INSERT no se repitió
