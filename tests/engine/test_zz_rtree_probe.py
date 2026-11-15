# SPDX-License-Identifier: GPL-2.0-or-later
"""Temporal (#154): st_intersects_extent en DuckDB 1.5 tras reabrir un archivo."""

import duckdb


def test_probe(tmp_path):
    out = []
    poly = "'POLYGON((0 0, 999 0, 999 59, 0 59, 0 0))'::GEOMETRY"
    make = {
        "CTAS": "CREATE TABLE t AS SELECT range AS id, "
        "('POINT(' || (range % 1000) || ' ' || (range // 1000) || ')')::GEOMETRY AS g FROM range({n})",
        "INSERT+PK": "CREATE TABLE t (id INTEGER PRIMARY KEY, g GEOMETRY); INSERT INTO t SELECT range, "
        "('POINT(' || (range % 1000) || ' ' || (range // 1000) || ')')::GEOMETRY FROM range({n})",
    }
    for kind, ddl in make.items():
        for n in (1000000, 100000):
            for reopen in (False, True):
                path = str(tmp_path / f"{kind}{n}{reopen}.duckdb")
                con = duckdb.connect(path)
                con.execute(ddl.format(n=n))
                if reopen:
                    con.close()
                    con = duckdb.connect(path)
                sqls = {
                    "simple": f"SELECT count(*) FROM t WHERE st_intersects_extent(g, {poly})",
                    "IS TRUE": f"SELECT count(*) FROM t WHERE st_intersects_extent(g, {poly}) IS TRUE",
                    "&&": f"SELECT count(*) FROM t WHERE g && {poly}",
                    "extensión": "SELECT min(ST_XMin(g)), max(ST_XMax(g)), min(ST_YMin(g)), max(ST_YMax(g)) FROM t",
                }
                for name, sql in sqls.items():
                    try:
                        got = con.execute(sql).fetchall()[0]
                    except duckdb.Error as exc:
                        got = str(exc).splitlines()[0][:80]
                    out.append(f"SONDA {duckdb.__version__} {kind} n={n} reabierto={reopen} {name}: {got}")
                con.close()
    raise AssertionError("\n".join(out))
