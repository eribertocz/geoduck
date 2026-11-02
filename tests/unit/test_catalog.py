# SPDX-License-Identifier: GPL-2.0-or-later
"""Modelo de catálogo (G1 paso 2, GD-CAT-001): invariantes de la instantánea, sin DuckDB."""

import pytest

from geoduck.domain.catalog import AccessMode, AttachedDatabase, CatalogSnapshot, catalog_key

RW, RO = AccessMode.READ_WRITE, AccessMode.READ_ONLY


def db(name, path=None, access=RW):
    return AttachedDatabase(name, path, access, "duckdb")


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("Ventas", "ventas", True),
        ("Año", "año", True),  # A se pliega; ñ no cambia
        ("Año", "AÑO", False),  # Ñ no se pliega en DuckDB
        ("Straße", "STRASSE", False),
        ("memory", "memory", True),
    ],
)
def test_catalog_key_follows_duckdb_ascii_folding(a, b, same):
    assert (catalog_key(a) == catalog_key(b)) is same


def test_snapshot_with_root_and_attached():
    snap = CatalogSnapshot((db("memory"), db("Ventas", "/d/v.duckdb", RO)), root="memory", default="memory")
    assert snap.root_database.in_memory and snap.root_database.access is RW
    assert [d.name for d in snap.attached] == ["Ventas"]
    assert snap.get("VENTAS").access is RO and snap.get("ventas").path == "/d/v.duckdb"
    assert snap.get("otra") is None
    assert snap.is_root("MEMORY") and not snap.is_root("Ventas")


def test_default_and_root_take_the_listed_spelling():
    """Tras `USE ventas`, DuckDB informa la grafía escrita, no la de la base."""
    snap = CatalogSnapshot((db("memory"), db("Ventas", "/d/v.duckdb")), root="MEMORY", default="ventas")
    assert snap.default == "Ventas" and snap.root == "memory"
    assert snap.default_database.path == "/d/v.duckdb"


def test_repeated_names_are_rejected():
    with pytest.raises(ValueError, match="repetido"):
        CatalogSnapshot((db("memory"), db("Ventas"), db("VENTAS")), root="memory", default="memory")


def test_non_ascii_variants_are_distinct_databases():
    snap = CatalogSnapshot((db("memory"), db("Año"), db("AÑO")), root="memory", default="AÑO")
    assert snap.default == "AÑO" and len(snap.attached) == 2


@pytest.mark.parametrize(("root", "default"), [("raiz", "memory"), ("memory", "fantasma")])
def test_root_and_default_must_be_listed(root, default):
    with pytest.raises(ValueError, match="no figura"):
        CatalogSnapshot((db("memory"),), root=root, default=default)


def test_snapshot_is_immutable():
    snap = CatalogSnapshot((db("memory"),), root="memory", default="memory")
    with pytest.raises(AttributeError):
        snap.default = "otra"


# -- esquemas, tablas y vistas (G1 paso 8, GD-CAT-001) --------------------------------------------

from geoduck.domain.catalog import CatalogObject, ObjectKind  # noqa: E402

T, V = ObjectKind.TABLE, ObjectKind.VIEW


def test_objects_are_grouped_by_database_and_schema():
    snap = CatalogSnapshot(
        (db("memory"), db("Ventas", "/d/v.duckdb", RO)),
        root="memory",
        default="memory",
        schemas=(("memory", "main"), ("Ventas", "main"), ("Ventas", "ventas")),
        objects=(
            CatalogObject("Ventas", "ventas", "t", T),
            CatalogObject("Ventas", "ventas", "v", V),
            CatalogObject("memory", "main", "r", T),
            CatalogObject("temp", "main", "tmp", T, temporary=True),
        ),
    )
    assert snap.schemas_of("VENTAS") == ("main", "ventas")
    assert [o.name for o in snap.objects_in("ventas", "ventas")] == ["t", "v"]
    assert snap.objects_in("Ventas", "main") == ()
    assert [o.name for o in snap.temporaries] == ["tmp"]


@pytest.mark.parametrize(
    ("schemas", "objects"),
    [
        ((("otra", "main"),), ()),  # esquema de una base no listada
        ((("memory", "main"),), (CatalogObject("memory", "nada", "x", T),)),  # esquema no listado
        (
            (("memory", "main"),),
            (CatalogObject("memory", "main", "x", T, temporary=True),),
        ),  # temp fuera de temp
    ],
)
def test_incoherent_objects_are_rejected(schemas, objects):
    with pytest.raises(ValueError):
        CatalogSnapshot((db("memory"),), root="memory", default="memory", schemas=schemas, objects=objects)
