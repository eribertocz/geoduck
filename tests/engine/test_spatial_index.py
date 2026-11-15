# SPDX-License-Identifier: GPL-2.0-or-later
"""Índice espacial R-tree desde GeoDuck (#154): crearlo, quitarlo y verlo en el catálogo."""

from __future__ import annotations

import duckdb
import pytest

from geoduck.engine.catalog import _single_column
from geoduck.engine.worker import SessionWorker

TIMEOUT = 120


def _spatial_available() -> bool:
    con = duckdb.connect()
    try:
        con.execute("LOAD spatial")
        return True
    except duckdb.Error:
        return False
    finally:
        con.close()


@pytest.mark.parametrize(
    ("expressions", "column"),
    [("[g]", ["g"]), ("['\"Geom col\"']", ["Geom col"]), (["g"], ["g"]), ("[a, b]", []), ("", [])],
)
def test_the_column_of_an_index_as_duckdb_lists_it(expressions, column):
    assert _single_column(expressions) == column


@pytest.fixture
def worker():
    w = SessionWorker(":memory:", spatial=True)
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def sql(worker, text):
    return worker.submit(lambda h, t: h.execute(text)).future.result(TIMEOUT)


@pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")
def test_create_and_remove_a_spatial_index_with_any_names(worker):
    sql(worker, 'CREATE SCHEMA "Mi esquema"')
    sql(worker, 'CREATE TABLE "Mi esquema"."Mis predios" (id INTEGER, "Geom col" GEOMETRY)')
    source = ("memory", "Mi esquema", "Mis predios")
    catalog = worker.spatial_index(source, "Geom col", None).future.result(TIMEOUT)
    index = catalog.spatial_index("MEMORY", "mi esquema", "mis predios", "geom col")
    assert index is not None and index.column == "Geom col"
    assert catalog.spatial_index(*source, "id") is None
    catalog = worker.spatial_index(source, "Geom col", index.name).future.result(TIMEOUT)
    assert catalog.spatial_indexes == ()
