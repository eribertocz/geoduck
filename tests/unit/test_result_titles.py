# SPDX-License-Identifier: GPL-2.0-or-later
"""Títulos descriptivos de las pestañas de resultado (mejora de la interfaz SQL)."""

import pytest

from geoduck.domain.sql import SqlStatement, automatic_title, result_title


def stmt(text, kind="SELECT", start=0):
    return SqlStatement(0, kind, text, start, start + len(text))


@pytest.mark.parametrize(
    ("sql", "kind", "title"),
    [
        ("SELECT * FROM productos;", "SELECT", "Productos"),
        ("SELECT COUNT(*) AS n FROM productos;", "SELECT", "Total productos"),
        ("SELECT count(*) FROM main.ventas_2026", "SELECT", "Total ventas 2026"),
        ("SELECT id, nombre FROM comercial.main.clientes WHERE id > 3", "SELECT", "Clientes"),
        ('SELECT * FROM "Ventas Año"', "SELECT", "Ventas Año"),
        ("WITH x AS (SELECT 1) SELECT * FROM x", "SELECT", "X"),
        ("SELECT 42 AS respuesta;", "SELECT", "Respuesta"),
        ("SELECT 1, 2", "SELECT", "Resultado"),
        ("SELECT 'FROM falsa' AS texto", "SELECT", "Texto"),
        ("INSERT INTO t SELECT 1 RETURNING *", "INSERT", "Insertados en t"),
        (
            "WITH n AS (SELECT 2) INSERT INTO pedidos SELECT * FROM n RETURNING id",
            "INSERT",
            "Insertados en pedidos",
        ),
        ("UPDATE ventas SET a = 1 RETURNING a", "UPDATE", "Actualizados en ventas"),
        ("DELETE FROM ventas WHERE a = 1 RETURNING a", "DELETE", "Eliminados de ventas"),
        ("EXPLAIN SELECT * FROM productos", "EXPLAIN", "Plan productos"),
        ("PRAGMA version", "PRAGMA", "PRAGMA VERSION"),
        ("CREATE TABLE productos AS SELECT 1", "CREATE", "Crear productos"),
        ("CREATE TABLE p AS SELECT range FROM range(500)", "CREATE", "Crear p"),
        ("CREATE OR REPLACE TEMP VIEW IF NOT EXISTS main.v_ventas AS SELECT 1", "CREATE", "Crear v ventas"),
        ("DROP TABLE IF EXISTS productos", "DROP", "Eliminar productos"),
        ("ATTACH 'c:/x/comercial.duckdb' AS comercial (READ_ONLY)", "ATTACH", "Adjuntar comercial"),
        ("DETACH comercial", "DETACH", "Desadjuntar comercial"),
        ("BEGIN TRANSACTION", "TRANSACTION", "BEGIN TRANSACTION"),
        ("COMMIT", "TRANSACTION", "COMMIT"),
        ("SET threads = 2", "SET", "SET THREADS"),
        ("CHECKPOINT", "CHECKPOINT", "Checkpoint"),
        (
            "SELECT * FROM una_tabla_con_un_nombre_muy_largo_de_verdad",
            "SELECT",
            "Una tabla con un nombre muy…",
        ),
    ],
)
def test_automatic_titles(sql, kind, title):
    assert automatic_title(stmt(sql, kind)) == title


def test_explicit_title_from_the_comment_above():
    editor = "SELECT 1;\n-- Total por región\nSELECT region, count(*) FROM ventas GROUP BY 1;"
    start = editor.index("SELECT region")
    assert result_title(editor, stmt(editor[start:], start=start)) == "Total por región"


def test_explicit_title_when_the_statement_text_includes_the_comment():
    """DuckDB 1.5.x incluye el comentario previo en el texto de la sentencia (F-35)."""
    editor = "-- Clientes activos\nSELECT * FROM clientes;"
    assert result_title(editor, stmt(editor)) == "Clientes activos"


def test_a_comment_separated_by_a_blank_line_is_not_a_title():
    editor = "-- notas generales\n\nSELECT * FROM clientes;"
    start = editor.index("SELECT")
    assert result_title(editor, stmt(editor[start:], start=start)) == "Clientes"


def test_comment_above_a_line_with_two_statements_names_only_the_first():
    editor = "-- Uno\nSELECT * FROM a; SELECT * FROM b;"
    first_end = editor.index("SELECT * FROM b")
    assert result_title(editor, stmt(editor[: first_end - 1])) == "Uno"
    assert result_title(editor, stmt(editor[first_end:], start=first_end)) == "B"
