# SPDX-License-Identifier: GPL-2.0-or-later
"""Temporal (#154): qué devuelve DuckDB con un índice R-tree en cada forma de consulta."""

import duckdb
import pytest


def test_probe(tmp_path):
    con = duckdb.connect(str(tmp_path / "p.duckdb"))
    try:
        con.execute("LOAD spatial")
    except duckdb.Error:
        pytest.skip("sin spatial")
    con.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, g GEOMETRY); INSERT INTO t SELECT range, "
        "('POINT(' || (range % 1000) || ' ' || (range // 1000) || ')')::GEOMETRY FROM range(1000000)"
    )
    poly = "'POLYGON((0 0, 999 0, 999 59, 0 59, 0 0))'::GEOMETRY"
    shapes = {
        "simple": f"SELECT count(*) FROM t WHERE st_intersects_extent(g, {poly})",
        "ST_Intersects": f"SELECT count(*) FROM t WHERE ST_Intersects(g, {poly})",
        "fid": f'SELECT count(*) FROM (SELECT id AS "__fid", * FROM t) WHERE st_intersects_extent(g, {poly})',
        "fid orden": f'SELECT count(*) FROM (SELECT * FROM (SELECT id AS "__fid", * FROM t) '
        f'WHERE st_intersects_extent(g, {poly}) ORDER BY "__fid" LIMIT 50000)',
        "fid sub": f'SELECT count(*) FROM (SELECT "__fid", id AS id, g AS g FROM (SELECT id AS "__fid", * FROM '
        f'(SELECT * FROM t) AS s) AS q) AS c WHERE st_intersects_extent(g, {poly})',
    }
    con.close()
    out = []
    for index in (False, True):
        con = duckdb.connect(str(tmp_path / "p.duckdb"))
        con.execute("LOAD spatial")
        if index:
            con.execute("CREATE INDEX r ON t USING RTREE (g)")
        for name, sql in shapes.items():
            try:
                got = con.execute(sql).fetchall()[0][0]
            except duckdb.Error as exc:
                got = type(exc).__name__ + ": " + str(exc).splitlines()[0]
            plan = "\n".join(r[1] for r in con.execute("EXPLAIN " + sql).fetchall())
            out.append(f"SONDA {duckdb.__version__} índice={index} {name}: {got} {'RTREE' if 'Rtree' in plan else ''}")
        con.close()
    raise AssertionError("\n".join(out))
