# SPDX-License-Identifier: GPL-2.0-or-later
"""DetachDatabase: `DETACH` efectivo y liberación del bloqueo (G1 pasos 4 y 5, GD-SES-004, AT-SES-004).

Todo ocurre en una sola operación del worker serial (ADR-0006): ningún lector Arrow puede seguir abierto
cuando llega el `DETACH`, y ninguna otra sentencia se intercala entre las comprobaciones, el `DETACH` y la
verificación final.

Hechos verificados con DuckDB 1.5.0, 1.5.6 y 2.0.0 (evidencia: `docs/evidence/g1/README.md`):

- DuckDB no desadjunta la base predeterminada (F-25). Desde #168 la predeterminada es **la base activa**
  de GeoDuck y no se cierra (tampoco la última): hay que activar otra antes. Cualquier otra base se cierra,
  también la del inicio (`memory`).
- En 1.5.x, un `DETACH` con un lector Arrow abierto sobre esa base se acepta y el lector entrega 0 filas
  sin error (F-26). Lo impide el guardia de lector abierto de `ConnectionHandle` (`ACTIVE_RESULT`).
- `DETACH` hace checkpoint: tras él, el `.wal` desaparece y otro proceso puede abrir el archivo y ve los
  datos confirmados (F-27).
- Con una transacción abierta con cambios, 1.5.0 desadjunta igualmente y 1.5.6/2.0 lo rechazan y dejan la
  transacción abortada (F-28, F-29). Regla obligatoria (dictamen del 2026-11-01): **con cualquier
  transacción abierta, activa o abortada, el `DETACH` se bloquea en todas las versiones**, antes de
  enviarlo a DuckDB.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import duckdb

from geoduck.domain.catalog import DetachResult, catalog_key
from geoduck.domain.errors import DetachError, ErrorCode
from geoduck.domain.i18n import tr
from geoduck.domain.sql_text import quote_identifier
from geoduck.domain.transaction import TransactionState
from geoduck.engine.catalog import read_catalog
from geoduck.engine.transactions import is_aborted_error, probe_transaction

if TYPE_CHECKING:
    from geoduck.engine.worker import ConnectionHandle

_log = logging.getLogger("geoduck.engine")


def detach_database(handle: ConnectionHandle, alias: str, root: str) -> DetachResult:
    transaction = probe_transaction(handle)
    if transaction.is_open:
        raise DetachError(
            tr("There is an open transaction: commit (COMMIT) or roll back (ROLLBACK) before detaching.")
            if transaction is TransactionState.ACTIVE
            else tr("The transaction is aborted: roll it back (ROLLBACK) before detaching."),
            detail=f"open_transaction: {transaction.value}",
        )
    catalog = read_catalog(handle, root)
    target = catalog.get(alias)
    if target is None:
        raise DetachError(tr("There is no attached database «{0}».").format(alias), detail="not_attached")
    # #168 (propietario, 2026-11-13): cualquier base se cierra, también la del inicio, salvo la activa y la
    # última. Nunca se cambia la activa en silencio para poder cerrarla.
    if catalog_key(target.name) == catalog_key(catalog.default):
        raise DetachError(
            tr("«{0}» is the active database: make another database active first.").format(target.name),
            code=ErrorCode.DEFAULT_CATALOG,
            detail="active_catalog",
        )
    if len(catalog.databases) == 1:
        raise DetachError(
            tr("«{0}» is the only database of the session.").format(target.name),
            code=ErrorCode.DEFAULT_CATALOG,
            detail="last_catalog",
        )
    try:
        _execute_detach(handle, f"DETACH {quote_identifier(target.name)}")
    except duckdb.FatalException:
        raise  # invalida la sesión (C13 §4 bis); no se clasifica
    except duckdb.Error as exc:
        raise _classify(exc) from exc
    # si se cerró la base del inicio, la referencia pasa a la activa (que sigue adjunta)
    after = read_catalog(handle, catalog.default if catalog.is_root(target.name) else root)
    if after.get(target.name) is not None:
        raise DetachError(tr("The database is still open after closing it."), detail="still_attached")
    return DetachResult(target, after)


def _classify(exc: duckdb.Error) -> DetachError:
    text = str(exc).lower()
    if is_aborted_error(exc):
        return DetachError(
            tr("The transaction is aborted; it can only be rolled back (ROLLBACK)."),
            code=ErrorCode.TRANSACTION_ABORTED,
            detail=type(exc).__name__,
        )
    if "outstanding work" in text:
        return DetachError(
            tr(
                "There is an open transaction with changes in that database; commit "
                "or roll back before detaching."
            ),
            detail=f"{type(exc).__name__}: outstanding work",
        )
    if "open result" in text:
        return DetachError(
            tr("There is an open result in the session."),
            code=ErrorCode.ACTIVE_RESULT,
            detail=type(exc).__name__,
        )
    return DetachError(tr("The database could not be closed."), detail=type(exc).__name__)


def _execute(handle: ConnectionHandle, sql: str) -> None:
    handle.execute(sql)


def _execute_detach(handle: ConnectionHandle, sql: str) -> None:
    handle.execute(sql)
