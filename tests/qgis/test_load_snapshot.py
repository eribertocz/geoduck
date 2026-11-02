# SPDX-License-Identifier: GPL-2.0-or-later
"""Modalidad Instantánea (GeoPackage en /vsimem) de punta a punta (G3/E3; AT-BRD-006, 007; ADR-0012)."""

from __future__ import annotations

import duckdb
import pytest
from osgeo import gdal
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsWkbTypes

from geoduck.app.events import LoadFailed, LoadFinished, LoadProgressed
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.session import SessionState
from geoduck.qgis_bridge import snapshot
from geoduck.qgis_bridge.vsimem import PREFIX
from tests.qgis.conftest import wait_for
from tests.qgis.test_load_memory import POINTS, Session, layer_rows

pytestmark = pytest.mark.qgis

TIMEOUT = 60


def geoduck_files():
    listing = gdal.ReadDirRecursive(PREFIX.rstrip("/")) or []
    return {f for f in listing if f.endswith(".gpkg")}


class SnapshotSession(Session):
    def load(self, sql, name="capa", **kw):
        before = len(self.events)
        load_id = self.coordinator.load(LoadRequest(sql=sql, mode=LoadMode.SNAPSHOT, layer_name=name, **kw))
        assert wait_for(
            lambda: any(
                isinstance(e, (LoadFinished, LoadFailed)) and e.load_id == load_id
                for e in self.events[before:]
            ),
            TIMEOUT,
        )
        return next(e for e in self.events[before:] if isinstance(e, (LoadFinished, LoadFailed)))


@pytest.fixture
def session(qgis_app):
    if snapshot.unavailable_reason():
        pytest.skip(snapshot.unavailable_reason())
    s = SnapshotSession()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def test_full_load_is_identical_and_editable(session):
    n = 30_000
    ev = session.load(POINTS.format(n=n), name="puntos")
    assert isinstance(ev, LoadFinished), ev
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    assert layer.providerType() == "ogr"
    assert layer.source().startswith(PREFIX)
    assert ev.report.rows == layer.featureCount() == n
    assert layer.crs().authid() == "OGC:CRS84"
    assert QgsWkbTypes.displayString(layer.wkbType()) == "Point"
    rows = layer_rows(layer)
    expected = sorted((i, f"n ñ {i}", None if i % 97 == 0 else i * 0.5, None, i % 2 == 0) for i in range(n))
    for got, exp in zip(rows, expected, strict=True):
        assert (got[0], got[1], got[2], got[4]) == (exp[0], exp[1], exp[2], exp[4])
    assert rows[0][3] == "2026-01-01T00:00:00"
    assert rows[1234][5] == "Point (2.34 0.01)"
    assert session.of(LoadProgressed)
    # editable
    assert layer.startEditing()
    f = QgsFeature(layer.fields())
    f.setAttribute("id", 999999)
    f.setAttribute("nombre", "nuevo")
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1, 1)))
    assert layer.addFeature(f)
    assert layer.commitChanges()
    assert layer.featureCount() == n + 1


def test_mixed_geometry_types_become_one_layer_per_type(session):
    ev = session.load(
        "SELECT range AS id, CASE WHEN range % 2 = 0 THEN 'POINT(1 1)' WHEN range % 10 = 1 THEN NULL "
        "ELSE 'POLYGON((0 0, 1 0, 1 1, 0 0))' END::GEOMETRY AS g FROM range(1000)"
    )
    assert isinstance(ev, LoadFinished), ev
    layers = {lyr.name(): lyr for lyr in QgsProject.instance().mapLayers().values()}
    assert {n: QgsWkbTypes.displayString(lyr.wkbType()) for n, lyr in layers.items()} == {
        "capa — Point": "Point",
        "capa — Polygon": "Polygon",
        "capa — sin geometría": "NoGeometry",
    }
    assert {n: lyr.featureCount() for n, lyr in layers.items()} == {
        "capa — Point": 500,
        "capa — Polygon": 400,
        "capa — sin geometría": 100,
    }
    assert any("mixtos" in w for w in ev.report.warnings)


def test_uniform_multi_family_is_declared(session):
    ev = session.load(
        "SELECT range AS id, CASE WHEN range % 2 = 0 THEN 'POLYGON((0 0, 1 0, 1 1, 0 0))' "
        "ELSE 'MULTIPOLYGON(((0 0, 1 0, 1 1, 0 0)))' END::GEOMETRY AS g FROM range(100)"
    )
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    assert QgsWkbTypes.displayString(layer.wkbType()) == "MultiPolygon"


def test_engine_error_mid_read_publishes_nothing_and_frees_vsimem(session):
    before_layers, before_files = set(QgsProject.instance().mapLayers()), geoduck_files()
    ev = session.load(
        "SELECT range AS id, CASE WHEN range < 30000 THEN range ELSE error('fallo') END AS x "
        "FROM range(40000)"
    )
    assert isinstance(ev, LoadFailed)
    assert "fallo" in ev.message
    assert set(QgsProject.instance().mapLayers()) == before_layers
    assert geoduck_files() == before_files
    assert session.coordinator.state is SessionState.READY


def test_cancel_publishes_nothing_and_frees_vsimem(session):
    before_layers, before_files = set(QgsProject.instance().mapLayers()), geoduck_files()
    load_id = session.coordinator.load(
        LoadRequest(sql=POINTS.format(n=5_000_000), mode=LoadMode.SNAPSHOT, layer_name="larga")
    )
    assert wait_for(
        lambda: any(
            isinstance(e, LoadProgressed) and e.load_id == load_id and e.rows > 0 for e in session.events
        ),
        TIMEOUT,
    )
    assert session.coordinator.cancel_current_operation()
    assert wait_for(
        lambda: any(isinstance(e, LoadFailed) and e.load_id == load_id for e in session.events), TIMEOUT
    )
    assert next(e for e in session.events if isinstance(e, LoadFailed)).cancelled
    assert set(QgsProject.instance().mapLayers()) == before_layers
    assert geoduck_files() == before_files
    assert session.coordinator.state is SessionState.READY


def test_user_column_named_fid_is_kept(session):
    ev = session.load("SELECT 'x' AS fid, 7 AS id, 'POINT(0 0)'::GEOMETRY AS g")
    assert isinstance(ev, LoadFinished), ev
    f = next(QgsProject.instance().mapLayer(ev.report.layer_id).getFeatures())
    assert f["fid"] == "x" and f["id"] == 7


def test_vsimem_is_freed_only_after_the_last_layer_is_removed(session):
    ev = session.load("SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY AS g")
    project = QgsProject.instance()
    first_id = ev.report.layer_id
    path = project.mapLayer(first_id).source().split("|")[0]
    twin_id = project.addMapLayer(project.mapLayer(first_id).clone()).id()  # QGIS es dueño de la copia
    project.removeMapLayer(first_id)
    assert gdal.VSIStatL(path) is not None  # la duplicada sigue usándolo
    assert sum(1 for _ in project.mapLayer(twin_id).getFeatures()) == 1
    project.removeMapLayer(twin_id)
    assert gdal.VSIStatL(path) is None


def test_crs_override_and_unknown_crs(session):
    ev = session.load("SELECT 'POINT(1 2)'::GEOMETRY AS g", crs_override="EPSG:32719")
    assert QgsProject.instance().mapLayer(ev.report.layer_id).crs().authid() == "EPSG:32719"
    ev = session.load("SELECT 'POINT(1 2)'::GEOMETRY AS g")
    assert "Sin SRC asignado" in ev.report.warnings


def test_layers_survive_detach_and_close(qgis_app, tmp_path):
    if snapshot.unavailable_reason():
        pytest.skip(snapshot.unavailable_reason())
    db = tmp_path / "datos.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE t AS SELECT range AS id, ('POINT(' || range || ' 0)')::GEOMETRY AS g FROM range(500)"
    )
    con.close()
    s = SnapshotSession()
    s.coordinator.attach_database(
        AttachRequest(str(db), AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING, alias="d")
    )
    assert wait_for(
        lambda: (
            s.coordinator.state is SessionState.READY
            and s.coordinator.catalog is not None
            and any(d.name == "d" for d in s.coordinator.catalog.databases)
        ),
        TIMEOUT,
    )
    ev = s.load("SELECT * FROM d.t", name="t")
    assert isinstance(ev, LoadFinished)
    s.coordinator.detach_database("d")
    assert wait_for(lambda: s.coordinator.state is SessionState.READY, TIMEOUT)
    s.close()
    db.unlink()
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    assert sum(1 for _ in layer.getFeatures()) == 500
    QgsProject.instance().removeAllMapLayers()


def test_unavailable_with_old_gdal(monkeypatch):
    monkeypatch.setattr(snapshot.gdal, "VersionInfo", lambda *a: "3070300")
    assert "GDAL 3.8" in snapshot.unavailable_reason()
