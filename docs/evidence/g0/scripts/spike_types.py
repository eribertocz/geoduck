import duckdb, json, os, sys, tempfile, warnings
V=duckdb.__version__; out={}
con=duckdb.connect(':memory:')
# 1. silent truncation check
con.execute("create table big as select range i from range(100000)")
r=con.sql("select * from big").to_arrow_reader(batch_size=1000)
n=r.read_next_batch().num_rows
try:
    con.execute("select 1").fetchall(); interleave="interleaved query accepted"
except Exception as e: interleave=type(e).__name__
err=None
try:
    for b in r: n+=b.num_rows
except Exception as e: err=f"{type(e).__name__}: {e}"[:120]
out["reader_after_interleaved_query"]={"interleave":interleave,"rows_read":n,"expected":100000,"error":err}
# 2. execute().to_arrow_reader path
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    try:
        c3=duckdb.connect(); c3.execute('create table big as select range i from range(1000)'); rr=c3.execute('select * from big').to_arrow_reader(1000) if hasattr(c3.execute('select 1'),'to_arrow_reader') else None
        out["execute_to_arrow_reader"]= "exists; warnings="+str([str(x.message)[:80] for x in w]) if rr is not None else "absent"
    except Exception as e: out["execute_to_arrow_reader"]=f"ERR {type(e).__name__}"
    con2=duckdb.connect(); out["execute_fetch_record_batch"]= hasattr(con2.execute("select 1"),"fetch_record_batch")
# 3. Arrow type mapping
sql = """select
 true b, 1::TINYINT ti, 1::UTINYINT uti, 2::SMALLINT si, 3::INTEGER i, 9223372036854775807::BIGINT bi,
 18446744073709551615::UBIGINT ubi, 170141183460469231731687303715884105727::HUGEINT hi,
 1.5::FLOAT f, 'nan'::DOUBLE d, 12345678901234567890.123456789012345678::DECIMAL(38,18) dec38, 1.25::DECIMAL(9,2) dec9,
 'á'::VARCHAR s, 'a'::ENUM_T e, uuid() u, DATE '2026-11-01' dt, TIMESTAMP '2026-11-01 10:00:00' ts,
 TIMESTAMPTZ '2026-11-01 10:00:00-04' tstz, TIME '10:00:00' tm, INTERVAL 3 DAY iv, '\\xAA'::BLOB bl,
 [1,2] lst, {'a':1} st, MAP {'k':1} mp, union_value(num := 2)::UNION(num INT, str VARCHAR) un, NULL::INTEGER nul,
 '{"a":1}'::JSON js, '101'::BIT bt, TIMESTAMP_NS '2026-11-01 10:00:00.123456789' tsns"""
con.execute("create type ENUM_T as enum ('a','b')")
try:
    t=con.sql(sql).to_arrow_table()
    out["arrow_types"]={f.name: str(f.type)+(" ext="+f.metadata.get(b'ARROW:extension:name',b'').decode() if f.metadata else "") for f in t.schema}
    out["duckdb_types"]=dict(zip(con.sql(sql).columns,[str(x) for x in con.sql(sql).types]))
except Exception as e: out["arrow_types"]=f"ERR {type(e).__name__}: {e}"[:200]
# 4. statement text fidelity
s=con.extract_statements("  -- c1\nSELECT 1 ;  /*x*/ select 'a;b' AS \"q;\"  ;")
out["stmt_query_text"]=[st.query for st in s]
json.dump(out,open(f"out/types_{V}.json","w"),indent=1,ensure_ascii=False)
print(V, json.dumps(out,indent=1,ensure_ascii=False))
