import duckdb, sys
con=duckdb.connect(':memory:')
def t(label, sql):
    try:
        r=con.execute(sql).fetchall(); print(f"  OK  {label}: {r!r}"[:220])
    except Exception as e:
        print(f"  ERR {label}: {type(e).__name__}: {str(e).splitlines()[0][:160]}")
print("duckdb", duckdb.__version__)
t("GEOMETRY core cast", "select 'POINT(1 2)'::GEOMETRY")
t("GEOMETRY('OGC:CRS84') type", "select typeof('POINT(1 2)'::GEOMETRY('OGC:CRS84'))")
t("GEOMETRY('EPSG:32719') type", "select typeof('POINT(1 2)'::GEOMETRY('EPSG:32719'))")
t("ST_CRS core", "select ST_CRS('POINT(1 2)'::GEOMETRY('EPSG:4326'))")
t("ST_SetCRS core", "select typeof(ST_SetCRS('POINT(1 2)'::GEOMETRY,'EPSG:3857'))")
t("ST_AsWKB core", "select ST_AsWKB('POINT(1 2)'::GEOMETRY)")
t("ST_GeomFromText core", "select ST_GeomFromText('POINT(1 2)')")
t("ST_GeometryType core", "select ST_GeometryType('POINT(1 2)'::GEOMETRY)")
t("geometry_always_xy setting", "select current_setting('geometry_always_xy')")
t("table w/ crs col", "create table g(id int, geom GEOMETRY('EPSG:4326'), g2 GEOMETRY); insert into g values (1,'POINT(1 2)','LINESTRING(0 0,1 1)'), (2,NULL,'POLYGON((0 0,1 0,1 1,0 0))')")
t("information_schema data_type", "select column_name,data_type from information_schema.columns where table_name='g'")
t("duckdb_columns", "select column_name,data_type from duckdb_columns() where table_name='g'")
try:
    rel=con.sql("select * from g")
    print("  rel.types:", [str(x) for x in rel.types])
    at=rel.to_arrow_table()
    print("  arrow schema:", at.schema.to_string().replace('\n',' | ')[:400])
    for f in at.schema: print("   field", f.name, f.type, f.metadata)
    print("  geom py values:", at.column('geom').to_pylist())
except Exception as e: print("  ERR arrow:", type(e).__name__, str(e)[:200])
