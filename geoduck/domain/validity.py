# SPDX-License-Identifier: GPL-2.0-or-later
"""Validez y reparación de geometrías (spatial-spec §9; decisión del propietario D2, 2026-11-02).

Estados distintos, contados por separado: `NULL`, vacía, ilegible (WKB/WKT de una columna marcada que no
se pudo leer), inválida (legible pero topológicamente inválida según GEOS) y válida. Módulo puro.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from geoduck.domain.i18n import tr

#: Motivos de GEOS que se muestran (los primeros); el resto se cuenta.
MAX_REASONS = 10


@dataclass(frozen=True)
class GeometryDiagnosis:
    layer_id: str
    layer_name: str
    examined: int = 0
    valid: int = 0
    invalid: int = 0
    empty: int = 0
    null: int = 0
    unreadable: int = 0
    invalid_fids: tuple[int, ...] = field(default=())
    unreadable_fids: tuple[int, ...] = field(default=())
    #: (FID, motivo de GEOS) de las primeras inválidas.
    reasons: tuple[tuple[int, str], ...] = field(default=())

    @property
    def selected(self) -> tuple[int, ...]:
        """Entidades que se seleccionan en la capa: inválidas e ilegibles."""
        return self.invalid_fids + self.unreadable_fids

    def lines(self) -> list[str]:
        out = [
            tr("Examined: {0}").format(self.examined),
            tr("Valid: {0}").format(self.valid),
            tr("Invalid: {0}").format(self.invalid),
            tr("Empty: {0}").format(self.empty),
            tr("No geometry (NULL): {0}").format(self.null),
            tr("Unreadable: {0}").format(self.unreadable),
        ]
        if self.reasons:
            out.append(tr("Reasons (first invalid ones):"))
            out.extend(tr("  · feature {0}: {1}").format(fid, reason) for fid, reason in self.reasons)
        return out


@dataclass(frozen=True)
class RepairReport:
    """Resultado de «Reparar en una copia…». La capa original y el origen no cambian."""

    source_name: str
    repaired: int = 0
    changed_type: int = 0
    changed_dimension: int = 0
    changed_parts: int = 0
    #: Entidades que no se pudieron reparar: quedan sin geometría en la copia.
    failed_fids: tuple[int, ...] = field(default=())
    layers: tuple[str, ...] = field(default=())
    warnings: tuple[str, ...] = field(default=())

    def message(self) -> str:
        names = ", ".join(f"«{n}»" for n in self.layers)
        parts = [
            tr("Repaired copy {0}: {1} geometries repaired").format(names, self.repaired),
            tr("{0} changed type").format(self.changed_type),
            tr("{0} changed dimension").format(self.changed_dimension),
            tr("{0} changed number of parts").format(self.changed_parts),
        ]
        text = "; ".join(parts) + tr(". The original layer does not change.")
        if self.failed_fids:
            ids = ", ".join(str(f) for f in self.failed_fids[:MAX_REASONS])
            more = "…" if len(self.failed_fids) > MAX_REASONS else ""
            text += tr(" {0} could not be repaired (left without geometry): {1}{2}.").format(
                len(self.failed_fids), ids, more
            )
        if self.warnings:
            text += " " + "; ".join(self.warnings) + "."
        return text
