# SPDX-License-Identifier: GPL-2.0-or-later
"""«Abrir existente» y «Crear nueva» contra DuckDB real (G1 paso 3, GD-SES-002, AT-SES-002).

Integridad: nunca se crea un archivo implícitamente, nunca se sobrescribe, el catálogo no cambia si la
operación falla. Bloqueo: un archivo bloqueado por otro proceso da `DB_LOCKED`, y el bloqueo que toma la
sesión impide abrirlo desde otro proceso mientras está adjunto.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading

import duckdb
import pytest

from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.errors import AttachError, ErrorCode, InvalidArgumentError
from geoduck.engine import attach as engine_attach
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30
RO, RW = AccessMode.READ_ONLY, AccessMode.READ_WRITE
OPEN, CREATE = OpenAction.OPEN_EXISTING, OpenAction.CREATE_NEW


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


@pytest.fixture
def existing(tmp_path):
    """Base existente con datos, en una ruta difícil (espacios, comilla, ñ)."""
    path = tmp_path / "datos de Año's.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t AS SELECT range AS x FROM range(10)")
    con.close()
    return str(path)


def digest(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def attach(worker, path, access, action, alias=None):
    return worker.attach(AttachRequest(path, access, action, alias)).result(TIMEOUT)


def attach_error(worker, path, access, action, alias=None):
    with pytest.raises(AttachError) as info:
        attach(worker, path, access, action, alias)
    return info.value


def names(worker):
    return [d.name for d in worker.read_catalog().result(TIMEOUT).attached]


def count_rows(worker, alias):
    sql = f'SELECT count(*) FROM "{alias}".t'
    return worker.submit(lambda h, t: h.execute(sql).rows[0][0]).future.result(TIMEOUT)


def hold_lock(path):
    """Otro proceso abre el archivo en lectura y escritura y lo mantiene bloqueado."""
    code = f"import duckdb,sys;c=duckdb.connect({path!r});print('ok',flush=True);sys.stdin.read()"
    proc = subprocess.Popen(
        [sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout.readline().strip() == "ok"
    return proc


def other_process_can_open(path):
    code = f"import duckdb;duckdb.connect({path!r}).close()"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=TIMEOUT, check=False)
    return done.returncode == 0


# -- Abrir existente --------------------------------------------------------------------------------


@pytest.mark.parametrize("access", [RO, RW])
def test_open_existing_attaches_with_requested_access(worker, existing, access):
    before = digest(existing) if access is RO else None
    result = attach(worker, existing, access, OPEN)
    assert result.database.name == "datos de Año's"  # alias por defecto: nombre sin extensión
    assert result.database.path == existing and result.database.access is access
    assert result.catalog.get("datos de Año's") == result.database
    assert count_rows(worker, "datos de Año's") == 10
    if access is RO:
        with pytest.raises(Exception, match="read-only"):
            worker.submit(lambda h, t: h.execute('CREATE TABLE "datos de Año\'s".u(x INT)')).future.result(
                TIMEOUT
            )
        assert digest(existing) == before


@pytest.mark.parametrize("access", [RO, RW])
def test_open_existing_never_creates_a_missing_file(worker, tmp_path, access):
    """F-18: DuckDB crearía el archivo en RW; GeoDuck lo impide."""
    missing = str(tmp_path / "no_existe.duckdb")
    error = attach_error(worker, missing, access, OPEN)
    assert error.code is ErrorCode.DB_NOT_FOUND
    assert not os.path.exists(missing) and not os.path.exists(missing + ".wal")
    assert names(worker) == []


def test_open_existing_rejects_a_file_replaced_during_attach(worker, existing, monkeypatch):
    """Si el archivo se borra entre la comprobación y el ATTACH, DuckDB crearía otro: se detecta."""
    original = engine_attach._execute_attach

    def replace_then_attach(handle, sql):
        os.remove(existing)
        original(handle, sql)

    monkeypatch.setattr(engine_attach, "_execute_attach", replace_then_attach)
    error = attach_error(worker, existing, RW, OPEN)
    assert error.code is ErrorCode.DB_NOT_FOUND and error.detail == "file_replaced_during_attach"
    assert names(worker) == []


def test_open_existing_on_a_non_duckdb_file_leaves_it_untouched(worker, tmp_path):
    other = tmp_path / "notas.duckdb"
    other.write_text("no es una base" * 50)
    before = digest(str(other))
    error = attach_error(worker, str(other), RW, OPEN)
    assert error.code is ErrorCode.ENGINE_ERROR and "no es una base DuckDB" in error.message
    assert digest(str(other)) == before and names(worker) == []


def test_open_existing_directory_is_not_a_file(worker, tmp_path):
    assert attach_error(worker, str(tmp_path), RO, OPEN).code is ErrorCode.DB_NOT_FOUND


# -- Crear nueva ------------------------------------------------------------------------------------


def test_create_new_creates_a_valid_empty_database(worker, tmp_path):
    path = str(tmp_path / "nueva base.duckdb")
    result = attach(worker, path, RW, CREATE, alias="Nueva")
    assert os.path.isfile(path)
    assert result.database.name == "Nueva" and result.database.access is RW and result.database.path == path
    worker.submit(lambda h, t: h.execute('CREATE TABLE "Nueva".t AS SELECT 1 AS x')).future.result(TIMEOUT)
    assert count_rows(worker, "Nueva") == 1


def test_create_new_never_overwrites(worker, existing):
    before = digest(existing)
    with pytest.raises(InvalidArgumentError, match="nunca lo sobrescribe"):
        attach(worker, existing, RW, CREATE)
    assert digest(existing) == before and names(worker) == []


def test_create_new_refuses_a_stale_wal(worker, tmp_path):
    path = str(tmp_path / "x.duckdb")
    with open(path + ".wal", "wb") as fh:
        fh.write(b"\0" * 16)
    with pytest.raises(InvalidArgumentError, match=r"\.wal"):
        attach(worker, path, RW, CREATE)
    assert not os.path.exists(path)


def test_create_new_never_creates_directories(worker, tmp_path):
    path = str(tmp_path / "no" / "existe" / "x.duckdb")
    assert attach_error(worker, path, RW, CREATE).code is ErrorCode.DB_NOT_FOUND
    assert not os.path.exists(tmp_path / "no")


def test_create_new_read_only_is_rejected_before_the_engine(tmp_path):
    with pytest.raises(InvalidArgumentError):
        AttachRequest(str(tmp_path / "x.duckdb"), RO, CREATE)


# -- alias -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("alias", ["Ventas", "VENTAS", "ventas"])
def test_alias_conflict_follows_duckdb_rule(worker, existing, tmp_path, alias):
    attach(worker, existing, RO, OPEN, alias="Ventas")
    path = str(tmp_path / "otra.duckdb")
    error = attach_error(worker, path, RW, CREATE, alias=alias)
    assert error.code is ErrorCode.DB_ALIAS_CONFLICT
    assert not os.path.exists(path)  # se rechaza antes de llegar a DuckDB


@pytest.mark.parametrize("alias", ["system", "TEMP"])
def test_reserved_aliases_are_rejected(worker, existing, alias):
    assert attach_error(worker, existing, RO, OPEN, alias=alias).code is ErrorCode.DB_ALIAS_CONFLICT


def test_root_name_is_taken(worker, existing):
    root = worker.read_catalog().result(TIMEOUT).root
    assert attach_error(worker, existing, RO, OPEN, alias=root.upper()).code is ErrorCode.DB_ALIAS_CONFLICT


def test_same_file_twice_in_read_write_is_a_conflict(worker, existing):
    attach(worker, existing, RW, OPEN, alias="a")
    assert attach_error(worker, existing, RW, OPEN, alias="b").code is ErrorCode.DB_ALIAS_CONFLICT
    assert names(worker) == ["a"]


def test_alias_with_quotes_and_semicolon_is_a_plain_identifier(worker, existing):
    alias = 'x"; DROP TABLE t; --'
    attach(worker, existing, RW, OPEN, alias=alias)
    assert names(worker) == [alias] and count_rows(worker, alias.replace('"', '""')) == 10


# -- bloqueos entre procesos ----------------------------------------------------------------------


@pytest.mark.parametrize("access", [RO, RW])
def test_file_locked_by_another_process_is_db_locked(worker, existing, access):
    proc = hold_lock(existing)
    try:
        error = attach_error(worker, existing, access, OPEN)
        assert error.code is ErrorCode.DB_LOCKED
        assert existing not in error.detail  # el detalle técnico no lleva la ruta del usuario
        assert names(worker) == []
    finally:
        proc.communicate("", timeout=TIMEOUT)
    attach(worker, existing, access, OPEN)  # liberado el bloqueo, la misma petición funciona


def test_read_write_attach_holds_the_lock_until_the_session_closes(existing):
    w = SessionWorker()
    w.start().result(TIMEOUT)
    attach(w, existing, RW, OPEN)
    assert not other_process_can_open(existing)
    w.close().result(TIMEOUT)
    assert other_process_can_open(existing)


# -- concurrencia ----------------------------------------------------------------------------------


def test_concurrent_creates_with_the_same_alias_only_one_wins(worker, tmp_path):
    results, errors = [], []

    def client(n):
        try:
            results.append(attach(worker, str(tmp_path / f"c{n}.duckdb"), RW, CREATE, alias="comun"))
        except AttachError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=client, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(TIMEOUT)
    assert len(results) == 1 and len(errors) == 5
    assert all(e.code is ErrorCode.DB_ALIAS_CONFLICT for e in errors)
    created = sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".duckdb")
    assert created == [os.path.basename(results[0].database.path)]  # ningún archivo de más
