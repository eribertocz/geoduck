"""G0 spike: Arrow RecordBatch -> QGIS memory layer (main thread), types, WKB, CRS, editor SQL."""
import os, sys, json, time, gc
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import duckdb, pyarrow as pa
from qgis.core import (Qgis, QgsApplication, QgsVectorLayer, QgsFields, QgsField, QgsFeature, QgsGeometry,
                       QgsProject, QgsCoordinateReferenceSystem, QgsWkbTypes)
from qgis.PyQt.QtCore import QT_VERSION_STR, PYQT_VERSION_STR, QVariant, QDate, QDateTime, QTime
app = QgsApplication([], True); app.initQgis()
out = {"qgis": Qgis.version(), "qt": QT_VERSION_STR, "pyqt": PYQT_VERSION_STR, "python": sys.version.split()[0],
       "duckdb": duckdb.__version__, "pyarrow": pa.__version__}
try:
    import numpy; out["numpy"] = numpy.__version__
except Exception: out["numpy"] = None
def rec(k, fn):
    try: out[k] = fn()
    except Exception as e: out[k] = f"ERR {type(e).__name__}: {str(e)[:200]}"

# Field type API differences (QVariant vs QMetaType) QGIS 3 vs 4
def field_api():
    r = {}
    try:
        from qgis.PyQt.QtCore import QMetaType
        f = QgsField("x", QMetaType.Type.LongLong); r["QgsField(QMetaType.Type)"] = f.typeName()
    except Exception as e: r["QgsField(QMetaType.Type)"] = f"ERR {e}"[:100]
    try:
        f = QgsField("x", QVariant.LongLong); r["QgsField(QVariant.LongLong)"] = f.typeName()
    except Exception as e: r["QgsField(QVariant)"] = f"ERR {e}"[:100]
    return r
rec("field_api", field_api)

con = duckdb.connect(":memory:")
con.execute("""create table t as select range id,
  (range*1.5)::DOUBLE d, 'nombre ' || range s, (range % 2 = 0) b,
  DATE '2026-01-01' + range::INT dt, TIMESTAMP '2026-01-01 00:00:00' + to_seconds(range) ts,
  9223372036854775807::BIGINT big, 18446744073709551615::UBIGINT ubig, 12345.678901234567890123::DECIMAL(38,20) decv,
  case when range % 10 = 0 then NULL else range end nullable,
  [range, range+1] lst, ('POINT(' || (range % 360 - 180) || ' ' || (range % 180 - 90) || ')')::GEOMETRY('OGC:CRS84') geom
  from range(100000)""")

def _types():
    """Compat adapter: QGIS >= 3.38 / 4.x accept QMetaType.Type; older QGIS 3 need QVariant.Type."""
    from qgis.PyQt.QtCore import QMetaType
    from types import SimpleNamespace as NS
    try:
        QgsField("probe", QMetaType.Type.Int); M = QMetaType.Type
        return NS(Bool=M.Bool, Int=M.Int, LongLong=M.LongLong, Double=M.Double, QString=M.QString, QDate=M.QDate, QDateTime=M.QDateTime)
    except TypeError:
        V = QVariant
        return NS(Bool=V.Bool, Int=V.Int, LongLong=V.LongLong, Double=V.Double, QString=V.String, QDate=V.Date, QDateTime=V.DateTime)
def build_fields(schema, geom_col):
    T = _types()
    m = {}
    fields = QgsFields()
    for f in schema:
        if f.name == geom_col: continue
        t = f.type
        if pa.types.is_boolean(t): qt = T.Bool; conv = None
        elif pa.types.is_int8(t) or pa.types.is_int16(t) or pa.types.is_int32(t) or pa.types.is_uint8(t) or pa.types.is_uint16(t): qt = T.Int; conv=None
        elif pa.types.is_int64(t) or pa.types.is_uint32(t): qt = T.LongLong; conv=None
        elif pa.types.is_uint64(t) or pa.types.is_decimal(t): qt = T.QString; conv=str
        elif pa.types.is_floating(t): qt = T.Double; conv=None
        elif pa.types.is_date(t): qt = T.QDate; conv=lambda v: QDate(v.year, v.month, v.day)
        elif pa.types.is_timestamp(t): qt = T.QDateTime; conv=lambda v: QDateTime(v)
        elif pa.types.is_string(t) or pa.types.is_large_string(t): qt = T.QString; conv=None
        else: qt = T.QString; conv=lambda v: json.dumps(v, default=str)
        fields.append(QgsField(f.name, qt)); m[f.name] = conv
    return fields, m

def transfer(sql, geom_col="geom", batch_size=8192, fail_at=None):
    rel = con.sql(f"select * from ({sql})")
    schema = rel.to_arrow_reader(batch_size=1).schema  # schema probe
    gf = schema.field(geom_col) if geom_col else None
    crs_meta = json.loads(gf.metadata[b"ARROW:extension:metadata"]) if gf is not None and gf.metadata else {}
    crs = QgsCoordinateReferenceSystem()
    if crs_meta.get("crs") is not None:
        crs.createFromUserInput(json.dumps(crs_meta["crs"]))  # PROJJSON from geoarrow.wkb metadata
    fields, conv = build_fields(schema, geom_col)
    uri = ("Point" if geom_col else "None") + "?crs=" + (crs.authid() or "")
    layer = QgsVectorLayer("Point" if geom_col else "None", "private", "memory")
    if geom_col and crs.isValid(): layer.setCrs(crs)
    pr = layer.dataProvider(); pr.addAttributes(fields.toList()); layer.updateFields()
    names = [f.name() for f in fields]
    rows_read = rows_added = 0; t_conv = 0.0
    with rel.to_arrow_reader(batch_size=batch_size) as reader:
        for batch in reader:
            t0 = time.perf_counter()
            cols = {n: batch.column(n).to_pylist() for n in names}
            geoms = batch.column(geom_col).to_pylist() if geom_col else None
            feats = []
            for i in range(batch.num_rows):
                if fail_at is not None and rows_read + i == fail_at: raise ValueError("fila corrupta simulada")
                ft = QgsFeature(fields)
                ft.setAttributes([ (conv[n](cols[n][i]) if conv[n] and cols[n][i] is not None else cols[n][i]) for n in names])
                if geoms is not None and geoms[i] is not None:
                    g = QgsGeometry(); g.fromWkb(geoms[i]); ft.setGeometry(g)
                feats.append(ft)
            ok, _ = pr.addFeatures(feats)
            if not ok: raise RuntimeError("addFeatures falló")
            rows_read += batch.num_rows; rows_added += len(feats); t_conv += time.perf_counter() - t0
    return layer, {"rows_read": rows_read, "rows_added": rows_added, "featureCount": layer.featureCount(),
                   "crs_authid": crs.authid(), "crs_valid": crs.isValid(), "crs_desc": crs.description(),
                   "convert_add_s": round(t_conv, 2), "wkbType": QgsWkbTypes.displayString(layer.wkbType())}

def full():
    layer, info = transfer("select * from t")
    f = next(layer.getFeatures())
    info["sample_attrs"] = {k: (repr(f[k]))[:60] for k in ["id", "d", "b", "dt", "ts", "big", "ubig", "decv", "nullable", "lst"]}
    f10 = [x for x in layer.getFeatures() if x["id"] == 10][0]
    info["null_attr_is_NULL"] = repr(f10["nullable"])
    info["geom_wkt"] = f.geometry().asWkt()
    QgsProject.instance().addMapLayer(layer)
    lid = layer.id()
    con.execute("drop table t2") if False else None
    return info, lid
rec("transfer_100k_points", lambda: full()[0])

def atomic():
    before = len(QgsProject.instance().mapLayers())
    try:
        transfer("select * from t", fail_at=30001)
    except ValueError as e:
        gc.collect()
        return {"error": str(e), "layers_before": before, "layers_after": len(QgsProject.instance().mapLayers())}
rec("atomic_fail_row_30001", atomic)

def survive_close():
    lyr = [l for l in QgsProject.instance().mapLayers().values()][0]
    con.close()
    return {"after_con_close_featureCount": lyr.featureCount(), "valid": lyr.isValid(), "provider": lyr.providerType()}
rec("layer_after_duckdb_close", survive_close)

def no_geom():
    global con
    con = duckdb.connect(":memory:")
    con.execute("create table t as select range id from range(10)")
    layer, info = transfer("select * from t", geom_col=None)
    return {**info, "isSpatial": layer.isSpatial()}
rec("no_geometry_table", no_geom)

def crs_tests():
    r = {}
    for s in ["OGC:CRS84", "EPSG:4326", "EPSG:32719"]:
        c = QgsCoordinateReferenceSystem(s); r[s] = (c.isValid(), c.authid(), c.hasAxisInverted())
    return r
rec("crs_axis", crs_tests)

def editor():
    r = {}
    try:
        from qgis.gui import QgsCodeEditorSQL
        e = QgsCodeEditorSQL(); e.setText("SELECT 1;"); r["QgsCodeEditorSQL"] = "OK " + type(e).__mro__[1].__name__
        r["has_setFieldNames"] = hasattr(e, "setFieldNames"); r["has_setExtraKeywords"] = hasattr(e, "setExtraKeywords")
    except Exception as ex: r["QgsCodeEditorSQL"] = f"ERR {ex}"[:120]
    try:
        from qgis.PyQt import Qsci; r["Qsci"] = "importable"
    except Exception as ex: r["Qsci"] = f"ERR {ex}"[:80]
    try:
        from qgis.core import QgsTask; r["QgsTask"] = True
    except Exception as ex: r["QgsTask"] = str(ex)
    return r
rec("editor_and_task", editor)
print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
json.dump(out, open(f"out/qgis_{out['qgis'].split('-')[0]}_{duckdb.__version__}.json", "w"), indent=1, ensure_ascii=False, default=str)
app.exitQgis()
