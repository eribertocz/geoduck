# SPDX-License-Identifier: GPL-2.0-or-later
"""#154: ¿usa DuckDB el R-tree en las consultas de una capa Conectada? Tiempo de una vista pequeña."""
import os, sys, time
sys.path.insert(0, "/home/claude/geoduck")
from qgis.core import QgsApplication, QgsFeatureRequest, QgsRectangle
app = QgsApplication([], False); app.initQgis()
import duckdb
from tests.qgis.test_load_connected import Session
from tests.qgis.test_lifecycle_connected import attach
N = int(sys.argv[1]); path = sys.argv[2]
if not os.path.exists(path):
    con = duckdb.connect(path)
    con.execute(f"CREATE TABLE t AS SELECT range AS id, ('POINT(' || (hash(range) % 1000000)/1000.0 || ' ' || (hash(range*7) % 1000000)/1000.0 || ')')::GEOMETRY AS g, 'n' || range AS nombre FROM range({N})")
    con.close()
s = Session()
attach(s, path)
_, layer = s.load('SELECT * FROM "d"."main"."t"', name="t", source=("d", "main", "t"))
sqls = []
orig = s.engine.read_table
def spy(sql, **kw):
    sqls.append(sql); return orig(sql, **kw)
s.engine.read_table = spy
def view(w):
    r = QgsFeatureRequest().setFilterRect(QgsRectangle(500, 500, 500 + w, 500 + w))
    t = time.monotonic(); n = sum(1 for _ in layer.getFeatures(r)); return n, time.monotonic() - t
def bench(label):
    for w in (10, 100, 1000):
        best = min(view(w)[1] for _ in range(3)); print(f"{label} vista {w}x{w}: {view(w)[0]} filas, {best*1000:.0f} ms", flush=True)
print("spatial:", s.engine.query("SELECT loaded FROM duckdb_extensions() WHERE extension_name='spatial'", priority=False).future.result(60).rows, "geodata:", os.environ.get("GEODUCK_SPATIAL"))
bench("sin índice")
q = sqls[-1]
ex = lambda: "\n".join(r[1] for r in s.engine.query("EXPLAIN " + q, priority=False).future.result(60).rows)
print("RTREE en el plan sin índice:", "Rtree Index Scan" in ex())
t = time.monotonic(); s.engine.query("CREATE INDEX IF NOT EXISTS r ON d.main.t USING RTREE (g)", priority=False).future.result(600); print(f"crear índice: {time.monotonic()-t:.1f} s")
sqls.clear(); bench("con índice")
q = sqls[0]
plan = ex(); print("RTREE en el plan con índice:", "Rtree Index Scan" in plan)
pass
s.close()
