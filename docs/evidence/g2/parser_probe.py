# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G2-A: parser de sentencias de DuckDB (ver README.md). Uso: python parser_probe.py"""
import duckdb, json
con = duckdb.connect()
print("==", duckdb.__version__)
s = con.extract_statements("SELECT 1")[0]
print(" attrs:", [a for a in dir(s) if not a.startswith("_")])
SCRIPT = """-- comentario con ; punto y coma
CREATE TABLE t AS SELECT 1 AS id, 'a;b' AS txt; /* bloque ; */
SELECT * FROM t;
  SELECT 'x'';y' AS q
;WITH n AS (SELECT 2 AS id) INSERT INTO t SELECT id, 'z' FROM n RETURNING *;
EXPLAIN SELECT * FROM t;
BEGIN; COMMIT;
SET threads = 2; PRAGMA version;
CREATE MACRO f(a) AS a + 1; SELECT $$dollar ; quote$$ AS d;
ATTACH ':memory:' AS m; DETACH m;"""
stmts = con.extract_statements(SCRIPT)
pos = 0
for st in stmts:
    q = st.query
    found = SCRIPT.find(q, pos)
    exact = found >= 0
    if exact: pos = found + len(q)
    print(f"  {str(st.type):32s} {str(getattr(st,'expected_result_type','?')):40s} exact={exact} {q[:40]!r}")
# ejecutar Statement directamente
st = con.extract_statements("SELECT 42 AS x")[0]
try: print(" execute(Statement):", con.execute(st).fetchall())
except Exception as e: print(" execute(Statement) error:", type(e).__name__, e)
# error con posición
for bad in ["SELECT * FROM nada", "SELEC 1", "SELECT 1 +"]:
    try: con.execute(bad)
    except Exception as e:
        print(f" error {type(e).__name__}: attrs={[a for a in vars(e)] if hasattr(e,'__dict__') else []} args={e.args[:1]!r}"[:230])
try: con.extract_statements("SELECT 1; SELEC 2; SELECT 3")
except Exception as e: print(" extract con error de sintaxis:", type(e).__name__, str(e).splitlines()[0][:100])
