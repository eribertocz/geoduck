# SPDX-License-Identifier: GPL-2.0-or-later
"""Comparación de versiones `X.Y.Z` sin dependencias externas (`packaging` no está garantizado en QGIS)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)(?:\.(\d+))?(.*)$")


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int = 0
    #: Sufijo de pre-release o build (`rc1`, `.dev12`); `at_least` lo trata como anterior al release.
    is_prerelease: bool = False

    @classmethod
    def parse(cls, text: str) -> Version:
        match = _VERSION_RE.match(text)
        if match is None:
            raise ValueError(f"Versión no reconocida: {text!r}")
        major, minor, patch, rest = match.groups()
        return cls(int(major), int(minor), int(patch or 0), bool(rest.strip()))

    def release(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def at_least(self, major: int, minor: int, patch: int = 0) -> bool:
        """Compara la versión de release; una pre-release de X.Y.Z no cumple `>= X.Y.Z`."""
        if self.release() == (major, minor, patch):
            return not self.is_prerelease
        return self.release() > (major, minor, patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def release_stage(version: str) -> str:
    """Etapa que se muestra junto a la versión del paquete, derivada de ella (PEP 440): `0.1.0a1` → «Alpha».

    Así la interfaz nunca contradice la versión real.
    """
    tail = version.lower().split("+", 1)[0]
    for marker, stage in (("rc", "RC"), ("b", "Beta"), ("a", "Alpha")):
        core, sep, rest = tail.partition(marker)
        if sep and rest[:1].isdigit() and core[-1:].isdigit():
            return stage
    return ""
