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
from geoduck.domain.filters import Condition, box_condition, is_numeric_type, where_condition
from geoduck.domain.i18n import N_, tr
from geoduck.domain.i18n import number as number_text
from geoduck.domain.sql_text import quote_identifier, quote_string_literal

#: Filas por página (sin selector).
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
    #: La casilla de filtro de cada columna (#144): `(columna, texto)`, solo las que tienen texto.
    boxes: tuple[tuple[str, str], ...] = ()
    #: Condiciones aparte: excluir valores de varias columnas a la vez (clic derecho).
    extra: tuple[Condition, ...] = ()
    #: La barra `WHERE` (SQL libre, ya validado por DuckDB).
    where: str = ""
    #: El resultado de una consulta en vez de una tabla (#144): su SQL, que se envuelve en una subconsulta.
    subquery: str = ""

    @property
    def source(self) -> str:
        if self.subquery:
            return f"({self.subquery}) AS geoduck_q"
        return ".".join(quote_identifier(part) for part in (self.database, self.schema, self.name))

    def box(self, column: str) -> str:
        """El texto de la casilla de `column` (vacío si no tiene)."""
        return dict(self.boxes).get(column, "")

    def with_box(self, column: str, text: str) -> Browse:
        """La casilla de `column` con `text` (vacío la quita). Mantiene el orden de las columnas."""
        boxes = dict(self.boxes)
        if text.strip():
            boxes[column] = text.strip()
        else:
            boxes.pop(column, None)
        order = [c.name for c in self.columns]
        ranked = sorted(boxes.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order))
        return replace(self, boxes=tuple(ranked))

    def with_extra(self, condition: Condition) -> Browse:
        return replace(self, extra=(*self.extra, condition))

    def without_extra(self, index: int) -> Browse:
        return replace(self, extra=self.extra[:index] + self.extra[index + 1 :])

    def with_where(self, text: str) -> Browse:
        return replace(self, where=text.strip())

    def cleared(self) -> Browse:
        """Sin ningún filtro (el orden se queda)."""
        return replace(self, filters=(), search="", boxes=(), extra=(), where="")

    @property
    def filtered(self) -> bool:
        return bool(self.filters or self.search or self.boxes or self.extra or self.where)

    def box_conditions(self) -> list[Condition]:
        """Las casillas como condiciones (una casilla que ya no se entiende no filtra: la interfaz no la
        deja entrar)."""
        columns = {c.name: c for c in self.columns}
        out = []
        for name, text in self.boxes:
            column = columns.get(name)
            if column is None:
                continue
            try:
                condition = box_condition(column, text)
            except ValueError:
                continue
            if condition is not None:
                out.append(condition)
        return out

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
        found += [c.sql for c in self.box_conditions()]
        found += [c.sql for c in self.extra]
        if self.where:
            where = where_condition(self.where)
            if where is not None:
                found.append(where.sql)
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

    @property
    def plain_table(self) -> bool:
        """Una tabla sin filtros ni orden: se puede leer por posición con `rowid` (performance-spec §9)."""
        return self.has_rowid and not self.subquery and not self.filtered and self.order is None

    def page_sql(self, offset: int, *, by_rowid: bool = False) -> str:
        """Un bloque de `PAGE` filas desde `offset`. Con `by_rowid` (una tabla sin filtros ni orden cuyos
        `rowid` van seguidos, sin huecos), por posición: no crece con la fila, a diferencia de `OFFSET`."""
        start = max(0, int(offset))
        if by_rowid and self.plain_table:
            return (
                f"SELECT {self._select_list(preview=True)} FROM {self.source}"
                f" WHERE rowid >= {start} AND rowid < {start + PAGE} ORDER BY rowid"
            )
        return (
            f"SELECT {self._select_list(preview=True)} FROM {self.source}{self._where()}{self._order_by()}"
            f" LIMIT {PAGE} OFFSET {start}"
        )

    def estimate_sql(self) -> str | None:
        """El total estimado al instante, de los metadatos de DuckDB (sin leer filas); None si no es una
        tabla sin filtros."""
        if not self.plain_table:
            return None
        return (
            "SELECT estimated_size FROM duckdb_tables() WHERE database_name = "
            f"{quote_string_literal(self.database)} AND schema_name = {quote_string_literal(self.schema)}"
            f" AND table_name = {quote_string_literal(self.name)}"
        )

    def last_rowid_sql(self) -> str:
        """El último `rowid`: si es el total menos uno, no hay huecos y se puede leer por posición."""
        return f"SELECT max(rowid) FROM {self.source}"

    def row_sql(self, index: int) -> str:
        """Una fila entera (geometrías completas) para el detalle."""
        return (
            f"SELECT {self._select_list(preview=False)} FROM {self.source}{self._where()}{self._order_by()}"
            f" LIMIT 1 OFFSET {max(0, int(index))}"
        )

    def count_sql(self) -> str:
        return f"SELECT count(*) FROM {self.source}{self._where()}"

    def total_sql(self) -> str:
        """El total sin filtros («1 234 de 1 000 000 filas»)."""
        return f"SELECT count(*) FROM {self.source}"

    def check_sql(self, condition: str) -> str:
        """Pregunta a DuckDB si una condición del usuario vale aquí, sin leer filas."""
        return f"SELECT 1 FROM {self.source} WHERE {condition} LIMIT 0"

    def values_sql(self, columns: tuple[str, ...], limit: int) -> str:
        """Ctrl+C de columnas enteras (#144, punto 9): las filas filtradas y ordenadas de esas columnas, como
        texto, hasta `limit` (lo lee DuckDB, no la pantalla)."""
        chosen = [c for c in self.columns if c.name in columns] or list(self.columns)
        names = ", ".join(f"CAST({quote_identifier(c.name)} AS VARCHAR)" for c in chosen)
        rest = f"{self._where()}{self._order_by()} LIMIT {max(0, int(limit))}"
        return f"SELECT {names} FROM {self.source}{rest}"

    def summary_sql(self, column: ColumnInfo) -> str:
        """Resumen de una columna (#144, punto 11), sobre todas las filas filtradas: suma, promedio, mínimo,
        máximo y nulos en una columna numérica; mínimo, máximo y nulos en las demás (la geometría, nulos)."""
        col = quote_identifier(column.name)
        nulls = f"count(*) FILTER (WHERE {col} IS NULL)"
        if column.is_geometry:
            parts = ["NULL", "NULL", "NULL", "NULL", nulls]
        elif is_numeric_type(column.data_type):
            parts = [f"sum({col})", f"avg({col})", f"min({col})", f"max({col})", nulls]
        else:
            parts = ["NULL", "NULL", f"CAST(min({col}) AS VARCHAR)", f"CAST(max({col}) AS VARCHAR)", nulls]
        return f"SELECT {', '.join(parts)} FROM {self.source}{self._where()}"

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


def page_label(offset: int, shown: int, total: int | None, *, estimate: int | None = None) -> str:
    """«Filas 1–100 de 48 312» según lo visible; «de ≈ 48 300» con el total estimado y «de …» mientras se
    cuenta. El mismo texto en la pestaña de tabla y en el resultado de una consulta (#170:
    desplazamiento continuo)."""
    if shown == 0:
        return tr("No rows")
    span = f"{number_text(offset + 1)}–{number_text(offset + shown)}"
    if total is None and estimate is not None:
        return tr("Rows {} of {}").format(span, "≈ " + number_text(estimate))
    if total is None:
        return tr("Rows {} of …").format(span)
    return tr("Rows {} of {}").format(span, number_text(total))


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


# -- icono de tipo en el encabezado (maqueta `tipo-columna`) ------------------------

#: Familias de tipo: el encabezado muestra solo el nombre con un icono de la familia; el tipo completo va
#: en la ayuda y en el detalle de la fila.
INTEGER, DECIMAL, TEXT, DATE, DATETIME, BOOLEAN, NESTED, BINARY, OTHER = (
    "integer", "decimal", "text", "date", "datetime", "boolean", "nested", "binary", "other",
)  # fmt: skip
#: Geometrías, por lo que hay en la página: puntos, líneas, polígonos o mixta (también sin filas).
POINT, LINE, POLYGON, MIXED = "point", "line", "polygon", "mixed"

_INTEGER_TYPE = re.compile(r"^U?(TINY|SMALL|BIG|HUGE)?INT(EGER)?\b|^(INT\d+|UINTEGER|UBIGINT|UHUGEINT)\b")
_DECIMAL_TYPE = re.compile(r"^(DOUBLE|FLOAT\d*|REAL|DECIMAL|NUMERIC)\b")
_TEXT_TYPE = re.compile(r"^(VARCHAR|CHAR|BPCHAR|TEXT|STRING|UUID|ENUM)\b")
_DATETIME_TYPE = re.compile(r"^(TIMESTAMP|DATETIME|TIME|INTERVAL)\b")
_NESTED_TYPE = re.compile(r"^(STRUCT|MAP|UNION|JSON|LIST|ARRAY)\b")
_BINARY_TYPE = re.compile(r"^(BLOB|BYTEA|BINARY|VARBINARY|BIT|BITSTRING)\b")
_GEOMETRY_FAMILY = {
    "POINT": POINT,
    "MULTIPOINT": POINT,
    "LINESTRING": LINE,
    "MULTILINESTRING": LINE,
    "POLYGON": POLYGON,
    "MULTIPOLYGON": POLYGON,
}


def type_family(data_type: str) -> str:  # noqa: PLR0911 - una familia por grupo de tipos
    """La familia de un tipo de DuckDB, para su icono: `INTEGER[]` o `STRUCT(…)` son `NESTED`."""
    kind = data_type.strip().upper()
    if kind.endswith("]") or _NESTED_TYPE.match(kind):
        return NESTED
    if _INTEGER_TYPE.match(kind):
        return INTEGER
    if _DECIMAL_TYPE.match(kind):
        return DECIMAL
    if _TEXT_TYPE.match(kind):
        return TEXT
    if _DATETIME_TYPE.match(kind):
        return DATETIME
    if kind.startswith("DATE"):
        return DATE
    if kind.startswith("BOOL"):
        return BOOLEAN
    if _BINARY_TYPE.match(kind):
        return BINARY
    return OTHER


def geometry_family(wkts: list[str | None]) -> str:
    """Puntos, líneas o polígonos si todas las geometrías de la página son de ese tipo (en WKT; los nulos no
    cuentan); si se mezclan o no hay ninguna, `MIXED`. DuckDB solo dice «GEOMETRY», sin el subtipo."""
    found = set()
    for wkt in wkts:
        if not wkt:
            continue
        head = wkt.lstrip().split("(", 1)[0].split()
        found.add(_GEOMETRY_FAMILY.get(head[0].upper(), MIXED) if head else MIXED)
        if len(found) > 1:
            return MIXED
    return found.pop() if found else MIXED
