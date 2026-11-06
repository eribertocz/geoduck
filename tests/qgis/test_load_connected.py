# SPDX-License-Identifier: GPL-2.0-or-later
"""Modalidad Conectada, lectura (G3/E5; AT-BRD-008, AT-BRD-009; qgis-bridge-spec §5).

Coordinador, worker DuckDB, proveedor `geoduck` y QGIS reales.
"""

from __future__ import annotations

import duckdb
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
from geoduck.app.events import LoadFailed, LoadFinished, SpatialActivated
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.session import SessionState
from geoduck.engine.worker import SessionWorker
from geoduck.qgis_bridge import provider as provider_module
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.connected import wkb_type_name
from geoduck.qgis_bridge.loader import BridgeLoader
from geoduck.qgis_bridge.provider import decode_uri
from geoduck.qgis_bridge.qgis_compat import RequestFlag
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
        QgsFeatureRequest().setFlags(RequestFlag.NoGeometry).setSubsetOfAttributes(["id"], layer.fields())
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
    assert decode_uri(layer.source())["fid"] == "content"
    assert layer.featureCount() == N // 2
    rect = QgsRectangle(10, 10, 10, 10)
    (f,) = list(layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)))
    assert f["id"] == 1010
    assert layer.getFeature(f.id())["id"] == 1010  # el FID no depende del filtro

    session.sql("CREATE VIEW vista AS SELECT id, geom FROM puntos WHERE id < 100")
    _, view = session.load(
        'SELECT * FROM "memory"."main"."vista"', name="vista", source=("memory", "main", "vista")
    )
    assert decode_uri(view.source())["fid"] == "content"
    assert ids(view) == list(range(100))


def test_table_without_key_uses_rowid_like_ctid(session):
    session.sql("CREATE TABLE sin_clave AS SELECT * FROM puntos WHERE id < 50")
    _, layer = session.load(
        'SELECT * FROM "memory"."main"."sin_clave"', source=("memory", "main", "sin_clave")
    )
    assert decode_uri(layer.source())["fid"] == "rowid"
    assert ids(layer) == list(range(50))
    assert {f.id(): f["id"] for f in layer.getFeatures()} == {i: i for i in range(50)}


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


def test_types_follow_section_7(session):
    """AT-BRD-007 en la modalidad Conectada: los mismos valores que Memoria e Instantánea."""
    report, layer = session.load(
        "SELECT 1::HUGEINT * 170141183460469231731687303715884105727 AS hi, 1234567.89::DECIMAL(9,2) AS d9, "
        "'b'::ENUM('a','b') AS en, DATE '2026-11-01' AS fecha, TIMESTAMPTZ '2026-11-01 12:00:00+02' AS tz, "
        "[1,2] AS li, '\\xAA'::BLOB AS bl, NULL::INTEGER AS nul"
    )
    f = next(layer.getFeatures())
    assert f["hi"] == "170141183460469231731687303715884105727"
    assert f["d9"] == pytest.approx(1234567.89)
    assert f["en"] == "b"
    assert f["fecha"].toString("yyyy-MM-dd") == "2026-11-01"
    assert f["tz"].toUTC().toString("yyyy-MM-ddTHH:mm:ss") == "2026-11-01T10:00:00"
    assert f["li"] == "[1,2]"
    assert bytes(f["bl"]) == b"\xaa"
    assert QgsVariantUtils.isNull(f["nul"])
    assert any("HUGEINT" in w for w in report.warnings)
    # Filtros sobre columnas convertidas: se evalúan en Python con la semántica de QGIS (no se compilan).
    assert [
        g["en"] for g in layer.getFeatures(QgsFeatureRequest().setFilterExpression("hi LIKE '1701%'"))
    ] == ["b"]


def _fid_by_id(layer, request=None):
    return {f["id"]: f.id() for f in layer.getFeatures(request or QgsFeatureRequest())}


def test_query_without_identifier_has_stable_content_fids(session):
    """Consulta sin identificador elegido: FID por huella del contenido, estable (2026-11-02)."""
    session.sql("CREATE TABLE sin_clave AS SELECT * FROM puntos")
    _, table = session.load("SELECT * FROM sin_clave", name="sc")
    _, grouped = session.load(  # orden de salida no determinista (agregación en paralelo)
        "SELECT id % 1000 AS id, count(*) AS n, any_value(geom) AS geom FROM puntos GROUP BY ALL", name="g"
    )
    assert decode_uri(table.source())["fid"] == "content"
    base = _fid_by_id(table)
    assert len(base) == N and len(set(base.values())) == N and min(base.values()) >= 0
    rect = QgsRectangle(10, 10, 20, 12)
    filtered = _fid_by_id(table, QgsFeatureRequest().setFilterRect(rect))
    assert filtered and all(base[i] == fid for i, fid in filtered.items())
    by_expr = _fid_by_id(table, QgsFeatureRequest().setFilterExpression("length(nombre) = 7"))
    assert by_expr and all(base[i] == fid for i, fid in by_expr.items())
    assert table.getFeature(base[4321])["id"] == 4321
    grouped_before = _fid_by_id(grouped)
    session.sql("DELETE FROM sin_clave WHERE id < 2000; CHECKPOINT")
    assert _fid_by_id(table) == {i: fid for i, fid in base.items() if i >= 2000}
    session.sql("SET threads = 1")
    assert _fid_by_id(grouped) == grouped_before
    session.sql("RESET threads")


def test_identical_rows_are_never_lost_or_repeated_across_pages(session, monkeypatch):
    monkeypatch.setattr(provider_module, "PAGE", 4)
    session.sql(
        "CREATE TABLE dup AS SELECT (range % 3)::INTEGER AS id, "
        "('POINT(0 ' || (range % 3) || ')')::GEOMETRY AS g FROM range(15)"  # cada fila aparece 5 veces
    )
    _, layer = session.load("SELECT * FROM dup", name="dup")  # consulta sin identificador
    feats = list(layer.getFeatures())
    assert sorted(f["id"] for f in feats) == sorted([0, 1, 2] * 5)
    assert len({f.id() for f in feats}) == 3  # filas idénticas: el mismo FID
    request = QgsFeatureRequest().setFilterExpression("id >= 1")
    assert sorted(f["id"] for f in layer.getFeatures(request)) == sorted([1, 2] * 5)


def test_table_with_identical_rows_uses_rowid_and_distinguishes_them(session):
    session.sql("CREATE TABLE dup2 AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY AS g FROM range(4)")
    _, layer = session.load('SELECT * FROM "memory"."main"."dup2"', source=("memory", "main", "dup2"))
    assert sorted(f.id() for f in layer.getFeatures()) == [0, 1, 2, 3]


@pytest.mark.parametrize(
    ("ddl", "cols", "mapped"),
    [
        ("CREATE TABLE k (codigo VARCHAR PRIMARY KEY, g GEOMETRY)", ["codigo"], True),
        ("CREATE TABLE k (a VARCHAR, b DATE, g GEOMETRY, PRIMARY KEY (a, b))", ["a", "b"], True),
        ("CREATE TABLE k (u UUID UNIQUE NOT NULL, g GEOMETRY)", ["u"], True),
        ("CREATE TABLE k (n BIGINT UNIQUE NOT NULL, g GEOMETRY)", ["n"], False),
    ],
)
def test_any_table_key_is_used_like_qgis_postgis(session, monkeypatch, ddl, cols, mapped):
    """Clave primaria o UNIQUE NOT NULL de cualquier tipo (PktFidMap de QGIS) (2026-11-02)."""
    monkeypatch.setattr(provider_module, "PAGE", 7)
    session.sql(ddl)
    values = {
        "codigo": "'c' || lpad(range::VARCHAR, 3, '0')",
        "a": "'a' || (range % 5)",
        "b": "DATE '2026-01-01' + (range // 5)::INTEGER",
        "u": "uuid()",
        "n": "range * 10",
    }
    session.sql(
        f"INSERT INTO k ({', '.join(cols)}, g) SELECT {', '.join(values[c] for c in cols)}, "
        "('POINT(' || range || ' 0)')::GEOMETRY FROM range(40)"
    )
    _, layer = session.load('SELECT * FROM "memory"."main"."k"', source=("memory", "main", "k"))
    assert decode_uri(layer.source())["fid"] == ("map" if mapped else "key")
    feats = {f.id(): f.geometry().asPoint().x() for f in layer.getFeatures()}
    assert len(feats) == 40 and sorted(feats.values()) == [float(i) for i in range(40)]  # páginas por clave
    some = sorted(feats)[5:8]
    got = {
        f.id(): f.geometry().asPoint().x() for f in layer.getFeatures(QgsFeatureRequest().setFilterFids(some))
    }
    assert got == {fid: feats[fid] for fid in some}
    rect = QgsRectangle(10, -1, 12, 1)
    assert {f.id() for f in layer.getFeatures(QgsFeatureRequest().setFilterRect(rect))} == {
        fid for fid, x in feats.items() if 10 <= x <= 12
    }


def test_layer_filter_like_any_qgis_layer(session):
    """Capa → Filtrar… (subset): SQL de DuckDB sobre los campos de la capa; se guarda en la fuente."""
    _, layer = load_table(session)
    assert layer.dataProvider().supportsSubsetString()
    assert layer.setSubsetString("id < 10 AND nombre LIKE 'n ñ %'")
    assert layer.featureCount() == 10
    assert ids(layer) == list(range(10))
    assert ids(layer, QgsFeatureRequest().setFilterExpression("id >= 5")) == [5, 6, 7, 8, 9]
    assert decode_uri(layer.source())["subset"] == "id < 10 AND nombre LIKE 'n ñ %'"
    assert not layer.setSubsetString("columna_que_no_existe = 1")  # inválido: se rechaza, sin cambios
    assert layer.subsetString() == "id < 10 AND nombre LIKE 'n ñ %'" and layer.featureCount() == 10
    from qgis.core import QgsVectorLayer

    copy = QgsVectorLayer(layer.source(), "copia", "geoduck")  # p. ej. al reabrir el proyecto
    assert copy.subsetString() == "id < 10 AND nombre LIKE 'n ñ %'" and len(ids(copy)) == 10
    assert layer.setSubsetString("")
    assert layer.featureCount() == N and len(ids(layer)) == N


def _spatial_available() -> bool:
    con = duckdb.connect()
    try:
        con.execute("LOAD spatial")
        return True
    except duckdb.Error:
        return False
    finally:
        con.close()


def _box(layer):
    e = layer.extent()
    return (e.xMinimum(), e.yMinimum(), e.xMaximum(), e.yMaximum())


def _check_filtered_extent(layer):
    assert _box(layer) == pytest.approx((0, 0, 99, 49))
    assert layer.setSubsetString("id IN (1010, 2025)")  # puntos (10 10) y (25 20)
    layer.updateExtents()
    assert _box(layer) == pytest.approx((10, 10, 25, 20))
    assert layer.setSubsetString("id < 0")  # nada: extensión vacía
    layer.updateExtents()
    assert layer.extent().isEmpty() or layer.extent().isNull()
    assert layer.setSubsetString("")  # sin filtro: vuelve la de toda la tabla
    layer.updateExtents()
    assert _box(layer) == pytest.approx((0, 0, 99, 49))


def test_layer_filter_changes_the_extent(session):
    """Capa → Filtrar…: «Zoom a la capa» se ajusta a lo filtrado (sin spatial: recorre la geometría)."""
    _, layer = load_table(session)
    _check_filtered_extent(layer)


@pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")
def test_layer_filter_changes_the_extent_with_spatial(session):
    """Con spatial cargada por el usuario, la extensión filtrada sale de ST_Extent_Agg."""
    session.coordinator.activate_spatial(install=False)
    assert wait_for(lambda: any(isinstance(e, SpatialActivated) for e in session.events), TIMEOUT)
    assert wait_for(lambda: session.coordinator.state is SessionState.READY, TIMEOUT)
    _, layer = load_table(session)
    _check_filtered_extent(layer)


def test_extent_with_empty_geometries_is_computed(session):
    """Con geometrías vacías, las estadísticas de DuckDB dan -inf…inf: se recorre la geometría."""
    session.sql(
        "CREATE TABLE vacias AS SELECT range AS id, CASE WHEN range % 10 = 0 THEN 'POINT EMPTY' "
        "ELSE 'POINT(' || range || ' ' || (range * 2) || ')' END::GEOMETRY AS g FROM range(100)"
    )
    report, layer = session.load(
        'SELECT * FROM "memory"."main"."vacias"', name="vacias", source=("memory", "main", "vacias")
    )
    assert layer.extent() == QgsRectangle(1, 2, 99, 198)
    assert not any("Extensión no disponible" in w for w in report.warnings)
    assert layer.dataProvider().editable  # tabla cargada desde el explorador: editable


def test_query_result_explains_how_to_edit(session):
    report, layer = session.load("SELECT * FROM puntos", name="consulta")
    assert not layer.dataProvider().editable
    assert report.origin == "consulta SQL"
    assert report.access.startswith("solo lectura") and "doble clic" in report.access
    assert not any("lectura" in w for w in report.warnings)


def test_messages_name_the_origin_and_access(session):
    """Mensajes de carga (decisión del propietario, 2026-11-02): origen y acceso explícitos."""
    from geoduck.ui.pro.load import finished_text

    report, _ = load_table(session)
    assert (report.origin, report.access) == ("tabla memory.main.puntos", "lectura y escritura")
    session.sql("CREATE VIEW vp AS SELECT * FROM puntos")
    view, _ = session.load(
        'SELECT * FROM "memory"."main"."vp"', name="vp", source=("memory", "main", "vp"), source_kind="view"
    )
    assert (view.origin, view.access) == ("vista memory.main.vp", "solo lectura")
    text = finished_text(report)
    first = f"Capa «capa» cargada · Conectada · {N:,} entidades".replace(",", " ")
    assert text == first + " · Origen: tabla memory.main.puntos · Acceso: lectura y escritura"
