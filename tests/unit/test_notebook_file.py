# SPDX-License-Identifier: GPL-2.0-or-later
"""Cuaderno como archivo `.sql` (G7, ADR-0014): formato, sin Qt ni disco."""

from __future__ import annotations

from geoduck.domain.notebook import Cell, Notebook
from geoduck.domain.notebook_file import dumps, loads

EXAMPLE = """-- %% cell · database: db
SELECT consumidor, medidor FROM main.consumidores20261030 LIMIT 3;

-- %% cell · database: memory
SELECT * FROM db.main.tabla2;
"""


def cells(notebook):
    return [(c.sql, c.database) for c in notebook.cells]


def test_each_cell_is_a_marker_comment_and_its_sql():
    notebook = Notebook(
        "Consumidores",
        [
            Cell("SELECT consumidor, medidor FROM main.consumidores20261030 LIMIT 3;", "db"),
            Cell("SELECT * FROM db.main.tabla2;", "memory"),
        ],
    )
    assert dumps(notebook) == EXAMPLE


def test_reading_gives_back_the_cells_and_their_bases():
    notebook = loads(EXAMPLE, "Consumidores")
    assert notebook.name == "Consumidores"
    assert cells(notebook) == [
        ("SELECT consumidor, medidor FROM main.consumidores20261030 LIMIT 3;", "db"),
        ("SELECT * FROM db.main.tabla2;", "memory"),
    ]


def test_round_trip_keeps_multiline_sql_empty_cells_bases_with_spaces_and_no_base():
    original = Notebook(
        "n",
        [
            Cell("-- comentario\nSELECT 1;\n\nSELECT 2;", "mis ventas"),
            Cell("", "db"),
            Cell("SELECT 3", None),
        ],
    )
    assert cells(loads(dumps(original), "n")) == cells(original)


def test_a_plain_sql_file_is_one_cell_and_spanish_markers_and_windows_lines_are_read():
    assert cells(loads("SELECT 1;\r\nSELECT 2;\r\n", "x")) == [("SELECT 1;\nSELECT 2;", None)]
    text = "SELECT 'antes';\n-- %% celda · base: db\nSELECT 2;\n-- %%CELL\nSELECT 3;"
    assert cells(loads(text, "x")) == [("SELECT 'antes';", None), ("SELECT 2;", "db"), ("SELECT 3;", None)]


def test_an_empty_file_is_one_empty_cell():
    assert cells(loads("", "vacío")) == [("", None)]
