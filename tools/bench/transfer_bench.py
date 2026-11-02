# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G3-A: benchmark de transferencia DuckDB → Arrow → QGIS (roadmap §3; qgis-bridge-spec §4–§5).

No es código del complemento. Mide, por escenario y en un proceso nuevo (para que el pico de memoria sea
limpio): tiempo total, filas por segundo, pico de memoria residente (RSS), tiempo del hilo principal y su
bloqueo máximo por lote, y verifica que la capa tenga todas las filas.

Etapas que se pueden aislar (`--stage`):
  engine    solo DuckDB → lector Arrow (sin QGIS)
  pylist    + conversión de columnas Arrow a listas de Python
  qgis      + QgsFeature/QgsGeometry y addFeatures en una capa memory

Estrategias de reparto del trabajo para `qgis` (`--strategy`):
  main             el hilo principal convierte, construye las entidades y las añade
  worker-lists     el hilo del motor convierte a listas; el principal construye y añade
  worker-features  el hilo del motor construye las QgsFeature; el principal solo las añade
  arrow-file       el hilo del motor escribe los lotes en un archivo Arrow IPC temporal y el principal
                   lo abre con el proveedor OGR (GDAL ≥ 3.8 lee geoarrow.wkb y su CRS)

Opciones que solo afectan a `main`:
  --chunk N        trocea cada lote en tramos de N filas y atiende eventos entre tramos
  --temporal       qdatetime (QDateTime(datetime), por defecto) o msecs (int64 → fromMSecsSinceEpoch)

Uso (un escenario):   python transfer_bench.py run --dataset points --rows 100000 --batch 8192 \
                         --stage qgis --strategy main
Uso (matriz → JSON):  python transfer_bench.py matrix --out resultados.json [--quick]
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import resource
import subprocess
import sys
import threading
import time

DATASETS = {
    # Tabla plana con tipos habituales.
    "tabular": (
        "SELECT range AS id, 'nombre ' || range AS nombre, range * 0.5 AS valor, "
        "TIMESTAMP '2026-01-01' + to_seconds(range) AS instante, range % 2 = 0 AS activo "
        "FROM range({rows})"
    ),
    # Puntos: GEOMETRY sin la extensión spatial; se exporta como geoarrow.wkb (F-10).
    "points": (
        "SELECT range AS id, ('POINT(' || (range % 1000) || ' ' || (range // 1000) || ')')::GEOMETRY AS geom "
        "FROM range({rows})"
    ),
    # Polígonos pequeños de 5 vértices.
    "polygons": (
        "SELECT range AS id, ('POLYGON((' || (range % 1000) || ' ' || (range // 1000) || ', ' || "
        "(range % 1000 + 1) || ' ' || (range // 1000) || ', ' || (range % 1000 + 1) || ' ' || "
        "(range // 1000 + 1) || ', ' || (range % 1000) || ' ' || (range // 1000 + 1) || ', ' || "
        "(range % 1000) || ' ' || (range // 1000) || '))')::GEOMETRY AS geom FROM range({rows})"
    ),
}
GEOMETRY_TYPE = {"points": "Point", "polygons": "Polygon"}


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KiB


def run(  # noqa: PLR0917 - script de medición, argumentos posicionales a propósito
    dataset: str,
    rows: int,
    batch: int,
    stage: str,
    strategy: str,
    chunk: int = 0,
    temporal: str = "qdatetime",
) -> dict:
    import duckdb

    con = duckdb.connect()
    sql = DATASETS[dataset].format(rows=rows)
    app = _start_qgis() if stage == "qgis" else None  # el arranque de QGIS no se mide
    base_rss = _rss_mb()
    out: dict = {
        "dataset": dataset,
        "rows": rows,
        "batch": batch,
        "stage": stage,
        "strategy": strategy,
        "chunk": chunk,
        "temporal": temporal,
        "duckdb": duckdb.__version__,
    }
    started = time.perf_counter()
    reader = con.sql(sql).to_arrow_reader(batch)
    if stage == "engine":
        n = 0
        for b in reader:
            n += b.num_rows
        out.update(rows_read=n)
    elif stage == "pylist":
        n = 0
        for b in reader:
            cols = [c.to_pylist() for c in b.columns]
            n += len(cols[0])
        out.update(rows_read=n)
    else:
        if strategy == "arrow-file":
            out.update(_arrow_file(reader))
        else:
            out.update(_qgis(reader, dataset, strategy, chunk, temporal))
        app.exitQgis()
    out["seconds"] = round(time.perf_counter() - started, 3)
    out["rows_per_s"] = int(rows / out["seconds"]) if out["seconds"] else None
    out["peak_rss_mb"] = round(_rss_mb(), 1)
    out["rss_growth_mb"] = round(out["peak_rss_mb"] - base_rss, 1)
    return out


def _start_qgis():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication

    app = QgsApplication([], False)
    app.initQgis()
    return app


def _qgis(  # noqa: PLR0915 - un solo bucle medido, más claro sin trocear
    reader, dataset: str, strategy: str, chunk: int, temporal_mode: str
) -> dict:
    import pyarrow as pa
    from qgis.core import Qgis, QgsFeature, QgsField, QgsFields, QgsGeometry, QgsVectorLayer
    from qgis.PyQt.QtCore import QCoreApplication, QDateTime, QMetaType, Qt

    schema = reader.schema
    ext = b"ARROW:extension:name"
    geom_index = next(
        (i for i, f in enumerate(schema) if (f.metadata or {}).get(ext) == b"geoarrow.wkb"), None
    )
    kinds = {
        "int64": QMetaType.Type.LongLong,
        "string": QMetaType.Type.QString,
        "double": QMetaType.Type.Double,
        "bool": QMetaType.Type.Bool,
        "timestamp[us]": QMetaType.Type.QDateTime,
    }
    # DuckDB entrega `range * 0.5` como DECIMAL: QGIS 3.44 rechaza Decimal de Python y 4.2 lo guarda
    # como texto (F-45). La ruta propia tiene que convertirlo explícitamente a Double.
    decimals = {i for i in range(len(schema)) if pa.types.is_decimal(schema[i].type)}
    fields = QgsFields()
    attr_idx = [i for i in range(len(schema)) if i != geom_index]
    for i in attr_idx:
        kind = (
            QMetaType.Type.Double if i in decimals else kinds.get(str(schema[i].type), QMetaType.Type.QString)
        )
        fields.append(QgsField(schema[i].name, kind))
    uri = GEOMETRY_TYPE.get(dataset, "None")
    layer = QgsVectorLayer(uri, "bench", "memory")
    provider = layer.dataProvider()
    provider.addAttributes(list(fields))
    layer.updateFields()

    temporal = {i for i in range(len(schema)) if str(schema[i].type).startswith("timestamp")}

    def to_lists(batch):
        cols = [
            (batch.column(i).cast(pa.float64()) if i in decimals else batch.column(i)).to_pylist()
            for i in range(batch.num_columns)
        ]
        for i in temporal:  # QGIS no convierte datetime de Python por sí solo: hace falta QDateTime
            if temporal_mode == "msecs":  # timestamp[us] → int64 µs → ms; evita QDateTime(datetime) (F-43)
                us = batch.column(i).cast(pa.int64()).to_pylist()
                utc = Qt.TimeSpec.UTC
                cols[i] = [None if v is None else QDateTime.fromMSecsSinceEpoch(v // 1000, utc) for v in us]
            else:
                cols[i] = [None if v is None else QDateTime(v) for v in cols[i]]
        return cols

    def to_features(cols):
        n = len(cols[0])
        features = []
        attrs = [cols[i] for i in attr_idx]
        geoms = cols[geom_index] if geom_index is not None else None
        for r in range(n):
            f = QgsFeature(fields)
            f.setAttributes([c[r] for c in attrs])
            if geoms is not None and geoms[r] is not None:
                g = QgsGeometry()
                g.fromWkb(geoms[r])
                f.setGeometry(g)
            features.append(f)
        return features

    q: queue.Queue = queue.Queue(maxsize=2)  # backpressure: como mucho 2 lotes en vuelo
    done = object()

    stop = threading.Event()  # si el hilo principal falla, el productor no queda bloqueado en put()

    def put(item) -> None:
        while not stop.is_set():
            try:
                q.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def producer():
        try:
            for b in reader:
                if stop.is_set():
                    return
                if strategy == "main":
                    put(b)
                elif strategy == "worker-lists":
                    put(to_lists(b))
                else:
                    put(to_features(to_lists(b)))
        finally:
            put(done)

    worker = threading.Thread(target=producer, daemon=True)
    worker.start()
    main_busy = 0.0
    max_block = 0.0
    added = 0
    try:
        while True:
            item = q.get()
            if item is done:
                break
            if strategy == "main" and chunk:
                pieces = [item.slice(o, chunk) for o in range(0, item.num_rows, chunk)]
            else:
                pieces = [item]
            for piece in pieces:
                t0 = time.perf_counter()
                if strategy == "main":
                    features = to_features(to_lists(piece))
                elif strategy == "worker-lists":
                    features = to_features(piece)
                else:
                    features = piece
                ok, _ = provider.addFeatures(features)
                if not ok:
                    raise RuntimeError(f"addFeatures falló: {provider.lastError()}")
                added += len(features)
                spent = time.perf_counter() - t0
                main_busy += spent
                max_block = max(max_block, spent)
                QCoreApplication.processEvents()  # la interfaz atiende eventos entre lotes/tramos
    finally:
        stop.set()
    worker.join()
    count = layer.featureCount()
    return {
        "qgis": Qgis.version(),
        "rows_added": added,
        "layer_count": count,
        "main_thread_s": round(main_busy, 3),
        "max_main_block_ms": round(max_block * 1000, 1),
    }


def _arrow_file(reader) -> dict:
    import tempfile

    import pyarrow as pa
    from qgis.core import Qgis, QgsVectorLayer
    from qgis.PyQt.QtCore import QCoreApplication

    path = os.path.join(tempfile.mkdtemp(prefix="geoduck-bench-"), "lote.arrow")
    state = {"written": 0}

    def producer():  # hilo del motor: solo escribe, sin objetos de QGIS
        with pa.ipc.new_file(path, reader.schema) as writer:
            for b in reader:
                writer.write_batch(b)
                state["written"] += b.num_rows

    worker = threading.Thread(target=producer)
    worker.start()
    while worker.is_alive():  # el principal sigue atendiendo eventos mientras se escribe
        QCoreApplication.processEvents()
        worker.join(0.02)
    t0 = time.perf_counter()
    layer = QgsVectorLayer(path, "bench", "ogr")
    count = layer.featureCount()
    spent = time.perf_counter() - t0
    size_mb = round(os.path.getsize(path) / 2**20, 1)
    crs = layer.crs().authid() if layer.crs().isValid() else ""
    del layer
    os.remove(path)
    return {
        "qgis": Qgis.version(),
        "rows_added": state["written"],
        "layer_count": count,
        "main_thread_s": round(spent, 3),
        "max_main_block_ms": round(spent * 1000, 1),
        "file_mb": size_mb,
        "crs": crs,
    }


def matrix(out_path: str, quick: bool, python: str, engine_only: bool = False) -> None:
    rows_list = (10_000, 100_000) if quick else (10_000, 100_000, 1_000_000)
    scenarios = []
    for dataset in ("tabular", "points", "polygons"):
        for rows in rows_list:
            for stage in ("engine", "pylist"):
                scenarios.append((dataset, rows, 8192, stage, "-", 0, "qdatetime"))
            for strategy in ("main", "worker-lists", "worker-features", "arrow-file"):
                scenarios.append((dataset, rows, 8192, "qgis", strategy, 0, "qdatetime"))
            scenarios.append((dataset, rows, 8192, "qgis", "main", 1024, "qdatetime"))  # tramos pequeños
        scenarios.append((dataset, rows_list[-1], 8192, "qgis", "main", 0, "msecs"))  # alternativa temporal
    for batch in (2048, 8192, 16384, 65536):  # tamaño de lote, con 1 M de puntos
        scenarios.append(("points", rows_list[-1], batch, "qgis", "main", 0, "qdatetime"))
        scenarios.append(("points", rows_list[-1], batch, "engine", "-", 0, "qdatetime"))
    if engine_only:
        scenarios = [s for s in scenarios if s[3] != "qgis"]
    results = []
    for dataset, rows, batch, stage, strategy, chunk, temporal in scenarios:
        cmd = [
            python,
            __file__,
            "run",
            "--dataset",
            dataset,
            "--rows",
            str(rows),
            "--batch",
            str(batch),
            "--stage",
            stage,
            "--strategy",
            strategy,
            "--chunk",
            str(chunk),
            "--temporal",
            temporal,
        ]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=900)
        except subprocess.TimeoutExpired:
            done = subprocess.CompletedProcess(cmd, -1, "", "timeout: más de 900 s")
        line = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            result = {
                "dataset": dataset,
                "rows": rows,
                "batch": batch,
                "stage": stage,
                "strategy": strategy,
                "chunk": chunk,
                "temporal": temporal,
                "error": done.stderr.strip().splitlines()[-1:],
            }
        results.append(result)
        print(json.dumps(result), flush=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    r.add_argument("--rows", type=int, required=True)
    r.add_argument("--batch", type=int, default=8192)
    r.add_argument("--stage", choices=("engine", "pylist", "qgis"), default="qgis")
    r.add_argument(
        "--strategy", choices=("main", "worker-lists", "worker-features", "arrow-file", "-"), default="main"
    )
    r.add_argument("--chunk", type=int, default=0)
    r.add_argument("--temporal", choices=("qdatetime", "msecs"), default="qdatetime")
    m = sub.add_parser("matrix")
    m.add_argument("--out", required=True)
    m.add_argument("--quick", action="store_true")
    m.add_argument("--engine-only", action="store_true", help="solo etapas engine/pylist (sin QGIS)")
    args = ap.parse_args()
    if args.cmd == "run":
        print(
            json.dumps(
                run(args.dataset, args.rows, args.batch, args.stage, args.strategy, args.chunk, args.temporal)
            )
        )
    else:
        matrix(args.out, args.quick, sys.executable, args.engine_only)


if __name__ == "__main__":
    main()
