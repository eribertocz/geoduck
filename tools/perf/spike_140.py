# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike #140: ¿cómo sacar los bucles de Python de la conversión QGIS ↔ DuckDB? (performance-spec §2).

    QT_QPA_PLATFORM=offscreen python tools/perf/spike_140.py [--rows 1000000] [--repeat 3]

Mide, con la misma capa de puntos (id entero, valor real, nombre texto, SRC EPSG:32719), cada forma de pasar
los datos. Solo la conversión: sin diálogo ni coordinador, para comparar los caminos entre sí.

QGIS → DuckDB
- `bucle`: lo que hace hoy el camino general (`LayerReader`): recorrer entidades en Python, atributos y WKB,
  lotes Arrow de 10 000 filas, `CREATE TABLE … AS SELECT` desde el lote.
- `bucle+`: el mismo bucle, pidiendo solo las columnas y con conversión por columna.
- `escritor→parquet`: `QgsVectorFileWriter` (C++) a un GeoParquet temporal y `read_parquet`.
- `escritor→arrow`: `QgsVectorFileWriter` a Arrow IPC temporal y PyArrow → DuckDB.
- `escritor→fgb`: `QgsVectorFileWriter` a FlatGeobuf temporal y `ST_Read` (necesita `spatial`).

DuckDB → QGIS (Copia en memoria)
- `bucle`: lo de hoy (`MemoryLoad`): lotes Arrow → `QgsFeature` uno por uno → `addFeatures`.
- `parquet→materialize`: `COPY … TO parquet` y `materialize()` de QGIS (C++) a una capa en memoria.
- `fgb→materialize`: lo mismo con FlatGeobuf (`spatial`).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import duckdb
import pyarrow as pa
from qgis.core import (
    QgsApplication,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

BATCH = 10_000


def make_layer(n: int) -> QgsVectorLayer:
    layer = QgsVectorLayer("Point?crs=EPSG:32719", "puntos", "memory")
    provider = layer.dataProvider()
    provider.addAttributes(
        [
            QgsField("id", QVariant.LongLong),
            QgsField("valor", QVariant.Double),
            QgsField("nombre", QVariant.String),
        ]
    )
    layer.updateFields()
    fields = layer.fields()
    feats = []
    for i in range(n):
        f = QgsFeature(fields)
        f.setAttributes([i, i * 0.5, f"p{i % 1000}"])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500000 + i % 1000, 8000000 + i // 1000)))
        feats.append(f)
        if len(feats) == 50_000:
            provider.addFeatures(feats)
            feats = []
    provider.addFeatures(feats)
    return layer


def to_duckdb_loop(layer: QgsVectorLayer, con: duckdb.DuckDBPyConnection, *, lean: bool) -> None:
    con.execute("DROP TABLE IF EXISTS t")
    request = QgsFeatureRequest()
    if lean:
        request.setSubsetOfAttributes([0, 1, 2])
    first = True

    def flush(ids: list, vals: list, names: list, wkbs: list) -> None:
        nonlocal first
        batch = pa.record_batch(
            {
                "id": pa.array(ids, pa.int64()),
                "valor": pa.array(vals, pa.float64()),
                "nombre": pa.array(names, pa.string()),
                "geom": pa.array(wkbs, pa.binary()),
            }
        )
        con.register("lote", batch)
        sql = "SELECT id, valor, nombre, ST_GeomFromWKB(geom) AS geom FROM lote"
        con.execute(f"CREATE TABLE t AS {sql}" if first else f"INSERT INTO t {sql}")
        con.unregister("lote")
        first = False

    ids: list = []
    vals: list = []
    names: list = []
    wkbs: list = []
    if lean:
        for f in layer.getFeatures(request):
            a = f.attributes()
            ids.append(a[0])
            vals.append(a[1])
            names.append(a[2])
            wkbs.append(bytes(f.geometry().asWkb()))
            if len(ids) == BATCH:
                flush(ids, vals, names, wkbs)
                ids, vals, names, wkbs = [], [], [], []
    else:
        from geoduck.qgis_bridge.importer import _value  # el convertidor de hoy, valor por valor

        for f in layer.getFeatures(request):
            a = f.attributes()
            row = [_value(a[k]) for k in (0, 1, 2)]
            ids.append(row[0])
            vals.append(row[1])
            names.append(row[2])
            g = f.geometry()
            wkbs.append(None if g.isNull() else bytes(g.asWkb()))
            if len(ids) == BATCH:
                flush(ids, vals, names, wkbs)
                ids, vals, names, wkbs = [], [], [], []
    if ids:
        flush(ids, vals, names, wkbs)


def write_file(layer: QgsVectorLayer, path: str, driver: str) -> None:
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    if driver == "Parquet":
        options.layerOptions = ["GEOMETRY_ENCODING=WKB"]
    error = QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, QgsCoordinateTransformContext(), options)
    if error[0] != QgsVectorFileWriter.WriterError.NoError:
        raise RuntimeError(f"{driver}: {error}")


def to_duckdb_file(layer: QgsVectorLayer, con: duckdb.DuckDBPyConnection, kind: str, folder: str) -> dict:
    con.execute("DROP TABLE IF EXISTS t")
    path = os.path.join(folder, f"capa.{kind}")
    t0 = time.perf_counter()
    write_file(layer, path, {"parquet": "Parquet", "arrow": "Arrow", "fgb": "FlatGeobuf"}[kind])
    t1 = time.perf_counter()
    if kind == "parquet":
        con.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet('{path}')")
    elif kind == "arrow":
        import pyarrow.dataset as ds

        con.register("archivo", ds.dataset(path, format="arrow"))
        con.execute("CREATE TABLE t AS SELECT * FROM archivo")
        con.unregister("archivo")
    else:
        con.execute(f"CREATE TABLE t AS SELECT * FROM ST_Read('{path}')")
    t2 = time.perf_counter()
    os.remove(path)
    return {"escribir": t1 - t0, "leer": t2 - t1}


def to_qgis_loop(con: duckdb.DuckDBPyConnection) -> QgsVectorLayer:
    from geoduck.qgis_bridge.convert import geometry_from_wkb

    layer = QgsVectorLayer("Point?crs=EPSG:32719", "copia", "memory")
    provider = layer.dataProvider()
    provider.addAttributes(
        [
            QgsField("id", QVariant.LongLong),
            QgsField("valor", QVariant.Double),
            QgsField("nombre", QVariant.String),
        ]
    )
    layer.updateFields()
    fields = layer.fields()
    reader = con.execute("SELECT id, valor, nombre, ST_AsWKB(geom) AS geom FROM t").to_arrow_reader(BATCH)
    for batch in reader:
        cols = [batch.column(i).to_pylist() for i in range(3)]
        wkbs = batch.column(3).to_pylist()
        feats = []
        for i in range(batch.num_rows):
            f = QgsFeature(fields)
            f.setAttributes([c[i] for c in cols])
            f.setGeometry(geometry_from_wkb(wkbs[i]))
            feats.append(f)
        provider.addFeatures(feats)
    return layer


def to_qgis_file(con: duckdb.DuckDBPyConnection, kind: str, folder: str) -> dict:
    path = os.path.join(folder, f"copia.{kind}")
    t0 = time.perf_counter()
    if kind == "parquet":
        con.execute(f"COPY t TO '{path}' (FORMAT parquet)")
    else:
        con.execute(f"COPY t TO '{path}' (FORMAT gdal, DRIVER 'FlatGeobuf', SRS 'EPSG:32719')")
    t1 = time.perf_counter()
    source = QgsVectorLayer(path, "archivo", "ogr")
    assert source.isValid(), path
    memory = source.materialize(QgsFeatureRequest())
    t2 = time.perf_counter()
    assert memory.featureCount() == source.featureCount()
    del memory, source
    os.remove(path)
    return {"escribir": t1 - t0, "materialize": t2 - t1}


def timed(fn, repeat: int) -> tuple[float, list]:
    out = []
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        out.append(fn())
        times.append(time.perf_counter() - t0)
    return statistics.median(times), out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    app = QgsApplication([], False)
    app.initQgis()
    con = duckdb.connect()
    con.execute("LOAD spatial")
    con.execute("SET geometry_always_xy = true")
    folder = tempfile.mkdtemp(prefix="geoduck-spike140-")
    t0 = time.perf_counter()
    layer = make_layer(args.rows)
    print(f"capa de {args.rows:,} puntos en {time.perf_counter() - t0:.1f} s", flush=True)
    results: dict = {"rows": args.rows, "duckdb": duckdb.__version__}
    for name, fn in (
        ("q→d bucle", lambda: to_duckdb_loop(layer, con, lean=False)),
        ("q→d bucle+", lambda: to_duckdb_loop(layer, con, lean=True)),
        ("q→d escritor→parquet", lambda: to_duckdb_file(layer, con, "parquet", folder)),
        ("q→d escritor→arrow", lambda: to_duckdb_file(layer, con, "arrow", folder)),
        ("q→d escritor→fgb", lambda: to_duckdb_file(layer, con, "fgb", folder)),
    ):
        median, parts = timed(fn, args.repeat)
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == args.rows
        results[name] = {"s": round(median, 3), "partes": parts[-1]}
        print(f"{name:28s} {median:7.2f} s  {parts[-1] or ''}", flush=True)
    for name, fn in (
        ("d→q bucle", lambda: to_qgis_loop(con).featureCount()),
        ("d→q parquet→materialize", lambda: to_qgis_file(con, "parquet", folder)),
        ("d→q fgb→materialize", lambda: to_qgis_file(con, "fgb", folder)),
    ):
        median, parts = timed(fn, args.repeat)
        results[name] = {"s": round(median, 3), "partes": parts[-1] if isinstance(parts[-1], dict) else None}
        print(f"{name:28s} {median:7.2f} s  {parts[-1] if isinstance(parts[-1], dict) else ''}", flush=True)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"spike140-{duckdb.__version__}.json").write_text(json.dumps(results, indent=2))
    app.exitQgis()


if __name__ == "__main__":
    main()
