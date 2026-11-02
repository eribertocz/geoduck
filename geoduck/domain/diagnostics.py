# SPDX-License-Identifier: GPL-2.0-or-later
"""Modelo del informe de diagnóstico del entorno (GD-BOOT-002)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CheckStatus(str, Enum):
    OK = "OK"
    INFO = "INFO"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Check:
    """Una comprobación. `action` dice qué hacer cuando no es OK; nunca queda vacía en FAIL."""

    id: str
    title: str
    status: CheckStatus
    detail: str
    action: str = ""

    def __post_init__(self) -> None:
        if self.status is CheckStatus.FAIL and not self.action:
            raise ValueError(f"La comprobación {self.id} falla sin acción recomendada")


@dataclass(frozen=True)
class SpatialProbe:
    """Estado de la extensión `spatial` sin instalar nada (security.md §2)."""

    installed: bool
    loaded: bool
    load_error: str = ""
    extension_directory: str = ""
    allow_unsigned_extensions: bool = False
    version: str = ""
    #: Valor de `geometry_always_xy` con `spatial` cargada: «true», «false», «sin fijar»; "" si no se leyó.
    always_xy: str = ""


@dataclass(frozen=True)
class DiagnosticReport:
    checks: tuple[Check, ...]
    facts: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True si ninguna comprobación bloquea el uso de GeoDuck."""
        return all(c.status is not CheckStatus.FAIL for c in self.checks)

    def by_id(self, check_id: str) -> Check:
        for check in self.checks:
            if check.id == check_id:
                return check
        raise KeyError(check_id)

    def to_text(self) -> str:
        lines = ["Diagnóstico de GeoDuck", ""]
        lines += [f"{k}: {v}" for k, v in self.facts.items()]
        lines.append("")
        for c in self.checks:
            lines.append(f"[{c.status.value}] {c.title}: {c.detail}")
            if c.action and c.status is not CheckStatus.OK:
                lines.append(f"       → {c.action}")
        lines.append("")
        lines.append("Resultado: " + ("utilizable" if self.ok else "NO utilizable"))
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "facts": dict(self.facts),
            "checks": [
                {
                    "id": c.id,
                    "title": c.title,
                    "status": c.status.value,
                    "detail": c.detail,
                    "action": c.action,
                }
                for c in self.checks
            ],
        }
