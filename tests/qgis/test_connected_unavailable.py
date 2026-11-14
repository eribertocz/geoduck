# SPDX-License-Identifier: GPL-2.0-or-later
"""Capas Conectadas que nunca quedan huérfanas (#183; qgis-bridge-spec §5.5).

Otro archivo con el mismo alias, guardar una base en memoria como archivo, abrir un proyecto con GeoDuck
cerrado, tablas temporales y un `DETACH` escrito en el editor.
"""

from __future__ import annotations

import duckdb
import pytest
from qgis.core import QgsProject

from geoduck.app.events import LoadFailed
from geoduck.domain.load import LoadMode, LoadRequest
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.provider import IN_MEMORY, decode_uri
from tests.qgis.conftest import wait_for
from tests.qgis.test_lifecycle_connected import attach, count, detach, load_t
from tests.qgis.test_load_connected import Session

pytestmark = pytest.mark.qgis

TIMEOUT = 60


def make_db(path, rows):
    con = duckdb.connect(str(path))
    con.execute(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, nombre VARCHAR, g GEOMETRY); "
        f"INSERT INTO t SELECT range, 'n' || range, ('POINT(' || range || ' 0)')::GEOMETRY FROM range({rows})"
    )
    con.close()
    return path


@pytest.fixture
def session(qgis_app):
    s = Session()
    yield s
    s.close()
    sessions.set_resolver(None)
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().clear()


def test_another_file_with_the_same_alias_never_feeds_the_layer(session, tmp_path):
    first, other = make_db(tmp_path / "a.duckdb", 300), make_db(tmp_path / "b.duckdb", 7)
    attach(session, first)
    layer = load_t(session)
    assert decode_uri(layer.source())["file"] == str(first)
    detach(session)
    attach(session, other)
    assert not layer.isValid()
    assert "otro archivo" in layer.dataProvider().unavailable_reason()
    detach(session)
    attach(session, first)
    assert layer.isValid() and count(layer) == 300


def test_a_memory_database_saved_as_a_file_keeps_its_layers(session, tmp_path):
    session.sql(
        "CREATE TABLE m AS SELECT range AS id, ('POINT(' || range || ' 1)')::GEOMETRY AS g FROM range(4)"
    )
    session.coordinator.refresh_catalog()
    _, layer = session.load('SELECT * FROM "memory"."main"."m"', name="m", source=("memory", "main", "m"))
    assert decode_uri(layer.source())["file"] == IN_MEMORY
    assert session.loader.in_memory() == {"memory": ["m"]}
    path = tmp_path / "guardada.duckdb"
    session.coordinator.save_database_as("memory", str(path))
    assert wait_for(lambda: session.coordinator.state is SessionState.READY and path.exists(), TIMEOUT)
    params = decode_uri(layer.source())
    assert params["file"] == str(path) and params["scope"] == "attached"
    assert layer.isValid() and count(layer) == 4
    assert session.loader.in_memory() == {}
    # Una sesión nueva: su base del inicio, vacía, se reemplaza por el archivo con el mismo alias.
    session.coordinator.close_session().result(TIMEOUT)
    assert wait_for(lambda: session.coordinator.state is SessionState.DISCONNECTED, TIMEOUT)
    assert not layer.isValid()
    ok = session.coordinator.open_for_project(str(path), "memory")
    assert ok, [e for e in session.events[-6:]]
    assert layer.isValid() and count(layer) == 4


def test_opening_a_project_starts_geoduck_and_opens_its_databases(session, tmp_path):
    database = make_db(tmp_path / "catastro.duckdb", 300)
    attach(session, database, alias="d")
    layer = load_t(session)
    layer_id = layer.id()
    project = QgsProject.instance()
    project_path = str(tmp_path / "proyecto.qgz")
    assert project.write(project_path)
    session.coordinator.close_session().result(TIMEOUT)
    assert wait_for(lambda: session.coordinator.state is SessionState.DISCONNECTED, TIMEOUT)
    project.clear()
    opened = []

    def resolve(alias, path):
        opened.append((alias, path))
        return session.coordinator.open_for_project(path, alias)

    sessions.set_resolver(resolve)
    assert project.read(project_path)
    reopened = project.mapLayer(layer_id)
    assert opened == [("d", str(database))]
    assert reopened is not None and reopened.isValid() and count(reopened) == 300
    assert session.coordinator.state is SessionState.READY


def test_a_missing_file_leaves_the_layer_unavailable_when_the_project_opens(session, tmp_path):
    database = make_db(tmp_path / "catastro.duckdb", 3)
    attach(session, database)
    layer_id = load_t(session).id()
    project = QgsProject.instance()
    project_path = str(tmp_path / "proyecto.qgz")
    assert project.write(project_path)
    detach(session)
    database.unlink()
    project.clear()
    sessions.set_resolver(lambda alias, path: session.coordinator.open_for_project(path, alias))
    assert project.read(project_path)
    reopened = project.mapLayer(layer_id)
    assert reopened is not None and not reopened.isValid()


def test_temporary_tables_only_load_as_a_copy(session):
    session.sql("CREATE TEMP TABLE tmp AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY AS g")
    for sql, source in (
        ('SELECT * FROM "temp"."main"."tmp"', ("temp", "main", "tmp")),
        ("SELECT * FROM tmp", None),
    ):
        before = len(session.events)
        session.coordinator.load(
            LoadRequest(sql=sql, mode=LoadMode.CONNECTED, layer_name="tmp", source=source)
        )
        assert wait_for(
            lambda before=before: any(isinstance(e, LoadFailed) for e in session.events[before:]), TIMEOUT
        )
        failed = next(e for e in session.events[before:] if isinstance(e, LoadFailed))
        assert "temporales" in failed.message


def test_a_typed_detach_of_a_memory_database_with_layers_is_rejected(session):
    session.sql(
        "ATTACH ':memory:' AS otra; CREATE TABLE otra.m AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY AS g"
    )
    session.coordinator.refresh_catalog()
    assert wait_for(
        lambda: (
            session.coordinator.catalog is not None
            and any(d.name == "otra" for d in session.coordinator.catalog.databases)
        ),
        TIMEOUT,
    )
    _, layer = session.load('SELECT * FROM "otra"."main"."m"', name="m", source=("otra", "main", "m"))
    session.coordinator.execute_sql("DETACH otra", RunScope.ALL)
    assert wait_for(lambda: session.coordinator.state is SessionState.READY, TIMEOUT)
    assert any(d.name == "otra" for d in session.coordinator.catalog.databases)
    assert layer.isValid() and count(layer) == 1
