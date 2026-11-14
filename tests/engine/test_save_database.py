# SPDX-License-Identifier: GPL-2.0-or-later
"""«Guardar como archivo» (#183): una base en memoria pasa a un archivo nuevo con el mismo alias."""

from __future__ import annotations

import pytest

from geoduck.domain.errors import InvalidArgumentError
from geoduck.engine.worker import SessionWorker

TIMEOUT = 60


def sql(worker, text):
    return worker.submit(lambda h, t: h.execute(text, max_rows=100)).future.result(TIMEOUT).rows


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


@pytest.mark.parametrize("active", [True, False])
def test_a_memory_database_becomes_a_file_with_the_same_alias(worker, tmp_path, active):
    sql(worker, "ATTACH ':memory:' AS otra")
    if not active:
        sql(worker, "USE otra")
    sql(worker, "CREATE TABLE memory.t AS SELECT range AS id FROM range(5)")
    sql(worker, "CREATE VIEW memory.v AS SELECT id * 2 AS doble FROM memory.t")
    path = tmp_path / "guardada.duckdb"
    result = worker.save_database_as("memory", str(path)).result(TIMEOUT)
    assert result.database.name == "memory" and result.database.path == str(path)
    assert sql(worker, "SELECT count(*), max(doble) FROM memory.v") == ((5, 8),)
    assert sql(worker, "SELECT current_database()") == ((("memory" if active else "otra"),),)
    names = {r[0] for r in sql(worker, "SELECT database_name FROM duckdb_databases() WHERE NOT internal")}
    assert names == {"memory", "otra"}  # sin bases provisionales


def test_an_existing_file_is_never_overwritten(worker, tmp_path):
    path = tmp_path / "existe.duckdb"
    path.write_bytes(b"datos del usuario")
    with pytest.raises(InvalidArgumentError):
        worker.save_database_as("memory", str(path)).result(TIMEOUT)
    assert path.read_bytes() == b"datos del usuario"
    assert sql(worker, "SELECT path FROM duckdb_databases() WHERE database_name = 'memory'") == ((None,),)


def test_a_project_file_replaces_the_empty_start_database_and_a_failure_restores_it(worker, tmp_path):
    from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
    from geoduck.domain.errors import GeoDuckError

    missing = AttachRequest(
        str(tmp_path / "no.duckdb"),
        AccessMode.READ_WRITE,
        OpenAction.OPEN_EXISTING,
        alias="memory",
        replace_empty_memory=True,
    )
    with pytest.raises(GeoDuckError):
        worker.attach(missing).result(TIMEOUT)
    assert sql(
        worker,
        "SELECT current_database(), (SELECT path FROM duckdb_databases() WHERE database_name = 'memory')",
    ) == (("memory", None),)
    path = tmp_path / "p.duckdb"
    sql(worker, f"ATTACH '{path}' AS x; CREATE TABLE x.t AS SELECT 1 AS id; DETACH x")
    request = AttachRequest(
        str(path), AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING, alias="memory", replace_empty_memory=True
    )
    worker.attach(request).result(TIMEOUT)
    assert sql(worker, "SELECT current_database(), count(*) FROM memory.t") == (("memory", 1),)


def test_geometries_keep_their_crs_in_the_saved_file(worker, tmp_path):
    sql(worker, "CREATE TABLE memory.g AS SELECT 'POINT(1 2)'::GEOMETRY('OGC:CRS84') AS g")
    path = tmp_path / "g.duckdb"
    worker.save_database_as("memory", str(path)).result(TIMEOUT)
    assert sql(worker, "SELECT typeof(g) FROM memory.g") == (("GEOMETRY('OGC:CRS84')",),)
