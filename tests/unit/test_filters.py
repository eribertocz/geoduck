# SPDX-License-Identifier: GPL-2.0-or-later
"""Filtros del resultado sin Qt ni DuckDB (#144, punto 36; `geoduck.domain.filters`)."""

from __future__ import annotations

import pytest

from geoduck.domain.browse import Browse
from geoduck.domain.catalog import ColumnInfo
from geoduck.domain.filters import (
    EXCLUDE,
    FILTER,
    GREATER,
    LESS,
    NO_EMPTY,
    ONLY_EMPTY,
    FilterError,
    box_condition,
    cell_filters,
    check_sql,
    comparable,
    preview,
    where_condition,
)
from geoduck.domain.i18n import tr

ZONA = ColumnInfo("zona", "VARCHAR", None)
TIPO = ColumnInfo("tipo", "VARCHAR", None)
KWH = ColumnInfo("kwh", "DOUBLE", None)
FECHA = ColumnInfo("fecha", "DATE", None)


@pytest.mark.parametrize(
    ("column", "text", "sql", "label"),
    [
        (ZONA, "norte", """contains(lower(CAST("zona" AS VARCHAR)), lower('norte'))""", None),
        (ZONA, "=Sur", """("zona" = 'Sur')""", "zona = Sur"),
        (KWH, ">50", '("kwh" > 50)', "kwh > 50"),
        (KWH, "> 50 AND < 100", '("kwh" > 50 AND "kwh" < 100)', "kwh > 50 AND kwh < 100"),
        (KWH, "10..50", '"kwh" BETWEEN 10 AND 50', "kwh 10..50"),
        (FECHA, "2024-01-01..2024-12-31", """"fecha" BETWEEN '2024-01-01' AND '2024-12-31'""", None),
        (FECHA, ">2024-01-01", """("fecha" > '2024-01-01')""", None),
        (ZONA, "/^cli/i", """regexp_matches(CAST("zona" AS VARCHAR), '^cli', 'i')""", "zona ~ /^cli/i"),
        (ZONA, "/o'k/", """regexp_matches(CAST("zona" AS VARCHAR), 'o''k')""", None),
        (KWH, "IN (1, 5)", '("kwh" IN (1, 5))', None),
        (ZONA, "like 'a%'", """("zona" LIKE 'a%')""", None),
        (KWH, "BETWEEN 1 AND 9 OR > 100", '("kwh" BETWEEN 1 AND 9 OR "kwh" > 100)', None),
        (KWH, "IS NULL", '("kwh" IS NULL)', None),
        (ZONA, "NOT IN ('a', 'b')", """("zona" NOT IN ('a', 'b'))""", None),
        (ZONA, "IS DISTINCT FROM 'Sur'", """("zona" IS DISTINCT FROM 'Sur')""", None),
        (ZONA, "isla", """contains(lower(CAST("zona" AS VARCHAR)), lower('isla'))""", None),
    ],
)
def test_the_filter_box_understands_text_comparisons_regex_and_sql(column, text, sql, label):
    condition = box_condition(column, text)
    assert condition is not None and condition.sql == sql and condition.column == column.name
    if label is not None:
        assert condition.label == label


def test_empty_and_not_empty_in_both_languages():
    for word in ("vacío", "empty", tr("empty")):
        assert box_condition(ZONA, word).sql == """("zona" IS NULL OR CAST("zona" AS VARCHAR) = '')"""
        assert box_condition(KWH, word).sql == '"kwh" IS NULL'
    for word in ("no vacío", "not empty", tr("not empty")):
        assert box_condition(KWH, word).sql == '"kwh" IS NOT NULL'


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("> 1; DROP TABLE t", "Only one condition: without «;»"),
        ("> 1 -- y", "Comments are not allowed in a filter"),
        ("> 1 /* y */", "Comments are not allowed in a filter"),
        ("IN (1, 2", "A «(» is not closed"),
        ("> 1) OR (1 = 1", "A «)» has no «(»"),
        ("= 'Sur", "A quote is not closed"),
        ("> 50 AND 100", "Each part joined with AND or OR must start with an operator (=, >, IN, LIKE…)"),
        (">", "A value is missing after «{}»"),
        ("//", "The regular expression is empty"),
    ],
)
def test_one_condition_only_with_a_clear_reason(text, reason):
    with pytest.raises(FilterError) as error:
        box_condition(KWH, text)
    assert error.value.message.startswith(tr(reason).split("{")[0])


def test_the_where_bar_is_one_free_condition():
    assert box_condition(KWH, "") is None and where_condition("  ") is None
    condition = where_condition("zona = 'Sur' AND (kwh > 80 OR kwh IS NULL)")
    assert condition.sql == "(zona = 'Sur' AND (kwh > 80 OR kwh IS NULL))"
    assert condition.label.startswith("SQL: ") and condition.column == ""
    assert where_condition("x" * 80).label.endswith("…")
    with pytest.raises(FilterError):
        where_condition("1 = 1; SELECT 2")
    assert check_sql(" a = 'b;c' ") == "a = 'b;c'"  # el ; dentro de un texto no cuenta


def test_right_click_filters_one_or_several_columns():
    boxes, extra = cell_filters([(ZONA, "Sur")], FILTER)
    assert boxes == {"zona": "= 'Sur'"} and extra is None
    boxes, _ = cell_filters([(ZONA, "Sur"), (ZONA, "Norte"), (ZONA, "Sur"), (KWH, 1.5)], FILTER)
    assert boxes == {"zona": "IN ('Sur', 'Norte')", "kwh": "= 1.5"}  # misma columna «o», distintas «y»
    boxes, _ = cell_filters([(ZONA, "Sur"), (ZONA, None)], FILTER)
    assert boxes == {"zona": "= 'Sur' OR IS NULL"}
    assert box_condition(ZONA, boxes["zona"]).sql == """("zona" = 'Sur' OR "zona" IS NULL)"""


def test_excluding_keeps_empty_rows_and_several_columns_go_together():
    boxes, extra = cell_filters([(ZONA, "Sur")], EXCLUDE)
    assert boxes == {"zona": "IS DISTINCT FROM 'Sur'"} and extra is None
    boxes, _ = cell_filters([(ZONA, "Sur"), (ZONA, "Este")], EXCLUDE)
    assert box_condition(ZONA, boxes["zona"]).sql == """("zona" IS NULL OR "zona" NOT IN ('Sur', 'Este'))"""
    boxes, extra = cell_filters([(ZONA, "Sur"), (TIPO, "Comercial")], EXCLUDE)
    assert boxes == {}
    assert extra.sql == """NOT coalesce(("zona" = 'Sur') AND ("tipo" = 'Comercial'), false)"""
    assert extra.label == tr("not ({})").format(tr(" and ").join(["zona = 'Sur'", "tipo = 'Comercial'"]))


def test_greater_less_and_empties():
    assert cell_filters([(KWH, 3.0), (KWH, 7.5)], GREATER)[0] == {"kwh": "> 7.5"}
    assert cell_filters([(KWH, 3), (KWH, 7)], LESS)[0] == {"kwh": "< 3"}
    with pytest.raises(FilterError):
        cell_filters([(KWH, 3), (FECHA, "2024-01-01")], GREATER)
    assert cell_filters([(ZONA, "a"), (KWH, 1)], ONLY_EMPTY)[0] == {"zona": tr("empty"), "kwh": tr("empty")}
    assert cell_filters([(ZONA, "a")], NO_EMPTY)[0] == {"zona": tr("not empty")}
    assert comparable(KWH) and comparable(FECHA) and not comparable(ZONA)


def test_the_menu_shows_the_exact_condition_before_applying_it():
    text = preview([(ZONA, "Sur"), (TIPO, "Comercial")], FILTER)
    assert text == tr(" and ").join(["zona = 'Sur'", "tipo = 'Comercial'"])
    assert preview([(ZONA, "Sur"), (TIPO, "x")], EXCLUDE).startswith(tr("not ({})").split("(")[0])


def test_browse_combines_boxes_extra_where_and_paging():
    columns = (ZONA, KWH)
    browse = Browse("memory", "main", "t", columns).with_box("kwh", ">50").with_box("zona", "=Sur")
    assert browse.boxes == (("zona", "=Sur"), ("kwh", ">50"))  # en el orden de las columnas
    browse = browse.with_where("kwh < 90").with_extra(cell_filters([(ZONA, "a"), (KWH, 1)], EXCLUDE)[1])
    assert browse.filtered and browse.box("zona") == "=Sur"
    sql = browse.page_sql(0)
    assert """WHERE ("zona" = 'Sur') AND ("kwh" > 50) AND NOT coalesce(""" in sql and "AND (kwh < 90)" in sql
    assert browse.with_box("zona", "").boxes == (("kwh", ">50"),)
    assert not browse.cleared().filtered and browse.without_extra(0).extra == ()
    assert browse.total_sql() == 'SELECT count(*) FROM "memory"."main"."t"'
    assert browse.check_sql("x > 1").endswith("WHERE x > 1 LIMIT 0")


def test_a_query_result_is_browsed_as_a_subquery():
    browse = Browse("", "", "", (ZONA, KWH), subquery="SELECT * FROM t\n", has_rowid=False)
    browse = browse.next_order("kwh").with_box("zona", "norte")
    assert browse.page_sql(100) == (
        """SELECT * FROM (SELECT * FROM t\n) AS geoduck_q WHERE contains(lower(CAST("zona" AS VARCHAR)), """
        """lower('norte')) ORDER BY "kwh" ASC NULLS LAST, "zona" LIMIT 100 OFFSET 100"""
    )


def test_summary_and_copy_read_every_filtered_row():
    browse = Browse("memory", "main", "t", (ZONA, KWH)).with_box("zona", "=Sur")
    assert browse.summary_sql(KWH).startswith('SELECT sum("kwh"), avg("kwh"), min("kwh"), max("kwh")')
    assert 'CAST(min("zona") AS VARCHAR)' in browse.summary_sql(ZONA)
    assert browse.values_sql(("kwh",), 10).startswith('SELECT CAST("kwh" AS VARCHAR) FROM')
    assert browse.values_sql(("kwh",), 10).endswith("LIMIT 10")
