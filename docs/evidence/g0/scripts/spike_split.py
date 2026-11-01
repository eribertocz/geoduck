import os, time, json, threading, queue
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import duckdb
from qgis.core import QgsApplication, QgsVectorLayer, QgsFeature, QgsGeometry, QgsField, QgsFields, Qgis
from qgis.PyQt.QtCore import QTimer, QEventLoop, QMetaType
app=QgsApplication([],True); app.initQgis()
con=duckdb.connect()
con.execute("create table t as select range id, (range*1.5)::DOUBLE d, 'n'||range s, ('POINT('||range%100||' '||range%50||')')::GEOMETRY g from range(200000)")
fields=QgsFields(); [fields.append(QgsField(n,t)) for n,t in (("id",QMetaType.Type.LongLong),("d",QMetaType.Type.Double),("s",QMetaType.Type.QString))]
def build(batch):
    ids,ds,ss,gs=(batch.column(i).to_pylist() for i in range(4)); out=[]
    for i in range(batch.num_rows):
        f=QgsFeature(fields); f.setAttributes([ids[i],ds[i],ss[i]]); g=QgsGeometry(); g.fromWkb(gs[i]); f.setGeometry(g); out.append(f)
    return out
# A) all on main thread
lyr=QgsVectorLayer("Point","a","memory"); pr=lyr.dataProvider(); pr.addAttributes(fields.toList()); lyr.updateFields()
tb=ta=0
with con.sql("select * from t").to_arrow_reader(8192) as r:
    for b in r:
        t0=time.perf_counter(); fs=build(b); t1=time.perf_counter(); ok,_=pr.addFeatures(fs); t2=time.perf_counter(); tb+=t1-t0; ta+=t2-t1
        if not ok: print("ERRS", pr.errors()[:2], fs[0].attributes(), fs[0].geometry().asWkt()); break
res={"qgis":Qgis.version(),"rows":lyr.featureCount(),"build_features_s":round(tb,2),"addFeatures_s":round(ta,2)}
# B) worker builds features, main only addFeatures, measure max main-loop gap
lyr2=QgsVectorLayer("Point","b","memory"); pr2=lyr2.dataProvider(); pr2.addAttributes(fields.toList()); lyr2.updateFields()
q=queue.Queue(maxsize=2); done=object()
def worker():
    c2=con  # single owner: only worker touches con from now
    with c2.sql("select * from t").to_arrow_reader(8192) as r:
        for b in r: q.put(build(b))
    q.put(done)
gaps=[]; last=[time.perf_counter()]; loop=QEventLoop(); added=[0]
def tick():
    now=time.perf_counter(); gaps.append(now-last[0]); last[0]=now
def drain():
    try: item=q.get_nowait()
    except queue.Empty: return
    if item is done: loop.quit(); return
    pr2.addFeatures(item); added[0]+=len(item)
hb=QTimer(); hb.timeout.connect(tick); hb.start(10)
dr=QTimer(); dr.timeout.connect(drain); dr.start(0)
th=threading.Thread(target=worker); t0=time.perf_counter(); th.start(); loop.exec(); th.join()
gaps.sort()
res.update({"B_rows":lyr2.featureCount(),"B_total_s":round(time.perf_counter()-t0,2),"B_main_gap_p50_ms":round(gaps[len(gaps)//2]*1000,1),"B_main_gap_p99_ms":round(gaps[int(len(gaps)*.99)]*1000,1),"B_main_gap_max_ms":round(gaps[-1]*1000,1)})
print(json.dumps(res))
