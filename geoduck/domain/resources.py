# SPDX-License-Identifier: GPL-2.0-or-later
"""Memoria y disco de la sesión (#172, performance-spec §4, GD-PERF-003).

- **Carpeta temporal propia:** DuckDB usa disco cuando una consulta no cabe en memoria. Sin fijarla, una
  base en memoria escribe en `.tmp` dentro de la carpeta de trabajo de QGIS (a menudo de solo lectura en
  Windows) y la consulta falla «sin memoria» cuando podía seguir. La sesión de GeoDuck es suya (ADR-0011
  solo protege lo ajeno): una carpeta por sesión en la temporal del sistema, que se borra al cerrarla.
- **Tope de disco:** 20 GB o la mitad del espacio libre, lo menor (también el resultado guardado, #170).
- **Presupuesto de una Copia a QGIS:** la mitad de la memoria libre. Si no cabe, se avisa antes y se
  ofrece «Conectada» o «Exportar»; nunca se carga sin límite.
"""

from __future__ import annotations

import itertools
import os
import sys
import tempfile

from geoduck.domain.i18n import decimal

#: Tope de disco de los archivos temporales de DuckDB (propietario, 2026-11-12: 20 GB o el 50 % libre).
DISK_CAP = 20 * 1024**3
_SESSIONS = itertools.count(1)


def session_temp_dir(base: str | None = None) -> str:
    """Una carpeta nueva por sesión: `<temporal>/geoduck/duckdb-<proceso>-<n>` (dos QGIS o dos sesiones
    seguidas nunca comparten archivos)."""
    root = os.path.join(base or tempfile.gettempdir(), "geoduck")
    return os.path.join(root, f"duckdb-{os.getpid()}-{next(_SESSIONS)}")


def temp_limit(free_bytes: int) -> int:
    """El tope de disco: 20 GB o la mitad de lo libre, lo menor (al menos 1 GB: DuckDB nunca sin nada)."""
    return max(1024**3, min(DISK_CAP, free_bytes // 2))


def size_text(size: int) -> str:
    """«20 GB», «1,5 GB» o «640 MB», según el idioma."""
    gb = size / 1024**3
    if gb >= 1:
        return f"{decimal(gb) if gb < 10 else round(gb)} GB"
    return f"{max(1, round(size / 1024**2))} MB"


def available_memory() -> int | None:
    """La memoria que el sistema puede dar ahora (bytes), o None si no se sabe (sin presupuesto)."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="ascii") as info:
                for line in info:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
        elif sys.platform == "win32":
            return _windows_available()
        elif sys.platform == "darwin":
            return _mac_available()
    except (OSError, ValueError):
        return None
    return None


def copy_budget(available: int | None) -> int | None:
    """Cuánto puede ocupar una Copia a QGIS: la mitad de la memoria libre."""
    return None if available is None else available // 2


def _windows_available() -> int | None:
    import ctypes  # noqa: PLC0415 - solo en Windows

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        return None
    return int(status.ullAvailPhys)


def _mac_available() -> int | None:
    """Páginas libres de macOS (`sysctl vm.page_free_count`), sin lanzar procesos (ADR-0011). Es una cifra
    prudente: no cuenta la memoria inactiva que el sistema podría liberar."""
    import ctypes  # noqa: PLC0415 - solo en macOS

    libc = ctypes.CDLL(None)
    values = []
    for name in (b"vm.page_free_count", b"hw.pagesize"):
        value = ctypes.c_uint64(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        if libc.sysctlbyname(name, ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
            return None
        values.append(value.value)
    return int(values[0] * values[1]) or None
