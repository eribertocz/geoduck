# SPDX-License-Identifier: GPL-2.0-or-later
# ruff: noqa: N802, N803, B008, B023 - firmas de la API de QGIS; las lambdas se ejecutan en el acto
"""Spike G3-B: prototipo de proveedor QGIS «geoduck» en PyQGIS, bajo demanda (no es código del complemento).

El proveedor no abre conexiones propias: cada petición de QGIS (dibujar, identificar, tabla de atributos)
se traduce a una consulta SQL y se ejecuta como una operación del `SessionWorker` real de GeoDuck
(`geoduck.engine.worker`). La conexión nunca sale de su hilo (ADR-0006). El iterador recibe lotes Arrow:

  fetch=stream  el lector queda abierto en el worker y entrega lotes por una cola acotada (2 lotes);
                el worker queda ocupado hasta que el iterador termina o se cierra.
  fetch=table   el worker lee el resultado entero de la petición y queda libre; el iterador lo recorre.

Pushdown:
  - extensión: `st_intersects_extent(geom, <rect>)` (núcleo de DuckDB ≥ 1.5, sin `spatial`) o, con
    `pushdown=spatial`, `ST_Intersects(geom, ST_MakeEnvelope(…))`, que usa un índice RTree si existe;
  - FID: `<key> IN (…)`; atributos pedidos: solo esas columnas; sin geometría: no se lee `geom`;
  - expresiones: comparaciones simples `"campo" op literal` (y AND de ellas) se traducen a SQL; el resto
    se evalúa en Python (no hay `QgsSqlExpressionCompiler` en PyQGIS);
  - `LIMIT`.

URI: `session=<id>|table=<catálogo.esquema.tabla>|geom=<columna>|key=<columna>|fetch=stream|pushdown=core`

Uso: python pyprovider_probe.py bench --rows 1000000 5000000 --out resultado.json
     python pyprovider_probe.py behaviour --out comportamiento.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import resource
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

SESSIONS: dict[str, object] = {}  # id de sesión → SessionWorker (en el complemento: el coordinador)
STATS = {"queries": 0, "sql": []}
_DONE = object()


def _rss_peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _rss_now_mb() -> float:
    with open("/proc/self/statm", encoding="ascii") as fh:
        return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def build_provider():
    from qgis.core import (
        Qgis,
        QgsAbstractFeatureIterator,
        QgsAbstractFeatureSource,
        QgsCoordinateReferenceSystem,
        QgsCsException,
        QgsDataProvider,
        QgsExpression,
        QgsExpressionContext,
        QgsExpressionContextUtils,
        QgsExpressionNodeBinaryOperator,
        QgsExpressionNodeColumnRef,
        QgsExpressionNodeLiteral,
        QgsFeature,
        QgsFeatureIterator,
        QgsFeatureRequest,
        QgsField,
        QgsFields,
        QgsGeometry,
        QgsRectangle,
        QgsVectorDataProvider,
        QgsWkbTypes,
    )
    from qgis.PyQt.QtCore import QMetaType

    from geoduck.engine.worker import ReadOutcome

    ops = {
        QgsExpressionNodeBinaryOperator.BinaryOperator.boEQ: "=",
        QgsExpressionNodeBinaryOperator.BinaryOperator.boNE: "<>",
        QgsExpressionNodeBinaryOperator.BinaryOperator.boLT: "<",
        QgsExpressionNodeBinaryOperator.BinaryOperator.boLE: "<=",
        QgsExpressionNodeBinaryOperator.BinaryOperator.boGT: ">",
        QgsExpressionNodeBinaryOperator.BinaryOperator.boGE: ">=",
    }

    def compile_expr(node, fields) -> str | None:
        """Traduce comparaciones simples y AND; None si no se puede (se evalúa en Python)."""
        if isinstance(node, QgsExpressionNodeBinaryOperator):
            op = node.op()
            if op == QgsExpressionNodeBinaryOperator.BinaryOperator.boAnd:
                left, right = compile_expr(node.opLeft(), fields), compile_expr(node.opRight(), fields)
                return f"({left}) AND ({right})" if left and right else None
            if op in ops and isinstance(node.opLeft(), QgsExpressionNodeColumnRef):
                lit = node.opRight()
                name = node.opLeft().name()
                if fields.indexOf(name) < 0 or not isinstance(lit, QgsExpressionNodeLiteral):
                    return None
                value = lit.value()
                if isinstance(value, bool) or value is None:
                    return None
                if isinstance(value, (int, float)):
                    return f"{_q(name)} {ops[op]} {value!r}"
                if isinstance(value, str):
                    return f"{_q(name)} {ops[op]} '" + value.replace("'", "''") + "'"
        return None

    kinds = {
        "BIGINT": QMetaType.Type.LongLong,
        "INTEGER": QMetaType.Type.Int,
        "DOUBLE": QMetaType.Type.Double,
        "VARCHAR": QMetaType.Type.QString,
        "BOOLEAN": QMetaType.Type.Bool,
    }

    class Source(QgsAbstractFeatureSource):
        def __init__(self, provider):
            super().__init__()
            self.p = provider

        def getFeatures(self, request=QgsFeatureRequest()):
            return QgsFeatureIterator(Iterator(self, request))

    class Iterator(QgsAbstractFeatureIterator):
        def __init__(self, source, request):
            super().__init__(request)
            self.s = source
            self.p = source.p
            self.r = QgsFeatureRequest(request)
            self.transform = self.r.calculateTransform(self.p.crs())
            self.local_expr = None
            self.started = False
            self.closed = False
            self.rows: list = []
            self.pos = 0
            self.q: queue.Queue = queue.Queue(maxsize=2)
            self.stop = threading.Event()
            self.handle = None
            self.batch_cols = None
            try:
                rect = self.filterRectToSourceCrs(self.transform)
            except QgsCsException:
                self.closed = True
                return
            self.sql = self._sql(rect)

        def _sql(self, rect) -> str:  # noqa: PLR0912 - una rama por tipo de filtro
            p, r = self.p, self.r
            flags = r.flags()
            no_geom = bool(flags & Qgis.FeatureRequestFlag.NoGeometry) and rect.isNull()
            if flags & Qgis.FeatureRequestFlag.SubsetOfAttributes:
                wanted = [
                    p._fields.at(i).name() for i in r.subsetOfAttributes() if 0 <= i < p._fields.count()
                ]
            else:
                wanted = [f.name() for f in p._fields]
            self.wanted = wanted
            cols = [_q(p.key)] + [_q(n) for n in wanted if n != p.key]
            self.with_geom = not no_geom
            if self.with_geom:
                cols.append(_q(p.geom))
            where = []
            if not rect.isNull():
                env = (
                    f"'POLYGON(({rect.xMinimum()} {rect.yMinimum()}, {rect.xMaximum()} {rect.yMinimum()}, "
                    f"{rect.xMaximum()} {rect.yMaximum()}, {rect.xMinimum()} {rect.yMaximum()}, "
                    f"{rect.xMinimum()} {rect.yMinimum()}))'::GEOMETRY"
                )
                if p.pushdown == "spatial":
                    where.append(
                        f"ST_Intersects({_q(p.geom)}, ST_MakeEnvelope({rect.xMinimum()}, "
                        f"{rect.yMinimum()}, {rect.xMaximum()}, {rect.yMaximum()}))"
                    )
                else:
                    where.append(f"st_intersects_extent({_q(p.geom)}, {env})")
            ft = r.filterType()
            if ft == Qgis.FeatureRequestFilterType.Fid:
                where.append(f"{_q(p.key)} = {int(r.filterFid())}")
            elif ft == Qgis.FeatureRequestFilterType.Fids:
                fids = sorted(int(x) for x in r.filterFids())
                where.append(f"{_q(p.key)} IN ({', '.join(map(str, fids)) or 'NULL'})")
            elif ft == Qgis.FeatureRequestFilterType.Expression:
                expr = r.filterExpression()
                compiled = compile_expr(expr.rootNode(), p._fields) if expr and expr.rootNode() else None
                if compiled:
                    where.append(compiled)
                else:
                    self.local_expr = QgsExpression(expr.expression())
                    ctx = QgsExpressionContext()
                    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(None))
                    self.ctx = ctx
                    self.local_expr.prepare(ctx)
            sql = f"SELECT {', '.join(cols)} FROM {p.table}"
            if where:
                sql += " WHERE " + " AND ".join(where)
            if r.limit() >= 0 and self.local_expr is None:
                sql += f" LIMIT {int(r.limit())}"
            return sql

        # --- comunicación con el worker de la sesión -----------------------------------------
        def _start(self):
            self.started = True
            worker = SESSIONS.get(self.p.session)
            STATS["queries"] += 1
            STATS["sql"].append(self.sql)
            if worker is None:
                self.closed = True
                return
            sql, q, stop, fetch = self.sql, self.q, self.stop, self.p.fetch

            def put(item) -> bool:
                while not stop.is_set():
                    try:
                        q.put(item, timeout=0.05)
                        return True
                    except queue.Full:
                        continue
                return False

            def op(handle, token):
                if fetch == "table":
                    batches: list = []
                    summary = handle.read_arrow(sql, batch_size=65536, on_batch=batches.append, token=token)
                    for b in batches:
                        if not put(b):
                            break
                    put(_DONE)
                    return summary
                with handle.arrow_batches(sql, batch_size=8192) as reader:
                    for b in reader:
                        if token.cancelled or not put(b):
                            break
                put(_DONE)
                return None

            try:
                self.handle = worker.submit(op)
            except Exception as exc:  # sesión cerrada o invalidada: la capa queda vacía, sin bloquear
                self.p.last_error = f"{type(exc).__name__}: {exc}"
                self.closed = True
                return

            def watch(fut, q=q):  # si la operación falla (p. ej. tras DETACH) el iterador no espera
                exc = fut.exception()
                if exc is not None:
                    self.p.last_error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
                    with contextlib.suppress(queue.Full):
                        q.put_nowait(_DONE)
                elif (
                    fut.result() is not None and getattr(fut.result(), "outcome", None) == ReadOutcome.FAILED
                ):
                    self.p.last_error = fut.result().error

            self.handle.future.add_done_callback(watch)

        def _next_batch(self) -> bool:
            item = self.q.get()
            if item is _DONE:
                return False
            names = item.schema.names
            cols = [item.column(i).to_pylist() for i in range(item.num_columns)]
            self.ids = cols[0]
            self.attr_cols = {n: cols[names.index(n)] for n in self.wanted if n in names}
            self.geoms = cols[-1] if self.with_geom else None
            self.n = item.num_rows
            self.pos = 0
            return True

        def fetchFeature(self, f):
            if self.closed:
                return False
            if not self.started:
                self._start()
                if self.closed:
                    return False
                self.n = self.pos = 0
            p = self.p
            while True:
                if self.pos >= self.n:
                    if not self._next_batch():
                        self.close()
                        return False
                    continue
                i = self.pos
                self.pos += 1
                f.setFields(p._fields, True)
                for name, col in self.attr_cols.items():
                    f.setAttribute(name, col[i])
                f.setId(self.ids[i])
                if self.geoms is not None and self.geoms[i] is not None:
                    g = QgsGeometry()
                    g.fromWkb(self.geoms[i])
                    f.setGeometry(g)
                    self.geometryToDestinationCrs(f, self.transform)
                else:
                    f.clearGeometry()
                f.setValid(True)
                if self.local_expr is not None:
                    self.ctx.setFeature(f)
                    if not self.local_expr.evaluate(self.ctx):
                        continue
                return True

        def rewind(self):
            if self.closed:
                return False
            self._abandon()
            self.started = False
            self.q = queue.Queue(maxsize=2)
            self.stop = threading.Event()
            return True

        def _abandon(self):
            self.stop.set()
            worker = SESSIONS.get(self.p.session)
            if self.handle is not None and worker is not None and not self.handle.future.done():
                worker.cancel(self.handle.op_id)

        def close(self):
            if not self.closed:
                self._abandon()
                self.closed = True
            return True

        def __iter__(self):
            return self

        def __next__(self):
            f = QgsFeature()
            if not self.nextFeature(f):
                raise StopIteration
            return f

    class Provider(QgsVectorDataProvider):
        @classmethod
        def providerKey(cls):
            return "geoduck"

        @classmethod
        def description(cls):
            return "GeoDuck (prototipo bajo demanda)"

        @classmethod
        def createProvider(cls, uri, options, flags=Qgis.DataProviderReadFlags()):
            return Provider(uri, options, flags)

        def __init__(
            self, uri="", options=QgsDataProvider.ProviderOptions(), flags=Qgis.DataProviderReadFlags()
        ):
            super().__init__(uri, options, flags)
            self._uri = uri
            parts = dict(x.split("=", 1) for x in uri.split("|") if "=" in x)
            self.session = parts.get("session", "")
            self.table = parts.get("table", "")
            self.geom = parts.get("geom", "geom")
            self.key = parts.get("key", "id")
            self.fetch = parts.get("fetch", "stream")
            self.pushdown = parts.get("pushdown", "core")
            self.last_error = ""
            self._valid = False
            self._fields = QgsFields()
            self._crs = QgsCoordinateReferenceSystem()
            self._extent = QgsRectangle()
            self._count = -1
            self._wkb = QgsWkbTypes.Type.Unknown if hasattr(QgsWkbTypes, "Type") else Qgis.WkbType.Unknown
            worker = SESSIONS.get(self.session)
            if worker is None:
                self.last_error = "sesión inexistente"
                return
            table, geom = self.table, self.geom

            def describe(handle, token):
                cols = handle.execute(f"DESCRIBE SELECT * FROM {table}", max_rows=1000).rows
                crs = handle.execute(f"SELECT ST_CRS({_q(geom)}) FROM {table} LIMIT 1").rows
                count = handle.execute(f"SELECT count(*) FROM {table}").rows[0][0]
                try:  # extensión: solo con la extensión spatial (el núcleo no tiene agregados de extensión)
                    ext = handle.execute(
                        f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
                        f"(SELECT ST_Extent_Agg({_q(geom)}) AS e FROM {table})"
                    ).rows[0]
                except Exception:
                    ext = None
                try:
                    gtype = handle.execute(
                        f"SELECT DISTINCT ST_GeometryType({_q(geom)}) FROM {table} LIMIT 2"
                    ).rows
                except Exception:
                    gtype = []
                return cols, crs, count, ext, gtype

            try:
                cols, crs, count, ext, gtype = worker.submit(describe).future.result()
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return
            for name, typ, *_ in cols:
                if name == geom:
                    continue
                self._fields.append(QgsField(name, kinds.get(str(typ).split("(")[0], QMetaType.Type.QString)))
            if crs and crs[0][0]:
                self._crs = QgsCoordinateReferenceSystem(str(crs[0][0]))
            if ext and None not in ext:
                self._extent = QgsRectangle(*ext)
            self._count = int(count)
            names = {str(g[0]).upper() for g in gtype}
            self._wkb = Qgis.WkbType.Point if names == {"POINT"} else Qgis.WkbType.Unknown
            self._valid = True

        def featureSource(self):
            return Source(self)

        def getFeatures(self, request=QgsFeatureRequest()):
            return QgsFeatureIterator(Iterator(Source(self), request))

        def fields(self):
            return self._fields

        def wkbType(self):
            return self._wkb

        def featureCount(self):
            return self._count

        def extent(self):
            return QgsRectangle(self._extent)

        def crs(self):
            return self._crs

        def isValid(self):
            return self._valid

        def capabilities(self):
            return Qgis.VectorProviderCapability.SelectAtId

        def dataSourceUri(self, expandAuthConfig=True):
            return self._uri

        def name(self):
            return self.providerKey()

        def storageType(self):
            return "DuckDB (sesión GeoDuck)"

        def reloadData(self):
            pass

    return Provider


# ------------------------------------------------------------------ pruebas


def _setup(rows_list):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication, QgsProviderMetadata, QgsProviderRegistry

    app = QgsApplication([], False)
    app.initQgis()
    provider = build_provider()
    meta = QgsProviderMetadata(provider.providerKey(), provider.description(), provider.createProvider)
    QgsProviderRegistry.instance().registerProvider(meta)
    from geoduck.engine.worker import SessionWorker

    worker = SessionWorker(":memory:")
    worker.start().result()
    SESSIONS["s1"] = worker
    work = tempfile.mkdtemp(prefix="geoduck-pyprov-")

    def run(sql):
        return worker.submit(lambda h, t: h.execute(sql, max_rows=10)).future.result()

    run("LOAD spatial")
    for rows in rows_list:
        side = int(rows**0.5)
        run(f"ATTACH '{work}/d{rows}.duckdb' AS d{rows}")
        run(
            f"CREATE TABLE d{rows}.puntos AS SELECT range AS id, 'n' || range AS nombre, "
            "range * 0.5 AS valor, "
            f"ST_Point((range % {side}) * 0.01, (range // {side}) * 0.01)::GEOMETRY('OGC:CRS84') AS geom "
            f"FROM range({rows})"
        )
        run(f"CREATE INDEX rt ON d{rows}.puntos USING RTREE (geom)")
    return app, worker, run, work


def _timed(fn):
    t0 = time.perf_counter()
    v = fn()
    return v, round(time.perf_counter() - t0, 3)


def _render(layer, extent, parallel=False):
    from qgis.core import QgsMapRendererParallelJob, QgsMapRendererSequentialJob, QgsMapSettings
    from qgis.PyQt.QtCore import QSize

    s = QgsMapSettings()
    s.setLayers(layer if isinstance(layer, list) else [layer])
    first = layer[0] if isinstance(layer, list) else layer
    s.setDestinationCrs(first.crs())
    s.setExtent(extent)
    s.setOutputSize(QSize(800, 600))
    job = (QgsMapRendererParallelJob if parallel else QgsMapRendererSequentialJob)(s)
    t0 = time.perf_counter()
    job.start()
    job.waitForFinished()
    return round(time.perf_counter() - t0, 3), [e.message for e in job.errors()]


def _gpkg(worker, table, path):
    """Instantánea de referencia: GeoPackage en /vsimem con WriteArrow (ruta recomendada en el estudio)."""
    from osgeo import ogr, osr

    srs = osr.SpatialReference()
    srs.SetFromUserInput("OGC:CRS84")
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    def op(handle, token):
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
        lyr = None
        with handle.arrow_batches(
            f"SELECT id, nombre, valor::DOUBLE AS valor, geom FROM {table}", batch_size=65536
        ) as r:
            for b in r:
                if lyr is None:
                    lyr = ds.CreateLayer(
                        "datos", srs, ogr.wkbPoint, ["GEOMETRY_NAME=geom", "SPATIAL_INDEX=YES"]
                    )
                    for f in b.schema:
                        if f.name != "geom":
                            lyr.CreateFieldFromPyArrowSchema(f)
                    ds.StartTransaction()
                lyr.WritePyArrow(b, options=["GEOMETRY_NAME=geom"])
        ds.CommitTransaction()
        ds = None
        return True

    worker.submit(op).future.result()


def bench(rows_list, out):  # noqa: PLR0915 - medición secuencial
    app, worker, run, _work = _setup(rows_list)
    from osgeo import gdal
    from qgis.core import Qgis, QgsFeatureRequest, QgsRectangle, QgsVectorLayer

    results = []
    for rows in rows_list:
        side = int(rows**0.5) * 0.01
        small = QgsRectangle(side * 0.45, side * 0.45, side * 0.55, side * 0.55)
        for fetch, pushdown in (("stream", "core"), ("stream", "spatial"), ("table", "spatial")):
            base_peak, base_now = _rss_peak_mb(), _rss_now_mb()
            uri = f"session=s1|table=d{rows}.puntos|geom=geom|key=id|fetch={fetch}|pushdown={pushdown}"
            layer, open_s = _timed(lambda uri=uri: QgsVectorLayer(uri, "pp", "geoduck"))
            e = {
                "qgis": Qgis.version(),
                "route": f"pyprovider-{fetch}-{pushdown}",
                "rows": rows,
                "valid": layer.isValid(),
                "open_s": open_s,
                "crs": layer.crs().authid(),
                "count": layer.featureCount(),
            }
            if layer.isValid():
                (n, e["bbox_s"]) = _timed(
                    lambda: sum(1 for _ in layer.getFeatures(QgsFeatureRequest().setFilterRect(small)))
                )
                e["bbox_rows"] = n
                n, e["attr_s"] = _timed(
                    lambda: sum(
                        1 for _ in layer.getFeatures(QgsFeatureRequest().setFilterExpression('"id" < 500'))
                    )
                )
                e["attr_rows"] = n
                n, e["attr_local_s"] = _timed(
                    lambda: sum(
                        1
                        for _ in layer.getFeatures(
                            QgsFeatureRequest().setFilterExpression('"nombre" LIKE \'n12%\' AND "id" < 2000')
                        )
                    )
                )
                e["attr_local_rows"] = n
                fids = list(range(0, rows, rows // 100))[:100]
                got, e["fids_s"] = _timed(
                    lambda: sorted(f.id() for f in layer.getFeatures(QgsFeatureRequest().setFilterFids(fids)))
                )
                e["fids_ok"] = got == fids
                e["render_zoom_s"], errs = _render(layer, small)
                e["render_full_s"], errs2 = _render(layer, layer.extent())
                e["render_errors"] = errs + errs2
                # Latencia de la sesión mientras se dibuja todo (otra operación en cola)
                lat = {}

                def probe():
                    time.sleep(0.2)
                    t0 = time.perf_counter()
                    run("SELECT 1")
                    lat["s"] = round(time.perf_counter() - t0, 3)

                th = threading.Thread(target=probe)
                th.start()
                _render(layer, layer.extent())
                th.join()
                e["session_wait_during_full_render_s"] = lat.get("s")
            e["peak_rss_growth_mb"] = round(_rss_peak_mb() - base_peak, 1)
            e["resident_growth_mb"] = round(_rss_now_mb() - base_now, 1)
            e["queries"] = STATS["queries"]
            results.append(e)
            print(json.dumps(e, ensure_ascii=False), flush=True)
            layer = None
        # Referencia: GeoPackage /vsimem
        path = f"/vsimem/geoduck/ref{rows}.gpkg"
        base_now = _rss_now_mb()
        _, load_s = _timed(lambda path=path, rows=rows: _gpkg(worker, f"d{rows}.puntos", path))
        layer = QgsVectorLayer(path, "gp", "ogr")
        e = {
            "qgis": Qgis.version(),
            "route": "gpkg-vsimem",
            "rows": rows,
            "valid": layer.isValid(),
            "open_s": load_s,
            "crs": layer.crs().authid(),
            "count": layer.featureCount(),
        }
        n, e["bbox_s"] = _timed(
            lambda: sum(1 for _ in layer.getFeatures(QgsFeatureRequest().setFilterRect(small)))
        )
        e["bbox_rows"] = n
        n, e["attr_s"] = _timed(
            lambda: sum(1 for _ in layer.getFeatures(QgsFeatureRequest().setFilterExpression('"id" < 500')))
        )
        e["attr_rows"] = n
        e["render_zoom_s"], _ = _render(layer, small)
        e["render_full_s"], _ = _render(layer, layer.extent())
        e["resident_growth_mb"] = round(_rss_now_mb() - base_now, 1)
        e["vsimem_mb"] = round(gdal.VSIStatL(path).size / 2**20, 1)
        results.append(e)
        print(json.dumps(e, ensure_ascii=False), flush=True)
        layer = None
        gdal.Unlink(path)
    worker.close().result()
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    app.exitQgis()


def behaviour(out):  # noqa: PLR0915 - una secuencia de comprobaciones
    app, worker, run, work = _setup([10_000])
    from qgis.core import Qgis, QgsFeatureRequest, QgsProject, QgsRectangle, QgsVectorLayer

    res: dict = {"qgis": Qgis.version()}

    def layer(table):
        return QgsVectorLayer(
            f"session=s1|table={table}|geom=geom|key=id|fetch=stream|pushdown=spatial", "pp", "geoduck"
        )

    def count(lyr):
        return sum(
            1 for _ in lyr.getFeatures(QgsFeatureRequest().setFlags(Qgis.FeatureRequestFlag.NoGeometry))
        )

    # Tabla de una base adjunta (ATTACH) y tabla TEMP de la propia sesión
    lyr = layer("d10000.puntos")
    res["attached_table"] = {"valid": lyr.isValid(), "rows": count(lyr)}
    run("CREATE TEMP TABLE tmp AS SELECT * FROM d10000.puntos WHERE id < 10")
    res["temp_table"] = {"valid": layer("temp.tmp").isValid(), "rows": count(layer("temp.tmp"))}
    run("CREATE VIEW d10000.v_pares AS SELECT * FROM d10000.puntos WHERE id % 2 = 0")
    res["view"] = {"valid": layer("d10000.v_pares").isValid(), "rows": count(layer("d10000.v_pares"))}
    # Transacción abierta: la capa ve cambios sin confirmar (misma conexión) y vuelve atrás tras ROLLBACK
    run("BEGIN")
    run("INSERT INTO d10000.puntos SELECT 99999999, 'nuevo', 0, ST_Point(0, 0)::GEOMETRY('OGC:CRS84')")
    res["uncommitted_visible"] = count(lyr) == 10_001
    run("ROLLBACK")
    res["after_rollback"] = count(lyr) == 10_000
    # Sesión ocupada con una consulta larga: el dibujado espera en la cola
    t_long = time.perf_counter()
    long = worker.submit(lambda h, t: h.execute("SELECT sum(range % 7) FROM range(20000000000)"))
    time.sleep(0.1)
    res["render_while_session_busy_s"], _ = _render(lyr, QgsRectangle(0, 0, 0.5, 0.5))
    long.future.result()
    res["busy_query_s"] = round(time.perf_counter() - t_long, 3)
    # Cancelación del dibujado a mitad: el worker queda libre
    from qgis.core import QgsMapRendererSequentialJob, QgsMapSettings
    from qgis.PyQt.QtCore import QSize

    s = QgsMapSettings()
    s.setLayers([lyr])
    s.setDestinationCrs(lyr.crs())
    s.setExtent(lyr.extent())
    s.setOutputSize(QSize(800, 600))
    job = QgsMapRendererSequentialJob(s)
    job.start()
    time.sleep(0.02)
    job.cancel()
    t0 = time.perf_counter()
    run("SELECT 1")
    res["session_free_after_render_cancel_s"] = round(time.perf_counter() - t0, 3)
    # Abandonar un iterador sin agotarlo libera el worker
    it = lyr.getFeatures()
    next(it)
    it.close()
    t0 = time.perf_counter()
    run("SELECT 1")
    res["session_free_after_iterator_close_s"] = round(time.perf_counter() - t0, 3)
    # Reapertura de proyecto con la sesión viva
    QgsProject.instance().addMapLayer(lyr)
    qgz = os.path.join(work, "p.qgz")
    QgsProject.instance().write(qgz)
    QgsProject.instance().clear()
    QgsProject.instance().read(qgz)
    reopened = list(QgsProject.instance().mapLayers().values())
    res["project_reopen_same_session"] = (
        bool(reopened) and reopened[0].isValid() and count(reopened[0]) == 10_000
    )
    QgsProject.instance().clear()
    # DETACH con la capa en el proyecto: la capa no se entera; las peticiones fallan sin colgar
    lyr = layer("d10000.puntos")
    run("DETACH d10000")
    t0 = time.perf_counter()
    n = count(lyr)
    res["after_detach"] = {
        "rows": n,
        "valid": lyr.isValid(),
        "s": round(time.perf_counter() - t0, 3),
        "error": lyr.dataProvider().last_error[:120],
    }
    # Cierre de la sesión
    run(f"ATTACH '{work}/d10000.duckdb' AS d10000")
    lyr = layer("d10000.puntos")
    worker.close().result()
    t0 = time.perf_counter()
    n = count(lyr)
    res["after_close"] = {
        "rows": n,
        "s": round(time.perf_counter() - t0, 3),
        "error": lyr.dataProvider().last_error[:120],
    }
    QgsProject.instance().addMapLayer(lyr)
    QgsProject.instance().write(qgz)
    QgsProject.instance().clear()
    SESSIONS.clear()
    QgsProject.instance().read(qgz)
    reopened = list(QgsProject.instance().mapLayers().values())
    res["project_reopen_without_session"] = {
        "layers": len(reopened),
        "valid": bool(reopened) and reopened[0].isValid(),
    }
    QgsProject.instance().clear()
    res["sql_examples"] = STATS["sql"][:6]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    app.exitQgis()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bench")
    b.add_argument("--rows", type=int, nargs="+", default=[1_000_000, 5_000_000])
    b.add_argument("--out", required=True)
    h = sub.add_parser("behaviour")
    h.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.cmd == "bench":
        bench(args.rows, args.out)
    else:
        behaviour(args.out)


if __name__ == "__main__":
    main()
