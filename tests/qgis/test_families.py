# SPDX-License-Identifier: GPL-2.0-or-later
"""G4/E3: familias mixtas, colecciones y dimensiones (AT-SPA-004; spatial-spec §6; F-96, F-97).

Sin pérdidas silenciosas: cada fila llega a una capa o se avisa su número; las dimensiones Z/M se
conservan; NULL y vacías se mantienen.
"""

from __future__ import annotations

import math

import pytest
from qgis.core import QgsFeatureRequest, QgsGeometry, QgsProject, QgsRectangle, QgsWkbTypes

from geoduck.app.events import LoadFailed, LoadFinished, LoadPrepared
from geoduck.domain.load import LoadMode
from geoduck.qgis_bridge.provider import decode_uri
from geoduck.ui.load_dialog import LoadDialog
from geoduck.ui.load_flow import finished_message
from tests.qgis.conftest import wait_for
from tests.qgis.test_multi_geometry import Session

pytestmark = pytest.mark.qgis

COPIES = [LoadMode.MEMORY, LoadMode.SNAPSHOT]

#: 3 000 filas: puntos, líneas y polígonos intercalados; cada 10, una NULL; la fila 7, vacía.
MIXTA = (
    "CREATE TABLE mixta AS SELECT range::INTEGER AS id, CASE "
    "WHEN range % 10 = 9 THEN NULL "
    "WHEN range = 7 THEN 'POINT EMPTY'::GEOMETRY "
    "WHEN range % 3 = 0 THEN ('POINT(' || range || ' 0)')::GEOMETRY "
    "WHEN range % 3 = 1 THEN ('LINESTRING(' || range || ' 0, ' || range || ' 1)')::GEOMETRY "
    "ELSE ('POLYGON((' || range || ' 0,' || (range + 1) || ' 0,' || range || ' 1,' || range || ' 0))')"
    "::GEOMETRY "
    "END AS g FROM range(3000)"
)


@pytest.fixture
def session(qgis_app):
    s = Session()
    s.sql(MIXTA)
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def published():
    return {lyr.name(): lyr for lyr in QgsProject.instance().mapLayers().values()}


def ids(layer, request=None):
    return [f["id"] for f in layer.getFeatures(request or QgsFeatureRequest())]


def expected_ids(session, condition):
    return sorted(r[0] for r in session.rows(f"SELECT id FROM mixta WHERE {condition}"))


# -- copias: una capa por familia, o error -----------------------------------------------------------


@pytest.mark.parametrize("mode", COPIES)
def test_copies_split_mixed_families_without_losing_rows(session, mode):
    ev = session.load(mode, "SELECT * FROM mixta", "mixta", crs_override="")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layers = published()
    assert set(layers) == {
        "mixta — Point",
        "mixta — LineString",
        "mixta — Polygon",
        "mixta — sin geometría",
    }
    families = {
        "mixta — Point": "id % 3 = 0 AND id % 10 <> 9",
        "mixta — LineString": "id % 3 = 1 AND id % 10 <> 9 AND id <> 7",
        "mixta — Polygon": "id % 3 = 2 AND id % 10 <> 9",
        "mixta — sin geometría": "id % 10 = 9",
    }
    families["mixta — Point"] += " OR id = 7"  # la vacía conserva su familia (POINT EMPTY)
    for name, condition in families.items():
        assert sorted(ids(layers[name])) == expected_ids(session, condition), name
    assert sum(lyr.featureCount() for lyr in layers.values()) == 3000
    assert QgsWkbTypes.geometryType(layers["mixta — Polygon"].wkbType()) == QgsWkbTypes.geometryType(
        QgsWkbTypes.Polygon
    )
    empty = next(f for f in layers["mixta — Point"].getFeatures() if f["id"] == 7).geometry()
    assert empty.isEmpty()
    assert any("una por tipo" in w for w in ev.report.warnings)
    assert "3 000 entidades en total" in finished_message(ev.report)


@pytest.mark.parametrize("mode", COPIES)
def test_copies_refuse_mixed_families_when_the_option_is_off(session, mode):
    ev = session.load(mode, "SELECT * FROM mixta", "mixta", crs_override="", split_families=False)
    assert isinstance(ev, LoadFailed)
    assert "«Tipos mixtos: una capa por tipo» está desactivada" in ev.message
    assert published() == {}
    assert session.loader.vsimem.tracked == frozenset()


def test_memory_single_family_keeps_nulls_in_the_layer(session):
    ev = session.load(LoadMode.MEMORY, "SELECT * FROM mixta WHERE id % 3 = 0", "puntos", crs_override="")
    assert isinstance(ev, LoadFinished)
    layer = published()["puntos"]
    assert layer.featureCount() == 1000
    assert sum(1 for f in layer.getFeatures() if f.geometry().isNull()) == 100


def test_memory_multi_part_found_late_makes_the_layer_multi(session):
    sql = (
        "SELECT range AS id, CASE WHEN range = 2500 THEN 'MULTIPOINT((1 1),(2 2))'::GEOMETRY "
        "ELSE ('POINT(' || range || ' 0)')::GEOMETRY END AS g FROM range(3000)"
    )
    ev = session.load(LoadMode.MEMORY, sql, "p", crs_override="")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = published()["p"]
    assert layer.wkbType() == QgsWkbTypes.MultiPoint
    assert all(QgsWkbTypes.isMultiType(f.geometry().wkbType()) for f in layer.getFeatures())
    assert layer.featureCount() == 3000


# -- dimensiones Z/M (F-97) --------------------------------------------------------------------------------

DIMS = (
    "SELECT range AS id, CASE WHEN range < 2000 THEN ('POINT(' || range || ' 1)')::GEOMETRY "
    "ELSE ('POINT Z(' || range || ' 1 5)')::GEOMETRY END AS g FROM range(3000)"
)


@pytest.mark.parametrize("mode", list(LoadMode))
def test_z_found_late_is_kept_and_2d_rows_get_nan(session, mode):
    ev = session.load(mode, DIMS, "z", crs_override="")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = published()["z"]
    assert QgsWkbTypes.hasZ(layer.wkbType())
    feats = {f["id"]: f.geometry() for f in layer.getFeatures()}
    assert len(feats) == 3000
    assert feats[2500].constGet().z() == 5
    assert math.isnan(feats[10].constGet().z())
    assert any("Z" in w for w in ev.report.warnings)


@pytest.mark.parametrize("mode", list(LoadMode))
@pytest.mark.parametrize(
    ("wkt", "has_m"),
    [
        ("POINT M(1 2 4)", True),
        ("POINT ZM(1 2 3 4)", True),
        ("GEOMETRYCOLLECTION(POINT(1 2),LINESTRING(0 0,1 1))", False),
    ],
)
def test_m_zm_and_collections_load_as_they_are(session, mode, wkt, has_m):
    ev = session.load(mode, f"SELECT 1 AS id, '{wkt}'::GEOMETRY AS g", "x", crs_override="")
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = published()["x"]
    g = next(layer.getFeatures()).geometry()
    assert g.equals(QgsGeometry.fromWkt(wkt)) or g.asWkt() == QgsGeometry.fromWkt(wkt).asWkt()
    assert QgsWkbTypes.hasM(layer.wkbType()) == has_m


# -- Conectada: Unknown o «Separar por tipo» -------------------------------------------------------------


def load_connected(session, **kw):
    return session.load(
        LoadMode.CONNECTED,
        'SELECT * FROM "memory"."main"."mixta"',
        "mixta",
        crs_override="",
        source=("memory", "main", "mixta"),
        source_kind="table",
        **kw,
    )


def test_connected_mixed_is_one_unknown_layer_with_every_row(session):
    ev = load_connected(session)
    assert isinstance(ev, LoadFinished)
    layer = published()["mixta"]
    assert layer.wkbType() == QgsWkbTypes.Unknown
    assert sorted(ids(layer)) == list(range(3000))
    assert "Tipos de geometría mixtos: simbología por tipo no disponible" in ev.report.warnings


def test_connected_separate_types_pushes_the_family_filter(session):
    ev = load_connected(session, separate_types=True)
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layers = published()
    assert set(layers) == {"mixta — Point", "mixta — LineString", "mixta — Polygon"}
    point, line, poly = layers["mixta — Point"], layers["mixta — LineString"], layers["mixta — Polygon"]
    assert decode_uri(point.source())["family"] == "Point"
    assert "IN (1, 4)" in point.dataProvider().base
    assert sorted(ids(point)) == expected_ids(session, "(id % 3 = 0 AND id % 10 <> 9) OR id = 7")
    assert sorted(ids(line)) == expected_ids(session, "id % 3 = 1 AND id % 10 <> 9 AND id <> 7")
    assert sorted(ids(poly)) == expected_ids(session, "id % 3 = 2 AND id % 10 <> 9")
    seen = ids(point) + ids(line) + ids(poly)
    assert len(seen) == len(set(seen)) == 2700  # sin duplicados; las 300 NULL se avisan
    assert point.featureCount() == len(ids(point))
    assert "300 filas sin geometría no aparecen en las capas por tipo" in ev.report.warnings
    assert QgsWkbTypes.geometryType(poly.wkbType()) == QgsWkbTypes.geometryType(QgsWkbTypes.Polygon)
    rect = QgsRectangle(29.5, -1, 33.5, 2)  # ids 30..33: punto 30 y 33, línea 31, polígono 32
    assert sorted(ids(point, QgsFeatureRequest(rect))) == [30, 33]
    assert sorted(ids(line, QgsFeatureRequest(rect))) == [31]
    assert sorted(ids(poly, QgsFeatureRequest(rect))) == [32]  # el 29 es NULL


def test_connected_reads_the_type_of_every_row_not_a_sample(session):
    # F-93 (decisión del propietario, PR #73): un tipo que solo aparece en la última de 20 000 filas no se
    # pierde: el tipo se lee de todas las cabeceras WKB, no de una muestra.
    session.sql(
        "CREATE TABLE tardia AS SELECT range::INTEGER AS id, CASE WHEN range = 19999 "
        "THEN 'POLYGON((0 0, 1 0, 0 1, 0 0))'::GEOMETRY "
        "ELSE ('POINT(' || range || ' 0)')::GEOMETRY END AS g FROM range(20000)"
    )
    kw = {"crs_override": "", "source": ("memory", "main", "tardia"), "source_kind": "table"}
    sql = 'SELECT * FROM "memory"."main"."tardia"'
    ev = session.load(LoadMode.CONNECTED, sql, "tardia", **kw)
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    assert published()["tardia"].wkbType() == QgsWkbTypes.Unknown
    ev = session.load(LoadMode.CONNECTED, sql, "separada", separate_types=True, **kw)
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layers = published()
    assert ids(layers["separada — Polygon"]) == [19999]
    assert len(ids(layers["separada — Point"])) == 19999


def test_editing_a_separated_layer_stays_in_its_family(session):
    load_connected(session, separate_types=True)
    layers = published()
    point, poly = layers["mixta — Point"], layers["mixta — Polygon"]
    before = poly.featureCount()
    assert point.startEditing()
    fid = next(f.id() for f in point.getFeatures() if f["id"] == 30)
    assert point.changeGeometry(fid, QgsGeometry.fromWkt("POINT(30 5)"))
    assert point.commitChanges(), point.commitErrors()
    assert session.rows("SELECT ST_AsText(g) FROM mixta WHERE id = 30")[0][0] == "POINT (30 5)"
    poly.reload()
    assert poly.featureCount() == before


# -- diálogo -------------------------------------------------------------------------------------------


def test_dialog_shows_the_mixed_types_option_of_each_mode(session):
    token = session.coordinator.prepare_load("SELECT * FROM mixta")
    assert wait_for(lambda: any(isinstance(e, LoadPrepared) and e.token == token for e in session.events))
    plan = next(e for e in session.events if isinstance(e, LoadPrepared) and e.token == token).plan
    dialog = LoadDialog("SELECT * FROM mixta", "m", plan, session.coordinator.load_modes())
    dialog.mode_buttons[LoadMode.MEMORY].setChecked(True)
    assert not dialog.split_check.isHidden() and dialog.separate_check.isHidden()
    assert dialog.request().split_families and not dialog.request().separate_types
    dialog.mode_buttons[LoadMode.CONNECTED].setChecked(True)
    assert dialog.split_check.isHidden() and not dialog.separate_check.isHidden()
    assert not dialog.request().separate_types
    dialog.separate_check.setChecked(True)
    assert dialog.request().separate_types
