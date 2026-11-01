# SPDX-License-Identifier: GPL-2.0-or-later
"""Seguimiento transaccional, COMMIT y ROLLBACK (G1 paso 6, GD-SES-005; ADR-0007 puntos 5 y 6).

Hechos verificados con DuckDB 1.5.0, 1.5.6 y 2.0.0 (`docs/evidence/g1/README.md`):

- No hay una función que diga si hay una transacción abierta, y un `BEGIN` dentro de otra **aborta la
  transacción del usuario** (F-30). No se puede usar para comprobar.
- `txid_current()` devuelve el mismo valor en dos sentencias seguidas solo dentro de una transacción
  explícita; en autocommit cada sentencia tiene el suyo (F-31). Dos lecturas seguidas, en la misma
  operación serial, distinguen el estado sin modificarlo. Con la transacción abortada, la lectura falla
  con «Current transaction is aborted».
- `COMMIT` de una transacción abortada responde OK y la revierte sin avisar (F-07). GeoDuck nunca lo envía:
  comprueba antes.
- Una interrupción dentro de una transacción la deja abortada en todas las versiones (F-32); un error de
  catálogo la aborta en 2.0 pero no en 1.5.x (F-33).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb

from geoduck.domain.errors import EngineError, ErrorCode, TransactionError
from geoduck.domain.transaction import TransactionState

if TYPE_CHECKING:
    from geoduck.engine.worker import ConnectionHandle

_TXID_SQL = "SELECT txid_current()"


def is_aborted_error(exc: BaseException) -> bool:
    return "current transaction is aborted" in str(exc).lower()


def probe_transaction(handle: ConnectionHandle) -> TransactionState:
    """Estado transaccional real, sin modificarlo. Errores distintos de «abortada» se propagan."""
    try:
        first = handle.execute(_TXID_SQL).rows
        second = handle.execute(_TXID_SQL).rows
    except duckdb.Error as exc:
        if is_aborted_error(exc):
            return TransactionState.ABORTED
        raise
    return TransactionState.ACTIVE if first == second else TransactionState.NONE


def commit(handle: ConnectionHandle) -> TransactionState:
    state = probe_transaction(handle)
    if state is TransactionState.ABORTED:
        raise TransactionError(
            "La transacción está abortada: COMMIT la revertiría sin avisar. Solo se puede revertir "
            "(ROLLBACK).",
            detail="commit_aborted",
        )
    if state is TransactionState.NONE:
        raise TransactionError(
            "No hay una transacción abierta.", code=ErrorCode.INVALID_ARGUMENT, detail="no_transaction"
        )
    _execute(handle, "COMMIT")
    return _expect_none(handle, "COMMIT")


def rollback(handle: ConnectionHandle) -> TransactionState:
    if probe_transaction(handle) is TransactionState.NONE:
        raise TransactionError(
            "No hay una transacción abierta.", code=ErrorCode.INVALID_ARGUMENT, detail="no_transaction"
        )
    _execute(handle, "ROLLBACK")
    return _expect_none(handle, "ROLLBACK")


def _expect_none(handle: ConnectionHandle, statement: str) -> TransactionState:
    state = probe_transaction(handle)
    if state is not TransactionState.NONE:
        raise EngineError(f"Tras {statement} la transacción sigue {state.value}")
    return state


def _execute(handle: ConnectionHandle, sql: str) -> None:
    handle.execute(sql)
