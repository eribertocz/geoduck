# SPDX-License-Identifier: GPL-2.0-or-later
"""Eventos que la capa de aplicación publica para la UI (siempre en el hilo principal)."""

from __future__ import annotations

from dataclasses import dataclass

from geoduck.domain.catalog import AttachedDatabase, CatalogSnapshot
from geoduck.domain.errors import ErrorCode
from geoduck.domain.operations import EngineInfo
from geoduck.domain.session import SessionState
from geoduck.domain.transaction import TransactionState


@dataclass(frozen=True)
class SessionStateChanged:
    previous: SessionState
    current: SessionState


@dataclass(frozen=True)
class SessionStarted:
    info: EngineInfo


@dataclass(frozen=True)
class SessionFailed:
    code: ErrorCode
    message: str


@dataclass(frozen=True)
class SessionInvalidated:
    """La conexión dejó de ser utilizable (C13 §4 bis). Se emite una sola vez por sesión."""

    code: ErrorCode
    message: str
    detail: str


@dataclass(frozen=True)
class CatalogChanged:
    """Nueva instantánea del catálogo, o `None` cuando ya no hay sesión de la que leerlo."""

    catalog: CatalogSnapshot | None


@dataclass(frozen=True)
class CatalogUnavailable:
    """No se pudo leer el catálogo. La instantánea anterior se descarta: nunca se muestra una dudosa."""

    code: ErrorCode
    message: str


@dataclass(frozen=True)
class DatabaseAttached:
    database: AttachedDatabase


@dataclass(frozen=True)
class AttachFailed:
    """No se adjuntó la base. La sesión sigue utilizable con el catálogo que tenía."""

    code: ErrorCode
    message: str


@dataclass(frozen=True)
class DatabaseDetached:
    database: AttachedDatabase


@dataclass(frozen=True)
class DetachFailed:
    """No se desadjuntó la base: sigue adjunta y la sesión sigue utilizable."""

    code: ErrorCode
    message: str


@dataclass(frozen=True)
class TransactionStateChanged:
    """Estado transaccional comprobado en DuckDB; `None` cuando ya no hay sesión."""

    state: TransactionState | None


@dataclass(frozen=True)
class TransactionFailed:
    """COMMIT o ROLLBACK rechazado o fallido."""

    code: ErrorCode
    message: str


@dataclass(frozen=True)
class CloseConfirmationRequired:
    """Hay una transacción abierta: el usuario elige COMMIT, ROLLBACK o cancelar el cierre.

    `commit_allowed` es False si COMMIT no es válido (transacción abortada, o una operación en curso).
    """

    transaction: TransactionState
    commit_allowed: bool


AppEvent = (
    SessionStateChanged
    | SessionStarted
    | SessionFailed
    | SessionInvalidated
    | CatalogChanged
    | CatalogUnavailable
    | DatabaseAttached
    | AttachFailed
    | DatabaseDetached
    | DetachFailed
    | TransactionStateChanged
    | TransactionFailed
    | CloseConfirmationRequired
)
