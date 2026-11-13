# SPDX-License-Identifier: GPL-2.0-or-later
"""Autocompletado: qué sugerir y qué insertar (G6 · E2, AT-SQL-007; sql-editor-spec §7). Sin DuckDB ni Qt."""

import pytest

from geoduck.domain.catalog import (
    AccessMode,
    AttachedDatabase,
    CatalogObject,
    CatalogSnapshot,
    ColumnInfo,
    ObjectKind,
)
from geoduck.domain.completion import MAX_ITEMS, Kind, Vocabulary, blank_code, complete

ROOT = AttachedDatabase("memory", None, AccessMode.READ_WRITE, "memory")
SALES = AttachedDatabase("mis ventas", "/datos/v.duckdb", AccessMode.READ_ONLY, "duckdb")
T, V = ObjectKind.TABLE, ObjectKind.VIEW
CATALOG = CatalogSnapshot(
    (ROOT, SALES),
    root="memory",
    default="memory",
    schemas=(("memory", "main"), ("memory", "censo"), ("mis ventas", "main"), ("mis ventas", "sur")),
    objects=(
        CatalogObject("memory", "main", "zonas", T),
        CatalogObject("memory", "main", "resumen", V),
        CatalogObject("memory", "censo", "hogares", T),
        CatalogObject("mis ventas", "sur", "Pedidos", T),
        CatalogObject("temp", "main", "tmp", T, temporary=True),
    ),
)
ZONAS = ("memory", "main", "zonas")
COLUMNS = {
    ZONAS: (ColumnInfo("id", "INTEGER", False), ColumnInfo("Nombre", "VARCHAR", True)),
    ("mis ventas", "sur", "Pedidos"): (ColumnInfo("order", "INTEGER", True),),
}
VOCABULARY = Vocabulary(
    frozenset({"select", "from", "order"}), ("from", "select", "where"), ("sum", "st_area")
)


def suggest(before, after="", *, explicit=False, columns=COLUMNS, vocabulary=VOCABULARY, catalog=CATALOG):
    result = complete(
        before,
        catalog=catalog,
        columns=columns,
        vocabulary=vocabulary,
        text_after_cursor=after,
        explicit=explicit,
    )
    return result


def labels(result, kind=None):
    return [s.label for s in result.items if kind is None or s.kind is kind]


def test_after_an_alias_dot_only_the_columns_of_that_object():
    result = suggest("SELECT z.", " FROM zonas z")
    assert result.prefix == "" and [(s.label, s.insert) for s in result.items] == [
        ("id", "id"),
        ("Nombre", '"Nombre"'),
    ]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("SELECT z.", " FROM zonas AS z"),
        ("SELECT * FROM resumen r JOIN zonas z ON z.", ""),
        ("SELECT * FROM resumen r, zonas z WHERE z.", ""),
        ("UPDATE zonas z SET z.", ""),
        ("SELECT zonas.", " FROM zonas"),
        ("SELECT main.zonas.", ""),
        ("SELECT memory.main.zonas.", ""),
    ],
)
def test_columns_by_alias_or_by_name(before, after):
    assert labels(suggest(before, after)) == ["id", "Nombre"]


def test_columns_of_the_tables_in_the_statement_come_first():
    result = suggest("SELECT ", " FROM zonas", explicit=True)
    assert labels(result)[:2] == ["id", "Nombre"]
    assert {"zonas", "resumen", "tmp"} <= set(labels(result, Kind.TABLE) + labels(result, Kind.VIEW))
    assert "hogares" not in labels(result)  # en otro esquema: con «censo.»


def test_only_the_statement_at_the_cursor_counts():
    result = suggest("SELECT * FROM resumen; SELECT ", " FROM zonas; SELECT * FROM tmp", explicit=True)
    assert labels(result, Kind.COLUMN) == ["id", "Nombre"]


def test_schemas_of_a_database_and_objects_of_a_schema():
    assert labels(suggest('SELECT * FROM "mis ventas".')) == ["main", "sur"]
    assert labels(suggest('SELECT * FROM "mis ventas".sur.')) == ["Pedidos"]
    assert labels(suggest("SELECT * FROM censo.")) == ["hogares"]


def test_names_are_quoted_only_when_needed():
    result = suggest("SELECT p.", ' FROM "mis ventas".sur."Pedidos" p')
    assert [(s.label, s.insert) for s in result.items] == [("order", '"order"')]  # palabra clave
    assert [s.insert for s in suggest('SELECT * FROM "mis ventas".sur.').items] == ['"Pedidos"']  # mayúscula
    databases = {s.label: s.insert for s in suggest("SELECT * FROM mi").items}
    assert databases == {"mis ventas": '"mis ventas"'}


def test_prefix_filters_case_insensitively_and_keeps_group_order():
    result = suggest("SELECT * FROM zo")
    assert result.prefix == "zo" and labels(result) == ["zonas"]
    result = suggest("SEL")
    assert [(s.label, s.insert, s.kind) for s in result.items] == [("SELECT", "SELECT", Kind.KEYWORD)]
    assert [s.insert for s in suggest("sel").items] == ["select"]  # como se escribe
    assert labels(suggest("SELECT su")) == ["sum"]


@pytest.mark.parametrize(
    "before",
    [
        "SELECT 'zo",  # cadena
        "-- zo",  # comentario de línea
        "/* zo",  # comentario de bloque
        'SELECT "zo',  # identificador citado a medio escribir
        "SELECT * FROM z",  # un solo carácter, sin pedirlo
        "SELECT ",  # nada escrito, sin pedirlo
    ],
)
def test_nothing_is_suggested_in_comments_strings_or_without_a_prefix(before):
    assert suggest(before) is None


def test_ctrl_space_suggests_even_without_a_prefix():
    assert suggest("SELECT ", explicit=True) is not None
    assert suggest("SELECT 'a", explicit=True) is None  # pero nunca dentro de una cadena


def test_after_a_closed_comment_or_string_it_works_again():
    assert labels(suggest("SELECT 'a;b' /* x */ FROM zo")) == ["zonas"]


def test_unknown_columns_are_reported_as_missing_not_invented():
    result = suggest("SELECT z.", " FROM zonas z", columns={})
    assert result.items == () and result.missing == (ZONAS,)
    result = suggest("SELECT ", " FROM zonas", explicit=True, columns={})
    assert result.missing == (ZONAS,) and "zonas" in labels(result)


def test_without_catalog_or_vocabulary_the_editor_still_works():
    assert suggest("SEL", catalog=None, vocabulary=None).items == ()
    assert labels(suggest("SELECT * FROM zo", vocabulary=None)) == ["zonas"]
    result = suggest("SELECT * FROM mi", vocabulary=None)
    assert [s.insert for s in result.items] == ['"mis ventas"']  # sin palabras clave, se cita


def test_the_list_is_bounded():
    many = Vocabulary(functions=tuple(f"f{i:04d}" for i in range(1000)))
    assert len(suggest("SELECT f0", vocabulary=many).items) == MAX_ITEMS


def test_blanking_keeps_positions_and_quoted_identifiers():
    text = 'SELECT \'a;b\' -- x\n, "q""r" /* c */ FROM t'
    code, inside = blank_code(text)
    assert len(code) == len(text) and not inside
    assert ";" not in code and '"q""r"' in code and "FROM t" in code


def test_the_name_under_the_cursor_is_a_table_a_column_or_a_function():
    from geoduck.domain.completion import target_at

    def at(text, word, nth=0):
        offset = [i for i in range(len(text)) if text.startswith(word, i)][nth] + 1
        return target_at(text, offset, catalog=CATALOG, columns=COLUMNS, vocabulary=VOCABULARY)

    text = 'SELECT z.Nombre, id, ST_Area(g) FROM zonas z JOIN "mis ventas".sur."Pedidos" p ON true'
    table = at(text, "zonas")
    assert (table.kind, table.source, text[table.start : table.end]) == (Kind.TABLE, ZONAS, "zonas")
    column = at(text, "Nombre")
    assert column.kind is Kind.COLUMN and column.source == ZONAS and column.column.data_type == "VARCHAR"
    assert at(text, "id").column.name == "id"
    assert at(text, "ST_Area").kind is Kind.FUNCTION
    assert at(text, "Pedidos").source == ("mis ventas", "sur", "Pedidos")
    assert at("SELECT 'zonas' FROM t", "zonas") is None  # dentro de un texto
    assert at("SELECT nada FROM zonas", "nada") is None
