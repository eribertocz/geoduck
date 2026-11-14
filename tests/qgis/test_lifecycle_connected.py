# SPDX-License-Identifier: GPL-2.0-or-later
"""Ciclo de vida de las capas Conectadas (G3/E7; AT-BRD-011; qgis-bridge-spec §5.5).

DETACH y ATTACH, cierre de la sesión, cambios sin guardar y reapertura del proyecto.
"""

from __future__ import annotations

import duckdb
import pytest
from qgis.core import QgsFeatureRequest, QgsProject

from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.errors import SessionStateError
from geoduck.domain.session import SessionState
from geoduck.qgis_bridge.provider import decode_uri
from tests.qgis.conftest import wait_for
from tests.qgis.test_load_connected import Session

pytestmark = pytest.mark.qgis

TIMEOUT = 60


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "datos.duckdb"
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, nombre VARCHAR, g GEOMETRY); "
        "INSERT INTO t SELECT range, 'n' || range, ('POINT(' || range || ' 0)')::GEOMETRY "
        "FROM range(300)"
    )
    con.close()
    return path


@pytest.fixture
def session(qgis_app):
    s = Session()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().clear()


def attach(s, path, alias="d"):
    s.coordinator.attach_database(
        AttachRequest(str(path), AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING, alias=alias)
    )
    assert wait_for(
        lambda: (
            s.coordinator.state is SessionState.READY
            and s.coordinator.catalog is not None
            and any(d.name == alias for d in s.coordinator.catalog.databases)
        ),
        TIMEOUT,
    )


def detach(s, alias="d"):
    s.coordinator.detach_database(alias)
    assert wait_for(
        lambda: (
            s.coordinator.state is SessionState.READY
            and not any(d.name == alias for d in s.coordinator.catalog.databases)
        ),
        TIMEOUT,
    )


def load_t(s):
    _, layer = s.load('SELECT * FROM "d"."main"."t"', name="t", source=("d", "main", "t"))
    return layer


def count(layer):
    return sum(1 for _ in layer.getFeatures())


def test_detach_makes_the_layer_unavailable_and_attach_brings_it_back(session, database):
    attach(session, database)
    layer = load_t(session)
    assert decode_uri(layer.source())["scope"] == "attached"
    assert count(layer) == 300
    detach(session)
    assert not layer.isValid()  # no disponible en QGIS (#183), con su nombre y en el proyecto
    assert layer.name() == "t" and QgsProject.instance().mapLayer(layer.id()) is layer
    assert count(layer) == 0
    attach(session, database)
    assert layer.isValid()
    assert count(layer) == 300


def test_unsaved_edits_block_detach_and_close(session, database):
    attach(session, database)
    layer = load_t(session)
    assert layer.startEditing()
    layer.changeAttributeValue(1, layer.fields().indexOf("nombre"), "sin guardar")
    with pytest.raises(SessionStateError, match="sin guardar"):
        session.coordinator.detach_database("d")
    with pytest.raises(SessionStateError, match="sin guardar"):
        session.coordinator.request_close()
    assert session.coordinator.state is SessionState.READY
    assert layer.commitChanges(), layer.commitErrors()
    detach(session)  # ya guardado: permitido


def test_close_makes_layers_unavailable_and_a_new_session_reconnects_attached_ones(session, database):
    attach(session, database)
    attached = load_t(session)
    session.sql("CREATE TABLE m AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY AS g")
    _, in_memory = session.load('SELECT * FROM "memory"."main"."m"', name="m", source=("memory", "main", "m"))
    assert count(in_memory) == 1
    session.coordinator.close_session().result(TIMEOUT)
    assert wait_for(lambda: session.coordinator.state is SessionState.DISCONNECTED, TIMEOUT)
    assert not attached.isValid() and not in_memory.isValid()
    session.coordinator.start_memory_session()
    assert wait_for(lambda: session.coordinator.state is SessionState.READY, TIMEOUT)
    session.engine = session.coordinator._engine
    session.sql("CREATE TABLE m AS SELECT 99 AS id, 'POINT(5 5)'::GEOMETRY AS g")
    assert not in_memory.isValid()  # :memory: no sobrevive: nunca muestra la tabla homónima de otra sesión
    attach(session, database)
    assert attached.isValid() and count(attached) == 300


def test_reopened_project_reconnects_when_the_database_is_attached(session, database, tmp_path):
    attach(session, database)
    layer = load_t(session)
    project = QgsProject.instance()
    path = str(tmp_path / "proyecto.qgz")
    assert project.write(path)
    layer_id = layer.id()
    project.clear()
    detach(session)
    assert project.read(path)
    reopened = project.mapLayer(layer_id)
    assert reopened is not None and reopened.providerType() == "geoduck"
    assert not reopened.isValid()  # sin la base adjunta: no disponible
    attach(session, database)
    assert reopened.isValid() and count(reopened) == 300
    assert reopened.dataProvider().editable
    assert reopened.startEditing()  # el guardado atómico vuelve a estar conectado
    reopened.changeAttributeValue(2, reopened.fields().indexOf("nombre"), "tras reabrir")
    assert reopened.commitChanges(), reopened.commitErrors()
    rows = (
        session.engine.query("SELECT nombre FROM d.t WHERE id = 2", priority=False)
        .future.result(TIMEOUT)
        .rows
    )
    assert rows == (("tras reabrir",),)


def test_g3_gate_walkthrough(session, database):
    """Recorrido del gate de G3: sesión → ATTACH → SELECT → las tres modalidades → editar la Conectada →
    DETACH. Memoria e Instantánea siguen intactas; la Conectada queda no disponible hasta volver a
    adjuntar la base."""
    from geoduck.app.events import LoadFinished
    from geoduck.domain.load import LoadMode, LoadRequest

    attach(session, database)
    layers = {}
    for mode in (LoadMode.MEMORY, LoadMode.SNAPSHOT):
        before = len(session.events)
        session.coordinator.load(LoadRequest('SELECT * FROM "d"."main"."t"', mode, mode.value))
        assert wait_for(
            lambda before=before: any(isinstance(e, LoadFinished) for e in session.events[before:]), TIMEOUT
        )
        event = next(e for e in session.events[before:] if isinstance(e, LoadFinished))
        layers[mode] = QgsProject.instance().mapLayer(event.report.layer_id)
    layers[LoadMode.CONNECTED] = load_t(session)
    assert {m: count(lyr) for m, lyr in layers.items()} == dict.fromkeys(LoadMode, 300)

    connected = layers[LoadMode.CONNECTED]
    assert connected.startEditing()
    connected.changeAttributeValue(5, connected.fields().indexOf("nombre"), "editada")
    assert connected.commitChanges(), connected.commitErrors()
    rows = (
        session.engine.query("SELECT nombre FROM d.t WHERE id = 5", priority=False)
        .future.result(TIMEOUT)
        .rows
    )
    assert rows == (("editada",),)

    detach(session)
    assert count(layers[LoadMode.MEMORY]) == 300
    assert count(layers[LoadMode.SNAPSHOT]) == 300
    assert not connected.isValid()
    attach(session, database)
    assert count(connected) == 300
    assert next(connected.getFeatures(QgsFeatureRequest(5)))["nombre"] == "editada"


def test_sql_detach_with_unsaved_edits_is_rejected_but_harmless_sql_runs(session, database):
    """§5.5: solo un DETACH real de la base con cambios sin guardar se rechaza; nada del script corre."""
    from geoduck.app.events import ScriptFinished, ScriptRejected
    from geoduck.domain.sql import RunScope

    attach(session, database)
    layer = load_t(session)
    assert layer.startEditing()
    layer.changeAttributeValue(1, layer.fields().indexOf("nombre"), "sin guardar")

    def run(text):
        before = len(session.events)
        session.coordinator.execute_sql(text, RunScope.ALL)
        assert wait_for(
            lambda: (
                session.coordinator.state is SessionState.READY
                and any(isinstance(e, (ScriptFinished, ScriptRejected)) for e in session.events[before:])
            ),
            TIMEOUT,
        )
        return next(e for e in session.events[before:] if isinstance(e, (ScriptFinished, ScriptRejected)))

    rejected = run("CREATE TABLE d.nueva (x INTEGER); DETACH d")
    assert isinstance(rejected, ScriptRejected) and "«t»" in rejected.message
    assert any(db.name == "d" for db in session.coordinator.catalog.databases)
    tables = session.engine.query("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'nueva'").future
    assert tables.result(TIMEOUT).rows == ((0,),)  # nada del script se ejecutó
    harmless = run("SELECT 'DETACH d' AS texto; -- DETACH d\n/* DETACH d */ SELECT 1")
    assert isinstance(harmless, ScriptFinished) and not harmless.run.failed
    assert layer.isEditable() and layer.isModified()  # los cambios siguen pendientes
    layer.rollBack()
    assert isinstance(run("DETACH d"), ScriptFinished)
