# SPDX-License-Identifier: GPL-2.0-or-later
"""Errores tipados de GeoDuck.

Los códigos `DB_*`, `ACTIVE_RESULT`, `DEFAULT_CATALOG`, `TRANSACTION_ABORTED` y `DETACH_FAILED` provienen
de `spec/specs/session-spec.md` §5. El resto son códigos operativos del implementador.
"""

from __future__ import annotations

from enum import Enum


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
    CANCELLED = "CANCELLED"
    UNSUPPORTED_ENGINE = "UNSUPPORTED_ENGINE"
    ENGINE_ERROR = "ENGINE_ERROR"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"


class GeoDuckError(Exception):
    """Error base con código estable. `detail` es técnico y nunca contiene datos del usuario."""

    code: ErrorCode = ErrorCode.ENGINE_ERROR

    def __init__(self, message: str, *, code: ErrorCode | None = None, detail: str = "") -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        self.message = message
        self.detail = detail

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


class OperationCancelledError(GeoDuckError):
    """La operación se canceló; su resultado nunca debe tratarse como completo."""

    code = ErrorCode.CANCELLED


class UnsupportedEngineError(GeoDuckError):
    """La versión de DuckDB disponible está fuera del rango soportado."""

    code = ErrorCode.UNSUPPORTED_ENGINE


class EngineError(GeoDuckError):
    """Error devuelto por DuckDB al ejecutar una operación."""

    code = ErrorCode.ENGINE_ERROR
