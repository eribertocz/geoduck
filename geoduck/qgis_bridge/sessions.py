# SPDX-License-Identifier: GPL-2.0-or-later
"""Sesiones a las que pueden hablar las capas Conectadas (qgis-bridge-spec §5).

El proveedor `geoduck` nunca abre conexiones: busca aquí el motor de su sesión por un identificador que
viaja en la URI de la capa. Si la sesión ya no existe o su base no está abierta (o es otro archivo), la
capa queda «no disponible» en QGIS (#183).
"""

from __future__ import annotations

import contextlib
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any

_lock = threading.Lock()
_engines: dict[str, Any] = {}
#: La sesión de GeoDuck activa: la usan las capas de bases adjuntas desde un archivo, que sobreviven a la
#: sesión (y al proyecto) y vuelven a estar disponibles cuando la base se adjunta de nuevo (§5.5).
_current: Any = None
#: Bases abiertas en cada sesión: alias en minúsculas → ruta del archivo (None en memoria). Sin entrada, la
#: sesión todavía no informó su catálogo.
_bases: dict[int, dict[str, str | None]] = {}
#: Abre una base que una capa necesita mientras QGIS lee un proyecto (#183): (alias, archivo) → abierta.
_resolver: Callable[[str, str], bool] | None = None
_quiet = threading.local()


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
        _bases.pop(id(engine), None)


def set_databases(engine: Any, bases: dict[str, str | None]) -> None:
    """Las bases abiertas en `engine` (alias → ruta o None), para saber si una capa Conectada puede leer."""
    with _lock:
        _bases[id(engine)] = {alias.lower(): path for alias, path in bases.items()}


def set_resolver(resolver: Callable[[str, str], bool] | None) -> None:
    global _resolver  # noqa: PLW0603
    with _lock:
        _resolver = resolver


def resolve(alias: str, path: str) -> bool:
    """Pide abrir `path` como `alias` para una capa que se está creando; nunca al recargar una capa."""
    with _lock:
        resolver = _resolver
    if resolver is None or getattr(_quiet, "on", False):
        return False
    return resolver(alias, path)


@contextlib.contextmanager
def without_resolving() -> Iterator[None]:
    """Las capas que se recargan aquí no abren bases: quedan como corresponde a lo que está abierto."""
    previous = getattr(_quiet, "on", False)
    _quiet.on = True
    try:
        yield
    finally:
        _quiet.on = previous


def databases(engine: Any) -> dict[str, str | None] | None:
    """Las bases abiertas en `engine`, o None si todavía no se conocen."""
    with _lock:
        known = _bases.get(id(engine))
        return dict(known) if known is not None else None


def clear() -> None:
    global _current  # noqa: PLW0603
    with _lock:
        _engines.clear()
        _bases.clear()
        _current = None
