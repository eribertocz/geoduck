# SPDX-License-Identifier: GPL-2.0-or-later
"""Temporal (#154): st_intersects_extent en DuckDB 1.5 con y sin spatial."""

import duckdb


def test_probe(tmp_path):
    out = []
    poly = "'POLYGON((0 0, 999 0, 999 59, 0 59, 0 0))'::GEOMETRY"
    for where in ("memoria", "archivo"):
        for spatial in (False, True):
            con = duckdb.connect(":memory:" if where == "memoria" else str(tmp_path / f"p{spatial}.duckdb"))
            if spatial:
                try:
                    con.execute("LOAD spatial")
                except duckdb.Error:
                    out.append("sin spatial")
                    continue
            con.execute(
                "CREATE TABLE t AS SELECT range AS id, "
                "('POINT(' || (range % 1000) || ' ' || (range // 1000) || ')')::GEOMETRY AS g FROM range(1000000)"
            )
            for name, sql in {
                "simple": f"SELECT count(*) FROM t WHERE st_intersects_extent(g, {poly})",
                "IS TRUE": f"SELECT count(*) FROM t WHERE st_intersects_extent(g, {poly}) IS TRUE",
                "200 filas": f"SELECT count(*) FROM (SELECT * FROM t LIMIT 200) WHERE st_intersects_extent(g, {poly})",
                "un punto": "SELECT st_intersects_extent('POINT(5 5)'::GEOMETRY, "
                f"{poly})",
            }.items():
                try:
                    got = con.execute(sql).fetchall()[0][0]
                except duckdb.Error as exc:
                    got = str(exc).splitlines()[0]
                plan = " ".join(
                    line.strip() for r in con.execute("EXPLAIN " + sql).fetchall() for line in r[1].splitlines()
                    if "Filter" in line or "intersects" in line.lower()
                )
                out.append(f"SONDA {duckdb.__version__} {where} spatial={spatial} {name}: {got} | {plan[:160]}")
            con.close()
    raise AssertionError("\n".join(out))
