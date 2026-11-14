# SPDX-License-Identifier: GPL-2.0-or-later
"""Errores de primer nivel sin Qt ni DuckDB (#145, punto 13; `geoduck.domain.sql_errors`).

Los mensajes son los de DuckDB 1.5 y 2.0 tal cual (la marca `LINE n ^` cambia de largo entre versiones)."""

from __future__ import annotations

import pytest

from geoduck.domain.i18n import tr
from geoduck.domain.sql import error_offset_in
from geoduck.domain.sql_errors import (
    CHOOSE_FILE,
    INSERT,
    LOAD_EXTENSION,
    OPEN_FOLDER,
    REPLACE,
    char_offset,
    error_class,
    explain,
    syntax_error,
)

BINDER = (
    'Binder Error: Referenced column "kwhh" not found in FROM clause!\nCandidate bindings: "kwh"\n\n'
    "LINE 2: SELECT zona, kwhh FROM norte;\n                     ^^^^"
)
CATALOG = (
    'Catalog Error: Table with name lectura does not exist!\nDid you mean "lecturas"?\n\n'
    "LINE 1: SELECT * FROM lectura\n                      ^"
)
SPATIAL = (
    'Catalog Error: Scalar Function with name "st_area" is not in the catalog, but it exists in the spatial '
    "extension.\n\nPlease try installing and loading the spatial extension:\n"
    "INSTALL spatial;\nLOAD spatial;\n"
)
CONVERSION = (
    "Conversion Error: Could not convert string 'n/d' to DOUBLE when casting from source column kwh\n\n"
    "LINE 1: SELECT kwh::DOUBLE FROM t\n                  ^^^^^^^^"
)
IO = 'IO Error: No files found that match the pattern "C:\\datos\\lecturas_2025.parquet"'
MEMORY = "Out of Memory Error: failed to allocate data of size 256.0 MiB (3.9 GiB/4.0 GiB used)"


def card_for(kind, message, text):
    offset = error_offset_in(text, message)
    return explain(kind, message, text, offset, statement_end=len(text))


def test_the_class_comes_from_the_exception_or_the_message():
    assert error_class("BinderException", "x") == "Binder Error"
    assert error_class("", "Catalog Error: Table with name t does not exist!") == "Catalog Error"
    assert error_class("", "algo raro") == ""


def test_a_missing_column_offers_the_candidate_duckdb_names():
    text = "CREATE TABLE norte AS SELECT 1 AS kwh;\nSELECT zona, kwhh FROM norte;"
    card = card_for("BinderException", BINDER, text)
    assert card.title == tr("The column «{}» does not exist").format("kwhh")
    assert card.where == tr("Line {0} · near «{1}»").format(2, "kwhh") and card.line == 1
    assert card.explanation == tr("Suggestion: {}.").format("kwh")
    [fix] = card.fixes
    assert (fix.kind, fix.label, text[fix.start : fix.end], fix.text) == (
        REPLACE,
        tr("Change to «{}»").format("kwh"),
        "kwhh",
        "kwh",
    )
    assert card.original == BINDER.strip()


def test_a_missing_table_follows_did_you_mean():
    text = "SELECT * FROM lectura"
    card = card_for("CatalogException", CATALOG, text)
    assert card.title == tr("The table «{}» does not exist").format("lectura")
    assert card.fixes[0].text == "lecturas" and text[card.fixes[0].start : card.fixes[0].end] == "lectura"


def test_a_function_of_spatial_asks_to_load_it_and_others_only_write_the_load():
    card = card_for("CatalogException", SPATIAL, "SELECT ST_Area(geom) FROM t")
    assert card.title == tr("This query needs the «{}» extension").format("spatial")
    assert [(f.kind, f.value) for f in card.fixes] == [(LOAD_EXTENSION, "spatial")]
    other = SPATIAL.replace("spatial", "httpfs").replace('"st_area"', '"read_x"')
    card = card_for("CatalogException", other, "SELECT read_x()")
    assert card.fixes[0].kind == INSERT and card.fixes[0].text == "INSTALL httpfs;\nLOAD httpfs;\n"


@pytest.mark.parametrize(
    ("text", "replacement"),
    [
        ("SELECT kwh::DOUBLE FROM t", "TRY_CAST(kwh AS DOUBLE)"),
        ("SELECT CAST(kwh AS DOUBLE) FROM t", "TRY_CAST"),
    ],
)
def test_a_value_that_does_not_convert_offers_try_cast(text, replacement):
    message = CONVERSION.replace("SELECT kwh::DOUBLE FROM t", text)
    card = explain("ConversionException", message, text, text.find("kwh::") if "::" in text else 7)
    assert card.title == tr("A value of «{}» is not a number").format("kwh")
    assert tr("source column «{}»").format("kwh") in card.where
    assert card.fixes[0].kind == REPLACE and card.fixes[0].text == replacement
    assert tr("The value «{0}» cannot be converted to {1}.").format("n/d", "DOUBLE") in card.explanation


def test_a_missing_file_offers_to_choose_another_and_open_its_folder():
    text = "SELECT * FROM 'C:\\datos\\lecturas_2025.parquet';"
    card = card_for("IOException", IO, text)
    assert card.title == tr("The file is not found")
    choose, folder = card.fixes
    assert (
        choose.kind == CHOOSE_FILE and text[choose.start : choose.end] == "'C:\\datos\\lecturas_2025.parquet'"
    )
    assert folder.kind == OPEN_FOLDER and folder.value == "C:\\datos"
    assert card.where == tr("Line {0} · «{1}»").format(1, "C:\\datos\\lecturas_2025.parquet")


def test_out_of_memory_says_how_much_and_writes_a_higher_limit():
    card = card_for("OutOfMemoryException", MEMORY, "SELECT * FROM grande")
    assert card.title == tr("The query needs more memory than allowed")
    assert card.explanation == tr("{0} of {1} were used (session «memory_limit»).").format(
        "3.9 GiB", "4.0 GiB"
    )
    assert card.where == tr("Line {0} · the whole statement").format(1)
    assert card.fixes[0].kind == INSERT and card.fixes[0].text == "SET memory_limit = '8GB';\n"


def test_a_syntax_error_and_any_other_class_still_get_a_card():
    text = "SELECT * FRM t"
    card = card_for("ParserException", 'Parser Error: syntax error at or near "t"', text)
    assert card.title == tr("Syntax error near «{}»").format("t") or card.title == tr("Syntax error")
    card = card_for("", 'Constraint Error: Duplicate key "id: 1" violates primary key constraint.', "INSERT")
    assert card.title == tr("A rule of the table does not allow this change") and card.fixes == ()
    card = card_for("WeirdException", "Something odd", "SELECT 1")
    assert card.title == tr("This statement could not run") and card.explanation == "Something odd"


def test_the_typing_check_reads_only_syntax_errors_and_counts_bytes():
    assert syntax_error({"error": False}) is None
    assert (
        syntax_error({"error": True, "error_type": "not implemented", "error_message": "Only SELECT"}) is None
    )
    found = syntax_error(
        {
            "error": True,
            "error_type": "parser",
            "error_message": 'syntax error at or near "zona"',
            "position": "42",
        }
    )
    assert found == ('syntax error at or near "zona"', 42)
    text = "SELECT 'ñandú', x FRM t"
    assert char_offset(text, len("SELECT 'ñandú', x ".encode())) == len("SELECT 'ñandú', x ")
