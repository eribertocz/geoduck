import duckdb, threading, time
def t(reader):
    c=duckdb.connect(); box={}
    def w():
        try:
            if reader:
                with c.sql("select a from range(3000000000) t(a) where a%3=0").to_arrow_reader(batch_size=8192) as r:
                    for _ in r: pass
            else: c.execute("select count(*) from range(3000000000) t(a) where a%7=3").fetchall()
            box['r']='finished'
        except Exception as e: box['r']=type(e).__name__
    th=threading.Thread(target=w); th.start(); time.sleep(0.5); t0=time.time(); c.interrupt(); th.join(30)
    ok = c.execute('select 1').fetchall()==[(1,)]
    return box.get('r'), round((time.time()-t0)*1000,1), ok, th.is_alive()
print(duckdb.__version__, 'execute', t(False), 'reader', t(True))
