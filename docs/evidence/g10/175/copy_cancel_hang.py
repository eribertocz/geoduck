# SPDX-License-Identifier: GPL-2.0-or-later
"""Sin GeoDuck: solo DuckDB. COPY ... TO Parquet y cancelarlo con interrupt() a un tiempo al azar."""
import duckdb, threading, time, random, os, sys, tempfile
d = tempfile.mkdtemp(dir=os.environ["TMPD"])
con = duckdb.connect()
if os.environ.get("PRESET"): con.execute(os.environ["PRESET"])
con.execute("CREATE TABLE t2 AS SELECT i AS id, 'cliente ' || (i % 1000) AS nombre, (i * 7919) % 10000 / 10.0 AS kwh, (i % 50) AS zona FROM range(200000) r(i)")
hangs = 0
for n in range(int(sys.argv[1])):
    def run():
        try: con.execute(f"COPY (SELECT a.* FROM t2 a, range(30)) TO '{d}/x.parquet' (FORMAT parquet)")
        except duckdb.Error: pass
    th = threading.Thread(target=run, daemon=True); th.start()
    time.sleep(random.uniform(0.05, 0.35)); con.interrupt()
    th.join(20)
    if th.is_alive():
        print("CUELGUE en la vuelta", n, flush=True); os._exit(1)
    if os.path.exists(f"{d}/x.parquet"): os.remove(f"{d}/x.parquet")
print(duckdb.__version__, os.environ.get("PRESET", "por defecto"), ": sin cuelgues en", sys.argv[1])
