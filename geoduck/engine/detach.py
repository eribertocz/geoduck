# SPDX-License-Identifier: GPL-2.0-or-later
"""DetachDatabase: `DETACH` efectivo y liberación del bloqueo (G1 pasos 4 y 5, GD-SES-004, AT-SES-004).

Todo ocurre en una sola operación del worker serial (ADR-0006): ningún lector Arrow puede seguir abierto
cuando llega el `DETACH`, y ninguna otra sentencia se intercala entre las comprobaciones, el `USE`, el
`DETACH` y la verificación final.

Hechos verificados con DuckDB 1.5.0, 1.5.6 y 2.0.0 (evidencia: `docs/evidence/g1/README.md`):

- DuckDB no desadjunta la base predeterminada (F-25): si lo es, primero se hace `USE` del catálogo raíz
  real (no se supone que se llame `memory`). Si el `DETACH` falla después, se restaura la predeterminada
  anterior, para no dejar un cambio oculto.
- En 1.5.x, un `DETACH` con un lector Arrow abierto sobre esa base se acepta y el lector entrega 0 filas
  sin error (F-26). Lo impide el guardia de lector abierto de `ConnectionHandle` (`ACTIVE_RESULT`).
- `DETACH` hace checkpoint: tras él, el `.wal` desaparece y otro proceso puede abrir el archivo y ve los
  datos confirmados (F-27).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import duckdb

from geoduck.domain.catalog import DetachResult
from geoduck.domain.errors import DetachError, ErrorCode
from geoduck.domain.sql_text import quote_identifier
from geoduck.engine.catalog import read_catalog

if TYPE_CHECKING:
    from geoduck.engine.worker import ConnectionHandle

_log = logging.getLogger("geoduck.engine")


def detach_database(handle: ConnectionHandle, alias: str, root: str) -> DetachResult:
    catalog = read_catalog(handle, root)
    target = catalog.get(alias)
    if target is None:
        raise DetachError(f"No hay ninguna base «{alias}» adjunta.", detail="not_attached")
    if catalog.is_root(target.name):
        raise DetachError(
            "La base raíz de la sesión no se puede desadjuntar.",
            code=ErrorCode.DEFAULT_CATALOG,
            detail="root_catalog",
        )
    previous_default = catalog.default
    switched = catalog.default_database.key == target.key
    if switched:
        _execute(handle, f"USE {quote_identifier(catalog.root)}")
    try:
        _execute_detach(handle, f"DETACH {quote_identifier(target.name)}")
    except duckdb.FatalException:
        raise  # invalida la sesión (C13 §4 bis); no se clasifica
    except duckdb.Error as exc:
        if switched:
            _restore_default(handle, previous_default)
        raise _classify(exc) from exc
    after = read_catalog(handle, root)
    if after.get(target.name) is not None:
        raise DetachError("DuckDB informó éxito pero la base sigue adjunta.", detail="still_attached")
    return DetachResult(target, after)


def _classify(exc: duckdb.Error) -> DetachError:
    text = str(exc).lower()
    if "outstanding work" in text:
        return DetachError(
            "Hay una transacción abierta con cambios en esa base; confirme o revierta antes de desadjuntar.",
            detail=f"{type(exc).__name__}: outstanding work",
        )
    if "open result" in text:
        return DetachError(
            "Hay un resultado abierto en la sesión.", code=ErrorCode.ACTIVE_RESULT, detail=type(exc).__name__
        )
    return DetachError("DuckDB no pudo desadjuntar la base.", detail=type(exc).__name__)


def _restore_default(handle: ConnectionHandle, name: str) -> None:
    try:
        _execute(handle, f"USE {quote_identifier(name)}")
    except duckdb.FatalException:
        raise
    except duckdb.Error:
        _log.warning("No se pudo restaurar la base predeterminada tras un DETACH fallido", exc_info=True)


def _execute(handle: ConnectionHandle, sql: str) -> None:
    handle.execute(sql)


def _execute_detach(handle: ConnectionHandle, sql: str) -> None:
    handle.execute(sql)
