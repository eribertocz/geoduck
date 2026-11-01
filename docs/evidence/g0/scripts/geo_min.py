import duckdb
con=duckdb.connect(':memory:')
con.execute("create table g(id int, geom GEOMETRY('OGC:CRS84'))")
con.execute("insert into g select 1, 'POINT(1 2)'::GEOMETRY('OGC:CRS84')")
res={}
for name, fn in [("rel.to_arrow_table", lambda: con.sql("select * from g").to_arrow_table()),
                 ("rel.to_arrow_reader", lambda: con.sql("select * from g").to_arrow_reader(batch_size=1024).read_all()),
                 ("ST_AsWKB via reader", lambda: con.sql("select id, ST_AsWKB(geom) w from g").to_arrow_reader(batch_size=1024).read_all()),
                 ("fetchall", lambda: con.sql("select * from g").fetchall())]:
    try:
        t=fn(); res[name]="OK "+(str(t.schema.field(1).type)+" "+str((t.schema.field(1).metadata or {}).get(b'ARROW:extension:name')) if hasattr(t,'schema') else str(t)[:60])
    except Exception as e: res[name]=f"ERR {type(e).__name__}: {str(e).splitlines()[0][:90]}"
print(duckdb.__version__, res)
