# SPDX-License-Identifier: GPL-2.0-or-later
"""Lo que muestra la pestaña de tabla: filtros en chips, búsqueda, orden y página (workspace-pro-spec §4;
GD-WSP-003; AT-WSP-003).

Sin Qt ni DuckDB: construye el SQL de solo lectura que ejecuta DuckDB (página de 100 filas, total aparte) y el
SQL equivalente de «Ver SQL». Los identificadores y valores se citan (`sql_text`, como todo SQL que GeoDuck
genera); nunca se ejecuta texto del usuario sin citar. Las geometrías se leen como texto (WKT): DuckDB 1.5
no entrega el tipo `GEOMETRY` a Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from geoduck.domain.catalog import ColumnInfo
from geoduck.domain.i18n import N_, tr
from geoduck.domain.sql_text import quote_identifier, quote_string_literal

#: Filas por página (propietario, 2026-11-05: sin selector).
PAGE = 100
#: Caracteres de una geometría en la grilla (el detalle de fila la lee entera).
GEOMETRY_PREVIEW = 2000

EQ, NE, GT, GE, LT, LE = "=", "<>", ">", ">=", "<", "<="
CONTAINS, STARTS, IS_NULL, NOT_NULL = "contains", "starts", "null", "not_null"
#: Operadores en el orden del menú, con su texto en el chip.
OPERATORS: tuple[tuple[str, str], ...] = (
    (EQ, "="),
    (NE, "≠"),
    (GT, ">"),
    (GE, "≥"),
    (LT, "<"),
    (LE, "≤"),
    (CONTAINS, N_("contains")),
    (STARTS, N_("starts with")),
    (IS_NULL, N_("is null")),
    (NOT_NULL, N_("is not null")),
)
#: Operadores sin valor.
UNARY = frozenset({IS_NULL, NOT_NULL})
_TEXT = re.compile(r"^(VARCHAR|TEXT|STRING|CHAR|BPCHAR|UUID|ENUM)", re.IGNORECASE)


def is_text(data_type: str) -> bool:
    return bool(_TEXT.match(data_type.strip()))


def operator_text(op: str) -> str:
    return tr(dict(OPERATORS)[op])


@dataclass(frozen=True)
class Filter:
    """Un chip: «columna operador valor». Se combinan con Y."""

    column: str
    op: str
    value: str = ""

    def __post_init__(self) -> None:
        if self.op not in dict(OPERATORS):
            raise ValueError(f"operador desconocido: {self.op!r}")

    def sql(self) -> str:
        col = quote_identifier(self.column)
        if self.op == IS_NULL:
            return f"{col} IS NULL"
        if self.op == NOT_NULL:
            return f"{col} IS NOT NULL"
        value = quote_string_literal(self.value)
        if self.op == CONTAINS:
            return f"contains(lower(CAST({col} AS VARCHAR)), lower({value}))"
        if self.op == STARTS:
            return f"starts_with(lower(CAST({col} AS VARCHAR)), lower({value}))"
        # Un literal de texto se convierte al tipo de la columna (DuckDB): «> '50'» compara números
        return f"{col} {self.op} {value}"

    @property
    def label(self) -> tuple[str, str, str]:
        """Las tres partes del chip: columna, operador y valor (vacío si no lleva)."""
        return self.column, operator_text(self.op), "" if self.op in UNARY else self.value


@dataclass(frozen=True)
class Browse:
    """Una tabla o vista con sus filtros, búsqueda y orden. `columns`: las de la tabla, en orden."""

    database: str
    schema: str
    name: str
    columns: tuple[ColumnInfo, ...]
    filters: tuple[Filter, ...] = ()
    search: str = ""
    #: `(columna, ascendente)` o `None` (orden de inserción, que DuckDB conserva).
    order: tuple[str, bool] | None = None
    #: Es una tabla (tiene `rowid`). Al ordenar, los empates se deshacen con `rowid` (en una vista, con las
    #: demás columnas): sin eso, las páginas de valores repetidos podrían repetir o saltarse filas.
    has_rowid: bool = True

    @property
    def source(self) -> str:
        return ".".join(quote_identifier(part) for part in (self.database, self.schema, self.name))

    def with_filter(self, item: Filter) -> Browse:
        return replace(self, filters=(*self.filters, item))

    def without_filter(self, index: int) -> Browse:
        return replace(self, filters=self.filters[:index] + self.filters[index + 1 :])

    def with_search(self, text: str) -> Browse:
        return replace(self, search=text.strip())

    def next_order(self, column: str) -> Browse:
        """Clic en el encabezado: ascendente, descendente, sin orden."""
        if self.order is None or self.order[0] != column:
            return replace(self, order=(column, True))
        if self.order[1]:
            return replace(self, order=(column, False))
        return replace(self, order=None)

    def conditions(self) -> list[str]:
        found = [f.sql() for f in self.filters]
        texts = [c for c in self.columns if is_text(c.data_type)]
        if self.search and texts:
            value = quote_string_literal(self.search)
            found.append(
                "("
                + " OR ".join(f"contains(lower({quote_identifier(c.name)}), lower({value}))" for c in texts)
                + ")"
            )
        elif self.search:
            found.append("FALSE")  # sin columnas de texto, la búsqueda no encuentra nada
        return found

    def _where(self) -> str:
        conditions = self.conditions()
        return " WHERE " + " AND ".join(conditions) if conditions else ""

    def _order_by(self) -> str:
        if self.order is None:
            return ""
        column, ascending = self.order
        parts = [f"{quote_identifier(column)} {'ASC' if ascending else 'DESC'} NULLS LAST"]
        if self.has_rowid:
            parts.append("rowid")
        else:
            parts += [
                quote_identifier(c.name) for c in self.columns if c.name != column and not c.is_geometry
            ]
        return " ORDER BY " + ", ".join(parts)

    def _select_list(self, *, preview: bool) -> str:
        if not any(c.is_geometry for c in self.columns):
            return "*"
        parts = []
        for column in self.columns:
            name = quote_identifier(column.name)
            if column.is_geometry:  # como texto: DuckDB 1.5 no entrega GEOMETRY a Python
                text = f"CAST({name} AS VARCHAR)"
                parts.append(
                    f"left({text}, {GEOMETRY_PREVIEW}) AS {name}" if preview else f"{text} AS {name}"
                )
            else:
                parts.append(name)
        return ", ".join(parts)

    def page_sql(self, offset: int) -> str:
        """Una página de `PAGE` filas desde `offset`."""
        return (
            f"SELECT {self._select_list(preview=True)} FROM {self.source}{self._where()}{self._order_by()}"
            f" LIMIT {PAGE} OFFSET {max(0, int(offset))}"
        )

    def row_sql(self, index: int) -> str:
        """Una fila entera (geometrías completas) para el detalle."""
        return (
            f"SELECT {self._select_list(preview=False)} FROM {self.source}{self._where()}{self._order_by()}"
            f" LIMIT 1 OFFSET {max(0, int(index))}"
        )

    def count_sql(self) -> str:
        return f"SELECT count(*) FROM {self.source}{self._where()}"

    def display_sql(self) -> str:
        """«Ver SQL»: la consulta equivalente, legible."""
        lines = [f"SELECT *\nFROM {self.source}"]
        conditions = self.conditions()
        if conditions:
            lines.append("WHERE " + "\n  AND ".join(conditions))
        if self.order is not None:
            lines.append(self._order_by().strip())
        return "\n".join(lines) + ";\n"


def structure_sql(database: str, schema: str, name: str) -> str:
    """«Estructura»: la definición (`CREATE`) y el tamaño aproximado, y las claves primaria y únicas, en filas
    `(kind, text, value, columns)`, solo de metadatos (`duckdb_tables`, `duckdb_views`,
    `duckdb_constraints`)."""
    db, sc, nm = (quote_string_literal(part) for part in (database, schema, name))
    where = f"database_name = {db} AND schema_name = {sc}"
    return (
        "SELECT 'definition' AS kind, sql AS text, estimated_size AS value, NULL::VARCHAR[] AS columns"
        f" FROM duckdb_tables() WHERE {where} AND table_name = {nm}"
        " UNION ALL SELECT 'definition', sql, NULL, NULL"
        f" FROM duckdb_views() WHERE {where} AND view_name = {nm}"
        " UNION ALL SELECT 'key', constraint_type, NULL, constraint_column_names"
        f" FROM duckdb_constraints() WHERE {where} AND table_name = {nm}"
        " AND constraint_type IN ('PRIMARY KEY', 'UNIQUE')"
    )


def size_sql(database: str, schema: str, name: str) -> str:
    """Tamaño aproximado en disco de una tabla: los bloques que ocupa por el tamaño de bloque de su base. Una
    tabla en memoria, o aún no guardada en disco, da 0."""
    qualified = ".".join(quote_identifier(part) for part in (database, schema, name))
    return (
        "SELECT count(DISTINCT block_id) FILTER (WHERE persistent) * (SELECT any_value(block_size)"
        f" FROM pragma_database_size() WHERE database_name = {quote_string_literal(database)})"
        f" FROM pragma_storage_info({quote_string_literal(qualified)})"
    )


def page_label(offset: int, shown: int, total: int | None) -> str:
    """«Filas 1–100 de 48 312»; «Filas 1–100 de …» mientras se cuenta. El mismo texto en la pestaña de tabla
    y en el resultado de una consulta (propietario, 2026-11-06)."""
    if shown == 0:
        return tr("No rows")
    span = f"{offset + 1:,}–{offset + shown:,}".replace(",", " ")
    if total is None:
        return tr("Rows {} of …").format(span)
    return tr("Rows {} of {}").format(span, f"{total:,}".replace(",", " "))


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def geometry_summary(wkt: str, data_type: str) -> tuple[str, str, int]:
    """Tipo («POLYGON»), SRC (el del tipo de la columna, p. ej. `GEOMETRY('EPSG:4326')`; vacío si no tiene) y
    número de vértices de una geometría en WKT, para el detalle de fila."""
    head, _, body = wkt.partition("(")
    words = head.upper().split()
    kind = words[0] if words else "GEOMETRY"
    flags = "".join(w for w in words[1:] if w in ("Z", "M", "ZM"))
    vertices = len(_NUMBER.findall(body)) // (2 + len(flags))
    found = re.search(r"\((.*)\)\s*$", data_type.strip())
    crs = found.group(1).strip().strip("'\"") if found else ""
    return kind, crs, vertices
