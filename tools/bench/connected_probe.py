# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G3-A: lectura bajo demanda y fidelidad de tipos (no es código del complemento).

Subcomandos:

  types    Fidelidad de tipos DuckDB → Arrow → GDAL (driver Arrow) → QGIS, uno por uno, frente a la
           tabla de conversión de qgis-bridge-spec §7. Incluye una segunda geometría.

  ondemand Lectura bajo demanda sin materializar, con 1 y 5 millones de puntos:
             - geoparquet: DuckDB escribe GeoParquet 1.0 (COPY … TO) y QGIS lo lee con el proveedor OGR.
             - adbc: QGIS lee la base .duckdb con el proveedor OGR y el driver ADBC de GDAL (≥ 3.11),
               que delega en DuckDB los filtros espaciales y de atributos. Necesita la extensión spatial
               y una biblioteca libduckdb con `duckdb_adbc_init` (--libduckdb).
           Mide apertura, conteo, filtro por extensión (≈1 % del área), filtro de atributo, recorrido,
           dibujado completo y con zoom.

Uso: python connected_probe.py types
     python connected_probe.py ondemand --libduckdb /ruta/libduckdb.so [--rows 1000000 5000000]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time

TYPES = {
    "b": "true",
    "ti": "127::TINYINT",
    "i": "2147483647::INTEGER",
    "bi": "9223372036854775807::BIGINT",
    "ubi": "18446744073709551615::UBIGINT",
    "hi": "170141183460469231731687303715884105727::HUGEINT",
    "f": "1.5::FLOAT",
    "d_nan": "'NaN'::DOUBLE",
    "d_inf": "'inf'::DOUBLE",
    "dec_9_2": "1234567.89::DECIMAL(9,2)",
    "dec_18_3": "123456789012345.678::DECIMAL(18,3)",
    "dec_38_10": "1234567890123456789012345678.0123456789::DECIMAL(38,10)",
    "vc": "'ñandú 🦆'",
    "en": "'b'::ENUM('a','b')",
    "uu": "'550e8400-e29b-41d4-a716-446655440000'::UUID",
    "dt": "DATE '2026-11-01'",
    "ts": "TIMESTAMP '2026-11-01 12:34:56.789123'",
    "tstz": "TIMESTAMPTZ '2026-11-01 12:34:56+02'",
    "tm": "TIME '12:34:56'",
    "iv": "INTERVAL 3 DAY",
    "bl": "'\\xAA\\xBB'::BLOB",
    "li": "[1,2,3]",
    "st": "{'x': 1, 'y': 'z'}",
    "mp": "MAP {'k': 1}",
    "nul": "NULL::INTEGER",
    "geom": "'POINT(1 2)'::GEOMETRY('OGC:CRS84')",
    "geom2": "'POINT(3 4)'::GEOMETRY",
}


class _VsiSink:
    def __init__(self, f) -> None:
        self._f = f
        self.closed = False

    def write(self, data) -> int:
        view = memoryview(data)
        self._f.write(view)
        return view.nbytes

    def tell(self) -> int:
        return self._f.tell()

    def flush(self) -> None:
        pass

    def close(self) -> None:
        if not self.closed:
            self._f.close()
            self.closed = True


def _qgis():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication

    app = QgsApplication([], False)
    app.initQgis()
    return app


def types() -> dict:
    app = _qgis()
    import duckdb
    import pyarrow as pa
    from osgeo import gdal
    from qgis.core import Qgis, QgsVectorLayer

    gdal.UseExceptions()
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    sql = "SELECT " + ", ".join(f"{v} AS {k}" for k, v in TYPES.items())
    reader = con.sql(sql).to_arrow_reader(10)
    schema = reader.schema
    path = "/vsimem/geoduck-types.arrow"
    sink = _VsiSink(gdal.VSIFile(path, "wb"))
    with pa.ipc.new_file(sink, schema) as writer:
        for b in reader:
            writer.write_batch(b)
    sink.close()
    duck = dict(zip(TYPES, con.execute(sql).fetchone(), strict=True))
    layer = QgsVectorLayer(path, "tipos", "ogr")
    feature = next(layer.getFeatures())
    rows = []
    for name, expr in TYPES.items():
        idx = layer.fields().indexOf(name)
        entry = {
            "columna": name,
            "duckdb": expr.split("::")[-1] if "::" in expr else "",
            "arrow": str(schema.field(name).type),
            "valor_duckdb": repr(duck[name])[:60],
        }
        if idx < 0:
            entry.update(qgis="(no es campo)", valor_qgis="")
        else:
            value = feature.attribute(idx)
            entry.update(qgis=layer.fields()[idx].typeName(), valor_qgis=repr(value)[:60])
        rows.append(entry)
    second = QgsVectorLayer(path + "|geometryname=geom2", "g2", "ogr")
    out = {
        "qgis": Qgis.version(),
        "gdal": gdal.__version__,
        "duckdb": duckdb.__version__,
        "geometria": {
            "tipo": layer.wkbType(),
            "crs": layer.crs().authid(),
            "wkt": feature.geometry().asWkt(),
        },
        "segunda_geometria_accesible": second.isValid(),
        "campos": rows,
    }
    del layer, second, feature
    gdal.Unlink(path)
    con.close()
    app.exitQgis()
    return out


def _measure(layer, small) -> dict:
    from qgis.core import QgsFeatureRequest, QgsMapRendererSequentialJob, QgsMapSettings, QgsRectangle
    from qgis.PyQt.QtCore import QSize

    def timed(fn):
        t0 = time.perf_counter()
        value = fn()
        return value, round(time.perf_counter() - t0, 3)

    res: dict = {}
    res["n"], res["count_s"] = timed(layer.featureCount)
    rect = QgsRectangle(*small)
    res["bbox_rows"], res["bbox_s"] = timed(
        lambda: sum(1 for _ in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)))
    )
    res["attr_rows"], res["attr_s"] = timed(
        lambda: sum(1 for _ in layer.getFeatures(QgsFeatureRequest().setFilterExpression('"id" < 500')))
    )
    res["scan_rows"], res["scan_s"] = timed(
        lambda: sum(1 for _ in layer.getFeatures(QgsFeatureRequest().setNoAttributes()))
    )
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(layer.crs())
    settings.setOutputSize(QSize(800, 600))
    for label, extent in (("render_full_s", layer.extent()), ("render_zoom_s", rect)):
        settings.setExtent(extent)
        job = QgsMapRendererSequentialJob(settings)
        _, res[label] = timed(lambda job=job: (job.start(), job.waitForFinished()))
    res["crs"] = layer.crs().authid()
    res["fields"] = [f.name() for f in layer.fields()]
    caps = layer.dataProvider().capabilities()
    res["editable"] = bool(caps & layer.dataProvider().Capability.AddFeatures)
    return res


def ondemand(libduckdb: str, rows_list: list[int]) -> list[dict]:  # noqa: PLR0915 - un escenario medido entero
    app = _qgis()
    import duckdb
    from osgeo import gdal
    from qgis.core import Qgis, QgsVectorLayer

    gdal.UseExceptions()
    results = []
    for rows in rows_list:
        work = tempfile.mkdtemp(prefix="geoduck-ondemand-")
        db = os.path.join(work, "fuente.duckdb")
        con = duckdb.connect(db)
        spatial = True
        try:
            con.execute("LOAD spatial")
        except duckdb.Error:
            spatial = False
        side = int(rows**0.5)
        con.execute(
            "CREATE TABLE puntos AS SELECT range AS id, 'n' || range AS nombre, "
            f"('POINT(' || (range % {side}) * 0.01 || ' ' || (range // {side}) * 0.01 || ')')"
            f"::GEOMETRY('OGC:CRS84') AS geom FROM range({rows})"
        )
        if spatial:
            t0 = time.perf_counter()
            con.execute("CREATE INDEX puntos_rtree ON puntos USING RTREE (geom)")
            rtree_s = round(time.perf_counter() - t0, 3)
        else:
            rtree_s = None
        span = side * 0.01
        small = (span * 0.45, span * 0.45, span * 0.55, span * 0.55)  # 1 % del área
        base = {
            "rows": rows,
            "qgis": Qgis.version(),
            "gdal": gdal.__version__,
            "duckdb": duckdb.__version__,
            "spatial": spatial,
            "rtree_s": rtree_s,
        }

        parquet = os.path.join(work, "puntos.parquet")
        t0 = time.perf_counter()
        con.execute(
            f"COPY puntos TO '{parquet}' (FORMAT parquet, GEOPARQUET_VERSION 'V1', ROW_GROUP_SIZE 65536)"
        )
        write_s = round(time.perf_counter() - t0, 3)
        con.close()  # el lector bajo demanda trabaja sin la sesión
        t0 = time.perf_counter()
        layer = QgsVectorLayer(parquet, "gp", "ogr")
        open_s = round(time.perf_counter() - t0, 3)
        entry = dict(
            base,
            route="geoparquet",
            write_s=write_s,
            open_s=open_s,
            valid=layer.isValid(),
            file_mb=round(os.path.getsize(parquet) / 2**20, 1),
        )
        if layer.isValid():
            entry.update(_measure(layer, small))
        results.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        del layer

        if spatial and libduckdb:
            uri = (
                f"ADBC:{db}|option:ADBC_DRIVER={libduckdb}|option:PRELUDE_STATEMENTS=LOAD spatial"
                "|option:SQL=SELECT id, nombre, geom FROM puntos"
            )
            listing = gdal.OpenEx(
                f"ADBC:{db}",
                gdal.OF_VECTOR,
                open_options=[f"ADBC_DRIVER={libduckdb}", "PRELUDE_STATEMENTS=LOAD spatial"],
            )
            tables = [listing.GetLayer(i).GetName() for i in range(listing.GetLayerCount())]
            listing = None
            t0 = time.perf_counter()
            layer = QgsVectorLayer(uri, "adbc", "ogr")
            open_s = round(time.perf_counter() - t0, 3)
            entry = dict(base, route="adbc-sql", open_s=open_s, valid=layer.isValid(), tables_listed=tables)
            if layer.isValid():
                entry.update(_measure(layer, small))
            results.append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            del layer
        shutil.rmtree(work, ignore_errors=True)
    app.exitQgis()
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("types")
    t.add_argument("--out")
    o = sub.add_parser("ondemand")
    o.add_argument("--libduckdb", default="")
    o.add_argument("--rows", type=int, nargs="+", default=[1_000_000, 5_000_000])
    o.add_argument("--out")
    args = ap.parse_args()
    result = types() if args.cmd == "types" else ondemand(args.libduckdb, args.rows)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
