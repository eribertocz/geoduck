# SPDX-License-Identifier: GPL-2.0-or-later
"""Normalización de tipos DuckDB → QGIS (qgis-bridge-spec §7, ADR-0012).

Una sola tabla de decisiones para las tres modalidades de carga. A partir de las columnas que devuelve
`DESCRIBE` (nombre y tipo tal como los escribe DuckDB 1.5.x y 2.x), produce un `SELECT` envolvente que
DuckDB ejecuta en C++: lo que QGIS o GDAL no representan sin pérdida se convierte aquí, de forma explícita
y con aviso. Nada se convierte en silencio.

Módulo puro: sin DuckDB ni QGIS; se prueba con cadenas de tipo.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.sql_text import quote_identifier


class FieldKind(str, Enum):
    """Tipo de campo resultante, común a QGIS (memory/ogr) y al proveedor conectado."""

    BOOL = "bool"
    INT = "int"  # entero de 32 bits
    INT64 = "int64"
    DOUBLE = "double"
    TEXT = "text"
    DATE = "date"
    DATETIME = "datetime"  # TIMESTAMP sin zona (µs)
    DATETIME_TZ = "datetime_tz"  # TIMESTAMPTZ: instante absoluto
    BINARY = "binary"


@dataclass(frozen=True)
class FieldPlan:
    """Una columna de salida: cómo se lee en DuckDB y qué campo de QGIS produce."""

    name: str
    source_type: str
    kind: FieldKind
    expression: str
    #: El valor de QGIS se puede escribir de vuelta en la columna sin pérdida (modalidad Conectada).
    writable: bool
    note: str = ""


class GeometryFormat(str, Enum):
    """Cómo guarda DuckDB una columna que se carga como geometría (spatial-spec §2.2)."""

    GEOMETRY = "geometry"  # tipo GEOMETRY
    WKB = "wkb"  # BLOB marcado por el usuario
    WKT = "wkt"  # VARCHAR marcado por el usuario


@dataclass(frozen=True)
class GeometryColumn:
    name: str
    source_type: str
    #: CRS declarado en el tipo (`GEOMETRY('OGC:CRS84')`), si lo hay; el definitivo viaja en GeoArrow.
    declared_crs: str | None
    format: GeometryFormat = GeometryFormat.GEOMETRY


@dataclass(frozen=True)
class LoadPlan:
    """Consulta normalizada lista para leerse con Arrow por lotes."""

    sql: str
    fields: tuple[FieldPlan, ...]
    geometry: GeometryColumn | None
    warnings: tuple[str, ...] = field(default=())
    #: Todas las columnas geométricas de la consulta (incluidas las marcadas), para que el usuario elija.
    geometries: tuple[GeometryColumn, ...] = field(default=())
    #: Columnas que el usuario puede marcar como geometría: (nombre, formato) para BLOB (WKB) y VARCHAR
    #: (WKT). Nunca se marcan solas (spatial-spec §2.2).
    candidates: tuple[tuple[str, GeometryFormat], ...] = field(default=())
    #: Columna booleana auxiliar de la consulta: verdadera si la geometría marcada no se pudo leer.
    #: Las copias la comprueban y no la cargan.
    unreadable_flag: str | None = None

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)


_INTS = {"TINYINT", "SMALLINT", "INTEGER", "UTINYINT", "USMALLINT"}
_DECIMAL = re.compile(r"^DECIMAL\((\d+),\s*(\d+)\)$")
_GEOMETRY = re.compile(r"^GEOMETRY(?:\('(?P<crs>(?:[^']|'')*)'\))?$")
_NESTED = ("STRUCT(", "MAP(", "UNION(")

#: Precisión máxima de un DECIMAL que cabe sin pérdida en un `double` (15 dígitos significativos).
DOUBLE_SAFE_DIGITS = 15


#: Nombre de la columna auxiliar de geometría ilegible (no puede chocar con un nombre de DuckDB válido
#: del usuario en la práctica; si chocara, `build_load_plan` lo rechaza).
UNREADABLE = "__geoduck_unreadable"


def is_geometry_type(source_type: str) -> bool:
    return bool(_GEOMETRY.match(source_type.strip()))


def candidate_format(source_type: str) -> GeometryFormat | None:
    """Formato con el que el usuario puede marcar una columna como geometría (`BLOB`, `VARCHAR`)."""
    upper = source_type.strip().upper()
    if upper == "BLOB":
        return GeometryFormat.WKB
    if upper == "VARCHAR":
        return GeometryFormat.WKT
    return None


def geometry_read_sql(column: str, fmt: GeometryFormat) -> str:
    """Expresión que convierte la columna en GEOMETRY con funciones del núcleo de DuckDB (sin `spatial`,
    spike G4-A F-94). Un valor ilegible da NULL."""
    col = quote_identifier(column)
    if fmt is GeometryFormat.WKB:
        return f"TRY(ST_GeomFromWKB({col}))"
    if fmt is GeometryFormat.WKT:
        return f"TRY(CAST({col} AS GEOMETRY))"
    return col


def geometry_write_sql(value: str, fmt: GeometryFormat) -> str:
    """Expresión que escribe una geometría (GEOMETRY en `value`) de vuelta en su formato de origen."""
    if fmt is GeometryFormat.WKB:
        return f"ST_AsWKB({value})"
    if fmt is GeometryFormat.WKT:
        return f"ST_AsText({value})"
    return value


def _geometry(name: str, source_type: str, fmt: GeometryFormat | None = None) -> GeometryColumn:
    if fmt is not None and fmt is not GeometryFormat.GEOMETRY:
        return GeometryColumn(name, source_type, None, fmt)  # WKB/WKT no declaran CRS (spatial-spec §4)
    match = _GEOMETRY.match(source_type.strip())
    crs = match.group("crs").replace("''", "'") if match and match.group("crs") else None
    return GeometryColumn(name, source_type, crs)


def plan_field(name: str, source_type: str) -> FieldPlan:  # noqa: PLR0911, PLR0912 - una salida por fila de §7
    """Decide la salida de una columna no geométrica según qgis-bridge-spec §7."""
    col = quote_identifier(name)
    t = source_type.strip()
    upper = t.upper()

    def same(kind: FieldKind, writable: bool = True, note: str = "") -> FieldPlan:
        return FieldPlan(name, t, kind, col, writable, note)

    def cast(kind: FieldKind, target: str, writable: bool, note: str) -> FieldPlan:
        return FieldPlan(name, t, kind, f"CAST({col} AS {target})", writable, note)

    if upper == "BOOLEAN":
        return same(FieldKind.BOOL)
    if upper in _INTS:
        return cast(FieldKind.INT, "INTEGER", True, "") if upper != "INTEGER" else same(FieldKind.INT)
    if upper == "BIGINT":
        return same(FieldKind.INT64)
    if upper == "UINTEGER":
        return cast(FieldKind.INT64, "BIGINT", True, "")
    if upper in {"UBIGINT", "HUGEINT", "UHUGEINT", "BIGNUM", "VARINT"}:
        return cast(FieldKind.TEXT, "VARCHAR", False, "convertida a texto (solo lectura)")
    if upper in {"FLOAT", "DOUBLE", "REAL"}:
        return same(FieldKind.DOUBLE)
    decimal = _DECIMAL.match(upper)
    if decimal:
        precision = int(decimal.group(1))
        if precision <= DOUBLE_SAFE_DIGITS:
            return cast(FieldKind.DOUBLE, "DOUBLE", True, "")
        return cast(FieldKind.TEXT, "VARCHAR", False, "convertida a texto (solo lectura)")
    if upper == "VARCHAR":
        return same(FieldKind.TEXT)
    if upper == "UUID":
        return cast(FieldKind.TEXT, "VARCHAR", True, "")
    if upper.startswith("ENUM("):
        return cast(FieldKind.TEXT, "VARCHAR", True, "")
    if upper == "DATE":
        return same(FieldKind.DATE)
    if upper in {"TIMESTAMP", "TIMESTAMP_S", "TIMESTAMP_MS"}:
        return (
            same(FieldKind.DATETIME)
            if upper == "TIMESTAMP"
            else cast(FieldKind.DATETIME, "TIMESTAMP", False, "")
        )
    if upper == "TIMESTAMP_NS":
        return cast(
            FieldKind.DATETIME,
            "TIMESTAMP",
            False,
            "reducida a microsegundos (solo lectura)",
        )
    if upper == "TIMESTAMP WITH TIME ZONE":
        return same(FieldKind.DATETIME_TZ)
    if upper in {"TIME", "TIME WITH TIME ZONE", "INTERVAL"} or upper.startswith("TIME"):
        return cast(FieldKind.TEXT, "VARCHAR", False, "convertida a texto ISO (solo lectura)")
    if upper == "BLOB":
        return same(FieldKind.BINARY)
    if upper == "BIT":
        return cast(FieldKind.TEXT, "VARCHAR", False, "convertida a texto (solo lectura)")
    if upper.endswith("]") or upper.startswith(_NESTED):
        return FieldPlan(
            name,
            t,
            FieldKind.TEXT,
            f"CAST(to_json({col}) AS VARCHAR)",
            False,
            "convertida a JSON (solo lectura)",
        )
    return cast(FieldKind.TEXT, "VARCHAR", False, "convertida a texto (solo lectura)")


def _marked_columns(types: dict[str, str], formats: Mapping[str, Any]) -> dict[str, GeometryFormat]:
    """Valida las columnas marcadas como geometría: solo BLOB → WKB y VARCHAR → WKT."""
    if UNREADABLE in types:
        raise GeoDuckError(f"Nombre de columna reservado: «{UNREADABLE}»", code=ErrorCode.INVALID_ARGUMENT)
    marked: dict[str, GeometryFormat] = {}
    for name, value in formats.items():
        fmt = GeometryFormat(value)
        if name not in types:
            raise GeoDuckError(f"«{name}» no es una columna de la consulta", code=ErrorCode.INVALID_ARGUMENT)
        if fmt is GeometryFormat.GEOMETRY or candidate_format(types[name]) is not fmt:
            raise GeoDuckError(
                f"«{name}» ({types[name]}) no se puede leer como {fmt.value.upper()}",
                code=ErrorCode.INVALID_ARGUMENT,
            )
        marked[name] = fmt
    return marked


def build_load_plan(
    inner_sql: str,
    columns: list[tuple[str, str]],
    *,
    geometry: str | None = None,
    pick_first: bool = False,
    formats: Mapping[str, GeometryFormat] | None = None,
) -> LoadPlan:
    """`SELECT` normalizado sobre `inner_sql`.

    `geometry`: columna geométrica primaria. Si es None y hay una sola columna geométrica, se usa esa; con
    varias, se exige elegirla (o, con `pick_first`, se propone la primera: para preguntar al usuario). Las
    geometrías no primarias se omiten con aviso.

    `formats`: columnas `BLOB`/`VARCHAR` que el usuario marcó como geometría WKB/WKT (spatial-spec §2.2).
    Cuentan como columnas geométricas; nada se marca solo.
    """
    if not columns:
        raise GeoDuckError("La consulta no devuelve columnas", code=ErrorCode.INVALID_ARGUMENT)
    types = dict(columns)
    marked = _marked_columns(types, formats or {})

    def is_geom(name: str, source_type: str) -> bool:
        return is_geometry_type(source_type) or name in marked

    geoms = [(n, t) for n, t in columns if is_geom(n, t)]
    if geometry is None and len(geoms) > 1 and not pick_first:
        raise GeoDuckError(
            "La consulta tiene varias columnas de geometría; elija cuál cargar: "
            + ", ".join(n for n, _ in geoms),
            code=ErrorCode.INVALID_ARGUMENT,
        )
    if geometry is not None and geometry not in {n for n, _ in geoms}:
        raise GeoDuckError(f"«{geometry}» no es una columna de geometría", code=ErrorCode.INVALID_ARGUMENT)
    primary = geometry if geometry is not None else (geoms[0][0] if geoms else None)

    fields: list[FieldPlan] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for name, source_type in columns:
        if name in seen:
            raise GeoDuckError(f"Nombre de columna repetido: «{name}»", code=ErrorCode.INVALID_ARGUMENT)
        seen.add(name)
        if is_geom(name, source_type):
            if name != primary:
                warnings.append(f"Columna «{name}» omitida (geometría secundaria)")
            continue
        plan = plan_field(name, source_type)
        fields.append(plan)
        if plan.note:
            warnings.append(f"Columna «{name}» ({source_type}) {plan.note}")

    select = [f"{f.expression} AS {quote_identifier(f.name)}" for f in fields]
    geom = None
    flag = None
    if primary is not None:
        geom = _geometry(primary, types[primary], marked.get(primary))
        read = geometry_read_sql(primary, geom.format)
        select.append(f"{read} AS {quote_identifier(primary)}")
        if geom.format is not GeometryFormat.GEOMETRY:
            col = quote_identifier(primary)
            flag = UNREADABLE
            select.append(f"({col} IS NOT NULL AND {read} IS NULL) AS {quote_identifier(flag)}")
    body = strip_terminator(inner_sql)
    sql = f"SELECT {', '.join(select) or '*'} FROM (\n{body}\n) AS __geoduck_q"  # \n: un `--` final no cierra
    candidates = tuple((n, fmt) for n, t in columns if (fmt := candidate_format(t)) is not None)
    return LoadPlan(
        sql,
        tuple(fields),
        geom,
        tuple(warnings),
        tuple(_geometry(n, t, marked.get(n)) for n, t in geoms),
        candidates,
        flag,
    )


def strip_terminator(sql: str) -> str:
    """Quita el `;` final y los espacios, para poder usar la consulta como subconsulta."""
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    if not text:
        raise GeoDuckError("La consulta está vacía", code=ErrorCode.INVALID_ARGUMENT)
    return text


def unreadable_warning(geometry: GeometryColumn, count: int) -> str:
    """Aviso de geometrías ilegibles en una columna marcada (spatial-spec §3, §9)."""
    return (
        f"{count} geometrías ilegibles en «{geometry.name}» ({geometry.format.value.upper()}): "
        "se muestran sin geometría"
    )


def unreadable_error(geometry: GeometryColumn, row: int) -> GeoDuckError:
    """Error de una copia con una geometría ilegible: no se publica nada (spatial-spec §3)."""
    return GeoDuckError(
        f"Geometría ilegible en la columna «{geometry.name}» ({geometry.format.value.upper()}), "
        f"fila {row}: no se cargó nada",
        code=ErrorCode.INVALID_ARGUMENT,
    )


def missing_crs_warning(geometry: GeometryColumn | None, override: str | None) -> str:
    """Aviso de capa sin CRS (spatial-spec §4): conserva el texto declarado si QGIS no lo reconoce."""
    declared = geometry.declared_crs if geometry is not None else None
    if override is None and declared:
        return f"SRC «{declared}» no reconocido por QGIS: sin SRC asignado"
    return "Sin SRC asignado"
