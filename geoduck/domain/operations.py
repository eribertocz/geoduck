# SPDX-License-Identifier: GPL-2.0-or-later
"""Resultados de operaciones del motor, independientes de DuckDB."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReadOutcome(str, Enum):
    """Por qué terminó una lectura por lotes."""

    EXHAUSTED = "EXHAUSTED"  # el lector se agotó normalmente: única condición de lectura completa
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ReadSummary:
    """Resumen de una lectura Arrow. `completed` es True solo si el lector se agotó (ADR-0006 §5)."""

    rows: int
    batches: int
    outcome: ReadOutcome
    error: str = ""

    @property
    def completed(self) -> bool:
        return self.outcome is ReadOutcome.EXHAUSTED


@dataclass(frozen=True)
class StatementOutcome:
    """Resultado acotado de una sentencia: columnas y, como mucho, `max_rows` filas."""

    columns: tuple[str, ...] = ()
    rows: tuple[tuple[object, ...], ...] = field(default_factory=tuple)
    truncated: bool = False
    #: Tipo DuckDB de cada columna, como texto (p. ej. `INTEGER`).
    types: tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineInfo:
    """Datos del motor una vez iniciada la sesión."""

    duckdb_version: str
    database: str
    interrupt_enabled: bool
    #: Nombre del catálogo raíz tal como lo informa DuckDB al conectar (`current_database()`).
    #: No se asume que se llame `memory` (session-spec §2, DetachDatabase).
    root_catalog: str
