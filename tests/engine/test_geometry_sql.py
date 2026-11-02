# SPDX-License-Identifier: GPL-2.0-or-later
"""SQL de geometría de G4 con DuckDB real y sin `spatial` (spatial-spec §5, §6; F-92, F-94).

Se ejecuta en la matriz de DuckDB del motor (1.5.0, 1.5.6, 2.0.0).
"""

from __future__ import annotations

import duckdb
import pytest

from geoduck.domain.bridge_types import (
    FAMILY_CODES,
    GeometryFormat,
    family_code_sql,
    family_filter_sql,
    geometry_read_sql,
    wkb_family,
)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("SET autoload_known_extensions = false")
    yield c
    c.close()


CASES = [
    ("POINT(1 2)", "Point"),
    ("MULTIPOINT((1 2),(3 4))", "Point"),
    ("LINESTRING Z(0 0 1, 1 1 1)", "LineString"),
    ("MULTILINESTRING((0 0, 1 1))", "LineString"),
    ("POLYGON M((0 0 1, 1 0 1, 1 1 1, 0 0 1))", "Polygon"),
    ("MULTIPOLYGON ZM(((0 0 1 2, 1 0 1 2, 1 1 1 2, 0 0 1 2)))", "Polygon"),
    ("GEOMETRYCOLLECTION(POINT(1 2))", "GeometryCollection"),
    ("POINT EMPTY", "Point"),
]


@pytest.mark.parametrize(("wkt", "family"), CASES)
def test_family_from_the_wkb_header_without_spatial(con, wkt, family):
    code = con.execute(f"SELECT {family_code_sql(repr(wkt) + '::VARCHAR::GEOMETRY')}").fetchall()[0][0]
    assert wkb_family(code) == family
    cond = family_filter_sql(repr(wkt) + "::VARCHAR::GEOMETRY", family)
    assert con.execute(f"SELECT {cond}").fetchall()[0][0] is True
    other = next(f for f in FAMILY_CODES if f != family)
    assert (
        con.execute(f"SELECT {family_filter_sql(repr(wkt) + '::VARCHAR::GEOMETRY', other)}").fetchall()[0][0]
        is False
    )


def test_null_geometry_matches_no_family(con):
    assert con.execute(f"SELECT {family_filter_sql('NULL::GEOMETRY', 'Point')}").fetchall()[0][0] is None


def test_wkb_and_wkt_columns_convert_and_unreadable_is_null(con):
    con.execute(
        "CREATE TABLE t AS SELECT * FROM (VALUES "
        "(from_hex('0101000000000000000000F03F0000000000000040'), 'POINT (1 2)'), "
        "(from_hex('000000000140080000000000004010000000000000'), 'LINESTRING (0 0, 1 1)'), "
        "(from_hex('0101'), 'no es WKT'), (NULL, NULL)) v(w, t)"
    )
    wkb = geometry_read_sql("w", GeometryFormat.WKB)
    wkt = geometry_read_sql("t", GeometryFormat.WKT)
    rows = con.execute(
        f"SELECT ST_AsText({wkb}), ST_AsText({wkt}), w IS NOT NULL AND {wkb} IS NULL FROM t"
    ).fetchall()
    assert rows == [
        ("POINT (1 2)", "POINT (1 2)", False),
        ("POINT (3 4)", "LINESTRING (0 0, 1 1)", False),  # WKB big-endian
        (None, None, True),
        (None, None, False),
    ]
