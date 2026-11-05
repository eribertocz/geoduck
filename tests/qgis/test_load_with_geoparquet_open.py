# SPDX-License-Identifier: GPL-2.0-or-later
"""Cargar de DuckDB a QGIS después de abrir un GeoParquet en QGIS (F-121).

En QGIS de conda, GDAL comparte la biblioteca Arrow con pyarrow y, al abrir un GeoParquet, registra
`geoarrow.wkb`: sin la corrección, las cargas fallaban («binary_slice») o perdían el SRC.
"""

from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from osgeo import ogr
from qgis.core import QgsProject, QgsVectorLayer

from geoduck.app.events import LoadFailed, LoadFinished
from geoduck.domain.load import LoadMode, LoadRequest
from tests.qgis.conftest import wait_for
from tests.qgis.test_load_connected import TIMEOUT, Session

pytestmark = pytest.mark.qgis

#: POINT(1 2) en WKB.
WKB = bytes.fromhex("0101000000000000000000f03f0000000000000040")


@pytest.fixture
def session(qgis_app):
    s = Session()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def open_geoparquet(tmp_path):
    if ogr.GetDriverByName("Parquet") is None:
        pytest.skip("GDAL sin el controlador Parquet (QGIS 3.34 de conda-forge)")
    geo = {"version": "1.0.0", "primary_column": "geometry", "columns": {"geometry": {"encoding": "WKB"}}}
    table = pa.table({"nombre": ["a"], "geometry": pa.array([WKB], pa.binary())})
    pq.write_table(table.replace_schema_metadata({b"geo": json.dumps(geo).encode()}), tmp_path / "x.parquet")
    layer = QgsVectorLayer(str(tmp_path / "x.parquet"), "x", "ogr")
    assert layer.isValid() and layer.featureCount() == 1


@pytest.mark.parametrize("mode", [LoadMode.MEMORY, LoadMode.SNAPSHOT, LoadMode.CONNECTED])
def test_load_keeps_working_and_keeps_the_crs(session, tmp_path, mode):
    open_geoparquet(tmp_path)
    session.sql(
        "CREATE TABLE p AS SELECT range AS id, "
        "ST_SetCRS(('POINT(' || range || ' 1)')::GEOMETRY, 'EPSG:32719') AS geom FROM range(50)"
    )
    before = len(session.events)
    load_id = session.coordinator.load(LoadRequest(sql="SELECT * FROM p", mode=mode, layer_name="p"))
    assert wait_for(
        lambda: any(
            isinstance(e, (LoadFinished, LoadFailed)) and e.load_id == load_id
            for e in session.events[before:]
        ),
        TIMEOUT,
    )
    event = next(e for e in session.events[before:] if isinstance(e, (LoadFinished, LoadFailed)))
    assert isinstance(event, LoadFinished), getattr(event, "message", event)
    layer = QgsProject.instance().mapLayer(event.report.layer_id)
    assert layer.featureCount() == 50
    assert layer.crs().authid() == "EPSG:32719"
