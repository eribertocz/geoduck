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


@pytest.mark.parametrize("fmt", [ExportFormat.CSV, ExportFormat.PARQUET])
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


# -- G9: más formatos, siempre con el motor de DuckDB (qgis-import-spec §10) -----------------------------


def test_json_and_arrow_need_nothing_installed(worker, tmp_path):
    from pyarrow import feather

    sql = "SELECT 1 AS id, ST_SetCRS('POINT(1 2)'::GEOMETRY, 'EPSG:4326') AS g"
    export(worker, sql, tmp_path / "a.ndjson", ExportFormat.JSON)
    assert (tmp_path / "a.ndjson").read_text().strip() == '{"id":1,"g":"POINT (1 2)"}'
    report = export(worker, sql, tmp_path / "a.arrow", ExportFormat.ARROW)
    table = feather.read_table(str(tmp_path / "a.arrow"))
    assert report.rows == 1 and table.num_rows == 1
    assert table.schema.field("g").metadata[b"ARROW:extension:name"] == b"geoarrow.wkb"
    assert leftovers(tmp_path) == []
    assert run_sql(
        worker, "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'"
    ).rows in (
        (),
        ((False,),),
    )


def test_a_gdal_format_without_permission_does_not_load_spatial(worker, tmp_path):
    with pytest.raises(GeoDuckError, match="spatial"):
        export(worker, "SELECT 1 AS id", tmp_path / "a.gpkg", ExportFormat.GPKG)
    assert not (tmp_path / "a.gpkg").exists() and leftovers(tmp_path) == []


def _spatial_available():
    import duckdb

    try:
        duckdb.connect().execute("LOAD spatial")
    except duckdb.Error:
        return False
    return True


GEO = (
    "SELECT range AS id, ST_SetCRS(('POINT(' || range || ' 1)')::GEOMETRY, 'EPSG:32719') AS geom "
    "FROM range(50)"
)


@pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")
@pytest.mark.parametrize("fmt", [f for f in ExportFormat if f.needs_spatial])
def test_gdal_formats_keep_rows_and_crs_and_set_the_axis_order(worker, tmp_path, fmt):
    target = tmp_path / f"pozos{fmt.suffix}"
    request = ExportRequest(GEO, str(target), fmt, None, allow_spatial=True)
    report = worker.export_query(request).future.result(TIMEOUT)
    assert report.rows == 50 and target.exists()
    assert leftovers(tmp_path) == []
    # #193: con `spatial`, longitud y latitud
    rows = run_sql(worker, "SELECT value FROM duckdb_settings() WHERE name = 'geometry_always_xy'").rows
    assert rows == (("true",),)
    source = quote_string_literal(str(target))
    back = run_sql(worker, f"SELECT count(*) FROM ST_Read({source})").rows
    assert back == ((50,),)
    if fmt in (ExportFormat.GPKG, ExportFormat.FGB, ExportFormat.GDB, ExportFormat.SHP):
        kinds = run_sql(worker, f"DESCRIBE SELECT * FROM ST_Read({source})").rows
        assert any("EPSG:32719" in str(k[1]) for k in kinds), kinds


@pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")
def test_a_shapefile_keeps_accents_with_its_cpg(worker, tmp_path):
    """#141: el Shapefile lleva su `.cpg` en UTF-8: «ñandú» vuelve igual."""
    target = tmp_path / "pozos.shp"
    sql = "SELECT 'ñandú áé' AS región, ST_SetCRS(ST_Point(1, 2), 'EPSG:32719') AS geom"
    request = ExportRequest(sql, str(target), ExportFormat.SHP, None, allow_spatial=True)
    worker.export_query(request).future.result(TIMEOUT)
    assert (tmp_path / "pozos.cpg").read_text().strip() == "UTF-8"
    source = quote_string_literal(str(target))
    assert run_sql(worker, f"SELECT región FROM ST_Read({source})").rows == (("ñandú áé",),)


@pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")
def test_an_axis_setting_chosen_by_the_user_is_not_touched(worker, tmp_path):
    run_sql(worker, "LOAD spatial")
    run_sql(worker, "SET geometry_always_xy = true")
    request = ExportRequest(GEO, str(tmp_path / "a.gpkg"), ExportFormat.GPKG, None, allow_spatial=True)
    worker.export_query(request).future.result(TIMEOUT)
    rows = run_sql(worker, "SELECT value FROM duckdb_settings() WHERE name = 'geometry_always_xy'").rows
    assert rows == (("true",),)


# -- G10 E2: cancelar una exportación al instante (performance-spec §3) --


def test_order_by_is_detected_outside_comments_and_strings():
    from geoduck.engine.export import has_order_by

    assert has_order_by("SELECT * FROM t ORDER BY x")
    assert has_order_by("select * from t\norder\n  by x desc")
    assert not has_order_by("SELECT 'order by' AS s FROM t -- order by x")
    assert not has_order_by("SELECT * FROM t /* ORDER BY x */")


def order_setting(worker):
    rows = run_sql(worker, "SELECT value FROM duckdb_settings() WHERE name = 'preserve_insertion_order'").rows
    return str(rows[0][0]).lower()


def test_insertion_order_is_off_only_during_the_export_and_order_by_is_kept(worker, tmp_path):
    import duckdb

    report = export(
        worker, "SELECT range AS n FROM range(200000)", tmp_path / "a.parquet", ExportFormat.PARQUET
    )
    assert report.rows == 200000 and order_setting(worker) == "true"  # como estaba
    export(
        worker,
        "SELECT range AS n FROM range(200000) ORDER BY n DESC",
        tmp_path / "b.parquet",
        ExportFormat.PARQUET,
    )
    con = duckdb.connect()
    first = con.execute(f"SELECT n FROM '{tmp_path / 'b.parquet'}' LIMIT 3").fetchall()
    assert first == [(199999,), (199998,), (199997,)]  # el ORDER BY del usuario se respeta
    assert order_setting(worker) == "true"


def test_an_order_setting_chosen_by_the_user_is_not_touched(worker, tmp_path):
    run_sql(worker, "SET preserve_insertion_order = false")
    export(worker, "SELECT 1 AS n", tmp_path / "a.csv", ExportFormat.CSV)
    assert order_setting(worker) == "false"


def test_cancelling_an_export_stops_quickly_and_leaves_nothing(worker, tmp_path):
    import time

    from geoduck.domain.errors import OperationCancelledError

    run_sql(worker, "CREATE TABLE big AS SELECT range AS id, 'obs ' || range AS nota FROM range(1000000)")
    request = ExportRequest(
        # 200 millones de filas: en ningún equipo termina antes de cancelar (se cancela a los 0,3 s)
        "SELECT a.* FROM big a, range(200)",
        str(tmp_path / "x.parquet"),
        ExportFormat.PARQUET,
        None,
    )
    handle = worker.export_query(request)
    time.sleep(0.3)
    begin = time.perf_counter()
    worker.cancel_current()
    with pytest.raises((OperationCancelledError, GeoDuckError)):
        handle.future.result(TIMEOUT)
    assert time.perf_counter() - begin < 1.0  # meta p95 ≤ 1 s; medido 14–77 ms
    assert not (tmp_path / "x.parquet").exists() and leftovers(tmp_path) == []
    assert order_setting(worker) == "true"
