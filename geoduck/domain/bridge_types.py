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
from dataclasses import dataclass, field
from enum import Enum

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


@dataclass(frozen=True)
class GeometryColumn:
    name: str
    source_type: str
    #: CRS declarado en el tipo (`GEOMETRY('OGC:CRS84')`), si lo hay; el definitivo viaja en GeoArrow.
    declared_crs: str | None


@dataclass(frozen=True)
class LoadPlan:
    """Consulta normalizada lista para leerse con Arrow por lotes."""

    sql: str
    fields: tuple[FieldPlan, ...]
    geometry: GeometryColumn | None
    warnings: tuple[str, ...] = field(default=())
    #: Todas las columnas geométricas de la consulta, para que el usuario elija la primaria.
    geometries: tuple[GeometryColumn, ...] = field(default=())

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)


_INTS = {"TINYINT", "SMALLINT", "INTEGER", "UTINYINT", "USMALLINT"}
_DECIMAL = re.compile(r"^DECIMAL\((\d+),\s*(\d+)\)$")
_GEOMETRY = re.compile(r"^GEOMETRY(?:\('(?P<crs>(?:[^']|'')*)'\))?$")
_NESTED = ("STRUCT(", "MAP(", "UNION(")

#: Precisión máxima de un DECIMAL que cabe sin pérdida en un `double` (15 dígitos significativos).
DOUBLE_SAFE_DIGITS = 15


def is_geometry_type(source_type: str) -> bool:
    return bool(_GEOMETRY.match(source_type.strip()))


def _geometry(name: str, source_type: str) -> GeometryColumn:
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


def build_load_plan(
    inner_sql: str,
    columns: list[tuple[str, str]],
    *,
    geometry: str | None = None,
    pick_first: bool = False,
) -> LoadPlan:
    """`SELECT` normalizado sobre `inner_sql`.

    `geometry`: columna geométrica primaria. Si es None y hay una sola columna geométrica, se usa esa; con
    varias, se exige elegirla (o, con `pick_first`, se propone la primera: para preguntar al usuario). Las
    geometrías no primarias se omiten con aviso.
    """
    if not columns:
        raise GeoDuckError("La consulta no devuelve columnas", code=ErrorCode.INVALID_ARGUMENT)
    geoms = [(n, t) for n, t in columns if is_geometry_type(t)]
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
        if is_geometry_type(source_type):
            if name != primary:
                warnings.append(f"Columna «{name}» omitida (geometría secundaria)")
            continue
        plan = plan_field(name, source_type)
        fields.append(plan)
        if plan.note:
            warnings.append(f"Columna «{name}» ({source_type}) {plan.note}")

    select = [f"{f.expression} AS {quote_identifier(f.name)}" for f in fields]
    geom = None
    if primary is not None:
        geom = _geometry(primary, dict(columns)[primary])
        select.append(quote_identifier(primary))
    body = strip_terminator(inner_sql)
    sql = f"SELECT {', '.join(select) or '*'} FROM (\n{body}\n) AS __geoduck_q"  # \n: un `--` final no cierra
    return LoadPlan(sql, tuple(fields), geom, tuple(warnings), tuple(_geometry(n, t) for n, t in geoms))


def strip_terminator(sql: str) -> str:
    """Quita el `;` final y los espacios, para poder usar la consulta como subconsulta."""
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    if not text:
        raise GeoDuckError("La consulta está vacía", code=ErrorCode.INVALID_ARGUMENT)
    return text
