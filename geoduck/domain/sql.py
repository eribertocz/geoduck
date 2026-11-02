# SPDX-License-Identifier: GPL-2.0-or-later
"""Modelo de ejecución de SQL del usuario (G2; spec/specs/sql-editor-spec.md §2–§4, ADR-0004).

Puro: sin DuckDB. El motor divide el script con el parser oficial y devuelve estos registros.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from geoduck.domain.errors import ErrorCode
from geoduck.domain.transaction import TransactionState

#: Tamaños de vista previa permitidos (sql-editor-spec §4). 200 por defecto.
PREVIEW_LIMITS = (50, 200, 500, 1000)
DEFAULT_PREVIEW_LIMIT = 200

#: Tipos de sentencia de DuckDB que solo leen. Son las únicas que se pueden repetir para cargar el resultado
#: completo en QGIS (GD-SQL-006); todas las demás cambian, o pueden cambiar, estructura, datos o estado.
_READ_TYPES = frozenset({"SELECT"})
_PLAN_TYPES = frozenset({"EXPLAIN"})


class OutputKind(str, Enum):
    """sql-editor-spec §3."""

    STATUS = "STATUS"
    TABULAR = "TABULAR"
    MUTATION_ROWS = "MUTATION_ROWS"
    PLAN = "PLAN"


class StatementStatus(str, Enum):
    OK = "OK"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    #: No se ejecutó porque una sentencia anterior falló o se canceló (sql-editor-spec §2).
    SKIPPED = "SKIPPED"


class RunScope(str, Enum):
    """GD-SQL-004: qué se ejecuta."""

    CURRENT = "CURRENT"
    SELECTION = "SELECTION"
    ALL = "ALL"


@dataclass(frozen=True)
class SqlStatement:
    """Una sentencia tal como la delimita el parser de DuckDB, con su rango en el texto del editor."""

    index: int
    #: Tipo que da el parser de DuckDB (`SELECT`, `INSERT`, `CREATE`, `TRANSACTION`, …); nunca la primera
    #: palabra del texto (un `WITH` puede preceder a un `INSERT`).
    type: str
    text: str
    #: Desplazamientos en caracteres dentro del texto completo del editor: [start, end).
    start: int
    end: int

    @property
    def is_read(self) -> bool:
        return self.type in _READ_TYPES

    @property
    def is_plan(self) -> bool:
        return self.type in _PLAN_TYPES

    @property
    def replayable(self) -> bool:
        """GD-SQL-006: solo una lectura puede volver a ejecutarse para cargar su resultado completo. Nunca
        DDL, DML (con o sin `RETURNING`), `ATTACH`/`DETACH`, transacciones ni configuración."""
        return self.is_read

    @property
    def may_change_state(self) -> bool:
        """Decisión del 2026-11-01: toda sentencia que no sea una lectura o un plan puede cambiar estructura,
        datos o estado de la sesión (invalidación conservadora de vistas previas)."""
        return not (self.is_read or self.is_plan)


@dataclass(frozen=True)
class Preview:
    """Vista previa acotada: nunca el resultado completo (sql-editor-spec §4)."""

    columns: tuple[str, ...]
    types: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    #: Había más filas que el límite; no se cuentan (no hay `COUNT(*)` automático).
    truncated: bool
    limit: int


@dataclass(frozen=True)
class StatementResult:
    statement: SqlStatement
    status: StatementStatus
    output: OutputKind | None = None
    duration_ms: float = 0.0
    message: str = ""
    preview: Preview | None = None
    error_code: ErrorCode | None = None
    #: Posición del error en el texto del editor (caracteres), si DuckDB la da (F-39).
    error_offset: int | None = None
    #: Estado transaccional comprobado después de la sentencia (decisión del 2026-11-01).
    transaction: TransactionState | None = None


@dataclass(frozen=True)
class ScriptRun:
    run_id: int
    scope: RunScope
    results: tuple[StatementResult, ...]
    #: Error de sintaxis que impidió ejecutar nada (F-38).
    parse_error: str = ""
    parse_error_offset: int | None = None

    @property
    def failed(self) -> bool:
        return bool(self.parse_error) or any(
            r.status in (StatementStatus.FAILED, StatementStatus.CANCELLED) for r in self.results
        )

    @property
    def last_transaction(self) -> TransactionState | None:
        known = [r.transaction for r in self.results if r.transaction is not None]
        return known[-1] if known else None


def statement_at(statements: tuple[SqlStatement, ...], offset: int) -> SqlStatement | None:
    """Sentencia «actual» para el cursor: la que lo contiene; si está entre dos, la anterior."""
    chosen = None
    for st in statements:
        if st.start <= offset:
            chosen = st
        if st.start <= offset < st.end:
            return st
    return chosen or (statements[0] if statements else None)


_LINE = re.compile(r"^LINE (\d+): (.*)$")


def error_offset_in(text: str, message: str) -> int | None:
    """Desplazamiento en `text` que DuckDB señala con `LINE n:` y `^` (F-39), o `None` si no se puede
    determinar con seguridad (por ejemplo, si DuckDB recortó la línea con «...»)."""
    lines = message.splitlines()
    for i, line in enumerate(lines[:-1]):
        m = _LINE.match(line)
        if not m:
            continue
        caret = lines[i + 1]
        column = caret.find("^") - (len(line) - len(m.group(2)))
        snippet = m.group(2)
        if column < 0 or snippet.startswith("..."):
            return None
        text_lines = text.split("\n")
        number = int(m.group(1)) - 1
        if number >= len(text_lines) or not text_lines[number].startswith(snippet.rstrip(".")[:column]):
            return None
        return sum(len(t) + 1 for t in text_lines[:number]) + column
    return None
