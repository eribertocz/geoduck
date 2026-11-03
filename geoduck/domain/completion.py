# SPDX-License-Identifier: GPL-2.0-or-later
"""Autocompletado del editor SQL (G6 · E2, GD-SQL-007, sql-editor-spec §7 «P1 en G6», AT-SQL-007).

Lógica pura: a partir del texto hasta el cursor, la instantánea del catálogo, las columnas ya leídas y el
vocabulario de DuckDB, decide qué sugerir y qué texto insertar. Nunca ejecuta SQL ni consulta DuckDB: si
faltan las columnas de un objeto, lo dice (`Completion.missing`) y quien llama las pide al worker.

El análisis del texto solo sirve para sugerir (comentarios, cadenas, alias y la sentencia del cursor); la
ejecución sigue usando el parser de DuckDB (sql-editor-spec §2).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from geoduck.domain.catalog import TEMP_CATALOG, CatalogSnapshot, ColumnInfo, catalog_key
from geoduck.domain.sql_text import sql_name

#: Máximo de sugerencias en la lista.
MAX_ITEMS = 200
#: Caracteres escritos a partir de los cuales la lista se abre sola (sin Ctrl+Espacio).
AUTO_PREFIX = 2

Source = tuple[str, str, str]


class Kind(str, Enum):
    COLUMN = "column"
    TABLE = "table"
    VIEW = "view"
    SCHEMA = "schema"
    DATABASE = "database"
    FUNCTION = "function"
    KEYWORD = "keyword"


#: Orden de los grupos en la lista: primero lo más probable en ese punto.
_ORDER = (Kind.COLUMN, Kind.TABLE, Kind.VIEW, Kind.SCHEMA, Kind.DATABASE, Kind.FUNCTION, Kind.KEYWORD)


@dataclass(frozen=True)
class Vocabulary:
    """Palabras de DuckDB de la sesión: `duckdb_keywords()` y `duckdb_functions()`."""

    #: Palabras clave que obligan a citar un identificador (todas menos `unreserved`).
    reserved: frozenset[str] = frozenset()
    #: Todas las palabras clave.
    keywords: tuple[str, ...] = ()
    #: Nombres de funciones (sin `pragma`), sin repetir.
    functions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Suggestion:
    #: Lo que se ve en la lista.
    label: str
    #: Lo que se escribe en lugar del prefijo.
    insert: str
    kind: Kind


@dataclass(frozen=True)
class Completion:
    #: Texto escrito que la sugerencia sustituye (puede estar vacío, p. ej. tras un `.`).
    prefix: str
    items: tuple[Suggestion, ...] = ()
    #: Objetos cuyas columnas harían falta y aún no se conocen.
    missing: tuple[Source, ...] = field(default_factory=tuple)


# -- análisis del texto hasta el cursor --------------------------------------------------------------

_IDENT = r'(?:[A-Za-z_][A-Za-z0-9_$]*|"(?:[^"]|"")+")'
_CHAIN_AT_END = re.compile(rf"((?:{_IDENT}\s*\.\s*)*)([A-Za-z_][A-Za-z0-9_$]*)?$")
_PART = re.compile(_IDENT)
_QUALIFIED = rf"{_IDENT}(?:\s*\.\s*{_IDENT}){{0,2}}"
_FROM_ITEM = re.compile(
    rf"(?P<name>{_QUALIFIED})(?:\s+(?:AS\s+)?(?P<alias>{_IDENT}))?",
    re.IGNORECASE,
)
_FROM_START = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+", re.IGNORECASE)
#: Palabras que, detrás de un nombre en FROM, no son su alias.
_NOT_ALIAS = frozenset(
    {
        "where", "join", "inner", "left", "right", "full", "cross", "natural", "on", "using", "group",
        "order", "limit", "offset", "having", "union", "except", "intersect", "window", "qualify",
        "set", "values", "select", "as", "positional", "asof", "anti", "semi", "lateral",
    }
)  # fmt: skip


def blank_code(text: str) -> tuple[str, bool]:
    """`text` con comentarios y cadenas sustituidos por espacios (las mismas posiciones), y si su final queda
    dentro de un comentario, una cadena o un identificador entre comillas (ahí no se sugiere nada)."""
    out = list(text)
    i, n = 0, len(text)
    inside = False
    while i < n:
        c = text[i]
        if c == "-" and text.startswith("--", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            inside = end == n
        elif c == "/" and text.startswith("/*", i):
            end = text.find("*/", i + 2)
            inside = end < 0
            end = n if end < 0 else end + 2
        elif c in "'\"":
            end = i + 1
            while True:
                end = text.find(c, end)
                if end < 0:
                    end, inside = n, True
                    break
                if text.startswith(c * 2, end):  # comilla duplicada: sigue dentro
                    end += 2
                    continue
                end += 1
                break
            if c == '"':  # los identificadores citados se conservan para leer nombres y alias
                i = end
                continue
        else:
            i += 1
            continue
        for j in range(i, end):
            if out[j] != "\n":
                out[j] = " "
        i = end
    return "".join(out), inside


def unquote(part: str) -> str:
    part = part.strip()
    if len(part) >= 2 and part[0] == part[-1] == '"':
        return part[1:-1].replace('""', '"')
    return part


def _statement_bounds(code: str, cursor: int) -> tuple[int, int]:
    """Sentencia del cursor en el texto ya sin comentarios ni cadenas (los `;` que quedan son reales)."""
    start = code.rfind(";", 0, cursor) + 1
    end = code.find(";", cursor)
    return start, len(code) if end < 0 else end


def _references(statement: str) -> list[tuple[list[str], str | None]]:
    """Objetos de FROM/JOIN/UPDATE/INTO de una sentencia: (partes del nombre, alias)."""
    refs: list[tuple[list[str], str | None]] = []
    for start in _FROM_START.finditer(statement):
        pos = start.end()
        while True:
            match = _FROM_ITEM.match(statement, pos)
            if match is None:
                break
            parts = [unquote(p) for p in _PART.findall(match.group("name"))]
            alias = match.group("alias")
            end = match.end()
            if alias is not None and unquote(alias).casefold() in _NOT_ALIAS:
                alias, end = None, match.end("name")
            refs.append((parts, unquote(alias) if alias else None))
            rest = re.match(r"\s*,\s*", statement[end:])
            if rest is None:
                break
            pos = end + rest.end()
    return refs


# -- resolución contra el catálogo ---------------------------------------------------------------------


def _resolve_object(catalog: CatalogSnapshot, parts: list[str]) -> Source | None:
    """`[obj]`, `[esquema, obj]` o `[base, esquema, obj]` → (base, esquema, obj), como DuckDB: primero la
    base en uso y su esquema `main`, luego las temporales."""
    if not parts or len(parts) > 3:
        return None
    if len(parts) == 3:
        candidates = [(parts[0], parts[1], parts[2])]
    elif len(parts) == 2:
        candidates = [(catalog.default, parts[0], parts[1]), (parts[0], "main", parts[1])]
    else:
        candidates = [(catalog.default, "main", parts[0]), (TEMP_CATALOG, "main", parts[0])]
    for database, schema, name in candidates:
        for obj in catalog.objects:
            if (
                catalog_key(obj.database) == catalog_key(database)
                and obj.schema.casefold() == schema.casefold()
                and obj.name.casefold() == name.casefold()
            ):
                return (obj.database, obj.schema, obj.name)
    return None


def complete(
    text_before_cursor: str,
    *,
    catalog: CatalogSnapshot | None,
    columns: Mapping[Source, tuple[ColumnInfo, ...]],
    vocabulary: Vocabulary | None,
    text_after_cursor: str = "",
    explicit: bool = False,
) -> Completion | None:
    """Sugerencias para el cursor. `None` si no hay nada que sugerir ahí (comentario, cadena, nada escrito
    sin pedirlo con Ctrl+Espacio…). `explicit`: pedido con Ctrl+Espacio."""
    code, inside = blank_code(text_before_cursor)
    if inside:
        return None
    match = _CHAIN_AT_END.search(code)
    chain = match.group(1) if match else ""
    prefix = (match.group(2) if match else None) or ""
    qualifier = [unquote(p) for p in _PART.findall(chain)]
    if not explicit and not qualifier and len(prefix) < AUTO_PREFIX:
        return None
    full_code, _ = blank_code(text_before_cursor + text_after_cursor)
    start, end = _statement_bounds(full_code, len(text_before_cursor))
    builder = _Builder(catalog, columns, vocabulary, full_code[start:end])
    if catalog is not None and qualifier:
        builder.after_dot(catalog, qualifier)
    elif catalog is not None:
        builder.anywhere(catalog)
    if not qualifier and vocabulary is not None:
        builder.words(vocabulary, upper=prefix[:1].isupper())
    return Completion(prefix, _rank(builder.found, prefix), tuple(dict.fromkeys(builder.missing)))


@dataclass
class _Builder:
    catalog: CatalogSnapshot | None
    columns: Mapping[Source, tuple[ColumnInfo, ...]]
    vocabulary: Vocabulary | None
    statement: str
    found: list[Suggestion] = field(default_factory=list)
    missing: list[Source] = field(default_factory=list)

    def name(self, value: str) -> str:
        return sql_name(value, self.vocabulary.reserved if self.vocabulary is not None else None)

    def add_columns(self, source: Source | None) -> None:
        if source is None:
            return
        known = self.columns.get(source)
        if known is None:
            self.missing.append(source)
            return
        self.found.extend(Suggestion(c.name, self.name(c.name), Kind.COLUMN) for c in known)

    def add_objects(self, catalog: CatalogSnapshot, database: str, schema: str) -> None:
        for obj in catalog.objects_in(database, schema):
            self.found.append(Suggestion(obj.name, self.name(obj.name), _kind_of(obj.kind.value)))

    def add_schemas(self, catalog: CatalogSnapshot, database: str, *, skip_main: bool = False) -> None:
        self.found.extend(
            Suggestion(s, self.name(s), Kind.SCHEMA)
            for s in catalog.schemas_of(database)
            if not (skip_main and s == "main")
        )

    def anywhere(self, catalog: CatalogSnapshot) -> None:
        """Sin `.` delante: columnas de los objetos de la sentencia, objetos visibles sin calificar,
        esquemas de la base en uso y bases."""
        for parts, _alias in _references(self.statement):
            self.add_columns(_resolve_object(catalog, parts))
        self.add_objects(catalog, catalog.default, "main")
        for obj in catalog.temporaries:
            self.found.append(Suggestion(obj.name, self.name(obj.name), _kind_of(obj.kind.value)))
        self.add_schemas(catalog, catalog.default, skip_main=True)
        self.found.extend(Suggestion(db.name, self.name(db.name), Kind.DATABASE) for db in catalog.databases)

    def after_dot(self, catalog: CatalogSnapshot, qualifier: list[str]) -> None:
        """Tras `x.` o `x.y.`: columnas de un alias o de un objeto, esquemas de una base u objetos de un
        esquema."""
        if len(qualifier) == 1:
            wanted = qualifier[0].casefold()
            for parts, alias in _references(self.statement):
                if alias is not None and alias.casefold() == wanted:
                    self.add_columns(_resolve_object(catalog, parts))
                    return
            db = catalog.get(qualifier[0])
            if db is not None:
                self.add_schemas(catalog, db.name)
            for schema in catalog.schemas_of(catalog.default):
                if schema.casefold() == wanted:
                    self.add_objects(catalog, catalog.default, schema)
        elif len(qualifier) == 2 and (db := catalog.get(qualifier[0])) is not None:
            for schema in catalog.schemas_of(db.name):
                if schema.casefold() == qualifier[1].casefold():
                    self.add_objects(catalog, db.name, schema)
        self.add_columns(_resolve_object(catalog, qualifier))

    def words(self, vocabulary: Vocabulary, *, upper: bool) -> None:
        self.found.extend(Suggestion(f, f, Kind.FUNCTION) for f in vocabulary.functions)
        self.found.extend(
            Suggestion(word, word, Kind.KEYWORD)
            for word in (k.upper() if upper else k for k in vocabulary.keywords)
        )


def _kind_of(object_kind: str) -> Kind:
    return Kind.TABLE if object_kind == "TABLE" else Kind.VIEW


def _rank(found: list[Suggestion], prefix: str) -> tuple[Suggestion, ...]:
    """Las que empiezan por el prefijo (sin distinguir mayúsculas), por grupo y por nombre, sin repetir."""
    needle = prefix.casefold()
    seen: set[tuple[str, Kind]] = set()
    kept: list[Suggestion] = []
    for item in found:
        key = (item.label.casefold(), item.kind)
        if key in seen or not item.label.casefold().startswith(needle):
            continue
        if needle and item.label.casefold() == needle and item.kind is Kind.KEYWORD:
            continue  # ya está escrita entera
        seen.add(key)
        kept.append(item)
    kept.sort(key=lambda s: (_ORDER.index(s.kind), s.label.casefold()))
    return tuple(kept[:MAX_ITEMS])
