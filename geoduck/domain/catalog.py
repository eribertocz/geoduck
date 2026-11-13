# SPDX-License-Identifier: GPL-2.0-or-later
"""Modelo del catálogo de la sesión: bases adjuntas (GD-CAT-001, base de G1).

Fuente de verdad: DuckDB (`duckdb_databases()` y `current_database()`), nunca un registro propio
(session-spec §2: «el registro de bases se reconcilia con `duckdb_databases()`»). Una instantánea es
inmutable y coherente: o se obtiene completa y válida, o no existe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.errors import InvalidArgumentError
from geoduck.domain.i18n import tr

#: DuckDB compara los nombres de catálogo plegando **solo** las letras ASCII: «Año» y «año» chocan,
#: «Año» y «AÑO» no (verificado con DuckDB 1.5.0 y 2.0.0). Se reproduce exactamente esa regla.
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def catalog_key(name: str) -> str:
    """Clave de comparación de nombres de catálogo, con la misma regla que DuckDB."""
    return name.translate(_ASCII_LOWER)


#: Nombres que DuckDB reserva para sus catálogos internos (verificado con DuckDB 1.5.0 y 2.0.0).
RESERVED_CATALOG_NAMES = frozenset({"system", "temp"})
#: Catálogo interno donde DuckDB guarda las tablas y vistas temporales de la sesión.
TEMP_CATALOG = "temp"


class ObjectKind(str, Enum):
    TABLE = "TABLE"
    VIEW = "VIEW"


@dataclass(frozen=True)
class CatalogObject:
    """Tabla o vista visible en la sesión (GD-CAT-001). Las temporales están en el catálogo `temp`."""

    database: str
    schema: str
    name: str
    kind: ObjectKind
    temporary: bool = False


@dataclass(frozen=True)
class ColumnInfo:
    """Columna de una tabla o vista (GD-CAT-002), tal como la informa `duckdb_columns()`."""

    name: str
    #: Tipo exacto de DuckDB (`DECIMAL(10,2)`, `GEOMETRY('EPSG:4326')`, `STRUCT(a INTEGER)`…).
    data_type: str
    #: `None` si DuckDB no lo informa.
    nullable: bool | None
    #: Parte de la clave primaria (`duckdb_constraints()`; #147: la llave en el explorador).
    primary_key: bool = False

    @property
    def is_geometry(self) -> bool:
        """Por el tipo, nunca por el nombre."""
        return is_geometry_type(self.data_type)


class AccessMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"


class OpenAction(str, Enum):
    """Las dos únicas formas de llegar a un archivo (session-spec §2). Nunca se crea uno implícitamente."""

    #: El archivo debe existir; si no, `DB_NOT_FOUND` y no se crea nada.
    OPEN_EXISTING = "OPEN_EXISTING"
    #: El archivo no debe existir; nunca se sobrescribe ni se reutiliza uno existente. Solo en RW.
    CREATE_NEW = "CREATE_NEW"


@dataclass(frozen=True)
class AttachedDatabase:
    """Una base visible en la sesión (las internas `system` y `temp` no se incluyen)."""

    name: str
    #: Ruta del archivo; `None` para una base en memoria (incluida la raíz `:memory:`).
    path: str | None
    access: AccessMode
    #: Tipo de almacenamiento que informa DuckDB (p. ej. `duckdb`).
    storage: str

    @property
    def in_memory(self) -> bool:
        return self.path is None

    @property
    def key(self) -> str:
        return catalog_key(self.name)


@dataclass(frozen=True)
class CatalogSnapshot:
    """Estado del catálogo en un instante. Valida sus invariantes al construirse.

    - los nombres son únicos según la regla de DuckDB (`catalog_key`);
    - el catálogo raíz y el predeterminado están entre las bases listadas;
    - `root` y `default` se guardan con la grafía listada por DuckDB (tras `USE ab`, DuckDB informa
      `ab` aunque la base se llame `Ab`).
    """

    databases: tuple[AttachedDatabase, ...]
    root: str
    default: str
    #: Esquemas `(base, esquema)` de las bases listadas.
    schemas: tuple[tuple[str, str], ...] = ()
    #: Tablas y vistas de esas bases, más las temporales (`database == "temp"`).
    objects: tuple[CatalogObject, ...] = ()

    def __post_init__(self) -> None:
        index: dict[str, AttachedDatabase] = {}
        for db in self.databases:
            if db.key in index:
                raise ValueError(
                    tr("Repeated catalog name: {0!r} and {1!r}").format(db.name, index[db.key].name)
                )
            index[db.key] = db
        for role in ("root", "default"):
            listed = index.get(catalog_key(getattr(self, role)))
            if listed is None:
                raise ValueError(
                    tr("The {0} catalog {1!r} is not among the databases").format(role, getattr(self, role))
                )
            object.__setattr__(self, role, listed.name)
        known_schemas = set()
        for database, schema in self.schemas:
            if catalog_key(database) not in index:
                raise ValueError(
                    tr("Schema {0!r} belongs to an unlisted database: {1!r}").format(schema, database)
                )
            known_schemas.add((catalog_key(database), schema))
        for obj in self.objects:
            if obj.temporary:
                if catalog_key(obj.database) != TEMP_CATALOG:
                    raise ValueError(tr("Temporary object outside the temp catalog: {0!r}").format(obj.name))
            elif (catalog_key(obj.database), obj.schema) not in known_schemas:
                raise ValueError(tr("Object {0!r} belongs to an unlisted schema").format(obj.name))

    def get(self, name: str) -> AttachedDatabase | None:
        key = catalog_key(name)
        return next((db for db in self.databases if db.key == key), None)

    def is_root(self, name: str) -> bool:
        return catalog_key(name) == catalog_key(self.root)

    @property
    def root_database(self) -> AttachedDatabase:
        db = self.get(self.root)
        assert db is not None  # garantizado por __post_init__
        return db

    @property
    def default_database(self) -> AttachedDatabase:
        db = self.get(self.default)
        assert db is not None  # garantizado por __post_init__
        return db

    @property
    def attached(self) -> tuple[AttachedDatabase, ...]:
        """Bases adjuntas por el usuario: todas menos la raíz."""
        return tuple(db for db in self.databases if not self.is_root(db.name))

    def schemas_of(self, database: str) -> tuple[str, ...]:
        key = catalog_key(database)
        return tuple(schema for db, schema in self.schemas if catalog_key(db) == key)

    def objects_in(self, database: str, schema: str) -> tuple[CatalogObject, ...]:
        key = catalog_key(database)
        return tuple(
            o
            for o in self.objects
            if not o.temporary and catalog_key(o.database) == key and o.schema == schema
        )

    @property
    def temporaries(self) -> tuple[CatalogObject, ...]:
        return tuple(o for o in self.objects if o.temporary)


@dataclass(frozen=True)
class AttachRequest:
    """Petición de «Abrir existente» o «Crear nueva». Se valida al construirse."""

    path: str
    access: AccessMode
    action: OpenAction
    #: Alias del catálogo. Si falta, se usa el nombre del archivo sin extensión, como hace DuckDB.
    alias: str | None = None

    def __post_init__(self) -> None:
        if not self.path.strip() or "\x00" in self.path:
            raise InvalidArgumentError(tr("Enter the file path"))
        if self.action is OpenAction.CREATE_NEW and self.access is not AccessMode.READ_WRITE:
            raise InvalidArgumentError(tr("«Create new» only allows read-write"))
        alias = self.effective_alias
        if not alias.strip() or "\x00" in alias:
            raise InvalidArgumentError(tr("Enter an alias for the database"))

    @property
    def effective_alias(self) -> str:
        if self.alias is not None:
            return self.alias
        name = re.split(r"[\\/]", self.path.rstrip("\\/"))[-1]
        stem, dot, _ext = name.rpartition(".")
        return stem if dot and stem else name


@dataclass(frozen=True)
class AttachResult:
    """Base recién adjuntada y el catálogo leído en la misma operación serial."""

    database: AttachedDatabase
    catalog: CatalogSnapshot


@dataclass(frozen=True)
class DetachResult:
    """Base desadjuntada y el catálogo leído después, en la misma operación serial."""

    database: AttachedDatabase
    catalog: CatalogSnapshot
