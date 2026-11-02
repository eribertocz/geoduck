# SPDX-License-Identifier: GPL-2.0-or-later
"""Sesiones a las que pueden hablar las capas Conectadas (qgis-bridge-spec §5).

El proveedor `geoduck` nunca abre conexiones: busca aquí el motor de su sesión por un identificador que
viaja en la URI de la capa. Si la sesión ya no existe (DETACH, cierre, proyecto reabierto sin ella), la
capa queda «no disponible»: vacía y sin errores.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

_lock = threading.Lock()
_engines: dict[str, Any] = {}


def register(engine: Any) -> str:
    """Identificador estable de `engine` (el mismo si ya estaba registrado)."""
    with _lock:
        for key, value in _engines.items():
            if value is engine:
                return key
        key = uuid.uuid4().hex
        _engines[key] = engine
        return key


def get(session_id: str) -> Any | None:
    with _lock:
        return _engines.get(session_id)


def forget(engine: Any) -> None:
    with _lock:
        for key in [k for k, v in _engines.items() if v is engine]:
            del _engines[key]


def clear() -> None:
    with _lock:
        _engines.clear()
