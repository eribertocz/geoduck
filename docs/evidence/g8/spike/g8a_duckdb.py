# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G8-A (DuckDB, sin `spatial`): SRC personalizados con ST_SetCRS y GeoParquet con read_parquet.

Uso: python g8a_duckdb.py DIR   (DIR: carpeta temporal para el Parquet)
"""
import json
import sys
from pathlib import Path

import duckdb

out = Path(sys.argv[1])
con = duckdb.connect()
con.execute("SET autoload_known_extensions = false")
print("DuckDB", duckdb.__version__)
POINT = "ST_GeomFromWKB(from_hex('0101000000666666666609b1c0000000000080b0c0'))"

WKT2 = (
    'PROJCRS["Local TM",BASEGEOGCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",6378137,'
    '298.257223563]]],CONVERSION["TM",METHOD["Transverse Mercator"],PARAMETER["Latitude of natural origin",0],'
    'PARAMETER["Longitude of natural origin",-68],PARAMETER["Scale factor at natural origin",1],'
    'PARAMETER["False easting",500000],PARAMETER["False northing",10000000]],CS[Cartesian,2],'
    'AXIS["easting",east],AXIS["northing",north],LENGTHUNIT["metre",1]]'
)
PROJJSON = json.dumps({"type": "GeographicCRS", "name": "WGS 84 personalizado",
                       "datum": {"type": "GeodeticReferenceFrame", "name": "WGS 84",
                                 "ellipsoid": {"name": "WGS 84", "semi_major_axis": 6378137,
                                               "inverse_flattening": 298.257223563}},
                       "coordinate_system": {"subtype": "ellipsoidal", "axis": [
                           {"name": "Longitude", "abbreviation": "lon", "direction": "east", "unit": "degree"},
                           {"name": "Latitude", "abbreviation": "lat", "direction": "north", "unit": "degree"}]}})

print("\n1. ST_SetCRS sin spatial")
for label, crs in [("EPSG:32719", "EPSG:32719"), ("ESRI:102033", "ESRI:102033"), ("OGC:CRS84", "OGC:CRS84"),
                   ("WKT2 personalizado", WKT2), ("PROJJSON personalizado", PROJJSON)]:
    lit = "'" + crs.replace("'", "''") + "'"
    try:
        con.execute(f"CREATE OR REPLACE TABLE t AS SELECT ST_SetCRS({POINT}, {lit}) AS geom")
        typ = con.execute("SELECT data_type FROM duckdb_columns() WHERE table_name = 't'").fetchall()[0][0]
        tbl = con.sql("SELECT geom FROM t").arrow()
        tbl = tbl.read_all() if hasattr(tbl, "read_all") else tbl
        meta = (tbl.schema.field(0).metadata or {}).get(b"ARROW:extension:metadata", b"")[:70]
        print(f"  {label:24} OK  tipo={typ[:46]!s:48} geoarrow={meta!r}")
    except duckdb.Error as exc:
        print(f"  {label:24} ERROR {str(exc).splitlines()[0][:90]}")

print("\n2. GeoParquet escrito por DuckDB y leído con read_parquet (sin spatial)")
for version in ("V1", "V2"):
    path = out / f"puntos_{version}.parquet"
    try:
        con.execute(
            "COPY (SELECT range AS id, ST_SetCRS(ST_GeomFromWKB(from_hex('0101000000666666666609b1c0000000000080b0c0')),"
            f" 'EPSG:4326') AS geom FROM range(5)) TO '{path}' (FORMAT parquet, GEOPARQUET_VERSION '{version}')"
        )
        desc = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()
        print(f"  {version}: {[(c[0], c[1]) for c in desc]}")
    except duckdb.Error as exc:
        print(f"  {version}: ERROR {str(exc).splitlines()[0][:100]}")

print("\n3. Selección como lista de identificadores (Conectada)")
con.execute("CREATE OR REPLACE TABLE c AS SELECT range AS id, range * 2 AS v FROM range(1000000)")
import time  # noqa: E402

for n in (1_203, 100_000):
    ids = list(range(0, n * 7, 7))
    t0 = time.perf_counter()
    lst = ", ".join(str(i) for i in ids)
    con.execute(f"CREATE OR REPLACE TABLE s AS SELECT * FROM c WHERE id IN ({lst})")
    t1 = time.perf_counter()
    import pyarrow as pa  # noqa: E402

    con.register("sel", pa.table({"id": pa.array(ids, pa.int64())}))
    con.execute("CREATE OR REPLACE TABLE s2 AS SELECT c.* FROM c JOIN sel USING (id)")
    t2 = time.perf_counter()
    print(f"  {n:>7} ids: IN (lista) {1000 * (t1 - t0):6.0f} ms · JOIN con tabla Arrow {1000 * (t2 - t1):6.0f} ms · "
          f"filas {con.execute('SELECT count(*) FROM s2').fetchone()[0]}")
