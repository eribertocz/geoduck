# SPDX-License-Identifier: GPL-2.0-or-later
"""Archivos → DuckDB contra DuckDB real (qgis-import-spec §10): el paso 1 lee solo metadatos y la copia la
hace DuckDB, nunca QGIS. Parquet, CSV, JSON y Arrow, sin `spatial`; los de GDAL, con `spatial` si está
instalada en el entorno de pruebas (GeoDuck nunca la instala sin permiso: spatial-spec §10)."""

from __future__ import annotations

import zipfile

import duckdb
import pyarrow as pa
import pytest
from pyarrow import feather

from geoduck.domain.channel import BatchChannel
from geoduck.domain.files import file_job
from geoduck.domain.importing import ImportMode
from geoduck.engine.files import NEEDS_SPATIAL
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 60


def _spatial_available() -> bool:
    try:
        con = duckdb.connect()
        con.execute("LOAD spatial")
        con.close()
    except duckdb.Error:
        return False
    return True


needs_spatial = pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def sql(worker, text, max_rows=1000):
    return [
        tuple(r)
        for r in worker.submit(lambda h, t: h.execute(text, max_rows=max_rows)).future.result(TIMEOUT).rows
    ]


def import_all(worker, items, **kw):
    jobs = [
        file_job(
            it, table=f"t{i}", mode=ImportMode.CREATE, database="memory", schema="main", temporary=False, **kw
        )
        for i, it in enumerate(items)
    ]
    channel: BatchChannel = BatchChannel(capacity=2)
    channel.finish()
    return worker.import_batches(jobs, channel).future.result(TIMEOUT)


@pytest.fixture
def plain(tmp_path):
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT i AS id, 'n' || i AS name FROM range(7) r(i)")
    con.execute(f"COPY t TO '{tmp_path / 'a.parquet'}' (FORMAT parquet)")
    con.execute(f"COPY t TO '{tmp_path / 'a.csv'}' (FORMAT csv, HEADER)")
    con.execute(f"COPY t TO '{tmp_path / 'a.json'}' (FORMAT json)")
    con.close()
    feather.write_feather(pa.table({"id": list(range(5)), "name": list("abcde")}), str(tmp_path / "a.arrow"))
    return tmp_path


def test_plain_files_are_read_by_duckdb_without_spatial(worker, plain):
    names = ["a.parquet", "a.csv", "a.json", "a.arrow"]
    items = worker.scan_files([str(plain / n) for n in names]).result(TIMEOUT)
    assert [(i.format, i.problem) for i in items] == [
        ("parquet", None),
        ("csv", None),
        ("json", None),
        ("arrow", None),
    ]
    assert [i.rows for i in items] == [7, -1, -1, 5]  # CSV y JSON no se cuentan en el paso 1
    report = import_all(worker, items)
    assert [t.rows for t in report.tables] == [7, 7, 7, 5]
    assert sql(worker, "SELECT name FROM t3 ORDER BY id LIMIT 1") == [("a",)]
    # GeoDuck no cargó `spatial` para esto
    assert sql(worker, "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'") in (
        [],
        [(False,)],
    )


def test_a_file_that_cannot_be_read_comes_back_with_its_reason(worker, tmp_path):
    bad = tmp_path / "roto.parquet"
    bad.write_text("no es parquet")
    (item,) = worker.scan_files([str(bad)]).result(TIMEOUT)
    assert item.problem


def test_gdal_files_need_spatial_and_geoduck_does_not_load_it(worker, tmp_path):
    path = tmp_path / "capa.gpkg"
    path.write_bytes(b"")
    (item,) = worker.scan_files([str(path)]).result(TIMEOUT)
    assert item.problem == NEEDS_SPATIAL
    assert sql(worker, "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'") in (
        [],
        [(False,)],
    )


@needs_spatial
def test_gdal_files_with_spatial_keep_layers_geometry_and_crs(worker, tmp_path):
    con = duckdb.connect()
    con.execute("LOAD spatial")
    con.execute("CREATE TABLE p AS SELECT i AS id, ST_Point(i, i) AS geom FROM range(4) r(i)")
    con.execute("CREATE TABLE z AS SELECT 1 AS id, ST_GeomFromText('POLYGON((0 0,1 0,1 1,0 0))') AS geom")
    con.execute(f"COPY p TO '{tmp_path / 'pozos.fgb'}' (FORMAT gdal, DRIVER 'FlatGeobuf')")
    con.execute(f"COPY p TO '{tmp_path / 'p.shp'}' (FORMAT gdal, DRIVER 'ESRI Shapefile')")
    con.execute(f"COPY z TO '{tmp_path / 'z.geojson'}' (FORMAT gdal, DRIVER 'GeoJSON')")
    con.close()
    with zipfile.ZipFile(tmp_path / "p.zip", "w") as archive:
        for ext in ("shp", "shx", "dbf"):
            archive.write(tmp_path / f"p.{ext}", f"p.{ext}")
    sql(worker, "LOAD spatial")  # como si el usuario lo hubiera aceptado
    paths = [str(tmp_path / n) for n in ("pozos.fgb", "p.zip", "z.geojson")]
    items = worker.scan_files(paths).result(TIMEOUT)
    assert [(i.problem, i.geometry_column is not None) for i in items] == [(None, True)] * 3
    assert [i.geometry_type for i in items] == ["Point", "Point", "Polygon"]
    assert items[1].gdal_source.startswith("/vsizip/")
    report = import_all(worker, items)
    assert [t.rows for t in report.tables] == [4, 4, 1]
    kinds = sql(
        worker,
        "SELECT data_type FROM information_schema.columns WHERE table_name = 't2' AND column_name = 'geom'",
    )
    assert kinds[0][0].startswith("GEOMETRY")
