# SPDX-License-Identifier: GPL-2.0-or-later
import duckdb, sys
print(duckdb.__version__)
con = duckdb.connect(); con.execute("INSTALL spatial; LOAD spatial")
con.execute("CREATE TABLE t AS SELECT range AS id, ('POINT(' || (hash(range) % 1000000)/1000.0 || ' ' || (hash(range*7) % 1000000)/1000.0 || ')')::GEOMETRY AS g FROM range(1000000)")
con.execute("CREATE INDEX r ON t USING RTREE (g)")
poly = "'POLYGON((500 500, 600 500, 600 600, 500 600, 500 500))'::GEOMETRY"
for pred in (f"st_intersects_extent(g, {poly})", f"ST_Intersects(g, {poly})", f"g && {poly}"):
    for extra in ("", " AND fid >= 500000", " AND id >= 500000"):
        sql = f"SELECT count(*) FROM (SELECT rowid AS fid, * FROM t) WHERE {pred}{extra}"
        ref = f"SELECT count(*) FROM (SELECT rowid AS fid, * FROM t) WHERE ({pred} OR random() < 0){extra}"
        try:
            got = con.execute(sql).fetchall()[0][0]
        except Exception as e:
            got = type(e).__name__
        print(pred[:22], extra or "(solo)", "→", got, "esperado", con.execute(ref).fetchall()[0][0])
