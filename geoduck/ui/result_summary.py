# SPDX-License-Identifier: GPL-2.0-or-later
"""Resumen del resultado de una celda (G7, GD-NB-004; ui-ux-spec §10).

«N filas · M columnas» y cada columna con su tipo, sacados de la vista previa que ya se mostró: **ninguna
consulta nueva**. Es la ayuda (ⓘ) del rótulo del resultado de cada celda, en la ventana y en el panel
(decisión del propietario, 2026-11-03: sin columna derecha).
"""

from __future__ import annotations

from geoduck.domain.i18n import tr
from geoduck.domain.sql import Preview


def rows_text(preview: Preview) -> str:
    """«3 filas», o «20+ filas» si había más (no se cuentan: sin `COUNT(*)` automático, §4)."""
    count = len(preview.rows)
    shown = f"{count}+" if preview.truncated else str(count)
    return (tr("{0} row") if shown == "1" else tr("{0} rows")).format(shown)


def summary_line(preview: Preview) -> str:
    columns = len(preview.columns)
    return " · ".join(
        (rows_text(preview), (tr("{0} column") if columns == 1 else tr("{0} columns")).format(columns))
    )


def summary_text(preview: Preview) -> str:
    """El resumen en texto, para la ayuda del rótulo del resultado."""
    lines = [summary_line(preview)]
    lines += [f"{name} · {kind}" for name, kind in zip(preview.columns, preview.types, strict=True)]
    return "\n".join(lines)
