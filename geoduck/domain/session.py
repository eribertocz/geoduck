# SPDX-License-Identifier: GPL-2.0-or-later
"""Máquina de estados de la sesión (spec/specs/session-spec.md §5; C13).

`TRANSITIONS` es la tabla normativa de `session-spec` §5 (un test de arquitectura la compara con la
especificación). Además, la entrada y la salida de `ERROR_RECOVERABLE` dependen de la causa del fallo:

- `READY → ERROR_RECOVERABLE` solo por invalidación de la sesión;
- `ERROR_RECOVERABLE → READY` solo si la conexión y la transacción siguen utilizables, es decir, si la
  causa fue el fallo de una operación (nunca tras una invalidación ni tras un arranque fallido).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from geoduck.domain.errors import SessionStateError


class SessionState(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    READY = "READY"
    BUSY = "BUSY"
    DETACHING = "DETACHING"
    CLOSING = "CLOSING"
    ERROR_RECOVERABLE = "ERROR_RECOVERABLE"


class ErrorCause(str, Enum):
    """Por qué la sesión está en `ERROR_RECOVERABLE`."""

    #: Falló una operación; la conexión responde y su estado transaccional es utilizable.
    OPERATION_FAILED = "OPERATION_FAILED"
    #: El arranque falló; no hay conexión.
    START_FAILED = "START_FAILED"
    #: La conexión dejó de ser utilizable (`SESSION_INVALIDATED`); no se reutiliza.
    SESSION_INVALIDATED = "SESSION_INVALIDATED"


_S = SessionState

#: Transiciones permitidas. Cualquier otra es un error de programación.
TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    _S.DISCONNECTED: frozenset({_S.CONNECTING}),
    _S.CONNECTING: frozenset({_S.READY, _S.ERROR_RECOVERABLE, _S.CLOSING}),
    _S.READY: frozenset({_S.BUSY, _S.DETACHING, _S.CLOSING, _S.ERROR_RECOVERABLE}),
    _S.BUSY: frozenset({_S.READY, _S.CLOSING, _S.ERROR_RECOVERABLE}),
    _S.DETACHING: frozenset({_S.READY, _S.ERROR_RECOVERABLE, _S.CLOSING}),
    _S.CLOSING: frozenset({_S.DISCONNECTED}),
    _S.ERROR_RECOVERABLE: frozenset({_S.CONNECTING, _S.READY, _S.CLOSING, _S.DISCONNECTED}),
}

Listener = Callable[[SessionState, SessionState], None]


class SessionStateMachine:
    """Estado observable de la sesión. No es thread-safe: vive en el hilo principal (capa app)."""

    def __init__(self, initial: SessionState = SessionState.DISCONNECTED) -> None:
        if initial is SessionState.ERROR_RECOVERABLE:
            raise SessionStateError("ERROR_RECOVERABLE requiere una causa; use transition()")
        self._state: SessionState = initial
        self._cause: ErrorCause | None = None
        self._listeners: list[Listener] = []

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def error_cause(self) -> ErrorCause | None:
        """Causa del fallo mientras el estado es `ERROR_RECOVERABLE`; `None` en otro caso."""
        return self._cause

    def can(self, target: SessionState, cause: ErrorCause | None = None) -> bool:
        return self._reject_reason(target, cause) is None

    def transition(self, target: SessionState, cause: ErrorCause | None = None) -> None:
        reason = self._reject_reason(target, cause)
        if reason is not None:
            raise SessionStateError(
                f"Transición no permitida: {self._state.value} → {target.value} ({reason})"
            )
        previous, self._state = self._state, target
        self._cause = cause if target is SessionState.ERROR_RECOVERABLE else None
        for listener in list(self._listeners):
            listener(previous, target)

    def _reject_reason(self, target: SessionState, cause: ErrorCause | None) -> str | None:
        if target not in TRANSITIONS[self._state]:
            return "no figura en la tabla de session-spec §5"
        if target is SessionState.ERROR_RECOVERABLE:
            return self._entry_rejection(cause)
        if cause is not None:
            return "la causa solo acompaña a ERROR_RECOVERABLE"
        if (
            self._state is SessionState.ERROR_RECOVERABLE
            and target is SessionState.READY
            and self._cause is not ErrorCause.OPERATION_FAILED
        ):
            return "la conexión no es utilizable; se requiere una sesión nueva"
        return None

    def _entry_rejection(self, cause: ErrorCause | None) -> str | None:
        if cause is None:
            return "falta la causa del fallo"
        if self._state is SessionState.READY and cause is not ErrorCause.SESSION_INVALIDATED:
            return "desde READY solo por invalidación"
        return None

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe
