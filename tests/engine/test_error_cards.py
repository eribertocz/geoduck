# SPDX-License-Identifier: GPL-2.0-or-later
"""Errores de primer nivel contra DuckDB real (#145; matriz 1.5 / 2.x): la sesión conserva la clase y el
mensaje completo de DuckDB, y cada tarjeta sale de ellos (título, lugar y arreglo)."""

from __future__ import annotations

import json

import pytest

from geoduck.domain.i18n import tr
from geoduck.domain.sql import RunScope, StatementStatus
from geoduck.domain.sql_errors import CHOOSE_FILE, LOAD_EXTENSION, REPLACE, explain, syntax_error
from geoduck.domain.sql_text import quote_string_literal
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 30


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    w.run_script(
        run_id=0,
        text="CREATE TABLE lecturas AS SELECT 'Sur' AS zona, 1.5::DOUBLE AS kwh, 'n/d' AS texto;",
        scope=RunScope.ALL,
        preview_limit=200,
    ).future.result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


def card(worker, text):
    run = worker.run_script(run_id=1, text=text, scope=RunScope.ALL, preview_limit=200).future.result(TIMEOUT)
    if run.parse_error:
        return explain("", run.parse_error_detail, text, run.parse_error_offset)
    failed = next(r for r in run.results if r.status is StatementStatus.FAILED)
    assert failed.error_kind and failed.error_detail.startswith(failed.message)
    return explain(
        failed.error_kind,
        failed.error_detail,
        text,
        failed.error_offset,
        statement_start=failed.statement.start,
        statement_end=failed.statement.end,
    )


def test_column_table_and_conversion_cards_from_real_duckdb(worker):
    text = "SELECT 1;\nSELECT kwhh FROM lecturas;"
    column = card(worker, text)
    assert column.title == tr("The column «{}» does not exist").format("kwhh") and column.line == 1
    assert column.fixes[0].kind == REPLACE and column.fixes[0].text == "kwh"
    assert text[column.fixes[0].start : column.fixes[0].end] == "kwhh"
    table = card(worker, "SELECT * FROM lectura;")
    assert table.title == tr("The table «{}» does not exist").format("lectura")
    assert table.fixes[0].text == "lecturas"
    text = "SELECT texto::DOUBLE FROM lecturas;"
    value = card(worker, text)
    assert value.title == tr("A value of «{}» is not a number").format("texto")
    assert value.fixes[0].text == "TRY_CAST(texto AS DOUBLE)"


def test_spatial_file_and_syntax_cards_from_real_duckdb(worker):
    spatial = card(worker, "SELECT ST_Area(NULL);")
    if spatial.fixes and spatial.fixes[0].kind == LOAD_EXTENSION:  # sin spatial cargada (lo normal)
        assert spatial.title == tr("This query needs the «{}» extension").format("spatial")
    missing = card(worker, "SELECT * FROM 'no/existe/lecturas.parquet';")
    assert missing.title == tr("The file is not found") and missing.fixes[0].kind == CHOOSE_FILE
    syntax = card(worker, "SELECT zona FROM lecturas\nGROUP zona;")
    assert syntax.kind == "Parser Error" and syntax.line == 1


def test_json_serialize_sql_checks_syntax_without_running(worker):
    def serialized(text):
        sql = f"SELECT json_serialize_sql({quote_string_literal(text)})"
        rows = worker.submit(lambda h, _t: h.execute(sql).rows).future.result(TIMEOUT)
        return json.loads(rows[0][0])

    message, position = syntax_error(serialized("SELECT zona, sum(kwh)\nFROM lecturas\nGROUP zona;"))
    assert "zona" in message and position == len("SELECT zona, sum(kwh)\nFROM lecturas\nGROUP ")
    assert syntax_error(serialized("SELECT kwhh FROM no_existe")) is None  # solo sintaxis: no lee el catálogo
    assert syntax_error(serialized("CREATE TABLE x AS SELECT 1")) is None  # «solo SELECT» no es un error
