# SPDX-License-Identifier: GPL-2.0-or-later
"""Máquina de estados de la sesión (spec/specs/session-spec.md §5)."""

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


_S = SessionState

#: Transiciones permitidas. Cualquier otra es un error de programación.
TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    _S.DISCONNECTED: frozenset({_S.CONNECTING}),
    _S.CONNECTING: frozenset({_S.READY, _S.ERROR_RECOVERABLE, _S.CLOSING}),
    _S.READY: frozenset({_S.BUSY, _S.DETACHING, _S.CLOSING}),
    _S.BUSY: frozenset({_S.READY, _S.CLOSING, _S.ERROR_RECOVERABLE}),
    _S.DETACHING: frozenset({_S.READY, _S.ERROR_RECOVERABLE, _S.CLOSING}),
    _S.CLOSING: frozenset({_S.DISCONNECTED}),
    _S.ERROR_RECOVERABLE: frozenset({_S.CONNECTING, _S.READY, _S.CLOSING, _S.DISCONNECTED}),
}

Listener = Callable[[SessionState, SessionState], None]


class SessionStateMachine:
    """Estado observable de la sesión. No es thread-safe: vive en el hilo principal (capa app)."""

    def __init__(self, initial: SessionState = SessionState.DISCONNECTED) -> None:
        self._state = initial
        self._listeners: list[Listener] = []

    @property
    def state(self) -> SessionState:
        return self._state

    def can(self, target: SessionState) -> bool:
        return target in TRANSITIONS[self._state]

    def transition(self, target: SessionState) -> None:
        if not self.can(target):
            raise SessionStateError(f"Transición no permitida: {self._state.value} → {target.value}")
        previous, self._state = self._state, target
        for listener in list(self._listeners):
            listener(previous, target)

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe
