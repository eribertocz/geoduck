# SPDX-License-Identifier: GPL-2.0-or-later
"""Evidencia G1 paso 6: comprobación del estado transaccional en DuckDB (ver README.md)."""
import duckdb, threading, time
con=duckdb.connect()
def st():
    try:
        a=con.execute("SELECT txid_current()").fetchall()[0][0]; b=con.execute("SELECT txid_current()").fetchall()[0][0]
        return "ACTIVE" if a==b else "NONE"
    except duckdb.TransactionException as e: return "ABORTED" if "aborted" in str(e).lower() else f"?{e}"
print("==", duckdb.__version__, "auto:", st())
con.execute("BEGIN"); print("  begin:", st()); con.execute("CREATE TEMP TABLE tt AS SELECT 1 x"); print("  after work:", st())
con.execute("COMMIT"); print("  commit:", st())
con.execute("BEGIN"); 
try: con.execute("SELECT * FROM nada")
except Exception: pass
print("  error in tx:", st())
con.execute("ROLLBACK"); print("  rollback:", st())
# cancel inside tx
con.execute("BEGIN"); con.execute("CREATE TABLE k AS SELECT 1 x")
th=threading.Timer(0.3, con.interrupt); th.start()
try: con.execute("SELECT count(*) FROM range(5000000000) t(a) WHERE a % 7 = 3").fetchall()
except Exception as e: print("  interrupted:", type(e).__name__)
print("  after interrupt in tx:", st())
try: con.execute("ROLLBACK"); print("  rb ok:", st())
except Exception as e: print("  rb err", e)
# commit conflict? two connections not applicable (single conn). commit of aborted silent:
con.execute("BEGIN"); con.execute("CREATE TABLE z AS SELECT 1 x")
try: con.execute("SELECT * FROM nada")
except Exception: pass
con.execute("COMMIT"); print("  commit-of-aborted -> z exists:", bool(con.execute("select count(*) from duckdb_tables() where table_name='z'").fetchall()[0][0]))
# USE/SET/TEMP persist
con.execute("SET threads=1"); print("  setting persists:", con.execute("select current_setting('threads')").fetchall())
