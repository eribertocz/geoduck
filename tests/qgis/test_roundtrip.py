# SPDX-License-Identifier: GPL-2.0-or-later
"""Ida y vuelta QGIS → GeoDuck → QGIS (#141): el dato espacial vuelve idéntico.

Cada caso es una capa de QGIS que se envía a DuckDB (por QGIS, el camino general) y se vuelve a cargar en
las tres modalidades (Copia, Instantánea, Conectada). Se compara: SRC, tipo de geometría, cada geometría
(WKB) y cada valor. Los SRC de Bolivia (UTM 19S, 20S, 21S y PSAD56), uno propio (PROJ) y uno ESRI; Z/M,
vacías y nulas; curvas (vuelven en segmentos rectos, con aviso); fechas, horas, enteros grandes, texto con
tildes. Las excepciones documentadas: las listas vuelven como JSON (solo lectura) y, en la Instantánea, la
hora vuelve como texto ISO (GeoPackage no tiene hora).
"""

from __future__ import annotations

import json

import pytest
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime, QVariant

from geoduck.app.events import LoadFailed, LoadFinished
from geoduck.domain.i18n import tr
from geoduck.domain.importing import ImportReport
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.qgis_bridge.importer import plan_layer
from geoduck.qgis_bridge.snapshot import unavailable_reason
from tests.qgis.conftest import wait_for
from tests.qgis.test_import_layers import rows, send
from tests.qgis.test_load_connected import TIMEOUT, Session

pytestmark = pytest.mark.qgis

INT = [QgsField("id", QVariant.Int)]

#: nombre → (URI de la capa en memoria, campos, [(atributos, WKT o None)])
CASES = {
    "utm19s_zm": (
        "PointZM?crs=EPSG:32719",
        INT,
        [([1], "PointZM (500000.123 8000000.456 3650.5 7)"), ([2], None)],
    ),
    "utm20s_lineas": (
        "LineString?crs=EPSG:32720",
        INT,
        [([1], "LineString (200000 8100000, 200100.5 8100200.25)"), ([2], "LineString EMPTY")],
    ),
    "utm21s_poligonos_z": (
        "MultiPolygonZ?crs=EPSG:32721",
        INT,
        [([1], "MultiPolygonZ (((0 0 1, 10 0 1, 10 10 2, 0 0 1)), ((20 20 0, 30 20 0, 30 30 0, 20 20 0)))")],
    ),
    "psad56_utm19s": ("Point?crs=EPSG:24879", INT, [([1], "Point (500000 8000000)")]),
    "src_propio": (
        "Point?crs=PROJ:+proj=tmerc +lat_0=0 +lon_0=-66 +k=0.9996 +x_0=500000 +y_0=10000000 +ellps=intl "
        "+units=m +no_defs",
        INT,
        [([1], "Point (500000 8000000)")],
    ),
    "esri": ("Point?crs=ESRI:102033", INT, [([1], "Point (-58.5 -34.6)")]),
    "invalida": (  # un «moño» que se cruza: vuelve tal cual, nunca reparado en silencio
        "Polygon?crs=EPSG:32719",
        INT,
        [([1], "Polygon ((0 0, 10 10, 10 0, 0 10, 0 0))")],
    ),
    "wgs84_ejes": ("Point?crs=EPSG:4326", INT, [([1], "Point (-68.15 -16.5)")]),  # lon/lat: sin girar
    "curvas": (
        "CompoundCurve?crs=EPSG:32720",
        INT,
        [([1], "CompoundCurve (CircularString (0 0, 1 1, 2 0), (2 0, 3 0))")],
    ),
    "atributos": (
        "Point?crs=EPSG:4326",
        [
            QgsField("id", QVariant.Int),
            QgsField("grande", QVariant.LongLong),
            QgsField("fecha", QVariant.Date),
            QgsField("instante", QVariant.DateTime),
            QgsField("hora", QVariant.Time),
            QgsField("activo", QVariant.Bool),
            QgsField("nombre", QVariant.String),
            QgsField("valor", QVariant.Double),
            QgsField("etiquetas", QVariant.StringList, subType=QVariant.String),
        ],
        [
            (
                [
                    1,
                    9_007_199_254_740_993,  # 2^53 + 1: no cabe en un double
                    QDate(2024, 2, 29),
                    QDateTime(QDate(2024, 1, 2), QTime(3, 4, 5, 678), Qt.TimeSpec.UTC),
                    QTime(23, 59, 58, 125),
                    True,
                    "ñandú áé ü «Potosí»",
                    0.1 + 0.2,
                    ["a", "b"],
                ],
                "Point (1 2)",
            ),
            ([2, None, None, None, None, None, None, None, None], "Point (3 4)"),
        ],
    ),
}


def _layer(uri: str, fields: list, features: list) -> QgsVectorLayer:
    layer = QgsVectorLayer(uri, "origen", "memory")
    assert layer.isValid(), uri
    layer.dataProvider().addAttributes(fields)
    layer.updateFields()
    out = []
    for attributes, wkt in features:
        feature = QgsFeature(layer.fields())
        feature.setAttributes(attributes)
        if wkt is not None:
            feature.setGeometry(QgsGeometry.fromWkt(wkt))
        out.append(feature)
    assert layer.dataProvider().addFeatures(out)
    return layer


def _load(session: Session, mode: LoadMode, name: str) -> list[QgsVectorLayer]:
    before = len(session.events)
    load_id = session.coordinator.load(LoadRequest(sql="SELECT * FROM t", mode=mode, layer_name=name))

    def finished():
        return next(
            (
                e
                for e in session.events[before:]
                if isinstance(e, (LoadFinished, LoadFailed)) and e.load_id == load_id
            ),
            None,
        )

    assert wait_for(lambda: finished() is not None, TIMEOUT)
    event = finished()
    assert isinstance(event, LoadFinished), getattr(event, "message", event)
    ids = [event.report.layer_id, *getattr(event.report, "extra_layer_ids", ())]
    return [QgsProject.instance().mapLayer(i) for i in ids if i]


def _same_crs(got, expected) -> bool:
    """El mismo SRC: igual, o la misma definición PROJ (QGIS 3.34 compara el WKT al pie de la letra y un SRC
    propio puede volver con otros nombres de ejes, «northing» por «(N)»)."""
    if got == expected:
        return True

    def proj(crs) -> str:
        return crs.toProj().replace(" +type=crs", "")

    return not expected.authid() and got.isValid() and proj(got) == proj(expected)


def _same_value(source, loaded, mode: LoadMode) -> bool:
    if source is None or (hasattr(source, "isNull") and source.isNull()):
        return loaded is None or (hasattr(loaded, "isNull") and loaded.isNull())
    if isinstance(source, list):  # listas: JSON de solo lectura (qgis-bridge-spec §3)
        return json.loads(loaded) == source
    if isinstance(source, QTime):
        if mode is LoadMode.SNAPSHOT:  # GeoPackage no tiene hora: texto ISO
            return str(loaded).startswith(source.toString("HH:mm:ss.zzz"))
        return loaded == source
    if isinstance(source, QDateTime):  # TIMESTAMP sin zona: vuelven los mismos dígitos del reloj, al ms
        return loaded.toString("yyyy-MM-ddTHH:mm:ss.zzz") == source.toString("yyyy-MM-ddTHH:mm:ss.zzz")
    return loaded == source


@pytest.fixture
def session(qgis_app):
    s = Session()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


@pytest.mark.parametrize("case", list(CASES))
def test_round_trip_keeps_crs_geometry_and_values(session, case):
    uri, fields, features = CASES[case]
    source = _layer(uri, fields, features)
    plan = plan_layer(source, table="t")
    curved = QgsWkbTypes.isCurvedType(source.wkbType())
    assert (tr("Curves are converted to straight segments: DuckDB has no curves") in plan.warnings) == curved
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    expected = {f["id"]: f for f in source.getFeatures()}
    modes = [LoadMode.MEMORY, LoadMode.CONNECTED]
    if unavailable_reason() is None:
        modes.append(LoadMode.SNAPSHOT)
    for mode in modes:
        loaded = _load(session, mode, f"{case}-{mode.value}")
        features_back = [f for layer in loaded for f in layer.getFeatures()]
        assert len(features_back) == len(expected), mode
        for layer in loaded:
            assert _same_crs(layer.crs(), source.crs()), (mode, layer.crs().toProj(), source.crs().toProj())
        for back in features_back:
            original = expected[back["id"]]
            geometry = QgsGeometry(original.geometry())
            if curved:
                geometry.convertToStraightSegment()
            got = back.geometry()
            if geometry.isNull():
                assert got.isNull(), (mode, got.asWkt())
            elif geometry.isEmpty():
                assert got.isEmpty(), (mode, got.asWkt())
            else:
                assert got.asWkb() == geometry.asWkb() or got.equals(geometry), (mode, got.asWkt())
                assert QgsWkbTypes.hasZ(got.wkbType()) == QgsWkbTypes.hasZ(geometry.wkbType())
                assert QgsWkbTypes.hasM(got.wkbType()) == QgsWkbTypes.hasM(geometry.wkbType())
            for field in source.fields():
                name = field.name()
                assert _same_value(original[name], back[name], mode), (mode, name, original[name], back[name])


def test_many_rows_round_trip_without_losses(session):
    """100 000 puntos en UTM 19S ida y vuelta: mismas filas y la misma suma de coordenadas."""
    source = QgsVectorLayer("Point?crs=EPSG:32719", "muchos", "memory")
    source.dataProvider().addAttributes([QgsField("id", QVariant.Int)])
    source.updateFields()
    batch = []
    for i in range(100_000):
        feature = QgsFeature(source.fields())
        feature.setAttributes([i])
        feature.setGeometry(QgsGeometry.fromWkt(f"Point ({400000 + i % 1000}.25 {8000000 + i // 1000}.5)"))
        batch.append(feature)
    source.dataProvider().addFeatures(batch)
    report, _ = send(session, [plan_layer(source, table="t")])
    assert isinstance(report, ImportReport), report
    assert rows(session, "SELECT count(*) FROM t") == ((100_000,),)
    [loaded] = _load(session, LoadMode.MEMORY, "muchos")
    assert loaded.featureCount() == 100_000
    assert _same_crs(loaded.crs(), source.crs())
    xs = sum(400000 + i % 1000 + 0.25 for i in range(100_000))
    ys = sum(8000000 + i // 1000 + 0.5 for i in range(100_000))
    points = [f.geometry().asPoint() for f in loaded.getFeatures()]
    assert sum(p.x() for p in points) == pytest.approx(xs)
    assert sum(p.y() for p in points) == pytest.approx(ys)
