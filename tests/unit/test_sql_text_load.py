# SPDX-License-Identifier: GPL-2.0-or-later
"""`load_sql`: la sentencia del editor, lista para envolverla en una subconsulta al cargar (G5 E4b)."""

import pytest

from geoduck.domain.sql_text import load_sql


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("SELECT 1", "SELECT 1\n"),
        ("SELECT 1;", "SELECT 1\n"),
        ("SELECT 1;;  \n", "SELECT 1\n"),
        ("SELECT 1\nFROM t\nWHERE x = '0201';\n-- Total por zona\n", "SELECT 1\nFROM t\nWHERE x = '0201'\n"),
        ("SELECT 1 -- nota final", "SELECT 1 -- nota final\n"),  # el salto de línea protege el `)`
        ("SELECT ';' AS s;", "SELECT ';' AS s\n"),  # un `;` dentro de un literal no se toca
        ("-- solo un comentario\nSELECT 2;\n-- y otro\n\n", "-- solo un comentario\nSELECT 2\n"),
    ],
)
def test_load_sql_strips_only_the_end(text, expected):
    assert load_sql(text) == expected
