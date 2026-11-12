# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G10-A (performance-spec §3, §8, §9): con DuckDB real y 10 millones de filas, cuánto cuesta repetir la
consulta por página frente a guardar el resultado una vez, leer por `rowid` frente a `OFFSET`, y cuánto tarda
`interrupt()` por tipo de operación. Uso: `python tools/perf/spike_g10a.py <carpeta>` (imprime JSON)."""

import json
import os
import statistics as st
import sys
import tempfile
import threading
import time

import duckdb

N = 10_000_000
out = {"duckdb": duckdb.__version__, "rows": N, "cpus": os.cpu_count()}
d = tempfile.mkdtemp(dir=sys.argv[1])
c = duckdb.connect(f"{d}/b.duckdb")
c.execute(f"SET temp_directory='{d}/tmp'")
c.execute(
    "CREATE TABLE t AS SELECT i AS id, 'cliente ' || (i % 1000) AS nombre, random()*100 AS kwh, "
    f"DATE '2020-01-01' + (i % 2000)::INT AS fecha, (i % 50) AS zona FROM range({N}) r(i)"
)
Q = "SELECT zona, nombre, id, kwh * 1.1 AS kwh2, fecha FROM t WHERE kwh > 5"


def t(f):
    a = time.perf_counter()
    r = f()
    return time.perf_counter() - a, r


# 1. hoy: primera página, página con OFFSET, contar
out["hoy_primera_pagina_s"], _ = t(lambda: c.execute(Q).fetchmany(100))
out["hoy_count_s"], n = t(lambda: c.execute(f"SELECT count(*) FROM ({Q})").fetchone()[0])
out["hoy_pagina_offset_5M_s"], _ = t(
    lambda: c.execute(f"SELECT * FROM ({Q}) LIMIT 100 OFFSET 5000000").fetchall()
)
out["hoy_pagina_offset_final_s"], _ = t(
    lambda: c.execute(f"SELECT * FROM ({Q}) LIMIT 100 OFFSET {n - 100}").fetchall()
)
# 2. propuesto: guardar una vez y leer por rowid
out["solo_ejecutar_s"], _ = t(
    lambda: c.execute(f"SELECT count(*), sum(kwh2), max(nombre) FROM ({Q})").fetchall()
)
out["guardar_resultado_s"], _ = t(lambda: c.execute(f"CREATE TEMP TABLE r AS {Q}"))
out["filas_resultado"] = n
ts = []
for off in (0, n // 2, n - 100, n // 3, n // 7):
    dt, rows = t(
        lambda o=off: c.execute(f"SELECT * FROM r WHERE rowid >= {o} AND rowid < {o + 100}").fetchall()
    )
    ts.append(dt)
    assert len(rows) == 100
out["propuesto_pagina_rowid_ms"] = round(max(ts) * 1000, 2)
out["propuesto_total_ms"] = round(t(lambda: c.execute("SELECT count(*) FROM r").fetchone())[0] * 1000, 2)
out["propuesto_ordenar_pagina_s"], _ = t(
    lambda: c.execute("SELECT * FROM r ORDER BY kwh2 DESC LIMIT 100").fetchall()
)
# 3. tabla: OFFSET vs rowid
out["tabla_offset_9M_ms"] = round(
    t(lambda: c.execute("SELECT * FROM t LIMIT 100 OFFSET 9000000").fetchall())[0] * 1000, 2
)
out["tabla_rowid_9M_ms"] = round(
    t(lambda: c.execute("SELECT * FROM t WHERE rowid >= 9000000 AND rowid < 9000100").fetchall())[0] * 1000, 2
)


# 4. cancelar: interrupt() desde otro hilo
def cancel(sql, wait=0.3):
    res = {}

    def run():
        try:
            c.execute(sql).fetchall()
            res["fin"] = "terminó"
        except Exception as e:
            res["fin"] = type(e).__name__
        res["t"] = time.perf_counter()

    th = threading.Thread(target=run)
    th.start()
    time.sleep(wait)
    a = time.perf_counter()
    c.interrupt()
    th.join(60)
    return round((res.get("t", a) - a) * 1000, 1), res.get("fin")


heavy = "SELECT count(*) FROM t a JOIN t b ON a.zona = b.zona AND a.kwh < b.kwh"
cs = {}
for name, sql in [
    ("consulta_pesada", heavy),
    ("crear_tabla", "CREATE OR REPLACE TEMP TABLE x AS SELECT a.* FROM t a, range(20)"),
    ("exportar_parquet", f"COPY (SELECT a.* FROM t a, range(20)) TO '{d}/x.parquet'"),
    ("ordenar", "SELECT * FROM t ORDER BY nombre, kwh"),
]:
    lat = [cancel(sql) for _ in range(5)]
    cs[name] = {
        "ms_max": max(x[0] for x in lat),
        "ms_mediana": st.median(x[0] for x in lat),
        "fin": sorted({x[1] for x in lat}),
    }
    ok = c.execute("SELECT 42").fetchone()[0]
    assert ok == 42
out["cancelar"] = cs
out["restos_parquet"] = os.path.exists(f"{d}/x.parquet")
for k, v in list(out.items()):
    if isinstance(v, float):
        out[k] = round(v, 3)
print(json.dumps(out, ensure_ascii=False, indent=1))
