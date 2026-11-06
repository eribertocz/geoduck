# SPDX-License-Identifier: GPL-2.0-or-later
"""Lugares de Workspace Pro: tablas, vistas y consultas que el usuario abre, con sus recientes, favoritos y
pestañas abiertas (workspace-pro-spec §3, §8; GD-WSP-007; AT-WSP-008).

Se recuerdan entre reinicios de QGIS guardando **solo nombres** (base, esquema, objeto; ruta del `.sql`),
nunca datos ni SQL. Sin Qt: el almacén es cualquier objeto con `value(clave, defecto)` y
`setValue(clave, valor)` (`QgsSettings` en GeoDuck, un diccionario en las pruebas). Un valor corrupto se
ignora.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from geoduck.domain.catalog import CatalogSnapshot, ObjectKind, catalog_key
from geoduck.domain.i18n import tr

TABLE = "table"
VIEW = "view"
QUERY = "query"
KINDS = (TABLE, VIEW, QUERY)

#: Máximo de recientes (§8).
MAX_RECENTS = 10
PREFIX = "geoduck/pro/"


class Store(Protocol):
    def value(self, key: str, defaultValue: Any = ...) -> Any: ...  # noqa: N803 - firma de QgsSettings

    def setValue(self, key: str, value: Any) -> None: ...  # noqa: N802


@dataclass(frozen=True)
class Place:
    """Una tabla o vista (`database`, `schema`, `name`) o una consulta (`name` y, guardada, `path`)."""

    kind: str
    name: str
    database: str = ""
    schema: str = ""
    path: str = ""

    @property
    def is_query(self) -> bool:
        return self.kind == QUERY

    @property
    def key(self) -> tuple[str, ...]:
        """Identidad: la misma tabla aunque cambie la grafía de la base (regla de DuckDB)."""
        if self.is_query:
            return (QUERY, self.path or self.name)
        return ("object", catalog_key(self.database), self.schema, self.name)

    @property
    def location(self) -> str:
        """Dónde está, para mostrarlo en gris: «db» o «db.ventas»; para una consulta, «SQL»."""
        if self.is_query:
            return "SQL"
        return self.database if self.schema in ("", "main") else f"{self.database}.{self.schema}"

    @property
    def remembered(self) -> bool:
        """Se puede recordar entre reinicios: un objeto, o una consulta guardada en un archivo."""
        return not self.is_query or bool(self.path)

    def to_json(self) -> dict[str, str]:
        if self.is_query:
            return {"kind": QUERY, "name": self.name, "path": self.path}
        return {"kind": self.kind, "database": self.database, "schema": self.schema, "name": self.name}

    @classmethod
    def from_json(cls, data: object) -> Place | None:
        if not isinstance(data, dict):
            return None
        kind = data.get("kind")
        fields = {k: data.get(k, "") for k in ("name", "database", "schema", "path")}
        if kind not in KINDS or not all(isinstance(v, str) for v in fields.values()) or not fields["name"]:
            return None
        if kind == QUERY:
            return cls(QUERY, fields["name"], path=fields["path"]) if fields["path"] else None
        if not fields["database"] or not fields["schema"]:
            return None
        return cls(kind, fields["name"], fields["database"], fields["schema"])


def icon_name(place: Place) -> str:
    """Icono de un lugar (de `icons.PATHS`)."""
    return {TABLE: "table", VIEW: "view"}.get(place.kind, "sql")


def place_of(database: str, schema: str, name: str, kind: ObjectKind) -> Place:
    return Place(VIEW if kind is ObjectKind.VIEW else TABLE, name, database, schema)


def missing_reason(place: Place, catalog: CatalogSnapshot | None) -> str | None:
    """Por qué un lugar recordado no se puede abrir ahora (se muestra atenuado con este motivo), o `None`."""
    if place.is_query:
        if place.path and not Path(place.path).is_file():
            return tr("The file no longer exists")
        return None
    if catalog is None:
        return tr("DuckDB is not started")
    if catalog.get(place.database) is None:
        return tr("The database «{}» is not open").format(place.database)
    key = catalog_key(place.database)
    for obj in catalog.objects:
        if catalog_key(obj.database) == key and obj.schema == place.schema and obj.name == place.name:
            return None
    return tr("It is no longer in the database")


def _read(store: Store, name: str) -> list[Place]:
    text = store.value(PREFIX + name, "")
    if not isinstance(text, str) or not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    places: list[Place] = []
    seen: set[tuple[str, ...]] = set()
    for entry in data:
        place = Place.from_json(entry)
        if place is not None and place.key not in seen:
            seen.add(place.key)
            places.append(place)
    return places


def _write(store: Store, name: str, places: list[Place]) -> None:
    store.setValue(PREFIX + name, json.dumps([p.to_json() for p in places], ensure_ascii=False))


class Places:
    """Recientes (máximo 10, el último primero) y favoritos, leídos al crearse y guardados en cada cambio."""

    def __init__(self, store: Store) -> None:
        self._store = store
        self.recents: list[Place] = _read(store, "recents")[:MAX_RECENTS]
        self.favorites: list[Place] = _read(store, "favorites")

    def touch(self, place: Place) -> None:
        """`place` se acaba de abrir: pasa al principio de los recientes."""
        if not place.remembered:
            return
        self.recents = [place] + [p for p in self.recents if p.key != place.key]
        del self.recents[MAX_RECENTS:]
        _write(self._store, "recents", self.recents)

    def is_favorite(self, place: Place) -> bool:
        return any(p.key == place.key for p in self.favorites)

    def toggle_favorite(self, place: Place) -> bool:
        """Marca o desmarca `place` como favorito; devuelve si quedó marcado."""
        if self.is_favorite(place):
            self.favorites = [p for p in self.favorites if p.key != place.key]
            marked = False
        elif place.remembered:
            self.favorites.append(place)
            marked = True
        else:
            return False
        _write(self._store, "favorites", self.favorites)
        return marked

    def rename_query(self, old: Place, new: Place) -> None:
        """Una consulta se guardó con otro nombre o ruta: recientes y favoritos la siguen."""
        for name in ("recents", "favorites"):
            places = [new if p.key == old.key else p for p in getattr(self, name)]
            setattr(self, name, places)
            _write(self._store, name, places)


def read_tabs(store: Store) -> tuple[list[Place], int]:
    """Pestañas abiertas en la sesión anterior (solo las que se pueden recordar) y la activa."""
    tabs = _read(store, "tabs")
    try:
        current = int(store.value(PREFIX + "tab", 0))
    except (TypeError, ValueError):
        current = 0
    return tabs, current if 0 <= current < len(tabs) else 0


def save_tabs(store: Store, tabs: list[Place], current: int) -> None:
    kept = [p for p in tabs if p.remembered]
    active = tabs[current] if 0 <= current < len(tabs) else None
    _write(store, "tabs", kept)
    index = next((i for i, p in enumerate(kept) if active is not None and p.key == active.key), 0)
    store.setValue(PREFIX + "tab", index)
