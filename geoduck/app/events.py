# SPDX-License-Identifier: GPL-2.0-or-later
"""Eventos que la capa de aplicación publica para la UI (siempre en el hilo principal)."""

from __future__ import annotations

from dataclasses import dataclass

from geoduck.domain.bridge_types import LoadPlan
from geoduck.domain.catalog import AttachedDatabase, CatalogSnapshot
from geoduck.domain.errors import ErrorCode
from geoduck.domain.load import LoadReport, LoadRequest
from geoduck.domain.operations import EngineInfo
from geoduck.domain.session import SessionState
from geoduck.domain.sql import ScriptRun, StatementResult
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


@dataclass(frozen=True)
class StatementFinished:
    """Una sentencia terminó (OK, FAILED, CANCELLED o SKIPPED). `epoch` sirve para saber si su vista
    previa quedó posiblemente obsoleta (`SessionCoordinator.is_stale`)."""

    run_id: int
    result: StatementResult
    epoch: int


@dataclass(frozen=True)
class ScriptFinished:
    run: ScriptRun


@dataclass(frozen=True)
class ScriptRejected:
    """El script no llegó a ejecutarse (petición inválida)."""

    code: ErrorCode
    message: str


@dataclass(frozen=True)
class PreviewsInvalidated:
    """Algo pudo cambiar estructura o datos: toda vista previa con época anterior a `epoch` es
    posiblemente obsoleta (decisión del 2026-11-01). No detecta cambios hechos fuera de la sesión."""

    epoch: int


@dataclass(frozen=True)
class LoadPrepared:
    """Plan de carga listo (geometrías, CRS declarado, avisos) para que la UI confirme."""

    token: int
    plan: LoadPlan


@dataclass(frozen=True)
class LoadPrepareFailed:
    token: int
    code: ErrorCode
    message: str


@dataclass(frozen=True)
class LoadStarted:
    load_id: int
    request: LoadRequest


@dataclass(frozen=True)
class LoadProgressed:
    load_id: int
    rows: int


@dataclass(frozen=True)
class LoadFinished:
    load_id: int
    report: LoadReport


@dataclass(frozen=True)
class LoadFailed:
    load_id: int
    code: ErrorCode
    message: str
    cancelled: bool


@dataclass(frozen=True)
class SpatialChecked:
    """Estado de `spatial` en la sesión, pedido por «Activar spatial…» (spatial-spec §10)."""

    installed: bool
    loaded: bool


@dataclass(frozen=True)
class SpatialActivated:
    """`spatial` cargada con consentimiento del usuario: versión y `geometry_always_xy` (sin modificar)."""

    version: str
    always_xy: str | None


@dataclass(frozen=True)
class SpatialActivationFailed:
    code: ErrorCode
    message: str


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
    | StatementFinished
    | ScriptFinished
    | ScriptRejected
    | PreviewsInvalidated
    | LoadPrepared
    | LoadPrepareFailed
    | LoadStarted
    | LoadProgressed
    | LoadFinished
    | LoadFailed
    | SpatialChecked
    | SpatialActivated
    | SpatialActivationFailed
)
