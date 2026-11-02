# SPDX-License-Identifier: GPL-2.0-or-later
"""Modalidad Conectada, lectura (G3/E5; AT-BRD-008, AT-BRD-009; qgis-bridge-spec §5).

Coordinador, worker DuckDB, proveedor `geoduck` y QGIS reales.
"""

from __future__ import annotations

import pytest
from qgis.core import (
    Qgis,
    QgsExpression,
    QgsFeatureRequest,
    QgsProject,
    QgsRectangle,
    QgsVariantUtils,
)

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import LoadFailed, LoadFinished
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.session import SessionState
from geoduck.engine.worker import SessionWorker
from geoduck.qgis_bridge import provider as provider_module
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.connected import wkb_type_name
from geoduck.qgis_bridge.loader import BridgeLoader
from geoduck.qgis_bridge.provider import decode_uri
from geoduck.qgis_bridge.sql_compile import compile_expression
from geoduck.ui.dispatcher import QtDispatcher
from tests.qgis.conftest import wait_for

pytestmark = pytest.mark.qgis

TIMEOUT = 60
N = 5_000

TABLE = (
    "CREATE TABLE puntos AS SELECT range::INTEGER AS id, 'n ñ ' || range AS nombre, "
    "CASE WHEN range % 97 = 0 THEN NULL ELSE range * 0.5::DOUBLE END AS valor, "
    "('POINT(' || (range % 100) || ' ' || (range // 100) || ')')::GEOMETRY('OGC:CRS84') AS geom "
    f"FROM range({N}); ALTER TABLE puntos ADD PRIMARY KEY (id)"
)


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
        for statement in text.split(";"):
            self.engine.query(statement, priority=False).future.result(TIMEOUT)

    def load(self, sql, name="capa", **kw):
        before = len(self.events)
        load_id = self.coordinator.load(LoadRequest(sql=sql, mode=LoadMode.CONNECTED, layer_name=name, **kw))
        assert wait_for(
            lambda: any(
                isinstance(e, (LoadFinished, LoadFailed)) and e.load_id == load_id
                for e in self.events[before:]
            ),
            TIMEOUT,
        )
        event = next(e for e in self.events[before:] if isinstance(e, (LoadFinished, LoadFailed)))
        assert isinstance(event, LoadFinished), getattr(event, "message", event)
        assert self.coordinator.state is SessionState.READY
        return event.report, QgsProject.instance().mapLayer(event.report.layer_id)

    def close(self):
        self.coordinator.shutdown()
        self.loader.shutdown()


@pytest.fixture
def session(qgis_app):
    s = Session()
    s.sql(TABLE)
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def ids(layer, request=None):
    return sorted(f["id"] for f in layer.getFeatures(request or QgsFeatureRequest()))


def load_table(session, **kw):
    return session.load('SELECT * FROM "memory"."main"."puntos"', source=("memory", "main", "puntos"), **kw)


def test_table_with_primary_key(session):
    report, layer = load_table(session)
    assert layer.providerType() == "geoduck"
    assert report.rows == layer.featureCount() == N
    assert layer.wkbType() == Qgis.WkbType.Point
    assert layer.crs().authid() == "OGC:CRS84"
    assert layer.extent() == QgsRectangle(0, 0, 99, 49)
    assert decode_uri(layer.source())["fid"] == "key"
    feats = {f.id(): f for f in layer.getFeatures()}
    assert sorted(feats) == list(range(N))
    f = feats[194]
    assert f["nombre"] == "n ñ 194"
    assert QgsVariantUtils.isNull(f["valor"])
    assert feats[195]["valor"] == 97.5
    assert f.geometry().asWkt() == "Point (94 1)"
    assert layer.getFeature(4321)["nombre"] == "n ñ 4321"


def test_extent_fid_and_attribute_pushdown(session):
    _, layer = load_table(session)
    rect = QgsRectangle(10, 10, 12, 11)
    expected = sorted(y * 100 + x for y in (10, 11) for x in (10, 11, 12))
    assert ids(layer, QgsFeatureRequest().setFilterRect(rect)) == expected
    request = QgsFeatureRequest().setFilterFids([3, 7, 4999])
    assert ids(layer, request) == [3, 7, 4999]
    request = (
        QgsFeatureRequest()
        .setFlags(Qgis.FeatureRequestFlag.NoGeometry)
        .setSubsetOfAttributes(["id"], layer.fields())
    )
    request.setLimit(10)
    feats = list(layer.getFeatures(request))
    assert len(feats) == 10
    assert not feats[0].hasGeometry()


@pytest.mark.parametrize(
    ("expression", "compiled"),
    [
        ("id < 10", True),
        ("id IN (1, 2, 3) OR nombre = 'n ñ 4000'", True),
        ("valor IS NULL", True),
        ("nombre LIKE 'n ñ 12%' AND NOT id > 125", True),
        ("valor IS 2.5", True),
        ("length(nombre) = 5", False),  # sin traducción: se evalúa en Python
    ],
)
def test_expressions(session, expression, compiled):
    _, layer = load_table(session)
    p = layer.dataProvider()
    assert (compile_expression(QgsExpression(expression).rootNode(), p.comparable) is not None) is compiled
    got = ids(layer, QgsFeatureRequest().setFilterExpression(expression))
    want = []
    for i in range(N):
        valor = None if i % 97 == 0 else i * 0.5
        nombre = f"n ñ {i}"
        ok = {
            "id < 10": i < 10,
            "id IN (1, 2, 3) OR nombre = 'n ñ 4000'": i in (1, 2, 3) or nombre == "n ñ 4000",
            "valor IS NULL": valor is None,
            "nombre LIKE 'n ñ 12%' AND NOT id > 125": nombre.startswith("n ñ 12") and not i > 125,
            "valor IS 2.5": valor == 2.5,
            "length(nombre) = 5": len(nombre) == 5,
        }[expression]
        if ok:
            want.append(i)
    assert got == want


def test_pages_cover_everything_once(session, monkeypatch):
    monkeypatch.setattr(provider_module, "PAGE", 700)
    _, layer = load_table(session)
    assert ids(layer) == list(range(N))
    rect = QgsRectangle(0, 0, 99, 30)
    assert len(ids(layer, QgsFeatureRequest().setFilterRect(rect))) == 3100


def test_query_and_view_use_stable_row_numbers(session):
    _, layer = session.load("SELECT * FROM puntos WHERE id % 2 = 0 ORDER BY id", name="pares")
    assert decode_uri(layer.source())["fid"] == "row"
    assert layer.featureCount() == N // 2
    rect = QgsRectangle(10, 10, 10, 10)
    (f,) = list(layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)))
    assert f["id"] == 1010
    assert layer.getFeature(f.id())["id"] == 1010  # el FID no depende del filtro

    session.sql("CREATE VIEW vista AS SELECT id, geom FROM puntos WHERE id < 100")
    _, view = session.load(
        'SELECT * FROM "memory"."main"."vista"', name="vista", source=("memory", "main", "vista")
    )
    assert decode_uri(view.source())["fid"] == "row"
    assert ids(view) == list(range(100))


def test_table_without_key_uses_rowid(session):
    session.sql("CREATE TABLE sin_clave AS SELECT * FROM puntos WHERE id < 50")
    report, layer = session.load(
        'SELECT * FROM "memory"."main"."sin_clave"', source=("memory", "main", "sin_clave")
    )
    assert decode_uri(layer.source())["fid"] == "rowid"
    assert any("Solo lectura" in w for w in report.warnings)
    assert ids(layer) == list(range(50))


def test_missing_session_leaves_the_layer_empty(session):
    _, layer = load_table(session)
    sessions.clear()
    assert layer.isValid()
    assert list(layer.getFeatures()) == []
    assert layer.dataProvider().unavailable


def test_geometry_type_from_wkb_headers():
    assert wkb_type_name(["0101000000"]) == ("Point", None)
    assert wkb_type_name(["0101000000", "0104000000"])[0] == "MultiPoint"
    assert wkb_type_name(["01E9030000"])[0] == "PointZ"
    name, note = wkb_type_name(["0101000000", "0103000000"])
    assert name == "Unknown" and note
    assert wkb_type_name([])[0] == "Unknown"


def render(layer):
    from qgis.core import QgsMapRendererSequentialJob, QgsMapSettings
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor

    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(layer.crs())
    settings.setExtent(layer.extent().buffered(1))
    settings.setOutputSize(QSize(200, 100))
    settings.setBackgroundColor(QColor(255, 255, 255))
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()
    return sum(
        1
        for x in range(0, 200, 2)
        for y in range(0, 100, 2)
        if image.pixelColor(x, y) != QColor(255, 255, 255)
    )


def test_map_rendering_draws_the_layer(session):
    _, layer = load_table(session)
    assert render(layer) > 100


def test_rendering_waits_for_user_sql_without_errors(session):
    """Una consulta larga del usuario ocupa el worker; la página del mapa espera y luego se dibuja."""
    import threading

    _, layer = load_table(session)
    started = threading.Event()

    def slow(handle, token):
        started.set()
        handle.execute("SELECT count(*) FROM range(60000000) a")
        return True

    long = session.engine.submit(slow)
    assert started.wait(TIMEOUT)
    queued = session.engine.submit(lambda h, t: "después")  # trabajo normal en cola: va detrás del mapa
    assert render(layer) > 100
    assert long.future.result(TIMEOUT) is True
    assert queued.future.result(TIMEOUT) == "después"
