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
#: La sesión de GeoDuck activa: la usan las capas de bases adjuntas desde un archivo, que sobreviven a la
#: sesión (y al proyecto) y vuelven a estar disponibles cuando la base se adjunta de nuevo (§5.5).
_current: Any = None


def set_current(engine: Any) -> None:
    global _current  # noqa: PLW0603 - un único registro por proceso, como el de proveedores de QGIS
    with _lock:
        _current = engine


def current() -> Any | None:
    with _lock:
        return _current


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
    global _current  # noqa: PLW0603
    with _lock:
        _engines.clear()
        _current = None
