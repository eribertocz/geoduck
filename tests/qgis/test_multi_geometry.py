# SPDX-License-Identifier: GPL-2.0-or-later
"""G4/E1: varias geometrías y columnas WKB/WKT marcadas (AT-SPA-001, AT-SPA-002; spatial-spec §2.2, §7).

Coordinador, worker DuckDB y QGIS reales, en las tres modalidades. Sin la extensión `spatial`.
"""

from __future__ import annotations

import pytest
from qgis.core import QgsFeatureRequest, QgsGeometry, QgsProject, QgsRectangle, QgsWkbTypes

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import LoadFailed, LoadFinished, LoadPrepared, LoadProgressed
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.session import SessionState
from geoduck.engine.worker import SessionWorker
from geoduck.qgis_bridge.loader import BridgeLoader
from geoduck.qgis_bridge.vsimem import PREFIX
from geoduck.ui.dispatcher import QtDispatcher
from geoduck.ui.load_dialog import LoadDialog
from geoduck.ui.load_flow import finished_message
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

TIMEOUT = 60
N = 300

#: Dos geometrías con CRS distintos (uno declarado, otro no) y atributos.
ZONAS = (
    "CREATE TABLE zonas AS SELECT range::INTEGER AS id, 'z' || range AS nombre, "
    "('POINT(' || range || ' ' || range || ')')::GEOMETRY('OGC:CRS84') AS centro, "
    "('POLYGON((' || range || ' 0,' || (range + 1) || ' 0,' || (range + 1) || ' 1,' || range || ' 0))')"
    "::GEOMETRY AS poligono "
    f"FROM range({N})"
)
#: Geometrías guardadas como WKB (BLOB) y WKT (VARCHAR), con una fila ilegible en cada una.
CRUDAS = (
    "CREATE TABLE crudas (id INTEGER PRIMARY KEY, wkb BLOB, wkt VARCHAR, etiqueta VARCHAR); "
    "INSERT INTO crudas VALUES "
    "(1, from_hex('0101000000000000000000F03F0000000000000040'), 'POINT (1 2)', 'a'), "
    "(2, from_hex('000000000140080000000000004010000000000000'), 'POINT (3 4)', 'b'), "
    "(3, NULL, NULL, 'c')"
)
BAD = "INSERT INTO crudas VALUES (4, from_hex('0101'), 'no es WKT', 'd')"


class Session:
    def __init__(self):
        self.events = []
        self.loader = BridgeLoader()
        self.coordinator = SessionCoordinator(SessionWorker, QtDispatcher(), self.loader)
        self.coordinator.subscribe(self.events.append)
        self.coordinator.start_memory_session()
        assert wait_for(lambda: self.coordinator.state is SessionState.READY, TIMEOUT)
        self.engine = self.coordinator._engine

    def sql(self, text):
        for statement in text.split("; "):
            self.engine.query(statement, priority=False).future.result(TIMEOUT)

    def rows(self, text):
        return self.engine.query(text, max_rows=10_000, priority=False).future.result(TIMEOUT).rows

    def load(self, mode, sql, name="capa", **kw):
        before = len(self.events)
        load_id = self.coordinator.load(LoadRequest(sql=sql, mode=mode, layer_name=name, **kw))
        assert wait_for(
            lambda: any(
                isinstance(e, (LoadFinished, LoadFailed)) and e.load_id == load_id
                for e in self.events[before:]
            ),
            TIMEOUT,
        )
        assert wait_for(lambda: self.coordinator.state is SessionState.READY, TIMEOUT)
        return next(e for e in self.events[before:] if isinstance(e, (LoadFinished, LoadFailed)))

    def close(self):
        self.coordinator.shutdown()
        self.loader.shutdown()


@pytest.fixture
def session(qgis_app):
    s = Session()
    s.sql(ZONAS)
    s.sql(CRUDAS)
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def layers():
    return QgsProject.instance().mapLayers().values()


def table_kw(table):
    return {"source": ("memory", "main", table), "source_kind": "table"}


# -- AT-SPA-002: una capa por columna marcada --------------------------------------------------------


@pytest.mark.parametrize("mode", list(LoadMode))
def test_two_geometries_make_two_complete_layers(session, mode):
    ev = session.load(
        mode,
        'SELECT * FROM "memory"."main"."zonas"',
        "zonas",
        geometries=("centro", "poligono"),
        crs_overrides=(("poligono", "EPSG:32719"),),
        **table_kw("zonas"),
    )
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    published = {lyr.name(): lyr for lyr in layers()}
    assert set(published) == {"zonas · centro", "zonas · poligono"}
    assert [name for _, name in ev.report.layers] == ["zonas · centro", "zonas · poligono"]
    centro, poligono = published["zonas · centro"], published["zonas · poligono"]
    assert centro.featureCount() == poligono.featureCount() == N
    assert QgsWkbTypes.geometryType(centro.wkbType()) == QgsWkbTypes.geometryType(QgsWkbTypes.Point)
    assert QgsWkbTypes.geometryType(poligono.wkbType()) == QgsWkbTypes.geometryType(QgsWkbTypes.Polygon)
    assert centro.crs().authid() == "OGC:CRS84"
    assert poligono.crs().authid() == "EPSG:32719"  # elegido por columna: etiqueta, no transforma
    for lyr, other in ((centro, "poligono"), (poligono, "centro")):
        names = lyr.fields().names()
        assert "id" in names and "nombre" in names and other not in names
    by_id = {f["id"]: f.geometry() for f in poligono.getFeatures()}
    assert by_id[7].boundingBox() == QgsRectangle(7, 0, 8, 1)
    assert {f["id"]: f.geometry().asPoint().x() for f in centro.getFeatures()}[7] == 7
    text = finished_message(ev.report)
    assert "Capas «zonas · centro», «zonas · poligono» cargadas" in text and "300 entidades cada una" in text


def test_connected_filters_each_layer_by_its_own_column(session):
    ev = session.load(
        LoadMode.CONNECTED,
        'SELECT * FROM "memory"."main"."zonas"',
        "zonas",
        geometries=("centro", "poligono"),
        **table_kw("zonas"),
    )
    assert isinstance(ev, LoadFinished)
    published = {lyr.name(): lyr for lyr in layers()}
    rect = QgsRectangle(10.5, 0.5, 12.5, 0.9)  # centros 11 y 12 no; polígonos 10, 11, 12 sí
    centro_ids = sorted(f["id"] for f in published["zonas · centro"].getFeatures(QgsFeatureRequest(rect)))
    poly_ids = sorted(f["id"] for f in published["zonas · poligono"].getFeatures(QgsFeatureRequest(rect)))
    assert centro_ids == []
    assert poly_ids == [10, 11, 12]
    assert published["zonas · centro"].dataProvider().editable
    assert published["zonas · poligono"].dataProvider().editable


def test_one_column_checked_makes_exactly_one_layer(session):
    ev = session.load(LoadMode.MEMORY, 'SELECT * FROM "memory"."main"."zonas"', "zonas", geometry="poligono")
    assert isinstance(ev, LoadFinished)
    assert [lyr.name() for lyr in layers()] == ["zonas"]
    assert "Columna «centro» omitida (geometría secundaria)" in ev.report.warnings


@pytest.mark.parametrize("mode", list(LoadMode))
def test_error_in_any_column_publishes_nothing(session, mode):
    ev = session.load(mode, "SELECT * FROM zonas", "zonas", geometries=("centro", "nope"))
    assert isinstance(ev, LoadFailed) and not ev.cancelled
    assert list(layers()) == []
    assert session.loader.vsimem.tracked == frozenset()


@pytest.mark.parametrize("mode", [LoadMode.MEMORY, LoadMode.SNAPSHOT])
def test_cancel_during_a_multiple_load_publishes_nothing(session, mode):
    big = (
        "SELECT range AS id, ('POINT(' || range || ' 0)')::GEOMETRY AS a, "
        "('POINT(0 ' || range || ')')::GEOMETRY AS b FROM range(3000000)"
    )
    from osgeo import gdal

    def gpkgs():
        return {p for p in (gdal.ReadDirRecursive(PREFIX) or []) if p.endswith(".gpkg")}

    files = gpkgs()
    before = len(session.events)
    session.coordinator.load(
        LoadRequest(sql=big, mode=mode, layer_name="grande", geometries=("a", "b"), crs_override="")
    )
    assert wait_for(lambda: any(isinstance(e, LoadProgressed) for e in session.events[before:]), TIMEOUT)
    assert session.coordinator.cancel_current_operation()
    assert wait_for(lambda: any(isinstance(e, LoadFailed) for e in session.events[before:]), TIMEOUT)
    failed = next(e for e in session.events[before:] if isinstance(e, LoadFailed))
    assert failed.cancelled
    assert list(layers()) == []
    assert session.loader.vsimem.tracked == frozenset()
    assert gpkgs() == files


# -- AT-SPA-001: columnas BLOB (WKB) y VARCHAR (WKT) ------------------------------------------------


@pytest.mark.parametrize("mode", list(LoadMode))
@pytest.mark.parametrize(("column", "fmt"), [("wkb", "wkb"), ("wkt", "wkt")])
def test_marked_blob_or_text_column_is_a_geometry(session, mode, column, fmt):
    before = session.rows("SELECT hash(wkb, wkt) FROM crudas ORDER BY id")
    ev = session.load(
        mode,
        'SELECT * FROM "memory"."main"."crudas"',
        "crudas",
        geometry=column,
        formats=((column, fmt),),
        crs_override="EPSG:4326",
        **table_kw("crudas"),
    )
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = next(iter(layers()))
    assert layer.featureCount() == 3
    assert layer.crs().authid() == "EPSG:4326"
    geoms = {f["id"]: f.geometry() for f in layer.getFeatures()}
    assert geoms[1].asWkt() == "Point (1 2)"
    assert geoms[2].asWkt() == "Point (3 4)"  # en WKB, big-endian: se lee igual
    assert geoms[3].isNull()
    assert column not in layer.fields().names()
    assert session.rows("SELECT hash(wkb, wkt) FROM crudas ORDER BY id") == before  # origen intacto


def test_unmarked_blob_and_text_are_never_geometries(session):
    token = session.coordinator.prepare_load("SELECT * FROM crudas")
    assert wait_for(lambda: any(isinstance(e, LoadPrepared) and e.token == token for e in session.events))
    plan = next(e for e in session.events if isinstance(e, LoadPrepared) and e.token == token).plan
    assert plan.geometry is None and plan.geometries == ()
    assert dict(plan.candidates) == {"wkb": "wkb", "wkt": "wkt", "etiqueta": "wkt"}
    ev = session.load(LoadMode.MEMORY, "SELECT * FROM crudas", "crudas")
    layer = next(iter(layers()))
    assert isinstance(ev, LoadFinished)
    assert layer.wkbType() == QgsWkbTypes.NoGeometry
    assert {"wkb", "wkt"} <= set(layer.fields().names())


@pytest.mark.parametrize("mode", [LoadMode.MEMORY, LoadMode.SNAPSHOT])
@pytest.mark.parametrize(("column", "fmt"), [("wkb", "wkb"), ("wkt", "wkt")])
def test_unreadable_value_fails_a_copy_with_its_row(session, mode, column, fmt):
    session.sql(BAD)
    ev = session.load(
        mode, "SELECT * FROM crudas ORDER BY id", "crudas", geometry=column, formats=((column, fmt),)
    )
    assert isinstance(ev, LoadFailed)
    assert f"Geometría ilegible en la columna «{column}» ({fmt.upper()}), fila 4" in ev.message
    assert list(layers()) == []


def test_unreadable_value_in_connected_is_counted_and_shown_without_geometry(session):
    session.sql(BAD)
    ev = session.load(
        LoadMode.CONNECTED,
        'SELECT * FROM "memory"."main"."crudas"',
        "crudas",
        geometry="wkb",
        formats=(("wkb", "wkb"),),
        **table_kw("crudas"),
    )
    assert isinstance(ev, LoadFinished)
    assert "1 geometrías ilegibles en «wkb» (WKB): se muestran sin geometría" in ev.report.warnings
    layer = next(iter(layers()))
    geoms = {f["id"]: f.geometry() for f in layer.getFeatures()}
    assert len(geoms) == 4 and geoms[4].isNull()


@pytest.mark.parametrize(
    ("column", "fmt", "expected"), [("wkb", "wkb", "POINT (5 6)"), ("wkt", "wkt", "POINT (5 6)")]
)
def test_connected_edit_writes_back_in_the_column_format(session, column, fmt, expected):
    ev = session.load(
        LoadMode.CONNECTED,
        'SELECT * FROM "memory"."main"."crudas"',
        "crudas",
        geometry=column,
        formats=((column, fmt),),
        **table_kw("crudas"),
    )
    assert isinstance(ev, LoadFinished)
    layer = next(iter(layers()))
    assert layer.dataProvider().editable
    assert layer.startEditing()
    fid = next(f.id() for f in layer.getFeatures() if f["id"] == 1)
    assert layer.changeGeometry(fid, QgsGeometry.fromWkt("POINT(5 6)"))
    assert layer.commitChanges(), layer.commitErrors()
    if column == "wkb":
        value = session.rows("SELECT typeof(wkb), hex(wkb) FROM crudas WHERE id = 1")[0]
        assert value == ("BLOB", "0101000000000000000000144000000000000018" + "40")
    else:
        assert session.rows("SELECT typeof(wkt), wkt FROM crudas WHERE id = 1")[0] == ("VARCHAR", expected)


# -- diálogo ------------------------------------------------------------------------------------


def test_dialog_marks_geometries_and_candidates(session):
    token = session.coordinator.prepare_load("SELECT * FROM zonas, crudas")
    assert wait_for(lambda: any(isinstance(e, LoadPrepared) and e.token == token for e in session.events))
    plan = next(e for e in session.events if isinstance(e, LoadPrepared) and e.token == token).plan
    dialog = LoadDialog("SELECT * FROM zonas, crudas", "z", plan, session.coordinator.load_modes())
    assert dialog.checked_geometries() == ["centro"]  # una sola por defecto
    dialog.geometry_checks["poligono"].setChecked(True)
    index = dialog.candidate_combo.findData("wkb")
    assert index > 0
    dialog.candidate_combo.setCurrentIndex(index)  # «Usar como geometría»: se añade marcada
    assert dialog.checked_geometries() == ["centro", "poligono", "wkb"]
    assert dialog.candidate_combo.findData("wkb") < 0
    assert set(dialog.crs_widgets) == {"poligono", "wkb"}  # sin CRS declarado: se pregunta por columna
    request = dialog.request()
    assert request.geometries == ("centro", "poligono", "wkb")
    assert request.formats == (("wkb", "wkb"),)
    assert dict(request.crs_overrides) == {"poligono": "", "wkb": ""}
    assert [r.layer_name for r in request.split()] == ["z · centro", "z · poligono", "z · wkb"]
    for name in ("centro", "poligono", "wkb"):
        dialog.geometry_checks[name].setChecked(False)
    assert not dialog._ok.isEnabled()  # al menos una geometría
