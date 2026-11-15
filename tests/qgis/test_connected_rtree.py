# SPDX-License-Identifier: GPL-2.0-or-later
"""Capas Conectadas sobre tablas con índice espacial R-tree (#154)."""

from __future__ import annotations

import duckdb
import pytest
from qgis.core import QgsFeatureRequest, QgsProject, QgsRectangle

from tests.qgis.test_lifecycle_connected import attach
from tests.qgis.test_load_connected import Session

pytestmark = pytest.mark.qgis

ROWS = 1_000_000


def _spatial_available() -> bool:
    con = duckdb.connect()
    try:
        con.execute("LOAD spatial")
        return True
    except duckdb.Error:
        return False
    finally:
        con.close()


needs_spatial = pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")


@pytest.fixture
def session(qgis_app, monkeypatch):
    monkeypatch.setenv("GEODUCK_SPATIAL", "1")
    s = Session()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def make_db(path, key):
    con = duckdb.connect(str(path))
    con.execute("LOAD spatial")
    pk = "id INTEGER PRIMARY KEY" if key else "id INTEGER"
    con.execute(
        f"CREATE TABLE t ({pk}, g GEOMETRY); "
        "INSERT INTO t SELECT range, ('POINT(' || (range % 1000) || ' ' || (range // 1000) || ')')::GEOMETRY "
        f"FROM range({ROWS}); CREATE INDEX r ON t USING RTREE (g)"
    )
    con.close()
    return path


@needs_spatial
@pytest.mark.parametrize("key", [True, False], ids=["con-clave", "sin-clave"])
def test_a_view_over_an_rtree_table_reads_every_feature(session, tmp_path, key):
    attach(session, make_db(tmp_path / "rtree.duckdb", key))
    _, layer = session.load('SELECT * FROM "d"."main"."t"', name="t", source=("d", "main", "t"))
    # 60 000 de 1 000 000 puntos: DuckDB usa el índice y la vista ocupa dos páginas
    request = QgsFeatureRequest().setFilterRect(QgsRectangle(0, 0, 999, 59))
    assert sum(1 for _ in layer.getFeatures(request)) == 60_000
    assert not layer.dataProvider().unavailable
