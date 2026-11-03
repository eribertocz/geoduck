# SPDX-License-Identifier: GPL-2.0-or-later
"""G4/E2: CRS, orden de ejes y reproyección (AT-SPA-003; spatial-spec §4, §8 AX-1..AX-5, §10).

Punto de referencia `POINT(-68.15 -16.5)` (La Paz). Tolerancias: 1e-9 en grados, 0,01 m en metros. Cada
prueba verifica coordenadas **y** CRS. Las pruebas que necesitan `spatial` se saltan si la extensión no
está instalada en el equipo (GeoDuck no la instala por su cuenta).
"""

from __future__ import annotations

import duckdb
import pytest
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)

from geoduck.app.events import (
    LoadFailed,
    LoadFinished,
    LoadPrepared,
    SpatialActivated,
    SpatialChecked,
    StatementFinished,
)
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.sql import RunScope
from geoduck.engine.probe import probe_spatial
from geoduck.infra.diagnostics import _check_spatial
from geoduck.ui.load_dialog import LoadDialog
from tests.qgis.conftest import wait_for
from tests.qgis.test_multi_geometry import TIMEOUT, Session

pytestmark = pytest.mark.qgis

LON, LAT = -68.15, -16.5
UTM = (590716.04, 8175564.99)
POINT = f"'POINT({LON} {LAT})'"
COPIES = [LoadMode.MEMORY, LoadMode.SNAPSHOT]


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
def session(qgis_app):
    s = Session()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def only_layer():
    layers = list(QgsProject.instance().mapLayers().values())
    assert len(layers) == 1
    return layers[0]


def point_of(layer):
    feats = list(layer.getFeatures())
    assert len(feats) == 1
    return feats[0].geometry().asPoint()


def to_utm(crs, p):
    tr = QgsCoordinateTransform(crs, QgsCoordinateReferenceSystem("EPSG:32719"), QgsProject.instance())
    return tr.transform(QgsPointXY(p))


def assert_lapaz_degrees(layer, authid):
    assert layer.crs().authid() == authid
    p = point_of(layer)
    assert p.x() == pytest.approx(LON, abs=1e-9) and p.y() == pytest.approx(LAT, abs=1e-9)
    return p


def activate(session):
    session.coordinator.activate_spatial(install=False)
    assert wait_for(lambda: any(isinstance(e, SpatialActivated) for e in session.events), TIMEOUT)


def run(session, sql):
    before = len(session.events)
    session.coordinator.execute_sql(sql, RunScope.ALL)
    assert wait_for(lambda: any(isinstance(e, StatementFinished) for e in session.events[before:]), TIMEOUT)
    return next(e for e in session.events[before:] if isinstance(e, StatementFinished)).result


# -- AX-1: CRS declarado, ejes sin reordenar ----------------------------------------------------------


@pytest.mark.parametrize("mode", list(LoadMode))
def test_ax_1a_crs84(session, mode):
    ev = session.load(mode, f"SELECT {POINT}::GEOMETRY('OGC:CRS84') AS g")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = only_layer()
    p = assert_lapaz_degrees(layer, "OGC:CRS84")
    u = to_utm(layer.crs(), p)
    assert u.x() == pytest.approx(UTM[0], abs=0.01) and u.y() == pytest.approx(UTM[1], abs=0.01)


@needs_spatial
@pytest.mark.parametrize("mode", list(LoadMode))
def test_ax_1b_epsg_4326_keeps_x_as_longitude(session, mode):
    activate(session)
    ev = session.load(mode, f"SELECT {POINT}::GEOMETRY('EPSG:4326') AS g")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = only_layer()
    p = assert_lapaz_degrees(layer, "EPSG:4326")
    assert layer.crs().hasAxisInverted()
    u = to_utm(layer.crs(), p)
    assert u.x() == pytest.approx(UTM[0], abs=0.01) and u.y() == pytest.approx(UTM[1], abs=0.01)


@needs_spatial
@pytest.mark.parametrize("mode", list(LoadMode))
def test_ax_1c_st_transform_from_user_sql(session, mode):
    activate(session)
    ev = session.load(mode, f"SELECT ST_Transform({POINT}::GEOMETRY('EPSG:4326'), 'EPSG:32719', true) AS g")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = only_layer()
    assert layer.crs().authid() == "EPSG:32719"
    p = point_of(layer)
    assert p.x() == pytest.approx(UTM[0], abs=0.01) and p.y() == pytest.approx(UTM[1], abs=0.01)


@needs_spatial
@pytest.mark.parametrize("mode", list(LoadMode))
def test_ax_1c_four_argument_form_declares_no_crs(session, mode):
    """F-99: `ST_Transform(g, origen, destino, …)` da GEOMETRY sin CRS: no se inventa (C4)."""
    activate(session)
    sql = f"SELECT ST_Transform({POINT}::GEOMETRY, 'EPSG:4326', 'EPSG:32719', true) AS g"
    ev = session.load(mode, sql, crs_override="")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = only_layer()
    assert not layer.crs().isValid()
    p = point_of(layer)
    assert p.x() == pytest.approx(UTM[0], abs=0.01) and p.y() == pytest.approx(UTM[1], abs=0.01)


# -- AX-2 y AX-3: geometry_always_xy se muestra y nunca se modifica ----------------------------------------


@needs_spatial
def test_ax_2_axis_setting_is_shown_never_changed(session):
    result = run(session, f"SELECT {POINT}::GEOMETRY AS g")
    assert "geometry_always_xy" not in result.message  # sin spatial el ajuste no existe
    activate(session)
    activated = next(e for e in session.events if isinstance(e, SpatialActivated))
    assert activated.always_xy in ("sin fijar", "true")  # 2.0: sin fijar; 2.1 lo fija a true
    expected = activated.always_xy
    assert f"geometry_always_xy: {expected}" in run(session, f"SELECT {POINT}::GEOMETRY AS g").message
    for value in ("true", "false"):
        run(session, f"SET geometry_always_xy = {value}")
        assert f"geometry_always_xy: {value}" in run(session, f"SELECT {POINT}::GEOMETRY AS g").message
    assert "geometry_always_xy" not in run(session, "SELECT 1 AS n").message  # solo con geometría
    probe = probe_spatial()
    assert probe.loaded and probe.always_xy
    assert f"geometry_always_xy: {probe.always_xy}" in _check_spatial(lambda: probe).detail


@needs_spatial
@pytest.mark.skipif(duckdb.__version__ < "2", reason="DuckDB 2.0: ST_Transform exige el orden de ejes")
def test_ax_3_st_transform_without_axis_order_is_the_users_error(session):
    activate(session)
    if next(e for e in session.events if isinstance(e, SpatialActivated)).always_xy != "sin fijar":
        pytest.skip("geometry_always_xy ya tiene valor por defecto en esta versión")
    ev = session.load(
        LoadMode.MEMORY, f"SELECT ST_Transform({POINT}::GEOMETRY, 'EPSG:4326', 'EPSG:32719') AS g"
    )
    assert isinstance(ev, LoadFailed)
    assert "geometry_always_xy" in ev.message or "axis order" in ev.message
    assert list(QgsProject.instance().mapLayers().values()) == []
    assert "geometry_always_xy: sin fijar" in run(session, f"SELECT {POINT}::GEOMETRY AS g").message


# -- AX-4: CRS ausente o no reconocido ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", list(LoadMode))
def test_ax_4a_without_crs_none_is_assigned(session, mode):
    ev = session.load(mode, f"SELECT {POINT}::GEOMETRY AS g", crs_override="")
    assert isinstance(ev, LoadFinished)
    layer = only_layer()
    assert not layer.crs().isValid()
    p = point_of(layer)
    assert (p.x(), p.y()) == (pytest.approx(LON, abs=1e-9), pytest.approx(LAT, abs=1e-9))
    assert "Sin SRC asignado" in ev.report.warnings


@pytest.mark.parametrize("mode", list(LoadMode))
def test_ax_4b_unknown_crs_is_kept_in_the_message_not_replaced(session, mode):
    ev = session.load(mode, f"SELECT ST_SetCRS({POINT}::GEOMETRY, 'FOO:123') AS g")
    assert isinstance(ev, LoadFinished)
    layer = only_layer()
    assert not layer.crs().isValid()
    p = point_of(layer)
    assert (p.x(), p.y()) == (pytest.approx(LON, abs=1e-9), pytest.approx(LAT, abs=1e-9))
    assert "SRC «FOO:123» no reconocido por QGIS: sin SRC asignado" in ev.report.warnings


def test_ax_4b_dialog_asks_when_qgis_does_not_recognize_the_crs(session):
    sql = f"SELECT ST_SetCRS({POINT}::GEOMETRY, 'FOO:123') AS g"
    token = session.coordinator.prepare_load(sql)
    assert wait_for(lambda: any(isinstance(e, LoadPrepared) and e.token == token for e in session.events))
    plan = next(e for e in session.events if isinstance(e, LoadPrepared) and e.token == token).plan
    dialog = LoadDialog(sql, "x", plan, session.coordinator.load_modes())
    assert dialog._crs_unknown and set(dialog.crs_widgets) == {"g"}
    assert "«FOO:123»" in dialog.warnings_label.text()


@pytest.mark.parametrize("mode", list(LoadMode))
def test_ax_4c_choosing_a_crs_labels_without_moving(session, mode):
    ev = session.load(mode, f"SELECT ST_SetCRS({POINT}::GEOMETRY, 'FOO:123') AS g", crs_override="EPSG:4326")
    assert isinstance(ev, LoadFinished)
    assert_lapaz_degrees(only_layer(), "EPSG:4326")


# -- AX-5: «Reproyectar a…» en las copias -------------------------------------------------------------------


@pytest.mark.parametrize("mode", COPIES)
def test_ax_5_reproject_copies_with_qgis(session, mode):
    session.sql(f"CREATE TABLE p AS SELECT 1 AS id, {POINT}::GEOMETRY('OGC:CRS84') AS g")
    ev = session.load(mode, "SELECT * FROM p", "p", reproject_to="EPSG:32719")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = only_layer()
    assert layer.crs().authid() == "EPSG:32719"
    p = point_of(layer)
    assert p.x() == pytest.approx(UTM[0], abs=0.01) and p.y() == pytest.approx(UTM[1], abs=0.01)
    assert "Reproyectada de OGC:CRS84 a EPSG:32719" in ev.report.warnings
    raw = session.rows("SELECT ST_AsText(g) FROM p")[0][0]
    assert raw == "POINT (-68.15 -16.5)"  # el origen en DuckDB no cambia


@pytest.mark.parametrize("mode", COPIES)
def test_reproject_needs_a_source_crs(session, mode):
    ev = session.load(mode, f"SELECT {POINT}::GEOMETRY AS g", crs_override="", reproject_to="EPSG:32719")
    assert isinstance(ev, LoadFailed)
    assert "necesita un SRC de origen" in ev.message
    assert list(QgsProject.instance().mapLayers().values()) == []


def test_reproject_after_choosing_the_source_crs(session):
    ev = session.load(
        LoadMode.SNAPSHOT,
        f"SELECT {POINT}::GEOMETRY AS g",
        crs_override="EPSG:4326",
        reproject_to="EPSG:32719",
    )
    assert isinstance(ev, LoadFinished)
    p = point_of(only_layer())
    assert p.x() == pytest.approx(UTM[0], abs=0.01) and p.y() == pytest.approx(UTM[1], abs=0.01)


def test_connected_is_never_reprojected(session):
    with pytest.raises(Exception, match="no se reproyecta"):
        session.coordinator.load(
            LoadRequest(
                sql=f"SELECT {POINT}::GEOMETRY('OGC:CRS84') AS g",
                mode=LoadMode.CONNECTED,
                layer_name="c",
                reproject_to="EPSG:32719",
            )
        )


def test_dialog_offers_reprojection_only_for_copies_with_crs(session):
    sql = f"SELECT {POINT}::GEOMETRY('OGC:CRS84') AS a, {POINT}::GEOMETRY AS b"
    token = session.coordinator.prepare_load(sql)
    assert wait_for(lambda: any(isinstance(e, LoadPrepared) and e.token == token for e in session.events))
    plan = next(e for e in session.events if isinstance(e, LoadPrepared) and e.token == token).plan
    dialog = LoadDialog(sql, "x", plan, session.coordinator.load_modes())
    dialog.mode_buttons[LoadMode.MEMORY].setChecked(True)
    assert dialog.reproject_check.isEnabled()  # «a» declara OGC:CRS84
    dialog.reproject_check.setChecked(True)
    dialog.reproject_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32719"))
    assert dialog.request().reproject_to == "EPSG:32719"
    dialog.mode_buttons[LoadMode.CONNECTED].setChecked(True)
    assert not dialog.reproject_check.isEnabled()
    assert dialog.request().reproject_to is None
    dialog.mode_buttons[LoadMode.SNAPSHOT].setChecked(True)
    dialog.geometry_checks["b"].setChecked(True)  # «b» sin SRC: hay que elegirlo antes
    assert not dialog.reproject_check.isEnabled()
    dialog.crs_widgets["b"].setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert dialog.reproject_check.isEnabled()


# -- «Activar spatial…»: consentimiento de LOAD y, aparte, de INSTALL (spatial-spec §10) -----------------


def _dock(session, answers):
    from geoduck.ui.workspace import WorkspaceContent

    asked = []

    def ask(_parent, title, _text):
        asked.append(title)
        return answers.pop(0)

    dock = WorkspaceContent(session.coordinator, _report, ask_yes_no=ask)
    return dock, asked


def _report():
    from geoduck.domain.diagnostics import DiagnosticReport

    return DiagnosticReport(checks=())


def _loaded(session):
    return session.rows("SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'")[0][0]


def test_spatial_is_not_loaded_without_consent(session):
    dock, asked = _dock(session, [False])
    dock.spatial_action.trigger()
    assert wait_for(lambda: bool(asked), TIMEOUT)
    assert asked == ["Activar spatial"]
    assert "No se cargó spatial" in dock.message_label.text()
    assert not _loaded(session)
    dock.detach()


@needs_spatial
def test_spatial_loads_for_this_session_with_consent(session):
    dock, asked = _dock(session, [True])
    dock.spatial_action.trigger()
    assert wait_for(lambda: any(isinstance(e, SpatialActivated) for e in session.events), TIMEOUT)
    assert asked == ["Activar spatial"]  # ya instalada: no se pregunta por INSTALL
    assert _loaded(session)
    assert (
        "Extensión spatial" in dock.message_label.text()
        and "cargada en esta sesión" in dock.message_label.text()
    )
    dock.detach()


def test_install_is_asked_separately_and_can_be_declined(session):
    dock, asked = _dock(session, [True, False])
    dock._confirm_spatial(SpatialChecked(installed=False, loaded=False))
    assert asked == ["Activar spatial", "Instalar spatial"]
    assert "No se instaló spatial" in dock.message_label.text()
    assert not _loaded(session)
    dock.detach()
