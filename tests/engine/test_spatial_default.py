# SPDX-License-Identifier: GPL-2.0-or-later
"""#193: `spatial` se carga al iniciar (y se instala si falta); sin ella, la sesión funciona y lo dice."""

from __future__ import annotations

import duckdb
import pytest

from geoduck.engine import worker as worker_module
from geoduck.engine.worker import SessionWorker

TIMEOUT = 120


def _spatial_available() -> bool:
    con = duckdb.connect()
    try:
        con.execute("LOAD spatial")
        return True
    except duckdb.Error:
        return False
    finally:
        con.close()


def sql(worker, text):
    return worker.submit(lambda h, t: h.execute(text, max_rows=10)).future.result(TIMEOUT).rows


@pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")
def test_a_session_starts_with_spatial_loaded_and_longitude_latitude():
    worker = SessionWorker(spatial=True)
    try:
        info = worker.start().result(TIMEOUT)
        assert info.spatial and info.spatial_error == ""
        loaded = sql(worker, "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'")
        assert loaded == ((True,),)
        assert sql(worker, "SELECT ST_Area('POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))'::GEOMETRY)") == ((4.0,),)
        axis = sql(worker, "SELECT value FROM duckdb_settings() WHERE name = 'geometry_always_xy'")
        assert axis in ((("true",),), ())  # el ajuste existe desde spatial 2.0
    finally:
        worker.close().result(TIMEOUT)


def test_without_internet_the_session_starts_anyway_with_duckdbs_message(monkeypatch):
    monkeypatch.setattr(worker_module, "_own_spatial", lambda con: "IO Error: Failed to download extension")
    worker = SessionWorker(spatial=True)
    try:
        info = worker.start().result(TIMEOUT)
        assert not info.spatial and info.spatial_error == "IO Error: Failed to download extension"
        assert sql(worker, "SELECT 42") == ((42,),)
    finally:
        worker.close().result(TIMEOUT)


def test_a_failed_install_returns_duckdbs_message_and_leaves_the_connection_usable(tmp_path):
    con = duckdb.connect()
    con.execute(f"SET extension_directory = '{tmp_path}'")  # vacía: hay que instalar
    con.execute("SET custom_extension_repository = 'http://127.0.0.1:9'")  # sin red
    message = worker_module._own_spatial(con)
    assert message  # el mensaje de DuckDB, tal cual
    assert con.execute("SELECT 1").fetchall() == [(1,)]
    con.close()


def test_spatial_can_be_left_out_for_tests():
    worker = SessionWorker(spatial=False)
    try:
        info = worker.start().result(TIMEOUT)
        assert not info.spatial and info.spatial_error == ""
    finally:
        worker.close().result(TIMEOUT)
