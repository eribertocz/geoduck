# SPDX-License-Identifier: GPL-2.0-or-later
"""Enviar capas de QGIS a DuckDB: reglas sin Qt ni DuckDB (G8, qgis-import-spec; ADR-0015).

Nombres de tabla y de columna, tipos de DuckDB para cada tipo de campo de QGIS, el SQL de cada lote y la
estimación de «capa grande». El motor (`geoduck.engine.importing`) lo ejecuta en una transacción.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from geoduck.domain.i18n import tr
from geoduck.domain.sql_text import quote_identifier, quote_string_literal

#: Nombre de la vista temporal con la que el motor registra cada lote Arrow.
BATCH_VIEW = "__geoduck_import_batch"
#: Columna del lote con la geometría en WKB.
WKB_COLUMN = "__geoduck_wkb"
#: Vista temporal con los identificadores de la selección de una capa Conectada (F-119: `JOIN`, no `IN`).
SELECTION_VIEW = "__geoduck_import_selection"
#: Entidades por segundo para estimar el camino general: cifra prudente del spike G8-A (F-114: 140–205 mil).
RATE = 100_000
#: Más de esto (segundos estimados) es una «capa grande»: se avisa, nunca se bloquea (qgis-import-spec §3).
LARGE_SECONDS = 60


class ImportMode(str, Enum):
    """Qué hacer con la tabla destino (qgis-import-spec §3)."""

    CREATE = "create"  # tabla nueva; si ya existe, falla
    REPLACE = "replace"
    APPEND = "append"


@dataclass(frozen=True)
class ImportColumn:
    """Un campo de la capa: su nombre en DuckDB, su columna en el lote Arrow y su tipo de DuckDB."""

    name: str
    source: str
    duck_type: str


@dataclass(frozen=True)
class ImportGeometry:
    """La geometría: nombre de la columna en DuckDB y SRC (`EPSG:…`, PROJJSON o None = sin SRC)."""

    name: str
    crs: str | None


@dataclass(frozen=True)
class ImportJob:
    """Una capa → una tabla. Los lotes llevan los campos en `columns[i].source` y la geometría en WKB."""

    layer_name: str
    table: str
    mode: ImportMode
    columns: tuple[ImportColumn, ...]
    geometry: ImportGeometry | None
    database: str = "memory"
    schema: str = "main"
    #: Tabla temporal (solo esta sesión): `database` y `schema` no se usan.
    temporary: bool = False
    #: Camino SQL (qgis-import-spec §5.1 y §5.2): `SELECT` con las columnas finales, que DuckDB ejecuta sin
    #: lotes. None = camino general (lotes Arrow del canal).
    source_sql: str | None = None
    #: Base en uso para `source_sql` (la de la capa Conectada, G7); None = no cambia.
    source_database: str | None = None
    #: Vista en vez de copia (solo un Parquet sin selección ni filtro, §5.2).
    as_view: bool = False
    #: Camino SQL con selección: tabla Arrow de identificadores que `source_sql` une como `SELECTION_VIEW`.
    selection: Any = None

    @property
    def by_sql(self) -> bool:
        return self.source_sql is not None

    @property
    def qualified(self) -> str:
        if self.temporary:
            return f"temp.main.{quote_identifier(self.table)}"
        return ".".join(quote_identifier(p) for p in (self.database, self.schema, self.table))

    @property
    def display(self) -> str:
        """Nombre para los mensajes: `db.main.tabla` o `tabla (temporal)`."""
        if self.temporary:
            return tr("{0} (temporary)").format(self.table)
        return f"{self.database}.{self.schema}.{self.table}"

    def select_sql(self) -> str:
        """`SELECT` sobre el lote registrado: cada campo convertido a su tipo y la geometría con su SRC."""
        parts = [
            f"CAST({quote_identifier(c.source)} AS {c.duck_type}) AS {quote_identifier(c.name)}"
            for c in self.columns
        ]
        if self.geometry is not None:
            geom = f"ST_GeomFromWKB({quote_identifier(WKB_COLUMN)})"
            if self.geometry.crs:  # sin `spatial`: ST_SetCRS sí; declarar GEOMETRY('EPSG:…') no (F-115)
                geom = f"ST_SetCRS({geom}, {quote_string_literal(self.geometry.crs)})"
            parts.append(f"{geom} AS {quote_identifier(self.geometry.name)}")
        return f"SELECT {', '.join(parts)} FROM {quote_identifier(BATCH_VIEW)}"

    def first_batch_sql(self) -> str:
        """Primer lote: crea la tabla (o la reemplaza), o añade filas por nombre de columna."""
        select = self.select_sql()
        temp = "TEMP " if self.temporary else ""
        name = quote_identifier(self.table) if self.temporary else self.qualified
        if self.mode is ImportMode.CREATE:
            return f"CREATE {temp}TABLE {name} AS {select}"
        if self.mode is ImportMode.REPLACE:
            return f"CREATE OR REPLACE {temp}TABLE {name} AS {select}"
        return self.next_batch_sql()

    def next_batch_sql(self) -> str:
        return f"INSERT INTO {self.qualified} BY NAME {self.select_sql()}"

    def source_write_sql(self) -> str:
        """Camino SQL: la tabla (o la vista) a partir de `source_sql`, o sus filas añadidas por nombre."""
        assert self.source_sql is not None
        temp = "TEMP " if self.temporary else ""
        name = quote_identifier(self.table) if self.temporary else self.qualified
        kind = "VIEW" if self.as_view else "TABLE"
        if self.mode is ImportMode.CREATE:
            return f"CREATE {temp}{kind} {name} AS {self.source_sql}"
        if self.mode is ImportMode.REPLACE:
            return f"CREATE OR REPLACE {temp}{kind} {name} AS {self.source_sql}"
        return f"INSERT INTO {self.qualified} BY NAME {self.source_sql}"


@dataclass(frozen=True)
class ImportedTable:
    display: str
    qualified: str
    mode: ImportMode
    rows: int


@dataclass(frozen=True)
class ImportReport:
    tables: tuple[ImportedTable, ...]
    warnings: tuple[str, ...] = field(default=())

    @property
    def rows(self) -> int:
        return sum(t.rows for t in self.tables)


# -- nombres ----------------------------------------------------------------------------------------


def table_name_for(layer_name: str) -> str:
    """Nombre de tabla propuesto: minúsculas, sin acentos, `_` en lugar de espacios y signos."""
    plain = unicodedata.normalize("NFKD", layer_name).encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")
    if not name:
        return "capa"
    return f"t_{name}" if name[0].isdigit() else name


def unique_name(name: str, taken: Iterable[str]) -> str:
    """`name`, o `name_2`, `name_3`… si ya está (sin distinguir mayúsculas, como DuckDB)."""
    used = {t.lower() for t in taken}
    if name.lower() not in used:
        return name
    n = 2
    while f"{name}_{n}".lower() in used:
        n += 1
    return f"{name}_{n}"


def column_names(names: Iterable[str]) -> tuple[list[str], list[str]]:
    """Nombres de columna para DuckDB, que no distingue mayúsculas: `ID` e `id` chocan y el segundo se
    renombra (`id_2`), con aviso (qgis-import-spec §6)."""
    out: list[str] = []
    warnings: list[str] = []
    for name in names:
        fixed = unique_name(name, out)
        if fixed != name:
            warnings.append(
                tr("Field «{0}» renamed to «{1}»: DuckDB does not tell upper and lower case apart").format(
                    name, fixed
                )
            )
        out.append(fixed)
    return out, warnings


# -- tipos -------------------------------------------------------------------------------------------

#: Tipo de campo de QGIS (nombre de `QMetaType`, sin depender de Qt) → tipo de DuckDB (qgis-import-spec §6).
_TYPES = {
    "int": "INTEGER",
    "uint": "UINTEGER",
    "longlong": "BIGINT",
    "qlonglong": "BIGINT",
    "ulonglong": "UBIGINT",
    "qulonglong": "UBIGINT",
    "double": "DOUBLE",
    "bool": "BOOLEAN",
    "qstring": "VARCHAR",
    "string": "VARCHAR",
    "qdate": "DATE",
    "date": "DATE",
    "qtime": "TIME",
    "time": "TIME",
    "qdatetime": "TIMESTAMP",
    "datetime": "TIMESTAMP",
    "qbytearray": "BLOB",
    "bytearray": "BLOB",
    "qstringlist": "VARCHAR[]",
    "stringlist": "VARCHAR[]",
}
_LIST_ITEMS = {"int": "BIGINT", "longlong": "BIGINT", "qlonglong": "BIGINT", "double": "DOUBLE"}


def duck_type_for(
    type_name: str, sub_type: str | None = None, *, timezone: bool = False
) -> tuple[str, str | None]:
    """Tipo de DuckDB para un campo de QGIS y un aviso si la conversión no es directa.

    `type_name`: nombre del `QMetaType` del campo (`int`, `QString`, `QDate`, `QVariantList`…);
    `sub_type`: el de sus elementos, en listas. `timezone`: fecha y hora con zona → `TIMESTAMPTZ`."""
    key = type_name.lower()
    if key in ("qdatetime", "datetime") and timezone:
        return "TIMESTAMPTZ", None
    if key in _TYPES:
        return _TYPES[key], None
    if key in ("qvariantlist", "list"):
        item = _LIST_ITEMS.get((sub_type or "").lower())
        if item is not None:
            return f"{item}[]", None
        return "VARCHAR[]", tr("list of «{0}» sent as text").format(sub_type or "?")
    return "JSON", tr("type «{0}» sent as JSON text").format(type_name)


# -- capa grande -------------------------------------------------------------------------------------


def estimated_seconds(features: int) -> float:
    """Estimación prudente del camino general (lectura de QGIS por lotes Arrow)."""
    return features / RATE


def is_large(features: int) -> bool:
    return estimated_seconds(features) > LARGE_SECONDS
