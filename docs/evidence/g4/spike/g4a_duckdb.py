# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G4-A (DuckDB, sin `spatial`): cabecera WKB, WKB/WKT desde BLOB/VARCHAR, filtro por extensión.

Uso: python g4a_duckdb.py  (con el DuckDB a probar; no carga ni instala extensiones)
"""
import time

import duckdb

con = duckdb.connect()
loaded = con.sql("SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'").fetchall()[0]
print("DuckDB", duckdb.__version__, "· spatial cargada:", bool(loaded and loaded[0]))
print("Funciones ST_ del núcleo:", [r[0] for r in con.sql(
    "SELECT DISTINCT function_name FROM duckdb_functions() WHERE function_name ILIKE 'st\\_%' ESCAPE '\\' ORDER BY 1"
).fetchall()])

FAMILY = ("CASE WHEN substr(h,1,2)='01' THEN ('0x'||substr(h,5,2)||substr(h,3,2))::INT "
          "ELSE ('0x'||substr(h,7,4))::INT END % 1000")
print("\n1. Código de tipo ISO desde la cabecera de ST_AsWKB (1/4 punto, 2/5 línea, 3/6 polígono, 7 colección)")
wkts = ["POINT(1 2)", "MULTIPOINT((1 2))", "LINESTRING Z(0 0 1,1 1 1)", "POLYGON M((0 0 1,1 0 1,1 1 1,0 0 1))",
        "MULTIPOLYGON ZM(((0 0 1 2,1 0 1 2,1 1 1 2,0 0 1 2)))", "GEOMETRYCOLLECTION(POINT(1 2))", "POINT EMPTY"]
vals = ",".join(f"('{w}')" for w in wkts)
for w, code in con.sql(f"SELECT w, {FAMILY} FROM (SELECT w, hex(ST_AsWKB(w::GEOMETRY)) h FROM (VALUES {vals}) t(w))").fetchall():
    print(f"  {w:55} → {code}")
big_endian = "00000000013FF00000000000004000000000000000"
print("  WKB big-endian (BLOB) normalizado a little-endian:",
      con.sql(f"SELECT substr(hex(ST_AsWKB(ST_GeomFromWKB(from_hex('{big_endian}')))),1,2)").fetchall()[0][0] == "01")

print("\n2. BLOB (WKB) y VARCHAR (WKT) → GEOMETRY con TRY (ilegible → NULL)")
for label, sql in [
    ("WKB válido", "ST_GeomFromWKB(from_hex('0101000000000000000000F03F0000000000000040')) IS NOT NULL"),
    ("WKB truncado", "TRY(ST_GeomFromWKB(from_hex('0101000000'))) IS NULL"),
    ("WKB basura", "TRY(ST_GeomFromWKB(from_hex('FF'))) IS NULL"),
    ("WKT válido", "'POINT(1 2)'::VARCHAR::GEOMETRY IS NOT NULL"),
    ("WKT ilegible", "TRY('xx'::VARCHAR::GEOMETRY) IS NULL"),
    ("WKT de vuelta (ST_AsText)", "ST_AsText('POINT(1 2)'::VARCHAR::GEOMETRY) = 'POINT (1 2)'"),
    ("filtro ST_Intersects_Extent sobre WKB", "ST_Intersects_Extent(ST_GeomFromWKB(from_hex('0101000000000000000000F03F0000000000000040')), 'POLYGON((0 0,5 0,5 5,0 5,0 0))'::VARCHAR::GEOMETRY)"),
]:
    try:
        print(f"  {label:40} {con.sql('SELECT ' + sql).fetchall()[0][0]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {label:40} ERROR {str(exc)[:80]}")

print("\n3. Coste de la muestra de tipos (1 M de filas mixtas)")
con.sql("CREATE TABLE t AS SELECT i, CASE WHEN i % 3 = 0 THEN ST_GeomFromWKB(ST_AsWKB('POINT(1 2)'::VARCHAR::GEOMETRY)) "
        "ELSE 'LINESTRING(0 0,1 1)'::VARCHAR::GEOMETRY END AS g FROM range(1000000) r(i)")
for n in (1000, 10000):
    t0 = time.perf_counter()
    con.sql(f"SELECT DISTINCT {FAMILY} FROM (SELECT hex(ST_AsWKB(g)) h FROM t LIMIT {n})").fetchall()
    print(f"  muestra de {n:>6} filas: {1000 * (time.perf_counter() - t0):.1f} ms")
t0 = time.perf_counter()
con.sql(f"SELECT count(*) FROM (SELECT hex(ST_AsWKB(g)) h FROM t) WHERE {FAMILY} IN (2,5)").fetchall()
print(f"  filtro de familia sobre 1 M filas: {1000 * (time.perf_counter() - t0):.0f} ms")
