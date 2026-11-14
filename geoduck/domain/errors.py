# SPDX-License-Identifier: GPL-2.0-or-later
"""Errores tipados de GeoDuck.

Los códigos `DB_*`, `ACTIVE_RESULT`, `DEFAULT_CATALOG`, `TRANSACTION_ABORTED` y `DETACH_FAILED` provienen
de `spec/specs/session-spec.md` §5. El resto son códigos operativos del implementador.
"""

from __future__ import annotations

from enum import Enum

from geoduck.domain.transaction import TransactionState


class ErrorCode(str, Enum):
    """Códigos estables y distinguibles que la UI traduce a mensajes accionables."""

    # session-spec §5
    DB_NOT_FOUND = "DB_NOT_FOUND"
    DB_LOCKED = "DB_LOCKED"
    DB_ALIAS_CONFLICT = "DB_ALIAS_CONFLICT"
    DB_READ_ONLY = "DB_READ_ONLY"
    ACTIVE_RESULT = "ACTIVE_RESULT"
    DEFAULT_CATALOG = "DEFAULT_CATALOG"
    TRANSACTION_ABORTED = "TRANSACTION_ABORTED"
    DETACH_FAILED = "DETACH_FAILED"
    # Operativos
    WRONG_THREAD = "WRONG_THREAD"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    SESSION_NOT_READY = "SESSION_NOT_READY"
    SESSION_CLOSED = "SESSION_CLOSED"
    #: session-spec §5 / C13 §4 bis: la conexión dejó de ser utilizable.
    SESSION_INVALIDATED = "SESSION_INVALIDATED"
    CANCELLED = "CANCELLED"
    UNSUPPORTED_ENGINE = "UNSUPPORTED_ENGINE"
    ENGINE_ERROR = "ENGINE_ERROR"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    #: qgis-import-spec §5.4: el filtro de la capa leído por DuckDB no da las filas que muestra QGIS.
    FILTER_MISMATCH = "FILTER_MISMATCH"
    #: #172 (performance-spec §4): una Copia a QGIS no cabe en el presupuesto de memoria.
    MEMORY_BUDGET = "MEMORY_BUDGET"


class GeoDuckError(Exception):
    """Error base con código estable. `detail` es técnico y nunca contiene datos del usuario."""

    code: ErrorCode = ErrorCode.ENGINE_ERROR

    def __init__(self, message: str, *, code: ErrorCode | None = None, detail: str = "") -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.detail = detail
        #: Estado transaccional comprobado por el worker tras el fallo (ADR-0007 punto 6); `None` si no
        #: llegó a comprobarse.
        self.transaction: TransactionState | None = None

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"


class ActiveResultError(GeoDuckError):
    """Se intentó usar la conexión mientras un lector Arrow propio sigue abierto (ADR-0006)."""

    code = ErrorCode.ACTIVE_RESULT


class WrongThreadError(GeoDuckError):
    """Se intentó usar la conexión fuera de su hilo propietario (ADR-0006)."""

    code = ErrorCode.WRONG_THREAD


class SessionStateError(GeoDuckError):
    """Transición de estado de sesión no permitida."""

    code = ErrorCode.INVALID_TRANSITION


class SessionClosedError(GeoDuckError):
    """La sesión está cerrada o cerrándose y no admite operaciones nuevas."""

    code = ErrorCode.SESSION_CLOSED


class InvalidArgumentError(GeoDuckError):
    """La petición es inválida antes de llegar al motor."""

    code = ErrorCode.INVALID_ARGUMENT


class AttachError(GeoDuckError):
    """No se pudo adjuntar una base. El código indica la causa (`DB_NOT_FOUND`, `DB_LOCKED`, …)."""


class TransactionError(GeoDuckError):
    """COMMIT o ROLLBACK rechazado. `TRANSACTION_ABORTED` si la transacción está abortada."""

    code = ErrorCode.TRANSACTION_ABORTED


class DetachError(GeoDuckError):
    """No se desadjuntó la base: sigue adjunta (session-spec §2, `DETACH_FAILED` por defecto)."""

    code = ErrorCode.DETACH_FAILED


class SessionInvalidatedError(SessionClosedError):
    """La conexión dejó de ser utilizable y la sesión se invalidó (C13 §4 bis, ADR-0007 §3).

    Es un `SessionClosedError`: ninguna operación posterior llega a DuckDB. La conexión no se reutiliza;
    salir del fallo exige una sesión nueva.
    """

    code = ErrorCode.SESSION_INVALIDATED

    def fresh(self) -> SessionInvalidatedError:
        """Copia sin traza, para entregar la misma causa a varias operaciones."""
        return SessionInvalidatedError(self.message, detail=self.detail)


class OperationCancelledError(GeoDuckError):
    """La operación se canceló; su resultado nunca debe tratarse como completo."""

    code = ErrorCode.CANCELLED


class MemoryBudgetError(GeoDuckError):
    """Una Copia a QGIS no cabe en la memoria libre (#172): se detuvo antes de llenarla. `estimate` y
    `available` en bytes, para el aviso con «Cargar como Conectada» o «Exportar»."""

    code = ErrorCode.MEMORY_BUDGET

    def __init__(self, message: str, *, estimate: int, available: int) -> None:
        super().__init__(message)
        self.estimate = estimate
        self.available = available


class UnsupportedEngineError(GeoDuckError):
    """La versión de DuckDB disponible está fuera del rango soportado."""

    code = ErrorCode.UNSUPPORTED_ENGINE


class EngineError(GeoDuckError):
    """Error devuelto por DuckDB al ejecutar una operación."""

    code = ErrorCode.ENGINE_ERROR
