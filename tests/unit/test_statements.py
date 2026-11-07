# SPDX-License-Identifier: GPL-2.0-or-later
"""La sentencia que marca y corre «Ejecutar» (workspace-pro-spec §5)."""

from __future__ import annotations

from geoduck.domain.statements import current_span, statement_spans

TEXT = "CREATE TABLE t AS SELECT 1 AS x;\n\n-- borrar\nDELETE FROM t;\n\nSELECT x\nFROM t\nWHERE x > 0;\n"


def pieces(text):
    return [text[a:b] for a, b in statement_spans(text)]


def test_spans_skip_blank_lines_comments_and_empty_pieces():
    assert pieces(TEXT) == [
        "CREATE TABLE t AS SELECT 1 AS x;",
        "DELETE FROM t;",
        "SELECT x\nFROM t\nWHERE x > 0;",
    ]
    assert pieces(";;  -- nada\n") == []
    assert pieces("SELECT 1") == ["SELECT 1"]  # la última sin `;`


def test_semicolons_in_strings_and_comments_do_not_split():
    text = "SELECT 'a;b' AS s; -- uno; dos\nSELECT \"c;d\" FROM t; /* x; y */ SELECT 3"
    assert pieces(text) == ["SELECT 'a;b' AS s;", 'SELECT "c;d" FROM t;', "SELECT 3"]


def test_the_cursor_picks_its_statement_and_between_two_the_previous():
    def at(cursor):
        span = current_span(TEXT, cursor)
        return TEXT[span[0] : span[1]] if span else None

    assert at(0) == "CREATE TABLE t AS SELECT 1 AS x;"
    assert at(TEXT.index("x;") + 2) == "CREATE TABLE t AS SELECT 1 AS x;"  # justo después del `;`
    assert at(TEXT.index("-- borrar")) == "CREATE TABLE t AS SELECT 1 AS x;"  # entre dos: la anterior
    assert at(TEXT.index("DELETE") + 3) == "DELETE FROM t;"
    assert at(TEXT.index("WHERE")) == "SELECT x\nFROM t\nWHERE x > 0;"
    assert at(len(TEXT)) == "SELECT x\nFROM t\nWHERE x > 0;"
    assert current_span("  -- solo un comentario\n", 3) is None
    assert current_span("", 0) is None


def test_typing_a_new_statement_below_without_semicolon_is_the_current_one():
    text = "SELECT 1;\nselect * from clientes"
    span = current_span(text, len(text))
    assert text[span[0] : span[1]] == "select * from clientes"
