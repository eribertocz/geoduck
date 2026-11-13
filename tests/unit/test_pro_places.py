# SPDX-License-Identifier: GPL-2.0-or-later
"""Recientes, favoritos y pestañas recordadas de Workspace Pro (G9 · E2; workspace-pro-spec §8)."""

from __future__ import annotations

import json

from geoduck.domain.catalog import AccessMode, AttachedDatabase, CatalogObject, CatalogSnapshot, ObjectKind
from geoduck.domain.i18n import tr
from geoduck.ui.pro.places import (
    MAX_RECENTS,
    PREFIX,
    QUERY,
    TABLE,
    VIEW,
    Place,
    Places,
    missing_reason,
    read_tabs,
    save_tabs,
)


class Store(dict):
    def value(self, key, defaultValue=None):  # noqa: N803
        return self.get(key, defaultValue)

    def setValue(self, key, value):
        self[key] = value


def table(name: str, database: str = "db", schema: str = "main") -> Place:
    return Place(TABLE, name, database, schema)


def catalog(*objects: CatalogObject) -> CatalogSnapshot:
    return CatalogSnapshot(
        databases=(
            AttachedDatabase("memory", None, AccessMode.READ_WRITE, "duckdb"),
            AttachedDatabase("db", "/tmp/db.duckdb", AccessMode.READ_WRITE, "duckdb"),
        ),
        root="memory",
        default="memory",
        schemas=(("memory", "main"), ("db", "main")),
        objects=objects,
    )


def test_recents_keep_the_last_ten_newest_first_without_duplicates():
    places = Places(Store())
    for i in range(12):
        places.touch(table(f"t{i}"))
    places.touch(table("t5"))
    names = [p.name for p in places.recents]
    assert len(names) == MAX_RECENTS
    assert names[:3] == ["t5", "t11", "t10"]
    assert names.count("t5") == 1


def test_recents_and_favorites_survive_a_restart_and_keep_only_names():
    store = Store()
    places = Places(store)
    places.touch(table("consumidores"))
    places.touch(Place(QUERY, "consumo.sql", path="/tmp/consumo.sql"))
    assert places.toggle_favorite(table("consumidores")) is True
    again = Places(store)
    assert [p.name for p in again.recents] == ["consumo.sql", "consumidores"]
    assert again.is_favorite(table("consumidores"))
    for key in ("recents", "favorites"):
        for entry in json.loads(store[PREFIX + key]):
            assert set(entry) <= {"kind", "name", "database", "schema", "path"}  # solo nombres, nunca datos


def test_an_unsaved_query_is_not_remembered():
    places = Places(Store())
    places.touch(Place(QUERY, "Consulta 1"))
    assert places.recents == []
    assert places.toggle_favorite(Place(QUERY, "Consulta 1")) is False


def test_the_same_table_with_another_spelling_of_the_database_is_one_place():
    places = Places(Store())
    places.touch(table("t", database="DB"))
    places.touch(table("t", database="db"))
    assert len(places.recents) == 1


def test_toggling_a_favorite_twice_removes_it():
    places = Places(Store())
    assert places.toggle_favorite(table("t")) is True
    assert places.toggle_favorite(table("t")) is False
    assert places.favorites == []


def test_corrupt_values_are_ignored():
    store = Store()
    store[PREFIX + "recents"] = "{no es json"
    store[PREFIX + "favorites"] = json.dumps([{"kind": "otro", "name": "x"}, {"kind": TABLE}, 3])
    store[PREFIX + "tab"] = "uno"
    places = Places(store)
    assert places.recents == [] and places.favorites == []
    assert read_tabs(store) == ([], 0)


def test_a_missing_object_says_why(tmp_path):
    snapshot = catalog(CatalogObject("db", "main", "consumidores", ObjectKind.TABLE))
    assert missing_reason(table("consumidores"), snapshot) is None
    assert missing_reason(table("borrada"), snapshot) == tr("It is no longer in the database")
    assert missing_reason(table("t", database="ventas"), snapshot) == tr(
        "The database «{}» is not open"
    ).format("ventas")
    assert missing_reason(table("consumidores"), None) == tr("GeoDuck is not started")
    sql = tmp_path / "consulta.sql"
    assert missing_reason(Place(QUERY, "consulta.sql", path=str(sql)), snapshot) == tr(
        "The file no longer exists"
    )
    sql.write_text("select 1")
    assert missing_reason(Place(QUERY, "consulta.sql", path=str(sql)), snapshot) is None


def test_open_tabs_are_remembered_with_the_active_one():
    store = Store()
    tabs = [table("a"), Place(QUERY, "Consulta 1"), Place(VIEW, "v", "db", "main")]
    save_tabs(store, tabs, 2)
    restored, current = read_tabs(store)
    assert [p.name for p in restored] == ["a", "v"]  # la consulta sin guardar no se recuerda
    assert restored[current].name == "v"


def test_location_is_short():
    assert table("t").location == "db"
    assert table("t", schema="ventas").location == "db.ventas"
    assert Place(QUERY, "q", path="/tmp/q.sql").location == "SQL"
