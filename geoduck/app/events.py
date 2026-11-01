# SPDX-License-Identifier: GPL-2.0-or-later
"""Eventos que la capa de aplicación publica para la UI (siempre en el hilo principal)."""

from __future__ import annotations

from dataclasses import dataclass

from geoduck.domain.errors import ErrorCode
from geoduck.domain.operations import EngineInfo
from geoduck.domain.session import SessionState


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


AppEvent = SessionStateChanged | SessionStarted | SessionFailed
