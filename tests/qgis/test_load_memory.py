# SPDX-License-Identifier: GPL-2.0-or-later
"""Modalidad Memoria de punta a punta (G3/E2; AT-BRD-001..005, AT-BRD-007; ADR-0012).

Coordinador, worker DuckDB y QGIS reales.
"""

from __future__ import annotations

import duckdb
import pytest
from qgis.core import QgsProject, QgsWkbTypes

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import LoadFailed, LoadFinished, LoadPrepared, LoadProgressed
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.session import SessionState
from geoduck.engine.worker import SessionWorker
from geoduck.qgis_bridge.loader import BridgeLoader
from geoduck.ui.dispatcher import QtDispatcher
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

TIMEOUT = 60

POINTS = (
    "SELECT range AS id, 'n ñ ' || range AS nombre, "
    "CASE WHEN range % 97 = 0 THEN NULL ELSE range * 0.5::DOUBLE END AS valor, "
    "TIMESTAMP '2026-01-01' + to_seconds(range) AS instante, range % 2 = 0 AS activo, "
    "('POINT(' || (range % 1000) * 0.01 || ' ' || (range // 1000) * 0.01 || ')')"
    "::GEOMETRY('OGC:CRS84') AS geom "
    "FROM range({n})"
)


class Session:
    def __init__(self):
        self.events = []
        self.loader = BridgeLoader()
        self.coordinator = SessionCoordinator(SessionWorker, QtDispatcher(), self.loader)
        self.coordinator.subscribe(self.events.append)
        self.coordinator.start_memory_session()
        assert wait_for(lambda: self.coordinator.state is SessionState.READY, TIMEOUT)

    def of(self, kind):
        return [e for e in self.events if isinstance(e, kind)]

    def load(self, sql, name="capa", **kw):
        before = len(self.events)
        load_id = self.coordinator.load(LoadRequest(sql=sql, mode=LoadMode.MEMORY, layer_name=name, **kw))
        assert wait_for(
            lambda: any(
                isinstance(e, (LoadFinished, LoadFailed)) and e.load_id == load_id
                for e in self.events[before:]
            ),
            TIMEOUT,
        )
        return next(e for e in self.events[before:] if isinstance(e, (LoadFinished, LoadFailed)))

    def close(self):
        self.coordinator.shutdown()
        self.loader.shutdown()  # como plugin.unload: sin señales de QgsProject hacia Python al salir


@pytest.fixture
def session(qgis_app):
    s = Session()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def layer_rows(layer):
    out = []
    for f in layer.getFeatures():
        dt = f["instante"]
        out.append(
            (
                f["id"],
                f["nombre"],
                None
                if f["valor"] is None
                or f["valor"] == ""
                or (hasattr(f["valor"], "isNull") and f["valor"].isNull())
                else f["valor"],
                dt.toString("yyyy-MM-ddTHH:mm:ss"),
                f["activo"],
                f.geometry().asWkt(2),
            )
        )
    return sorted(out)


def test_full_load_is_identical_row_by_row(session):
    n = 30_000
    ev = session.load(POINTS.format(n=n), name="puntos")
    assert isinstance(ev, LoadFinished), ev
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    assert layer is not None and layer.providerType() == "memory"
    assert ev.report.rows == layer.featureCount() == n
    assert layer.crs().authid() == "OGC:CRS84"
    assert QgsWkbTypes.displayString(layer.wkbType()) == "Point"
    assert [f.name() for f in layer.fields()] == ["id", "nombre", "valor", "instante", "activo"]
    rows = layer_rows(layer)
    expected = sorted((i, f"n ñ {i}", None if i % 97 == 0 else i * 0.5, None, i % 2 == 0) for i in range(n))
    for got, exp in zip(rows, expected, strict=True):
        assert got[0] == exp[0] and got[1] == exp[1] and got[2] == exp[2] and got[4] == exp[4]
    first = rows[0]
    assert first[3] == "2026-01-01T00:00:00"
    assert first[5] == "Point (0 0)"
    assert rows[1234][5] == "Point (2.34 0.01)"
    assert session.of(LoadProgressed)
    assert session.coordinator.state is SessionState.READY


def test_types_follow_section_7(session):
    ev = session.load(
        "SELECT 1::HUGEINT * 170141183460469231731687303715884105727 AS hi, 1234567.89::DECIMAL(9,2) AS d9, "
        "'b'::ENUM('a','b') AS en, DATE '2026-11-01' AS fecha, TIMESTAMPTZ '2026-11-01 12:00:00+02' AS tz, "
        "[1,2] AS li, '\\xAA'::BLOB AS bl, NULL::INTEGER AS nul"
    )
    assert isinstance(ev, LoadFinished), ev
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    f = next(layer.getFeatures())
    assert f["hi"] == "170141183460469231731687303715884105727"
    assert f["d9"] == pytest.approx(1234567.89)
    assert f["en"] == "b"
    assert f["fecha"].toString("yyyy-MM-dd") == "2026-11-01"
    assert f["tz"].toUTC().toString("yyyy-MM-ddTHH:mm:ss") == "2026-11-01T10:00:00"
    assert f["li"] == "[1,2]"
    assert bytes(f["bl"]) == b"\xaa"
    assert f["nul"] is None or (hasattr(f["nul"], "isNull") and f["nul"].isNull())
    assert any("HUGEINT" in w for w in ev.report.warnings)


def test_failure_at_row_30001_publishes_nothing(session):
    sql = (
        "SELECT range AS id, CASE WHEN range < 30000 THEN 'POINT(1 1)' ELSE 'POLYGON((0 0, 1 0, 1 1, 0 0))' "
        "END::GEOMETRY AS g FROM range(30010)"
    )
    layers_before = set(QgsProject.instance().mapLayers())
    # G4: por defecto los tipos mixtos se separan (spatial-spec §6); sin esa opción, fila 30 001 = fallo
    ev = session.load(sql, split_families=False)
    assert isinstance(ev, LoadFailed)
    assert "tipos distintos" in ev.message
    assert set(QgsProject.instance().mapLayers()) == layers_before
    assert session.coordinator.state is SessionState.READY


def test_cancel_publishes_nothing_and_frees_the_session(session):
    layers_before = set(QgsProject.instance().mapLayers())
    load_id = session.coordinator.load(
        LoadRequest(sql=POINTS.format(n=3_000_000), mode=LoadMode.MEMORY, layer_name="larga")
    )
    assert wait_for(
        lambda: any(isinstance(e, LoadProgressed) and e.load_id == load_id for e in session.events), TIMEOUT
    )
    assert session.coordinator.cancel_current_operation()
    assert wait_for(
        lambda: any(isinstance(e, LoadFailed) and e.load_id == load_id for e in session.events), TIMEOUT
    )
    ev = next(e for e in session.events if isinstance(e, LoadFailed) and e.load_id == load_id)
    assert ev.cancelled
    assert set(QgsProject.instance().mapLayers()) == layers_before
    assert session.coordinator.state is SessionState.READY
    assert isinstance(session.load("SELECT 1 AS x"), LoadFinished)


def test_null_geometries_first_and_promotion_to_multi(session):
    sql = (
        "SELECT range AS id, CASE WHEN range < 2000 THEN NULL WHEN range % 2 = 0 THEN 'POINT(1 1)' "
        "ELSE 'MULTIPOINT((1 1), (2 2))' END::GEOMETRY AS g FROM range(5000)"
    )
    ev = session.load(sql)
    assert isinstance(ev, LoadFinished), ev
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    assert layer.featureCount() == 5000
    assert QgsWkbTypes.isMultiType(layer.wkbType())
    assert sum(1 for f in layer.getFeatures() if not f.hasGeometry()) == 2000


def test_empty_result_and_table_without_geometry(session):
    ev = session.load("SELECT range AS id FROM range(0)")
    assert isinstance(ev, LoadFinished), ev
    assert QgsProject.instance().mapLayer(ev.report.layer_id).featureCount() == 0
    ev = session.load("SELECT range AS id, 'x' AS t FROM range(10)")
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    assert layer.featureCount() == 10 and not layer.isSpatial()


def test_unknown_crs_warns_or_uses_the_user_choice(session):
    ev = session.load("SELECT 'POINT(1 2)'::GEOMETRY AS g")
    assert isinstance(ev, LoadFinished)
    assert not QgsProject.instance().mapLayer(ev.report.layer_id).crs().isValid()
    assert "Sin SRC asignado" in ev.report.warnings
    ev = session.load("SELECT 'POINT(1 2)'::GEOMETRY AS g", crs_override="EPSG:32719")
    assert QgsProject.instance().mapLayer(ev.report.layer_id).crs().authid() == "EPSG:32719"


def test_prepare_reports_geometries_and_warnings(session):
    token = session.coordinator.prepare_load(
        "SELECT 'POINT(0 0)'::GEOMETRY AS a, 'POINT(1 1)'::GEOMETRY AS b, 1::HUGEINT AS h", "b"
    )
    assert wait_for(
        lambda: any(isinstance(e, LoadPrepared) and e.token == token for e in session.events), TIMEOUT
    )
    plan = next(e for e in session.events if isinstance(e, LoadPrepared)).plan
    assert plan.geometry.name == "b"
    assert any("«a»" in w for w in plan.warnings)


def test_layers_survive_detach_and_close(qgis_app, tmp_path):
    db = tmp_path / "datos.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE t AS SELECT range AS id, ('POINT(' || range || ' 0)')::GEOMETRY AS g FROM range(500)"
    )
    con.close()
    s = Session()
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
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    assert layer.featureCount() == 500
    s.close()
    db.unlink()
    assert sum(1 for _ in layer.getFeatures()) == 500
    assert layer.getFeature(1).geometry().asWkt() == "Point (0 0)"
    QgsProject.instance().removeAllMapLayers()
