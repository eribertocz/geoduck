# SPDX-License-Identifier: GPL-2.0-or-later
"""Eventos que la capa de aplicación publica para la UI (siempre en el hilo principal)."""

from __future__ import annotations

from dataclasses import dataclass

from geoduck.domain.bridge_types import LoadPlan
from geoduck.domain.catalog import AttachedDatabase, CatalogSnapshot, ColumnInfo
from geoduck.domain.errors import ErrorCode
from geoduck.domain.export import ExportReport, ExportRequest
from geoduck.domain.importing import ImportedTable, ImportReport, SendRequest
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
class ColumnsListed:
    """Columnas de `source = (base, esquema, objeto)` (GD-CAT-002), del catálogo que se muestra ahora."""

    source: tuple[str, str, str]
    columns: tuple[ColumnInfo, ...]


@dataclass(frozen=True)
class ColumnsUnavailable:
    """No se pudieron leer las columnas de `source` (p. ej. el objeto ya no existe)."""

    source: tuple[str, str, str]
    code: ErrorCode
    message: str


@dataclass(frozen=True)
class VocabularyChanged:
    """Llegó el vocabulario de DuckDB (palabras clave y funciones) del catálogo mostrado."""


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
class DatabaseSaved:
    """Una base en memoria se guardó como archivo y sigue abierta con el mismo alias (#183)."""

    database: AttachedDatabase


@dataclass(frozen=True)
class SaveDatabaseFailed:
    """No se guardó la base; sigue como estaba."""

    code: ErrorCode
    message: str


@dataclass(frozen=True)
class DetachFailed:
    """No se desadjuntó la base: sigue adjunta y la sesión sigue utilizable."""

    code: ErrorCode
    message: str


@dataclass(frozen=True)
class ActivationFailed:
    """No se cambió la base activa (#168): sigue la anterior y la sesión sigue utilizable."""

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
class ExportStarted:
    """«Exportar ▾» en curso (G7 · E3): la sesión queda ocupada hasta `ExportFinished` o `ExportFailed`."""

    export_id: int
    request: ExportRequest


@dataclass(frozen=True)
class ExportFinished:
    export_id: int
    report: ExportReport


@dataclass(frozen=True)
class ExportFailed:
    export_id: int
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


@dataclass(frozen=True)
class SendStarted:
    """«Enviar a DuckDB» en curso (G8): la sesión queda ocupada hasta `SendFinished` o `SendFailed`."""

    send_id: int
    request: SendRequest


@dataclass(frozen=True)
class SendProgressed:
    send_id: int
    #: Entidades leídas de QGIS (las capas que DuckDB copia por SQL no cuentan aquí).
    rows: int


@dataclass(frozen=True)
class SendFinished:
    send_id: int
    report: ImportReport


@dataclass(frozen=True)
class SendFailed:
    send_id: int
    code: ErrorCode
    message: str
    cancelled: bool


@dataclass(frozen=True)
class SendUndone:
    """«Deshacer»: las tablas nuevas del envío se borraron."""

    tables: tuple[ImportedTable, ...]


@dataclass(frozen=True)
class SendUndoFailed:
    code: ErrorCode
    message: str


AppEvent = (
    SessionStateChanged
    | SessionStarted
    | SessionFailed
    | SessionInvalidated
    | CatalogChanged
    | CatalogUnavailable
    | ColumnsListed
    | ColumnsUnavailable
    | VocabularyChanged
    | DatabaseAttached
    | AttachFailed
    | DatabaseDetached
    | DatabaseSaved
    | SaveDatabaseFailed
    | DetachFailed
    | ActivationFailed
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
    | ExportStarted
    | ExportFinished
    | ExportFailed
    | SpatialChecked
    | SpatialActivated
    | SpatialActivationFailed
    | SendStarted
    | SendProgressed
    | SendFinished
    | SendFailed
    | SendUndone
    | SendUndoFailed
)
