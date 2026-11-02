# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G3-A: comparación de rutas DuckDB → QGIS (no es código del complemento).

Rutas comparadas (`--route`):
  memory        DuckDB → Arrow → listas de Python → QgsFeature → capa «memory» de QGIS.
                La mejor variante medida en transfer_bench.py: hilo principal, tramos de 1024 filas,
                fechas desde int64 (fromMSecsSinceEpoch).
  arrow-vsimem  DuckDB → GeoArrow (lotes Arrow) → archivo Arrow IPC en /vsimem/ (memoria de GDAL, sin
                disco) → proveedor OGR de QGIS. La conversión de tipos, geometría y CRS la hace GDAL.
  arrow-disk    Igual que arrow-vsimem, pero el archivo IPC va a un directorio temporal en disco.
  gpkg-vsimem   DuckDB → GeoArrow → OGRLayer.WriteArrow (C++) en un GeoPackage en /vsimem/ →
                proveedor OGR. Capa editable.

Para cada ruta se verifica, en un proceso nuevo:
  - tiempo total, tiempo del hilo principal y bloqueo máximo;
  - RAM: pico de RSS y RSS residente tras la carga (lo que la capa retiene);
  - integridad: número de filas y huella de cada fila (atributos + WKB) contra DuckDB;
  - CRS reconocido por QGIS y tipos de campo;
  - cancelación a mitad de la carga: ninguna capa en el proyecto, nada en /vsimem, sesión usable;
  - persistencia: la capa se lee completa e igual tras DETACH de la base, cierre de la conexión
    y borrado del archivo .duckdb.

Uso: python transfer_compare.py run --route arrow-vsimem --rows 100000
     python transfer_compare.py matrix --out resultado.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROUTES = ("memory", "arrow-vsimem", "arrow-disk", "gpkg-vsimem")

# Tabla con atributos habituales, NULL, texto no ASCII y una geometría con CRS (OGC:CRS84 es el único
# CRS que DuckDB 2.0 acepta sin la extensión spatial; con spatial cargada vale cualquier EPSG).
CREATE = (
    "CREATE TABLE src.datos AS SELECT range AS id, 'nombre ñ ' || range AS nombre, "
    "CASE WHEN range % 97 = 0 THEN NULL ELSE range * 0.5 END AS valor, "
    "TIMESTAMP '2026-01-01' + to_seconds(range) AS instante, range % 2 = 0 AS activo, "
    "('POINT(' || (range % 1000) * 0.01 || ' ' || (range // 1000) * 0.01 || ')')::GEOMETRY('OGC:CRS84') "
    "AS geom "
    "FROM range({rows})"
)
QUERY = "SELECT * FROM src.datos ORDER BY id"
BATCH = 8192
CHUNK = 1024


def _rss_now_mb() -> float:
    with open("/proc/self/statm", encoding="ascii") as fh:
        return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def _rss_peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _fingerprint_duckdb(con) -> tuple[int, str]:
    """Huella de referencia, calculada en Python sobre los mismos valores que entrega DuckDB."""
    h = hashlib.sha256()
    n = 0
    for b in con.sql(QUERY).to_arrow_reader(BATCH):
        cols = [c.to_pylist() for c in b.columns]
        for row in zip(*cols, strict=True):
            h.update(_row_key(row[0], row[1], row[2], row[3], row[4], bytes(row[5])))
            n += 1
    return n, h.hexdigest()


def _row_key(  # noqa: PLR0917 - una fila, en orden de columnas
    fid, nombre, valor, instante, activo, wkb: bytes
) -> bytes:
    stamp = "" if instante is None else instante.strftime("%Y-%m-%dT%H:%M:%S")
    val = "" if valor is None else repr(float(valor))
    return f"{fid}|{nombre}|{val}|{stamp}|{bool(activo)}|".encode() + wkb + b"\n"


def _fingerprint_layer(layer) -> tuple[int, str, float]:
    from qgis.core import QgsFeatureRequest

    started = time.perf_counter()
    idx = [layer.fields().indexOf(n) for n in ("id", "nombre", "valor", "instante", "activo")]
    rows = []
    for f in layer.getFeatures(QgsFeatureRequest()):
        a = f.attributes()
        vals = [a[i] for i in idx]
        dt = vals[3]
        stamp = (
            ""
            if dt is None or (hasattr(dt, "isNull") and dt.isNull())
            else dt.toString("yyyy-MM-ddTHH:mm:ss")
        )
        valor = vals[2]
        if valor is None or (hasattr(valor, "isNull") and valor.isNull()):
            valor = None
        g = f.geometry()
        rows.append((int(vals[0]), str(vals[1]), valor, stamp, bool(vals[4]), bytes(g.asWkb())))
    rows.sort(key=lambda r: r[0])  # el orden de lectura del proveedor no está garantizado
    h = hashlib.sha256()
    for fid, nombre, valor, stamp, activo, wkb in rows:
        val = "" if valor is None else repr(float(valor))
        h.update(f"{fid}|{nombre}|{val}|{stamp}|{activo}|".encode() + wkb + b"\n")
    return len(rows), h.hexdigest(), round(time.perf_counter() - started, 3)


def _use_metrics(layer) -> dict:
    """Coste de usar la capa ya cargada: recorrer geometrías y dibujar el mapa completo."""
    from qgis.core import QgsFeatureRequest, QgsMapRendererSequentialJob, QgsMapSettings
    from qgis.PyQt.QtCore import QSize

    t0 = time.perf_counter()
    n = sum(1 for _ in layer.getFeatures(QgsFeatureRequest().setNoAttributes()))
    geom_s = time.perf_counter() - t0
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(layer.crs())
    settings.setExtent(layer.extent())
    settings.setOutputSize(QSize(800, 600))
    renders = []
    for _ in range(2):  # el segundo dibujado muestra el efecto de cachés del proveedor
        job = QgsMapRendererSequentialJob(settings)
        t0 = time.perf_counter()
        job.start()
        job.waitForFinished()
        renders.append(round(time.perf_counter() - t0, 3))
    return {"iterate_geom_s": round(geom_s, 3), "iterate_geom_rows": n, "render_s": renders}


# ---------------------------------------------------------------- rutas


class Cancelled(Exception):  # noqa: N818 - no es un error: lo pide el usuario
    pass


def _drain_in_worker(write_batches, cancel_after: int | None):
    """Ejecuta la escritura en otro hilo; el principal atiende eventos. Devuelve (filas, error)."""
    from qgis.PyQt.QtCore import QCoreApplication

    state: dict = {"rows": 0, "error": None}
    cancel = threading.Event()

    def should_stop(rows_done: int) -> bool:
        if cancel_after is not None and rows_done >= cancel_after:
            cancel.set()
        return cancel.is_set()

    def target():
        try:
            write_batches(should_stop, state)
        except Exception as exc:
            state["error"] = exc

    worker = threading.Thread(target=target)
    worker.start()
    max_gap = 0.0
    last = time.perf_counter()
    while worker.is_alive():
        QCoreApplication.processEvents()
        worker.join(0.01)
        now = time.perf_counter()
        max_gap = max(max_gap, now - last)
        last = now
    return state, max_gap


class _VsiSink:
    """gdal.VSIFile.write solo acepta bytes/bytearray/memoryview; pyarrow le pasa pyarrow.Buffer."""

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


def route_arrow(reader, path: str, cancel_after: int | None, *, vsimem: bool):
    import pyarrow as pa
    from osgeo import gdal

    def write(should_stop, state):
        sink = _VsiSink(gdal.VSIFile(path, "wb")) if vsimem else open(path, "wb")  # noqa: SIM115
        try:
            with pa.ipc.new_file(sink, reader.schema) as writer:
                for b in reader:
                    writer.write_batch(b)
                    state["rows"] += b.num_rows
                    if should_stop(state["rows"]):
                        raise Cancelled
        finally:
            sink.close()

    return _drain_in_worker(write, cancel_after)


def route_gpkg(reader, path: str, cancel_after: int | None):
    import pyarrow as pa
    from osgeo import ogr, osr

    schema = reader.schema
    geom_field = next(f for f in schema if (f.metadata or {}).get(b"ARROW:extension:name") == b"geoarrow.wkb")
    meta = json.loads(geom_field.metadata.get(b"ARROW:extension:metadata", b"{}") or b"{}")
    srs = None
    if meta.get("crs"):
        srs = osr.SpatialReference()
        srs.SetFromUserInput(json.dumps(meta["crs"]) if isinstance(meta["crs"], dict) else meta["crs"])
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    def write(should_stop, state):
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
        lyr = ds.CreateLayer(
            "datos", srs, ogr.wkbUnknown, ["GEOMETRY_NAME=" + geom_field.name, "SPATIAL_INDEX=NO"]
        )
        # GPKG no admite DECIMAL con precisión > 19 (DuckDB da decimal128(21,1) para range * 0.5):
        # esos campos se crean como Real y la columna se convierte con pyarrow.compute (C++).
        wide = {f.name for f in schema if pa.types.is_decimal(f.type) and f.type.precision > 18}
        for f in schema:
            if f.name == geom_field.name:
                continue
            if f.name in wide:
                lyr.CreateField(ogr.FieldDefn(f.name, ogr.OFTReal))
            else:
                lyr.CreateFieldFromPyArrowSchema(f)
        ds.StartTransaction()
        try:
            for raw in reader:
                b = raw
                for name in wide:
                    i = b.schema.get_field_index(name)
                    b = b.set_column(
                        i, b.schema.field(i).with_type(pa.float64()), b.column(i).cast(pa.float64())
                    )
                lyr.WritePyArrow(
                    b, options=["GEOMETRY_NAME=" + geom_field.name, "FID=", "IF_FID_NOT_PRESERVED=NOTHING"]
                )
                state["rows"] += b.num_rows
                if should_stop(state["rows"]):
                    raise Cancelled
            ds.CommitTransaction()
        except BaseException:
            ds.RollbackTransaction()
            raise
        finally:
            ds = None

    return _drain_in_worker(write, cancel_after)


def route_memory(reader, cancel_after: int | None):
    import pyarrow as pa
    from qgis.core import QgsFeature, QgsField, QgsFields, QgsGeometry, QgsVectorLayer
    from qgis.PyQt.QtCore import QCoreApplication, QDateTime, QMetaType, Qt

    schema = reader.schema
    kinds = {
        "int64": QMetaType.Type.LongLong,
        "string": QMetaType.Type.QString,
        "double": QMetaType.Type.Double,
        "bool": QMetaType.Type.Bool,
        "timestamp[us]": QMetaType.Type.QDateTime,
    }
    geom_i = next(
        i for i, f in enumerate(schema) if (f.metadata or {}).get(b"ARROW:extension:name") == b"geoarrow.wkb"
    )
    attr_i = [i for i in range(len(schema)) if i != geom_i]
    fields = QgsFields()
    for i in attr_i:
        fields.append(QgsField(schema[i].name, kinds.get(str(schema[i].type), QMetaType.Type.QString)))
    layer = QgsVectorLayer("Point?crs=OGC:CRS84", "datos", "memory")  # CRS: lo tendría que traducir GeoDuck
    provider = layer.dataProvider()
    provider.addAttributes(list(fields))
    layer.updateFields()
    temporal = {i for i in attr_i if str(schema[i].type).startswith("timestamp")}
    state = {"rows": 0, "error": None}
    max_block = 0.0
    try:
        for b in reader:
            for o in range(0, b.num_rows, CHUNK):
                t0 = time.perf_counter()
                piece = b.slice(o, CHUNK)
                cols = {}
                for i in attr_i:
                    if i in temporal:
                        us = piece.column(i).cast(pa.int64()).to_pylist()
                        cols[i] = [
                            None if v is None else QDateTime.fromMSecsSinceEpoch(v // 1000, Qt.TimeSpec.UTC)
                            for v in us
                        ]
                    else:
                        cols[i] = piece.column(i).to_pylist()
                wkbs = piece.column(geom_i).to_pylist()
                feats = []
                for r in range(piece.num_rows):
                    f = QgsFeature(fields)
                    f.setAttributes([cols[i][r] for i in attr_i])
                    g = QgsGeometry()
                    g.fromWkb(wkbs[r])
                    f.setGeometry(g)
                    feats.append(f)
                ok, _ = provider.addFeatures(feats)
                if not ok:
                    raise RuntimeError(provider.lastError())
                state["rows"] += piece.num_rows
                max_block = max(max_block, time.perf_counter() - t0)
                QCoreApplication.processEvents()
                if cancel_after is not None and state["rows"] >= cancel_after:
                    raise Cancelled
    except Exception as exc:
        state["error"] = exc
        layer = None
    return state, max_block, layer


# ---------------------------------------------------------------- escenario


def run(route: str, rows: int, cancel: bool) -> dict:  # noqa: PLR0915 - un escenario medido de principio a fin
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import duckdb
    from osgeo import gdal
    from qgis.core import Qgis, QgsApplication, QgsProject, QgsVectorLayer

    app = QgsApplication([], False)
    app.initQgis()
    work = tempfile.mkdtemp(prefix="geoduck-cmp-")
    db = os.path.join(work, "fuente.duckdb")
    con = duckdb.connect()
    con.execute(f"ATTACH '{db}' AS src")
    con.execute(CREATE.format(rows=rows))
    ref_rows, ref_hash = _fingerprint_duckdb(con)
    out: dict = {
        "route": route,
        "rows": rows,
        "cancel": cancel,
        "qgis": Qgis.version(),
        "gdal": gdal.__version__,
        "duckdb": duckdb.__version__,
        "drivers": {d: gdal.GetDriverByName(d) is not None for d in ("Arrow", "GPKG")},
    }
    cancel_after = rows // 2 if cancel else None
    base_rss = _rss_now_mb()
    started = time.perf_counter()
    reader = con.sql(QUERY).to_arrow_reader(BATCH)
    path = ""
    layer = None
    if route == "memory":
        state, block, layer = route_memory(reader, cancel_after)
    else:
        if route == "arrow-vsimem":
            path = f"/vsimem/geoduck/{os.getpid()}/datos.arrow"
            state, block = route_arrow(reader, path, cancel_after, vsimem=True)
        elif route == "arrow-disk":
            path = os.path.join(work, "datos.arrow")
            state, block = route_arrow(reader, path, cancel_after, vsimem=False)
        else:
            path = f"/vsimem/geoduck/{os.getpid()}/datos.gpkg"
            state, block = route_gpkg(reader, path, cancel_after)
        if state["error"] is None:
            t0 = time.perf_counter()
            layer = QgsVectorLayer(path, "datos", "ogr")
            block = max(block, time.perf_counter() - t0)
    reader.close()
    out["max_main_block_ms"] = round(block * 1000, 1)

    if state["error"] is not None:  # cancelación (o fallo): no queda nada
        if path.startswith("/vsimem/"):
            gdal.Unlink(path)
        elif path and os.path.exists(path):
            os.remove(path)
        leftover = path.startswith("/vsimem/") and gdal.VSIStatL(path) is not None
        if not isinstance(state["error"], Cancelled):
            import traceback

            traceback.print_exception(state["error"])
        out.update(
            seconds=round(time.perf_counter() - started, 3),
            cancelled=isinstance(state["error"], Cancelled),
            error="" if isinstance(state["error"], Cancelled) else repr(state["error"]),
            rows_before_cancel=state["rows"],
            project_layers=len(QgsProject.instance().mapLayers()),
            leftover_file=leftover or (bool(path) and os.path.exists(path)),
            session_usable=con.execute("SELECT 42").fetchone()[0] == 42,
        )
        con.close()
        shutil.rmtree(work, ignore_errors=True)
        app.exitQgis()
        return out

    if not layer.isValid():
        raise RuntimeError(f"capa no válida: {path}")
    QgsProject.instance().addMapLayer(layer)  # publicación (atómica: la capa ya está completa)
    out["seconds"] = round(time.perf_counter() - started, 3)
    out["rows_per_s"] = int(rows / out["seconds"])
    out["peak_rss_growth_mb"] = round(_rss_peak_mb() - base_rss, 1)
    out["resident_after_load_mb"] = round(_rss_now_mb() - base_rss, 1)
    out["vsimem_mb"] = round(gdal.VSIStatL(path).size / 2**20, 1) if path.startswith("/vsimem/") else 0
    out["crs"] = layer.crs().authid() if layer.crs().isValid() else ""
    out["fields"] = {f.name(): f.typeName() for f in layer.fields()}
    caps = layer.dataProvider().capabilities()
    from qgis.core import QgsVectorDataProvider as P

    out["editable"] = bool(caps & P.Capability.AddFeatures) and bool(
        caps & P.Capability.ChangeAttributeValues
    )
    out.update(_use_metrics(layer))
    n, h, it = _fingerprint_layer(layer)
    out.update(layer_rows=n, integrity=(n == ref_rows and h == ref_hash), iterate_s=it)

    # Persistencia: DETACH, cierre de la conexión y borrado del archivo de origen.
    con.execute("DETACH src")
    con.close()
    os.remove(db)
    n2, h2, _ = _fingerprint_layer(layer)
    out["survives_detach_close"] = n2 == ref_rows and h2 == ref_hash
    QgsProject.instance().removeAllMapLayers()
    if path.startswith("/vsimem/"):
        gdal.Unlink(path)
    shutil.rmtree(work, ignore_errors=True)
    app.exitQgis()
    return out


def matrix(out_path: str, rows_list: list[int]) -> None:
    results = []
    for rows in rows_list:
        for route in ROUTES:
            for cancel in (False, True):
                if cancel and rows != rows_list[0]:
                    continue  # la cancelación se comprueba con un solo volumen
                cmd = [sys.executable, __file__, "run", "--route", route, "--rows", str(rows)]
                if cancel:
                    cmd.append("--cancel")
                done = subprocess.run(cmd, capture_output=True, text=True, check=False)
                lines = done.stdout.strip().splitlines()
                try:
                    result = json.loads(lines[-1])
                except (IndexError, json.JSONDecodeError):
                    result = {
                        "route": route,
                        "rows": rows,
                        "cancel": cancel,
                        "error": done.stderr.strip().splitlines()[-3:],
                    }
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--route", choices=ROUTES, required=True)
    r.add_argument("--rows", type=int, required=True)
    r.add_argument("--cancel", action="store_true")
    m = sub.add_parser("matrix")
    m.add_argument("--out", required=True)
    m.add_argument("--rows", type=int, nargs="+", default=[100_000, 1_000_000])
    args = ap.parse_args()
    if args.cmd == "run":
        print(json.dumps(run(args.route, args.rows, args.cancel), ensure_ascii=False))
    else:
        matrix(args.out, args.rows)


if __name__ == "__main__":
    main()
