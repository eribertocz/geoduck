# SPDX-License-Identifier: GPL-2.0-or-later
"""F-122: una capa con tipos de geometría mixtos o con colecciones conserva el SRC de los datos.

Con un tipo de capa «desconocido» (mixtos) o `GeometryCollection`, QGIS no toma el SRC del proveedor ni del
GeoPackage: GeoDuck lo fija desde los datos. Sin SRC en los datos, ninguno (C4).
"""

from __future__ import annotations

import pytest
from qgis.core import QgsProject

from geoduck.app.events import LoadFailed, LoadFinished
from geoduck.domain.load import LoadMode, LoadRequest
from tests.qgis.conftest import wait_for
from tests.qgis.test_load_connected import TIMEOUT, Session

pytestmark = pytest.mark.qgis

MIXED = ["POINT (1 2)", "LINESTRING (0 0, 1 1)"]
COLLECTION = ["GEOMETRYCOLLECTION (POINT (1 1), LINESTRING (0 0, 1 1))"]


@pytest.fixture
def session(qgis_app):
    s = Session()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def load(session, mode):
    before = len(session.events)
    session.coordinator.load(LoadRequest(sql="SELECT * FROM t", mode=mode, layer_name="t"))

    def ended():
        return [e for e in session.events[before:] if isinstance(e, (LoadFinished, LoadFailed))]

    assert wait_for(lambda: bool(ended()), TIMEOUT)
    event = ended()[0]
    assert isinstance(event, LoadFinished), getattr(event, "message", event)
    ids = [i for i, _ in event.report.layers] or [event.report.layer_id]
    return [QgsProject.instance().mapLayer(i) for i in ids], event.report


@pytest.mark.parametrize("mode", [LoadMode.MEMORY, LoadMode.SNAPSHOT, LoadMode.CONNECTED])
@pytest.mark.parametrize("wkts", [MIXED, COLLECTION], ids=["mixtos", "coleccion"])
def test_the_crs_of_the_data_is_kept(session, mode, wkts):
    values = ", ".join(f"('{w}')" for w in wkts)
    session.sql(
        f"CREATE TABLE t AS SELECT ST_SetCRS(w::GEOMETRY, 'EPSG:32719') AS geom FROM (VALUES {values}) v(w)"
    )
    layers, report = load(session, mode)
    assert [layer.crs().authid() for layer in layers] == ["EPSG:32719"] * len(layers)
    assert not any("SRC" in w or "CRS" in w for w in report.warnings)


@pytest.mark.parametrize("mode", [LoadMode.SNAPSHOT, LoadMode.CONNECTED])
def test_without_crs_in_the_data_none_is_invented(session, mode):
    session.sql(
        "CREATE TABLE t AS SELECT w::GEOMETRY AS geom "
        "FROM (VALUES ('POINT (1 2)'), ('LINESTRING (0 0, 1 1)')) v(w)"
    )
    layers, _ = load(session, mode)
    assert all(not layer.crs().isValid() for layer in layers)
