# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G8-A (QGIS): camino general QGIS → Arrow → DuckDB, lectura en otro hilo y SRC personalizado.

Uso: QT_QPA_PLATFORM=offscreen python g8a_qgis.py DIR   (con el Python de QGIS, duckdb y pyarrow)
Mide con datos sintéticos (puntos y polígonos con 4 atributos), sin `spatial`.
"""
import math
import sys
import threading
import time
from pathlib import Path

import duckdb
import pyarrow as pa
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerFeatureSource,
)
from qgis.PyQt.QtCore import QDate, QVariant

app = QgsApplication([], False)
app.initQgis()
out = Path(sys.argv[1])
print("QGIS", Qgis.version(), "· DuckDB", duckdb.__version__, "· PyArrow", pa.__version__)
BATCH = 50_000


def make_layer(kind, n):
    """GeoPackage sintético: id, nombre, valor, fecha y geometría."""
    path = out / f"{kind}_{n}.gpkg"
    if path.exists():
        path.unlink()
    fields = QgsFields()
    fields.append(QgsField("id", QVariant.LongLong))
    fields.append(QgsField("nombre", QVariant.String))
    fields.append(QgsField("valor", QVariant.Double))
    fields.append(QgsField("alta", QVariant.Date))
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    wkb = Qgis.WkbType.Point if kind == "puntos" else Qgis.WkbType.Polygon
    w = QgsVectorFileWriter.create(str(path), fields, wkb, QgsCoordinateReferenceSystem("EPSG:4326"),
                                   QgsCoordinateTransformContext(), opts)
    feats = []
    for i in range(n):
        f = QgsFeature(fields)
        f.setAttributes([i, f"N{i}", i * 0.5, QDate(2025, 1 + i % 12, 1)])
        x, y = -68 + (i % 1000) / 1000, -16 - (i // 1000) / 1000
        if kind == "puntos":
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        else:
            ring = [QgsPointXY(x + 0.0004 * math.cos(a / 20 * 2 * math.pi), y + 0.0004 * math.sin(a / 20 * 2 * math.pi))
                    for a in range(21)]
            f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
        feats.append(f)
        if len(feats) == 50_000:
            w.addFeatures(feats)
            feats = []
    w.addFeatures(feats)
    del w
    return QgsVectorLayer(f"{path}|layername={kind}_{n}", kind, "ogr")


def send(layer, con, table):
    """Lee en un hilo aparte y envía por lotes Arrow; devuelve tiempos (leer+armar, insertar)."""
    source = QgsVectorLayerFeatureSource(layer)
    names = ["id", "nombre", "valor", "alta"]
    idx = {n: layer.fields().indexOf(n) for n in names}
    # Sin `spatial`, declarar GEOMETRY('EPSG:4326') en CREATE TABLE falla; con CREATE TABLE AS + ST_SetCRS, no.
    con.execute(f"DROP TABLE IF EXISTS {table}")
    times = {"leer": 0.0, "insertar": 0.0, "filas": 0}
    errors = []

    def run():
        try:
            cols = {n: [] for n in names}
            geoms = []
            t0 = time.perf_counter()

            def flush():
                t1 = time.perf_counter()
                tbl = pa.table({
                    "id": pa.array(cols["id"], pa.int64()),
                    "nombre": pa.array(cols["nombre"], pa.string()),
                    "valor": pa.array(cols["valor"], pa.float64()),
                    "alta": pa.array(cols["alta"], pa.date32()),
                    "wkb": pa.array(geoms, pa.binary()),
                })
                t2 = time.perf_counter()
                con.register("lote", tbl)
                select = "SELECT id, nombre, valor, alta, ST_SetCRS(ST_GeomFromWKB(wkb), 'EPSG:4326') AS geom FROM lote"
                if not times["filas"]:
                    con.execute(f"CREATE TABLE {table} AS {select}")
                else:
                    con.execute(f"INSERT INTO {table} {select}")
                con.unregister("lote")
                t3 = time.perf_counter()
                times["leer"] += (t2 - t0) if not times["filas"] else (t2 - t1) + pending[0]
                times["insertar"] += t3 - t2
                times["filas"] += len(geoms)
                for v in cols.values():
                    v.clear()
                geoms.clear()

            pending = [0.0]
            tr = time.perf_counter()
            for f in source.getFeatures():
                a = f.attributes()  # el GeoPackage añade «fid» delante
                cols["id"].append(a[idx["id"]])
                cols["nombre"].append(a[idx["nombre"]])
                cols["valor"].append(a[idx["valor"]])
                d = a[idx["alta"]]
                cols["alta"].append(d.toPyDate() if d else None)
                g = f.geometry()
                geoms.append(bytes(g.asWkb()) if not g.isNull() else None)
                if len(geoms) == BATCH:
                    pending[0] = time.perf_counter() - tr
                    flush()
                    tr = time.perf_counter()
            pending[0] = time.perf_counter() - tr
            if geoms:
                flush()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    th = threading.Thread(target=run)
    th.start()
    th.join()
    if errors:
        raise errors[0]
    return times


con = duckdb.connect()
con.execute("SET autoload_known_extensions = false")
print("\n1. Camino general (GeoPackage → hilo → Arrow → DuckDB), lotes de", BATCH)
for kind, n in (("puntos", 100_000), ("puntos", 1_000_000), ("poligonos", 100_000)):
    layer = make_layer(kind, n)
    assert layer.isValid() and layer.featureCount() == n
    t0 = time.perf_counter()
    times = send(layer, con, "t")
    total = time.perf_counter() - t0
    count = con.execute("SELECT count(*), count(geom) FROM t").fetchone()
    crs = con.execute("SELECT data_type FROM duckdb_columns() WHERE table_name = 't' AND column_name = 'geom'").fetchone()[0]
    print(f"  {kind:9} {n:>9,}: total {total:6.1f} s · leer+armar {times['leer']:6.1f} s · insertar "
          f"{times['insertar']:5.1f} s · {n / total:9,.0f} ent/s · filas {count[0]:,} geom {count[1]:,} · {crs}")

print("\n2. Lectura en otro hilo por proveedor (QgsVectorLayerFeatureSource)")
csv = out / "puntos.csv"
csv.write_text("id,x,y\n" + "".join(f"{i},{-68 + i / 1e4},{-16.5}\n" for i in range(10_000)))
mem = QgsVectorLayer("Point?crs=EPSG:4326&field=id:integer", "m", "memory")
mem.dataProvider().addFeatures([QgsFeature() for _ in range(10_000)])
for label, lyr in (("ogr (GeoPackage)", make_layer("puntos", 10_000)),
                   ("memory", mem),
                   ("delimitedtext (CSV)", QgsVectorLayer(f"file://{csv}?delimiter=,&xField=x&yField=y&crs=EPSG:4326",
                                                         "csv", "delimitedtext"))):
    src = QgsVectorLayerFeatureSource(lyr)
    got = []
    th = threading.Thread(target=lambda: got.append(sum(1 for _ in src.getFeatures())))
    th.start()
    th.join()
    print(f"  {label:22} válida={lyr.isValid()} leídas en hilo: {got[0] if got else 'error'} de {lyr.featureCount()}")

print("\n3. SRC personalizado de QGIS hacia DuckDB")
crs = QgsCoordinateReferenceSystem.fromProj("+proj=tmerc +lat_0=0 +lon_0=-68 +k=1 +x_0=500000 +y_0=10000000 "
                                            "+datum=WGS84 +units=m +no_defs")
print("  authid:", repr(crs.authid()), "· isValid:", crs.isValid())
has_json = hasattr(crs, "toJsonString")
print("  toJsonString disponible:", has_json)
wkt2 = crs.toWkt(Qgis.CrsWktVariant.Wkt2_2019 if hasattr(Qgis, "CrsWktVariant") else QgsCoordinateReferenceSystem.WKT2_2019)
from osgeo import osr  # noqa: E402

srs = osr.SpatialReference()
srs.ImportFromWkt(wkt2)
projjson = crs.toJsonString() if has_json else srs.ExportToPROJJSON()
for label, text in (("WKT2", wkt2), ("PROJJSON (GDAL osr)" if not has_json else "PROJJSON", projjson)):
    if not text:
        print(f"  {label}: no disponible en esta versión de QGIS")
        continue
    lit = "'" + text.replace("'", "''") + "'"
    con.execute(f"CREATE OR REPLACE TABLE c AS SELECT ST_SetCRS(ST_GeomFromWKB(from_hex("
                f"'0101000000000000000000F03F0000000000000040')), {lit}) AS geom")
    tbl = con.sql("SELECT geom FROM c").arrow()
    tbl = tbl.read_all() if hasattr(tbl, "read_all") else tbl
    meta = tbl.schema.field(0).metadata.get(b"ARROW:extension:metadata", b"{}").decode()
    import json  # noqa: E402

    back = json.loads(meta).get("crs")
    back_crs = QgsCoordinateReferenceSystem()  # como GeoDuck al cargar (convert.crs_from_field)
    if back:
        back_crs.createFromUserInput(json.dumps(back) if isinstance(back, dict) else str(back))
    print(f"  {label}: DuckDB guarda {'SRC' if back else 'NADA'} · QGIS lo reconoce: {back_crs.isValid()} · "
          f"mismo SRC: {back_crs == crs}")
import os  # noqa: E402

sys.stdout.flush()
os._exit(0)  # sin exitQgis: el cierre del proveedor ogr falla en conda (ruido, no del envío)
