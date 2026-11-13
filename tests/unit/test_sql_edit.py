# SPDX-License-Identifier: GPL-2.0-or-later
"""Lo que hace el editor al escribir, sin Qt (#146, puntos 17 y 30; `geoduck.domain.sql_edit`)."""

from __future__ import annotations

import re

import pytest

from geoduck.domain.sql_edit import (
    backspace_pair,
    clean_for_save,
    dedent_after,
    enter_text,
    expand_snippet,
    format_sql,
    in_code,
    pair_action,
    reindent,
    toggle_comment,
    uppercase_word,
)


def test_code_ends_where_a_string_or_a_comment_starts():
    assert in_code("SELECT a, ")
    assert not in_code("SELECT 'abc")
    assert in_code("SELECT 'it''s' ")
    assert not in_code('SELECT "Mi ')
    assert not in_code("SELECT 1 -- nota ")


@pytest.mark.parametrize(
    ("char", "before", "after", "action"),
    [
        ("(", "SELECT count", "", "pair"),
        ("(", "SELECT count", ")", "pair"),
        ("(", "SELECT ", "zona", ""),  # delante de una palabra no se cierra
        (")", "SELECT count(", ")", "skip"),
        ("'", "WHERE zona = ", "", "pair"),
        ("'", "WHERE zona = 'Sur", "'", "skip"),
        ("'", "it", "", ""),
        ("(", "SELECT 'abc", "", ""),  # dentro de un texto
        ("(", "-- nota ", "", ""),  # dentro de un comentario
        ("]", "SELECT [1, 2", "", ""),
        ("x", "SELECT ", "", ""),
    ],
)
def test_pairs_close_and_skip_only_in_code(char, before, after, action):
    assert pair_action(char, before, after) == action


def test_backspace_removes_an_empty_pair():
    assert backspace_pair("SELECT count(", ")")
    assert backspace_pair("WHERE a = '", "'")
    assert not backspace_pair("SELECT count(", "*)")
    assert not backspace_pair("", ")")


def test_enter_keeps_and_grows_the_indentation():
    assert enter_text("    SELECT a,", "") == ("\n    ", 5)
    assert enter_text("SELECT count(", "") == ("\n    ", 5)
    assert enter_text("SELECT CASE", "") == ("\n    ", 5)
    assert enter_text("WITH t AS (", ")") == ("\n    \n", 5)  # el cierre baja
    assert enter_text("  x = 'abc(", "") == ("\n  ", 3)  # dentro de un texto, solo se mantiene


def test_a_closing_paren_or_end_moves_back_one_level():
    assert dedent_after("        )") == "    )"
    assert dedent_after("    end") == "end"
    assert dedent_after(")") is None
    assert dedent_after("    zona") is None


def test_pasted_lines_take_the_indentation_of_the_place():
    pasted = "SELECT a,\n        b\n    FROM t"
    assert reindent(pasted, "    ") == "SELECT a,\n        b\n    FROM t"
    assert reindent("x", "    ") == "x"
    assert reindent("SELECT 1\n\n  FROM t", "  ") == "SELECT 1\n\n  FROM t"


def test_comment_toggles_on_all_lines_at_the_smallest_indentation():
    lines = ["SELECT a,", "    b", "", "FROM t"]
    commented = toggle_comment(lines)
    assert commented == ["-- SELECT a,", "--     b", "", "-- FROM t"]
    assert toggle_comment(commented) == lines
    assert toggle_comment(["    a", "        b"]) == ["    -- a", "    --     b"]
    assert toggle_comment(["", ""]) == ["", ""]


def test_saving_removes_trailing_spaces_and_ends_with_one_newline():
    assert clean_for_save("SELECT 1   \nFROM t\t\n\n\n") == "SELECT 1\nFROM t\n"
    assert clean_for_save("SELECT 1") == "SELECT 1\n"
    assert clean_for_save("") == ""


def test_keywords_go_up_only_when_they_are_keywords():
    keywords = frozenset({"select", "from"})
    assert uppercase_word("select", keywords) == "SELECT"
    assert uppercase_word("SELECT", keywords) is None
    assert uppercase_word("zona", keywords) is None


def test_snippets_expand_with_the_cursor_and_the_indentation():
    found = expand_snippet("sel", "    ")
    assert found is not None
    assert found.text == "SELECT *\n    FROM ;" and found.text[found.cursor :] == ";"
    assert expand_snippet("zona", "") is None


FORMATS = [
    (
        "select zona, sum(kwh) as total from lecturas l left join zonas z on l.id = z.id and z.x > 1 "
        "where kwh between 1 and 9 and zona = 'Sur' group by zona order by total desc limit 10;",
        "SELECT zona,\n    sum(kwh) AS total\nFROM lecturas l\nLEFT JOIN zonas z ON l.id = z.id\n"
        "    AND z.x > 1\n"
        "WHERE kwh BETWEEN 1 AND 9\n    AND zona = 'Sur'\nGROUP BY zona\nORDER BY total DESC\nLIMIT 10;\n",
    ),
    (
        "with t as (select a from x where a in (1,2)) select * from t",
        "WITH t AS (\n    SELECT a\n    FROM x\n    WHERE a IN (1, 2)\n)\nSELECT *\nFROM t\n",
    ),
    ("select cast(a as DOUBLE)::int from t", "SELECT CAST(a AS DOUBLE)::int\nFROM t\n"),  # tipos, tal cual
    ("insert into t values (1, 'a');", "INSERT INTO t\nVALUES (1, 'a');\n"),
]


@pytest.mark.parametrize(("text", "formatted"), FORMATS)
def test_format_puts_each_clause_on_its_line(text, formatted):
    assert format_sql(text) == formatted
    assert format_sql(formatted) == formatted  # dos veces da lo mismo


@pytest.mark.parametrize(
    "text",
    [
        "select 'from where  AND' as \"select  x\" from t -- from where\nwhere a = 1",
        "SELECT a /* from\n where */ FROM t; select 'x;y'",
        "select e'a\\nb', [1,2], {'k': 1}, a->>'$.x' from t",
    ],
)
def test_format_never_changes_strings_names_or_comments(text):
    def words(sql):
        found = re.findall(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/|\S", sql, re.DOTALL)
        return [w if w[0] in "'\"-/" else w.upper() for w in found]

    assert words(format_sql(text)) == words(text)


def test_parameter_help_reads_duckdb_functions_rows():
    from geoduck.domain.sql_edit import call_before, signature_lines, signature_sql

    assert "duckdb_functions()" in signature_sql("ST_Area") and "'ST_Area'" in signature_sql("ST_Area")
    rows = [
        ("round", ["x", "precision"], ["DOUBLE", "INTEGER"], None, "DOUBLE", "Rounds x"),
        ("round", ["x", "precision"], ["DOUBLE", "INTEGER"], None, "DOUBLE", None),
        ("round", ["x"], ["DOUBLE"], None, "DOUBLE", None),
        ("concat", ["value"], ["ANY"], "ANY", "VARCHAR", None),
    ]
    assert signature_lines(rows) == [
        "round(x DOUBLE, precision INTEGER) → DOUBLE",
        "round(x DOUBLE) → DOUBLE",
        "concat(value, ANY…) → VARCHAR",
        "Rounds x",
    ]
    assert call_before("SELECT round(kwh, ") == ("round", 1)
    assert call_before("SELECT round(sum(a), 'x,y', ") == ("round", 2)
    assert call_before("SELECT a") is None
