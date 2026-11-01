# SPDX-License-Identifier: GPL-2.0-or-later
"""Evidencia G1 paso 3: adjuntar un archivo existente no cambia su tamaño ni su fecha (ver README.md)."""
import duckdb, os, tempfile, time
d=tempfile.mkdtemp(); p=os.path.join(d,"g.duckdb")
c=duckdb.connect(p); c.execute("create table t as select 1 x"); c.close()
time.sleep(0.05)
def sig(): s=os.stat(p); return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
con=duckdb.connect(); a=sig(); con.execute(f"ATTACH '{p}' AS g"); b=sig(); print(duckdb.__version__, "RW attach changes sig:", a!=b, a[2:], b[2:])
con.execute("select * from g.t").fetchall(); c2=sig(); print("  after read:", c2!=a)
con.execute("DETACH g"); e=sig(); print("  after detach:", e!=a)
con.execute(f"ATTACH '{p}' AS g (READ_ONLY)"); f=sig(); print("  RO attach:", f!=e)
