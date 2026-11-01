"""GeoDuck G0 spike: session, parser, ATTACH/DETACH, readers, transactions. Run with each DuckDB version."""
import duckdb, os, sys, tempfile, threading, time, subprocess, json
V = duckdb.__version__
out = {}
def rec(key, fn):
    try:
        out[key] = "OK " + str(fn())[:300]
    except Exception as e:
        out[key] = f"ERR {type(e).__name__}: {str(e).splitlines()[0][:200]}"
tmp = tempfile.mkdtemp(prefix="gd_")
con = duckdb.connect(":memory:")

# --- A. parser ---
script = """-- comentario; con punto y coma
CREATE TABLE productos AS SELECT 1 AS id, 'Medi;dor' AS nombre;
/* bloque ; */ SELECT * FROM productos;
SELECT COUNT(*) AS n FROM productos;
WITH x AS (SELECT 2 AS id) INSERT INTO productos SELECT id, 'b' FROM x RETURNING *;
EXPLAIN SELECT 1;
ATTACH ':memory:' AS m2;
DETACH m2;
CREATE MACRO f(a) AS a || ';';
SELECT f('x');
"""
def parse():
    sts = con.extract_statements(script)
    attrs = sorted(a for a in dir(sts[0]) if not a.startswith("_"))
    return {"n": len(sts), "attrs": attrs,
            "types": [str(s.type) for s in sts],
            "queries": [s.query[:40] for s in sts]}
rec("A.extract_statements", parse)
rec("A.parse_error", lambda: con.extract_statements("SELEC 1; SELECT 2"))

# --- B. execute Statement objects & result shapes ---
def run_all():
    con2 = duckdb.connect(":memory:")
    res = []
    for s in con2.extract_statements(script):
        r = con2.execute(s)
        desc = r.description
        rows = r.fetchall() if desc else None
        res.append((str(s.type).split(".")[-1], bool(desc), len(rows) if rows is not None else None))
    return res
rec("B.execute_statement_objects", run_all)

# --- J. RETURNING via relation re-runs? ---
def returning_rel():
    c = duckdb.connect(":memory:"); c.execute("create table t(i int)")
    rel = c.sql("insert into t values (1) returning *")
    a = rel.fetchall() if hasattr(rel, "fetchall") else None
    b = rel.fetchall() if hasattr(rel, "fetchall") else None
    return {"rel_type": type(rel).__name__, "after_two_fetch_count": c.execute("select count(*) from t").fetchone()[0]}
rec("J.sql_insert_returning_rerun", returning_rel)
def returning_exec():
    c = duckdb.connect(":memory:"); c.execute("create table t(i int)")
    r = c.execute("insert into t values (1) returning *"); r.fetchall()
    return c.execute("select count(*) from t").fetchone()[0]
rec("J.execute_insert_returning_count", returning_exec)
def sql_ddl():
    c = duckdb.connect(":memory:"); r = c.sql("create table z(i int)")
    return {"returns": type(r).__name__ if r is not None else None, "exists": c.execute("select count(*) from duckdb_tables() where table_name='z'").fetchone()[0]}
rec("J.sql_ddl_returns", sql_ddl)
def rel_rerun_volatile():
    c = duckdb.connect(":memory:"); rel = c.sql("select random() r")
    return rel.fetchall() != rel.fetchall()
rec("J.relation_reruns_on_each_read(random differs)", rel_rerun_volatile)

# --- C. ATTACH/DETACH, USE ---
f1 = os.path.join(tmp, "comercial á ñ.duckdb")
c0 = duckdb.connect(f1); c0.execute("create table ventas as select range id, range*1.5 v from range(100000)"); c0.close()
rec("C.attach_ro", lambda: con.execute(f"ATTACH '{f1}' AS \"comer cial\" (READ_ONLY)").fetchall())
rec("C.ro_write_rejected", lambda: con.execute('insert into "comer cial".main.ventas values (1,1)').fetchall())
rec("C.databases", lambda: con.execute("select database_name, path is not null, readonly, internal, type from duckdb_databases() order by 1").fetchall())
rec("C.current_database", lambda: con.execute("select current_database()").fetchall())
rec("C.use_attached", lambda: con.execute('USE "comer cial"').fetchall())
rec("C.detach_current_default", lambda: con.execute('DETACH "comer cial"').fetchall())
rec("C.use_memory_then_detach", lambda: (con.execute("USE memory"), con.execute('DETACH "comer cial"').fetchall())[1])
rec("C.attach_param_path", lambda: con.execute("ATTACH ? AS p (READ_ONLY)", [f1]).fetchall())
rec("C.detach_p", lambda: con.execute("DETACH p").fetchall())

# --- F. lock release after DETACH: external process opens RW ---
f2 = os.path.join(tmp, "rw.duckdb")
duckdb.connect(f2).close()
con.execute(f"ATTACH '{f2}' AS rw"); con.execute("create table rw.t as select 1 i")
probe = f"import duckdb; c=duckdb.connect(r'''{f2}'''); c.execute('insert into t values (2)'); print('EXTERNAL_RW_OK')"
def ext():
    p = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=60)
    return (p.stdout.strip() or p.stderr.strip().splitlines()[-1])[:150]
rec("F.external_rw_while_attached", ext)
con.execute("DETACH rw")
rec("F.external_rw_after_detach", ext)

# --- D/E. open Arrow reader + other ops on same connection ---
con.execute(f"ATTACH '{f1}' AS c (READ_ONLY)")
rdr = con.sql("select * from c.ventas").to_arrow_reader(batch_size=1000)
first = rdr.read_next_batch()
rec("E.query_while_reader_open", lambda: con.execute("select 42").fetchall())
rec("D.detach_while_reader_open", lambda: con.execute("DETACH c").fetchall())
def finish():
    n = first.num_rows
    for b in rdr: n += b.num_rows
    return n
rec("D.reader_continue_after_attempts", finish)
rec("D.detach_after_reader_done", lambda: con.execute("DETACH c").fetchall() if "c" in [r[0] for r in con.execute("select database_name from duckdb_databases()").fetchall()] else "already detached")

# --- batch sizes honored ---
def batches():
    rel = con.sql("select range i from range(50000)")
    with rel.to_arrow_reader(batch_size=8192) as r:
        return [b.num_rows for b in r]
rec("K.reader_batch_sizes_8192", batches)
rec("K.reader_context_manager", lambda: hasattr(con.sql("select 1").to_arrow_reader(10), "__enter__"))
rec("K.preview_limit", lambda: con.sql("select range i from range(100000000)").limit(200).to_arrow_table().num_rows)

# --- G. interrupt from another thread ---
def interrupt_test(reader_mode):
    c = duckdb.connect(":memory:")
    q = "select count(*) from range(3000000000) t(a) where a % 7 = 3"
    t0 = time.time(); box = {}
    def worker():
        try:
            if reader_mode:
                with c.sql("select a, a%7 b from range(3000000000) t(a) where a % 9999991 = 1 or a%3=0").to_arrow_reader(batch_size=8192) as r:
                    for _ in r: pass
            else:
                c.execute(q).fetchall()
            box["r"] = "finished"
        except Exception as e:
            box["r"] = f"{type(e).__name__}: {str(e).splitlines()[0][:80]}"
    th = threading.Thread(target=worker); th.start(); time.sleep(1.0)
    ti = time.time(); c.interrupt(); th.join(30)
    return {"alive_after_30s": th.is_alive(), "result": box.get("r"), "latency_s": round(time.time() - ti, 3)}
rec("G.interrupt_execute", lambda: interrupt_test(False))
rec("G.interrupt_reader", lambda: interrupt_test(True))
rec("G.connection_usable_after_interrupt", lambda: (lambda c: (c.interrupt(), c.execute("select 1").fetchall())[1])(duckdb.connect()))

# --- H. transactions ---
def tx():
    c = duckdb.connect(":memory:"); c.execute("create table t(i int primary key)")
    c.execute("BEGIN"); c.execute("insert into t values (1)")
    try: c.execute("insert into t values (1)")
    except Exception as e: err = type(e).__name__
    try: c.execute("select 1").fetchall(); after = "select ok"
    except Exception as e: after = type(e).__name__
    try: c.execute("COMMIT"); cm = "commit accepted"
    except Exception as e: cm = type(e).__name__ + ": " + str(e).splitlines()[0][:80]
    return {"dup_err": err, "next_stmt": after, "commit": cm, "rows": c.execute("select count(*) from t").fetchone()[0]}
rec("H.failed_stmt_in_tx", tx)
rec("H.autocommit_script_partial", lambda: "n/a")

# --- threads: same connection from 2 threads ---
def two_threads():
    c = duckdb.connect(":memory:"); errs = []
    def w():
        try:
            for _ in range(200): c.execute("select sum(range) from range(100000)").fetchall()
        except Exception as e: errs.append(type(e).__name__)
    ts = [threading.Thread(target=w) for _ in range(2)]; [t.start() for t in ts]; [t.join() for t in ts]
    return errs[:3] or "no error"
if os.environ.get("GD_SKIP_MT") != "1": rec("T.same_connection_two_threads", two_threads)
else: out["T.same_connection_two_threads"] = "SKIPPED (segfault reproducido)"
rec("T.connection_created_in_thread_used_in_other", lambda: (lambda box: (threading.Thread(target=lambda: box.append(duckdb.connect(":memory:"))).start(), time.sleep(0.3), box[0].execute("select 1").fetchall())[2])([]))

json.dump(out, open(f"out/session_{V}.json", "w"), indent=1, ensure_ascii=False)
for k, v in out.items(): print(f"{k:48s} {v}")
