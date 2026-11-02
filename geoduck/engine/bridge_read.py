# SPDX-License-Identifier: GPL-2.0-or-later
"""Lectura de una consulta repetible para cargarla en QGIS (qgis-bridge-spec §2, ADR-0012).

Fuente común de las tres modalidades: describe la consulta, la normaliza según §7
(`geoduck.domain.bridge_types`) y la lee con `to_arrow_reader` por lotes. Se ejecuta dentro de una
operación del worker; los lotes salen por `on_batch` en el hilo del worker (contrapresión a cargo del
consumidor, p. ej. `BatchChannel`). Nunca se usa con DDL, DML ni `RETURNING`: eso lo garantiza quien
llama (sql-editor-spec §5).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from geoduck.domain.bridge_types import LoadPlan, build_load_plan, strip_terminator
from geoduck.domain.operations import ReadSummary

if TYPE_CHECKING:
    from geoduck.engine.worker import CancelToken, ConnectionHandle

#: Lote inicial (F-44: el tamaño de lote apenas cambia el total).
DEFAULT_BATCH = 8192
_MAX_COLUMNS = 100_000


@dataclass(frozen=True)
class LoadOutcome:
    plan: LoadPlan
    summary: ReadSummary


def describe_query(handle: ConnectionHandle, sql: str) -> list[tuple[str, str]]:
    """Columnas y tipos de una consulta sin ejecutarla (`DESCRIBE` solo la enlaza)."""
    body = strip_terminator(sql)
    out = handle.execute(f"DESCRIBE SELECT * FROM (\n{body}\n) AS __geoduck_q", max_rows=_MAX_COLUMNS)
    return [(str(r[0]), str(r[1])) for r in out.rows]


def prepare_load(handle: ConnectionHandle, sql: str, geometry: str | None = None) -> LoadPlan:
    return build_load_plan(sql, describe_query(handle, sql), geometry=geometry)


def load_query(
    handle: ConnectionHandle,
    token: CancelToken,
    sql: str,
    *,
    geometry: str | None,
    batch_size: int,
    on_plan: Callable[[LoadPlan], None],
    on_batch: Callable[[Any], None],
) -> LoadOutcome:
    """Describe, normaliza y lee por lotes. `on_plan` llega antes del primer lote, en este hilo."""
    plan = prepare_load(handle, sql, geometry)
    token.raise_if_cancelled()
    on_plan(plan)
    summary = handle.read_arrow(plan.sql, batch_size=batch_size, on_batch=on_batch, token=token)
    return LoadOutcome(plan, summary)
