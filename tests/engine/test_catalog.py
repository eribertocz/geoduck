# SPDX-License-Identifier: GPL-2.0-or-later
"""Lectura del catálogo contra DuckDB real (G1 paso 2, GD-CAT-001). Matriz 1.5.0 / 1.5.x / 2.x.

Integridad: el catálogo sale siempre de `duckdb_databases()`, completo o no sale.
Concurrencia: lecturas y cambios desde varios hilos se serializan; ninguna instantánea es incoherente.
"""

from __future__ import annotations

import threading

import duckdb
import pytest

from geoduck.domain.catalog import AccessMode
from geoduck.domain.errors import ActiveResultError, EngineError, SessionClosedError
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.engine import catalog as engine_catalog
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


@pytest.fixture
def db_file(tmp_path):
    """Archivo DuckDB existente con un nombre difícil (espacios, comilla, ñ)."""
    path = tmp_path / "datos de Año's.duckdb"
    duckdb.connect(str(path)).close()
    return str(path)


def run_sql(worker, sql):
    """Solo para preparar escenarios: ATTACH/DETACH de la UI llegan en los pasos 3 y 4."""
    return worker.submit(lambda h, t: h.execute(sql)).future.result(TIMEOUT)


def test_fresh_session_has_only_the_root(worker):
    info_root = worker.submit(lambda h, t: h.execute("SELECT current_database()").rows[0][0])
    snap = worker.read_catalog().result(TIMEOUT)
    assert snap.root == info_root.future.result(TIMEOUT) == snap.default
    assert snap.attached == ()
    assert snap.root_database.in_memory and snap.root_database.access is AccessMode.READ_WRITE
    assert {d.name for d in snap.databases}.isdisjoint({"system", "temp"})


def test_engine_info_reports_the_real_root_name():
    w = SessionWorker()
    info = w.start().result(TIMEOUT)
    try:
        assert info.root_catalog == w.read_catalog().result(TIMEOUT).root
    finally:
        w.close().result(TIMEOUT)


def test_catalog_reflects_attach_detach_and_use(worker, db_file):
    alias = "Ventas Año"
    run_sql(worker, f"ATTACH {quote_string_literal(db_file)} AS {quote_identifier(alias)} (READ_ONLY)")
    run_sql(worker, "ATTACH ':memory:' AS scratch")
    snap = worker.read_catalog().result(TIMEOUT)
    assert [d.name for d in snap.attached] == [alias, "scratch"]
    ventas = snap.get(alias)
    assert ventas.path == db_file and ventas.access is AccessMode.READ_ONLY and ventas.storage == "duckdb"
    assert snap.get("scratch").in_memory and snap.get("scratch").access is AccessMode.READ_WRITE

    run_sql(worker, 'USE "ventas año"')  # otra grafía ASCII del mismo nombre
    assert worker.read_catalog().result(TIMEOUT).default == alias

    run_sql(worker, f"USE {quote_identifier(worker.read_catalog().result(TIMEOUT).root)}")
    run_sql(worker, f"DETACH {quote_identifier(alias)}")
    snap = worker.read_catalog().result(TIMEOUT)
    assert snap.get(alias) is None and [d.name for d in snap.attached] == ["scratch"]


def test_catalog_is_never_truncated(worker, monkeypatch):
    run_sql(worker, "ATTACH ':memory:' AS uno")
    monkeypatch.setattr(engine_catalog, "CATALOG_LIMIT", 1)
    with pytest.raises(EngineError, match="incompleto"):
        worker.read_catalog().result(TIMEOUT)


def test_catalog_cannot_interleave_with_an_open_arrow_reader(worker):
    """ADR-0006: con un lector abierto, la introspección se rechaza antes de llegar a DuckDB."""

    def op(h, t):
        with h.arrow_batches("SELECT * FROM range(10)", batch_size=5):
            return engine_catalog.read_catalog(h, "memory")

    with pytest.raises(ActiveResultError):
        worker.submit(op).future.result(TIMEOUT)
    assert worker.read_catalog().result(TIMEOUT).attached == ()


def test_concurrent_changes_and_reads_are_serialized_and_coherent(worker):
    errors: list[BaseException] = []
    snapshots = []
    lock = threading.Lock()

    def client(n):
        try:
            for i in range(25):
                alias = f"c{n}_{i}"
                run_sql(worker, f"ATTACH ':memory:' AS {alias}")
                snap = worker.read_catalog().result(TIMEOUT)
                assert snap.get(alias) is not None  # lo propio ya es visible
                with lock:
                    snapshots.append(snap)
                if i % 2:
                    run_sql(worker, f"DETACH {alias}")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=client, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert errors == []
    assert len(snapshots) == 100
    final = worker.read_catalog().result(TIMEOUT)
    expected = {f"c{n}_{i}" for n in range(4) for i in range(0, 25, 2)}
    assert {d.name for d in final.attached} == expected


def test_read_catalog_after_close_fails_without_touching_duckdb():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    w.close().result(TIMEOUT)
    with pytest.raises(SessionClosedError):
        w.read_catalog().result(TIMEOUT)


def test_catalog_lists_schemas_tables_views_and_temporaries(worker, db_file):
    """GD-CAT-001 / AT-CAT-001: `main` es un esquema del usuario aunque DuckDB lo marque como interno."""
    con = duckdb.connect(db_file)
    con.execute("CREATE SCHEMA ventas; CREATE TABLE ventas.t(a INT); CREATE VIEW ventas.v AS SELECT 1 AS a")
    con.close()
    run_sql(worker, f"ATTACH {quote_string_literal(db_file)} AS d (READ_ONLY)")
    run_sql(worker, "CREATE TABLE r(a INT)")
    run_sql(worker, "CREATE TEMP TABLE tmp(a INT)")
    snap = worker.read_catalog().result(TIMEOUT)
    assert snap.schemas_of("d") == ("main", "ventas")
    assert {(o.name, o.kind.value) for o in snap.objects_in("d", "ventas")} == {("t", "TABLE"), ("v", "VIEW")}
    assert [o.name for o in snap.objects_in(snap.root, "main")] == ["r"]
    assert [o.name for o in snap.temporaries] == ["tmp"]
    assert all(o.database not in ("system",) for o in snap.objects)  # nada interno de DuckDB


def test_object_list_is_never_truncated(worker, monkeypatch):
    run_sql(worker, "CREATE TABLE a(x INT)")
    run_sql(worker, "CREATE TABLE b(x INT)")
    monkeypatch.setattr(engine_catalog, "OBJECT_LIMIT", 1)
    with pytest.raises(EngineError, match="incompleto"):
        worker.read_catalog().result(TIMEOUT)
