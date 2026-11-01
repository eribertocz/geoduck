import duckdb
con=duckdb.connect(':memory:')
print("duckdb", duckdb.__version__)
def t(label, sql):
    try: print(f"  OK  {label}: {con.execute(sql).fetchall()!r}"[:240])
    except Exception as e: print(f"  ERR {label}: {type(e).__name__}: {str(e).splitlines()[0][:160]}")
t("plain GEOMETRY col create", "create table p(g GEOMETRY)")
t("crs table", "create table g(id int, geom GEOMETRY('OGC:CRS84'), g2 GEOMETRY)")
t("insert", "insert into g values (1, 'POINT(1 2)'::GEOMETRY('OGC:CRS84'), ST_AsWKB('POINT(1 2)'::GEOMETRY('OGC:CRS84'))::GEOMETRY), (2,NULL,NULL)")
t("insert v2", "insert into g select 3, 'POLYGON((0 0,1 0,1 1,0 0))'::GEOMETRY('OGC:CRS84'), NULL")
t("known crs list?", "select * from duckdb_functions() where function_name ilike '%crs%' limit 5")
t("ST_CRS col", "select ST_CRS(geom), ST_CRS(g2) from g limit 1")
t("information_schema", "select column_name,data_type from information_schema.columns where table_name='g'")
try:
    rel=con.sql("select * from g")
    print("  rel.types:", [str(x) for x in rel.types])
    at=rel.to_arrow_table()
    for f in at.schema: print("   field", f.name, f.type, f.metadata)
    print("  geom values:", at.column('geom').to_pylist())
except Exception as e: print("  ERR arrow:", type(e).__name__, str(e)[:200])
for setting in ["arrow_extension_types", "arrow_lossless_conversion"]:
    t("setting "+setting, f"select current_setting('{setting}')")
