# SPDX-License-Identifier: GPL-2.0-or-later
"""Reglas de «Enviar a DuckDB» sin Qt ni DuckDB (G8 · E1; qgis-import-spec §3, §6, §7)."""

from __future__ import annotations

import pytest

from geoduck.domain.importing import (
    PATH_PARQUET,
    PATH_QGIS,
    ImportColumn,
    ImportedTable,
    ImportGeometry,
    ImportJob,
    ImportMode,
    SendCandidate,
    append_problem,
    column_names,
    duck_type_for,
    estimated_seconds,
    is_large,
    table_name_for,
    unique_name,
)


@pytest.mark.parametrize(
    ("layer", "table"),
    [
        ("Consumidores", "consumidores"),
        ("Zonas de Distribución 2025", "zonas_de_distribucion_2025"),
        ("  --señal--  ", "senal"),
        ("2025 lecturas", "t_2025_lecturas"),
        ("ñ", "n"),
        ("###", "capa"),
    ],
)
def test_table_name_for(layer, table):
    assert table_name_for(layer) == table


def test_unique_name_ignores_case_like_duckdb():
    assert unique_name("zonas", ["Zonas", "zonas_2"]) == "zonas_3"
    assert unique_name("zonas", ["otra"]) == "zonas"


def test_columns_that_differ_only_in_case_are_renamed_with_a_warning():
    names, warnings = column_names(["ID", "nombre", "id", "Id"])
    assert names == ["ID", "nombre", "id_2", "Id_3"]
    assert len(warnings) == 2 and "«id» renombrado a «id_2»" in warnings[0]


@pytest.mark.parametrize(
    ("qt", "sub", "duck", "warns"),
    [
        ("int", None, "INTEGER", False),
        ("qlonglong", None, "BIGINT", False),
        ("double", None, "DOUBLE", False),
        ("bool", None, "BOOLEAN", False),
        ("QString", None, "VARCHAR", False),
        ("QDate", None, "DATE", False),
        ("QTime", None, "TIME", False),
        ("QDateTime", None, "TIMESTAMP", False),
        ("QByteArray", None, "BLOB", False),
        ("QStringList", None, "VARCHAR[]", False),
        ("QVariantList", "int", "BIGINT[]", False),
        ("QVariantList", "double", "DOUBLE[]", False),
        ("QVariantList", "QString", "VARCHAR[]", True),
        ("QVariantMap", None, "JSON", True),
    ],
)
def test_duck_type_for(qt, sub, duck, warns):
    got, warning = duck_type_for(qt, sub)
    assert got == duck and (warning is not None) == warns


def test_timestamp_with_time_zone():
    assert duck_type_for("QDateTime", timezone=True) == ("TIMESTAMPTZ", None)


def test_large_layer_estimate():
    assert estimated_seconds(1_000_000) == 10
    assert not is_large(6_000_000) and is_large(6_000_001)


def test_sql_of_each_mode():
    cols = (ImportColumn("Nombre", "nombre", "VARCHAR"),)
    geom = ImportGeometry("geom", "EPSG:4326")
    create = ImportJob("c", "t", ImportMode.CREATE, cols, geom, database="db", schema="main")
    assert create.first_batch_sql().startswith(
        'CREATE TABLE "db"."main"."t" AS SELECT CAST("nombre" AS VARCHAR)'
    )
    assert 'ST_SetCRS(ST_GeomFromWKB("__geoduck_wkb"), \'EPSG:4326\') AS "geom"' in create.select_sql()
    assert create.next_batch_sql().startswith('INSERT INTO "db"."main"."t" BY NAME SELECT')
    replace = ImportJob("c", "t", ImportMode.REPLACE, cols, None, temporary=True)
    assert replace.first_batch_sql().startswith('CREATE OR REPLACE TEMP TABLE "t" AS')
    assert replace.display == "t (temporal)"
    append = ImportJob("c", "t", ImportMode.APPEND, cols, ImportGeometry("g", None))
    assert append.first_batch_sql() == append.next_batch_sql()
    assert 'ST_GeomFromWKB("__geoduck_wkb") AS "g"' in append.select_sql()
    quoted = ImportJob("c", "t", ImportMode.CREATE, cols, ImportGeometry("g", "it's"))
    assert "'it''s'" in quoted.select_sql()


# -- diálogo (G8 · E3) --------------------------------------------------------------------------------

APPEND_COLUMNS = (ImportColumn("id", "c0", "INTEGER"), ImportColumn("nombre", "c1", "VARCHAR"))


def test_append_accepts_same_or_wider_types_and_missing_table_columns():
    target = (("ID", "BIGINT"), ("nombre", "VARCHAR"), ("extra", "DATE"), ("geom", "GEOMETRY('EPSG:4326')"))
    assert append_problem(APPEND_COLUMNS, ImportGeometry("geom", "EPSG:4326"), target) is None


def test_append_explains_the_failing_column():
    assert "«nombre»" in append_problem(APPEND_COLUMNS, None, (("id", "INTEGER"),))
    problem = append_problem(APPEND_COLUMNS, None, (("id", "SMALLINT"), ("nombre", "VARCHAR")))
    assert "«id»" in problem and "SMALLINT" in problem


def test_append_requires_the_same_crs():
    target = (("id", "INTEGER"), ("nombre", "VARCHAR"), ("geom", "GEOMETRY('EPSG:32719')"))
    assert "EPSG:32719" in append_problem(APPEND_COLUMNS, ImportGeometry("geom", "EPSG:4326"), target)
    assert (
        append_problem(APPEND_COLUMNS, ImportGeometry("geom", None), (*target[:2], ("geom", "GEOMETRY")))
        is None
    )


def candidate(path=PATH_QGIS, *, features=10, selected=0, filtered=False):
    return SendCandidate(
        "L",
        "capa",
        "GeoPackage",
        features,
        selected,
        "Point",
        "EPSG:4326",
        filtered,
        path,
        (),
        None,
        (),
        "capa",
    )


def test_candidate_view_rows_and_path():
    assert candidate(PATH_PARQUET).can_view
    assert not candidate(PATH_PARQUET, filtered=True).can_view
    parquet = candidate(PATH_PARQUET, selected=2)
    assert parquet.path_for(only_selected=True) == PATH_QGIS
    assert parquet.path_for(only_selected=False) == PATH_PARQUET
    assert parquet.rows_for(True) == 2 and parquet.rows_for(False) == 10
    assert candidate(selected=0).rows_for(True) == 10  # sin selección, toda la capa
    with_geometry = SendCandidate(
        "L",
        "capa",
        "Parquet",
        10,
        0,
        "Point",
        "EPSG:4326",
        False,
        PATH_PARQUET,
        (),
        ImportGeometry("geom", "EPSG:4326"),
        (),
        "capa",
    )
    assert with_geometry.path_for(False, reproject=True) == PATH_QGIS  # DuckDB no reproyecta sin `spatial`
    assert with_geometry.path_for(False) == PATH_PARQUET


def test_only_new_tables_can_be_undone():
    def table(mode):
        return ImportedTable("t", "t", mode, 1)

    assert table(ImportMode.CREATE).can_undo
    assert not table(ImportMode.REPLACE).can_undo
    assert not table(ImportMode.APPEND).can_undo
