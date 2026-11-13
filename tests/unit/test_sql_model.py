# SPDX-License-Identifier: GPL-2.0-or-later
"""Modelo de ejecución SQL (G2), sin DuckDB."""

import pytest

from geoduck.domain.sql import SqlStatement, error_offset_in, error_token, statement_at


def st(i, start, end, kind="SELECT"):
    return SqlStatement(i, kind, "x", start, end)


STATEMENTS = (st(0, 0, 10), st(1, 10, 25), st(2, 27, 40))


@pytest.mark.parametrize(("cursor", "index"), [(0, 0), (9, 0), (10, 1), (24, 1), (26, 1), (27, 2), (99, 2)])
def test_current_statement_for_the_cursor(cursor, index):
    assert statement_at(STATEMENTS, cursor).index == index


def test_current_statement_of_an_empty_script():
    assert statement_at((), 5) is None


@pytest.mark.parametrize(
    ("kind", "replayable", "changes"),
    [
        ("SELECT", True, False),
        ("EXPLAIN", False, False),
        ("INSERT", False, True),
        ("CREATE", False, True),
        ("TRANSACTION", False, True),
        ("ATTACH", False, True),
        ("PRAGMA", False, True),
    ],
)
def test_only_reads_are_replayable_and_everything_else_may_change_state(kind, replayable, changes):
    statement = st(0, 0, 1, kind)
    assert statement.replayable is replayable and statement.may_change_state is changes


def test_error_offset_from_duckdb_message():
    text = "SELECT 1;\n\n  SELEC 2;"
    message = 'Parser Error: syntax error at or near "SELEC"\n\nLINE 3:   SELEC 2;\n          ^^^^^'
    assert text[error_offset_in(text, message) :].startswith("SELEC")


def test_error_offset_is_unknown_when_duckdb_truncates_the_line():
    text = "SELECT " + "x, " * 200 + "nada"
    message = "Binder Error: algo\n\nLINE 1: ...x, x, nada\n                    ^"
    assert error_offset_in(text, message) is None


def test_error_offset_is_unknown_without_position():
    assert error_offset_in("SELECT 1", "Catalog Error: sin posición") is None


def test_error_token_uses_the_word_duckdb_names_at_the_offset():
    text = "SELECT zona\nFROM t GROUP zona;"
    offset = text.rindex("zona")
    assert error_token(text, offset, 'Parser Error: syntax error at or near "zona"') == "zona"
    text = "SELECT zona, kwhh FROM norte"
    message = 'Binder Error: Referenced column "kwhh" not found in FROM clause!\nCandidate bindings: "kwh"'
    assert error_token(text, text.index("kwhh"), message) == "kwhh"


def test_error_token_falls_back_to_the_token_at_the_offset():
    text = 'SELECT "Nombre Cliente", x::DOUBLE FROM t'
    assert error_token(text, text.index('"Nombre'), "Some error") == '"Nombre Cliente"'
    assert error_token(text, text.index("::"), "Conversion Error: …") == ":"
    assert error_token(text, text.index("x::"), "Conversion Error: …") == "x"
    assert error_token(text, None, "x") == ""
    assert error_token(text, len(text), "x") == ""
