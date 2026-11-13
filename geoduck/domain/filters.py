# SPDX-License-Identifier: GPL-2.0-or-later
"""Filtros del resultado (#144, punto 36; workspace-pro-spec §4): de lo que escribe el usuario al SQL que
ejecuta DuckDB por páginas.

Sin Qt ni DuckDB. Tres formas, que se combinan con Y:

- **la casilla de cada columna** (fila de filtros bajo los encabezados), una por columna, con un chip:
  - texto: contiene (`norte`);
  - comparaciones: `>50`, `=Sur`, `10..50` (entre, incluidos);
  - vacíos: `vacío` / `no vacío` (también en inglés);
  - expresiones regulares: `/…/` o `/…/i` (`regexp_matches`);
  - SQL que empieza con un operador: `> 50 AND < 100`, `IN (1, 5)`, `LIKE 'a%'`, `BETWEEN 1 AND 9`,
    `IS NULL`, `NOT IN (…)`. Cada parte unida con AND u OR empieza con su operador y lleva la columna delante.
- **el clic derecho en las celdas** (`cell_filters`): filtrar o excluir esos valores, mayor o menor, vacíos;
  lo de una sola columna se escribe en su casilla (así la fila de filtros y los chips siempre coinciden);
  excluir valores de varias columnas a la vez es una condición aparte (`NOT (…)`).
- **la barra `WHERE`**: una condición SQL libre.

El SQL del usuario va tal cual (es su sesión), pero siempre **una sola condición**: sin `;`, sin comentarios
y con los paréntesis y comillas equilibrados, para que nunca cambie la página, el orden ni el total que
GeoDuck pide alrededor. DuckDB valida el resto (la interfaz lo pregunta antes de aplicarlo).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from geoduck.domain.catalog import ColumnInfo
from geoduck.domain.i18n import tr
from geoduck.domain.sql_text import quote_identifier, quote_string_literal

#: Palabras para «vacío» y «no vacío» (en los dos idiomas: la casilla acepta ambas).
EMPTY_WORDS = ("vacío", "vacio", "empty")
NOT_EMPTY_WORDS = ("no vacío", "no vacio", "not empty", "non empty")

_NUMBER = re.compile(r"^[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?$")
_REGEX = re.compile(r"^/(.*)/(i?)$", re.DOTALL)
_RANGE = re.compile(r"^(?P<low>[^.\s]\S*?)\s*\.\.\s*(?P<high>\S+)$")
#: Operadores con los que puede empezar una parte (el más largo primero).
_OPERATOR = re.compile(
    r"^(?P<op>>=|<=|<>|!=|==|=|>|<|"
    r"(?:NOT\s+)?(?:IN|LIKE|ILIKE|GLOB|BETWEEN|SIMILAR\s+TO)\b|"
    r"IS\s+(?:NOT\s+)?DISTINCT\s+FROM\b|IS\b)\s*(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_COMPARE = frozenset({"=", "==", "<>", "!=", ">", "<", ">=", "<="})
#: Palabras que no son un valor a citar después de `=` / `>`…
_KEYWORDS = frozenset({"NULL", "TRUE", "FALSE"})


class FilterError(ValueError):
    """La casilla o la barra `WHERE` no se pueden usar tal cual; `message` dice por qué (traducido)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Condition:
    """Una condición lista para el `WHERE`, con su texto para el chip. `column`: la columna de su casilla, o
    vacío (barra `WHERE`, exclusión de varias columnas)."""

    sql: str
    label: str
    column: str = ""


def is_number(text: str) -> bool:
    return bool(_NUMBER.match(text.strip()))


def _literal(text: str) -> str:
    """Un valor escrito por el usuario como literal SQL: números tal cual, lo demás entre comillas (DuckDB lo
    convierte al tipo de la columna: `kwh > '50'` compara números, `fecha > '2024-01-01'` fechas)."""
    value = text.strip()
    return value if is_number(value) else quote_string_literal(value)


def check_sql(text: str) -> str:
    """El SQL del usuario como una sola condición: sin `;`, sin comentarios y con paréntesis y comillas
    equilibrados (fuera de las comillas). Devuelve el texto sin espacios de los bordes."""
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:  # '' dentro de un texto
                    i += 2
                    continue
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == ";":
            raise FilterError(tr("Only one condition: without «;»"))
        elif text.startswith("--", i) or text.startswith("/*", i):
            raise FilterError(tr("Comments are not allowed in a filter"))
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise FilterError(tr("A «)» has no «(»"))
        i += 1
    if quote:
        raise FilterError(tr("A quote is not closed"))
    if depth:
        raise FilterError(tr("A «(» is not closed"))
    return text.strip()


def _split_top(text: str) -> list[tuple[str, str]]:
    """Partes unidas por AND u OR fuera de paréntesis y comillas: `[(unión, parte), …]` (la primera, con unión
    vacía). `BETWEEN a AND b` no se parte."""
    parts: list[tuple[str, str]] = []
    joiner, start, depth, quote, i = "", 0, 0, "", 0
    between = False
    upper = text.upper()
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            match = re.match(r"\s+(AND|OR)\s+", upper[i:]) if ch.isspace() else None
            if match:
                word = match.group(1)
                if word == "AND" and between:
                    between = False  # el AND de BETWEEN a AND b
                else:
                    parts.append((joiner, text[start:i].strip()))
                    joiner = word
                    start = i + match.end()
                    i = start
                    continue
            elif re.match(r"BETWEEN\b", upper[i:]) and (i == 0 or not upper[i - 1].isalnum()):
                between = True
        i += 1
    parts.append((joiner, text[start:].strip()))
    return parts


def _operator_part(column: str, part: str) -> tuple[str, str]:
    """`> 50` → (`"kwh" > 50`, `kwh > 50`). Un valor suelto tras una comparación (`=Sur`) se cita."""
    match = _OPERATOR.match(part)
    if match is None:
        raise FilterError(tr("Each part joined with AND or OR must start with an operator (=, >, IN, LIKE…)"))
    op = re.sub(r"\s+", " ", match.group("op").upper())
    rest = match.group("rest").strip()
    if op in _COMPARE:
        if not rest:
            raise FilterError(tr("A value is missing after «{}»").format(op))
        bare = not re.search(r"['\"()\s]", rest) and rest.upper() not in _KEYWORDS
        value = _literal(rest) if bare else rest
        op = "=" if op == "==" else op
        return f"{quote_identifier(column)} {op} {value}", f"{column} {op} {rest}"
    if not rest and op not in ("IS",):
        raise FilterError(tr("A value is missing after «{}»").format(op))
    return f"{quote_identifier(column)} {op} {rest}".rstrip(), f"{column} {op} {rest}".rstrip()


def box_condition(column: ColumnInfo, text: str) -> Condition | None:  # noqa: PLR0911 - una por forma
    """La casilla de filtro de `column` (fila de filtros bajo los encabezados). `None` si está vacía."""
    raw = text.strip()
    if not raw:
        return None
    name = column.name
    col = quote_identifier(name)
    textual = _is_text(column.data_type)
    lowered = raw.lower()
    if lowered in EMPTY_WORDS or lowered == tr("empty").lower():
        sql = f"({col} IS NULL OR CAST({col} AS VARCHAR) = '')" if textual else f"{col} IS NULL"
        return Condition(sql, tr("{}: empty").format(name), name)
    if lowered in NOT_EMPTY_WORDS or lowered == tr("not empty").lower():
        sql = f"({col} IS NOT NULL AND CAST({col} AS VARCHAR) <> '')" if textual else f"{col} IS NOT NULL"
        return Condition(sql, tr("{}: not empty").format(name), name)
    regex = _REGEX.match(raw)
    if regex:
        pattern, flags = regex.group(1), regex.group(2)
        if not pattern:
            raise FilterError(tr("The regular expression is empty"))
        options = ", 'i'" if flags else ""
        sql = f"regexp_matches(CAST({col} AS VARCHAR), {quote_string_literal(pattern)}{options})"
        return Condition(sql, f"{name} ~ {raw}", name)
    if _OPERATOR.match(raw):
        check_sql(raw)
        parts = []
        labels = []
        for joiner, part in _split_top(raw):
            sql, label = _operator_part(name, part)
            parts.append(f"{joiner} {sql}" if joiner else sql)
            labels.append(f"{joiner} {label}" if joiner else label)
        return Condition("(" + " ".join(parts) + ")", " ".join(labels), name)
    span = _RANGE.match(raw)
    if span:
        low, high = _literal(span.group("low")), _literal(span.group("high"))
        return Condition(f"{col} BETWEEN {low} AND {high}", f"{name} {raw}", name)
    value = quote_string_literal(raw)
    sql = f"contains(lower(CAST({col} AS VARCHAR)), lower({value}))"
    return Condition(sql, tr("{0} contains «{1}»").format(name, raw), name)


def where_condition(text: str) -> Condition | None:
    """La barra `WHERE`: una condición SQL libre (la valida DuckDB). `None` si está vacía."""
    raw = check_sql(text)
    if not raw:
        return None
    short = raw if len(raw) <= 40 else raw[:39] + "…"
    return Condition(f"({raw})", "SQL: " + short)


# -- clic derecho en celdas ----------------------------------------------------------------------------

FILTER, EXCLUDE, GREATER, LESS, ONLY_EMPTY, NO_EMPTY = "filter", "exclude", "gt", "lt", "empty", "not_empty"


def _value_text(value: object) -> str:
    """Un valor de una celda como literal para la casilla: números tal cual, el resto entre comillas."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    return quote_string_literal(str(value))


def comparable(column: ColumnInfo) -> bool:
    """Mayor y menor tienen sentido: números y fechas u horas."""
    kind = column.data_type.upper()
    return _is_number_type(kind) or any(word in kind for word in ("DATE", "TIME", "INTERVAL"))


def cell_filters(
    cells: Sequence[tuple[ColumnInfo, object]], action: str
) -> tuple[dict[str, str], Condition | None]:
    """El clic derecho en una o varias celdas (#144, punto 36). Devuelve el texto nuevo de la casilla de cada
    columna tocada y, al excluir valores de varias columnas a la vez, la condición aparte (`NOT (…)`).

    - filtrar: una columna con un valor `= v`; con varios, `IN (…)`; columnas distintas, cada una la suya (y);
    - excluir: `IS DISTINCT FROM v` o `IS NULL OR NOT IN (…)` (las filas vacías no se pierden); con varias
      columnas, `NOT (a = x AND b = y)`;
    - mayor o menor que el valor (una columna, números y fechas); solo vacíos; sin vacíos.
    """
    by_column: dict[str, tuple[ColumnInfo, list[object]]] = {}
    for column, value in cells:
        values = by_column.setdefault(column.name, (column, []))[1]
        if value not in values:
            values.append(value)
    if not by_column:
        return {}, None
    if action in (ONLY_EMPTY, NO_EMPTY):
        word = tr("empty") if action == ONLY_EMPTY else tr("not empty")
        return dict.fromkeys(by_column, word), None
    if action in (GREATER, LESS):
        if len(by_column) != 1:
            raise FilterError(tr("Greater or less: choose cells of one column"))
        _column, values = next(iter(by_column.values()))
        present = [v for v in values if v is not None]
        if not present:
            raise FilterError(tr("An empty cell has no value to compare"))
        edge = max(present) if action == GREATER else min(present)  # type: ignore[type-var]
        return {next(iter(by_column)): (">" if action == GREATER else "<") + " " + _value_text(edge)}, None
    if action == FILTER:
        return {name: _in_text(values) for name, (_c, values) in by_column.items()}, None
    if action == EXCLUDE and len(by_column) == 1:
        name, (_c, values) = next(iter(by_column.items()))
        return {name: _not_in_text(values)}, None
    if action == EXCLUDE:
        parts = []
        labels = []
        for column, values in by_column.values():
            condition = box_condition(column, _in_text(values))
            assert condition is not None
            parts.append(condition.sql)
            labels.append(condition.label)
        sql = "NOT coalesce(" + " AND ".join(parts) + ", false)"
        return {}, Condition(sql, tr("not ({})").format(tr(" and ").join(labels)))
    raise ValueError(f"acción desconocida: {action!r}")


def _in_text(values: list[object]) -> str:
    present = [v for v in values if v is not None]
    if not present:
        return tr("empty")
    text = (
        "= " + _value_text(present[0])
        if len(present) == 1
        else "IN (" + ", ".join(_value_text(v) for v in present) + ")"
    )
    return text + (" OR IS NULL" if len(present) < len(values) else "")


def _not_in_text(values: list[object]) -> str:
    present = [v for v in values if v is not None]
    if not present:
        return tr("not empty")
    if len(present) == 1:
        text = "IS DISTINCT FROM " + _value_text(present[0])
    else:
        text = "IS NULL OR NOT IN (" + ", ".join(_value_text(v) for v in present) + ")"
    return text if len(present) == len(values) else text.replace("IS NULL OR ", "") + " AND IS NOT NULL"


def preview(cells: Sequence[tuple[ColumnInfo, object]], action: str) -> str:
    """La condición exacta que el menú muestra antes de aplicarla («zona = 'Sur' y tipo = 'Comercial'»)."""
    try:
        boxes, extra = cell_filters(cells, action)
    except FilterError as exc:
        return exc.message
    if extra is not None:
        return extra.label
    columns = {column.name: column for column, _value in cells}
    labels = []
    for name, text in boxes.items():
        condition = box_condition(columns[name], text)
        if condition is not None:
            labels.append(condition.label)
    return tr(" and ").join(labels)


_TEXT_TYPE = re.compile(r"^(VARCHAR|TEXT|STRING|CHAR|BPCHAR|UUID|ENUM)", re.IGNORECASE)
_NUMBER_TYPE = re.compile(
    r"^(TINYINT|SMALLINT|INTEGER|INT|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT|UHUGEINT|"
    r"FLOAT|REAL|DOUBLE|DECIMAL|NUMERIC)",
    re.IGNORECASE,
)


def _is_text(data_type: str) -> bool:
    return bool(_TEXT_TYPE.match(data_type.strip()))


def _is_number_type(data_type: str) -> bool:
    return bool(_NUMBER_TYPE.match(data_type.strip()))


def is_numeric_type(data_type: str) -> bool:
    return _is_number_type(data_type)
