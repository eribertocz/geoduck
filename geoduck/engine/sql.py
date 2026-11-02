# SPDX-License-Identifier: GPL-2.0-or-later
"""Ejecución de scripts SQL del usuario (G2; GD-SQL-001, 002, 004, 005; sql-editor-spec §2–§4).

Una sola operación del worker serial ejecuta el script entero, en orden, y se detiene en el primer error o
cancelación. Hechos verificados (`docs/evidence/g2/README.md`):

- Se divide con `extract_statements`; un error de sintaxis en cualquier sentencia impide ejecutar nada
  (F-34, F-38).
- El texto de cada sentencia es un tramo del script con límites distintos en 1.5 y 2.0, y `PRAGMA` se
  reescribe en 1.5 (F-35, F-36): los rangos se calculan buscando en orden y asignando los huecos.
- Se ejecuta el texto de cada sentencia, no el objeto `Statement`, porque así DuckDB indica la línea del
  error (F-39).
- Tras **cada** sentencia se comprueba el estado transaccional (decisión del 2026-11-01).
- La vista previa usa `fetchmany(límite + 1)`: nunca `fetchall()` (GD-SQL-005).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import duckdb

from geoduck.domain.errors import ErrorCode, InvalidArgumentError
from geoduck.domain.operations import StatementOutcome
from geoduck.domain.sql import (
    PREVIEW_LIMITS,
    OutputKind,
    Preview,
    RunScope,
    ScriptRun,
    SqlStatement,
    StatementResult,
    StatementStatus,
    error_offset_in,
    statement_at,
)
from geoduck.engine.compat import is_interrupt_error
from geoduck.engine.transactions import is_aborted_error, probe_transaction

if TYPE_CHECKING:
    from geoduck.engine.worker import CancelToken, ConnectionHandle

#: Recibe cada resultado en cuanto termina (en el hilo del worker).
StatementListener = Callable[[StatementResult], None]

_DML = frozenset({"INSERT", "UPDATE", "DELETE"})


def split_script(handle: ConnectionHandle, text: str, base: int = 0) -> tuple[SqlStatement, ...]:
    """Divide `text` con el parser de DuckDB. `base` es la posición de `text` dentro del editor."""
    parsed = handle.extract_statements(text)
    found: list[tuple[int, int] | None] = []
    cursor = 0
    for st in parsed:
        at = text.find(st.query, cursor)
        if at < 0:
            found.append(None)
        else:
            found.append((at, at + len(st.query)))
            cursor = at + len(st.query)
    statements = []
    for i, st in enumerate(parsed):
        span = found[i]
        if span is None:  # F-36: el hueco entre la sentencia anterior y la siguiente
            previous = found[i - 1] if i > 0 else None
            start = previous[1] if previous is not None else 0
            nxt = next((f for f in found[i + 1 :] if f is not None), None)
            span = (start, nxt[0] if nxt else len(text))
        statements.append(SqlStatement(i, _type_name(st.type), str(st.query), base + span[0], base + span[1]))
    return tuple(statements)


def run_script(
    handle: ConnectionHandle,
    token: CancelToken,
    *,
    run_id: int,
    text: str,
    scope: RunScope,
    cursor: int = 0,
    base: int = 0,
    preview_limit: int,
    on_statement: StatementListener | None = None,
) -> ScriptRun:
    """Ejecuta `text` según `scope`. Para `CURRENT`, `text` es el editor completo y `cursor` la posición;
    para `SELECTION`, `text` es la selección y `base` su posición en el editor."""
    if preview_limit not in PREVIEW_LIMITS:
        raise InvalidArgumentError(f"Límite de vista previa no admitido: {preview_limit}")
    try:
        statements = split_script(handle, text, base)
    except duckdb.ParserException as exc:
        offset = error_offset_in(text, str(exc))
        return ScriptRun(
            run_id,
            scope,
            (),
            parse_error=_first_line(exc),
            parse_error_offset=None if offset is None else base + offset,
        )
    if scope is RunScope.CURRENT:
        chosen = statement_at(statements, cursor)
        statements = (chosen,) if chosen is not None else ()
    results: list[StatementResult] = []
    stopped = False
    for st in statements:
        if stopped or token.cancelled:
            result = StatementResult(st, StatementStatus.SKIPPED)
        else:
            result = _execute_one(handle, st, preview_limit)
            stopped = result.status is not StatementStatus.OK
        results.append(result)
        if on_statement is not None:
            on_statement(result)
    return ScriptRun(run_id, scope, tuple(results))


def _execute_one(handle: ConnectionHandle, st: SqlStatement, limit: int) -> StatementResult:
    started = time.perf_counter()
    try:
        out = handle.execute(st.text, max_rows=limit)
    except duckdb.FatalException:
        raise  # invalida la sesión en el worker (C13 §4 bis)
    except duckdb.Error as exc:
        cancelled = is_interrupt_error(exc)
        offset = error_offset_in(st.text, str(exc))
        return StatementResult(
            st,
            StatementStatus.CANCELLED if cancelled else StatementStatus.FAILED,
            duration_ms=_ms(started),
            message="Ejecución cancelada" if cancelled else _first_line(exc),
            error_code=ErrorCode.CANCELLED
            if cancelled
            else ErrorCode.TRANSACTION_ABORTED
            if is_aborted_error(exc)
            else ErrorCode.ENGINE_ERROR,
            error_offset=None if offset is None else st.start + offset,
            transaction=probe_transaction(handle),
        )
    duration = _ms(started)
    transaction = probe_transaction(handle)
    output, message, preview = _describe(st, out, limit)
    return StatementResult(
        st, StatementStatus.OK, output, duration, message, preview, transaction=transaction
    )


def _describe(st: SqlStatement, out: StatementOutcome, limit: int) -> tuple[OutputKind, str, Preview | None]:
    columns, types, rows = out.columns, out.types, out.rows
    if not columns:
        return OutputKind.STATUS, "OK", None
    if not st.is_read and columns == ("Count",) and types == ("BIGINT",):
        # DDL/DML sin filas propias: DuckDB devuelve el número de filas afectadas.
        count = rows[0][0] if rows else None
        return OutputKind.STATUS, ("OK" if count is None else f"{count} filas afectadas"), None
    if not st.is_read and columns == ("Success",) and types == ("BOOLEAN",):
        # SET, ATTACH, DETACH, BEGIN, COMMIT, PRAGMA de configuración: columna «Success» sin filas.
        return OutputKind.STATUS, "OK", None
    preview = Preview(columns, types, rows, out.truncated, limit)
    if st.is_plan:
        return OutputKind.PLAN, "", preview
    if st.type in _DML:
        return OutputKind.MUTATION_ROWS, "Resultado de escritura: no se repite al cargar", preview
    return OutputKind.TABULAR, "", preview


def _type_name(value: Any) -> str:
    name = getattr(value, "name", None) or str(value)
    return str(name).rsplit(".", 1)[-1].replace("_STATEMENT", "")


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
