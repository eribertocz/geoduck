# SPDX-License-Identifier: GPL-2.0-or-later
"""Tokens del sistema de diseño de Workspace Pro (workspace-pro-spec §10; ADR-0016; spike E0b aprobado).

Un solo lugar para colores, tipografía, tamaños, espacios, radios y duraciones. Los estilos (`style`) y los
iconos (`icons`) se generan de aquí: cambiar un color es cambiar una línea.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Colors:
    """Colores de un tema. Contraste: `text` y `muted` ≥ 4,5:1 sobre `bg` y `side` (AA); `faint`, solo para
    información secundaria que se repite en otro sitio (tipos, cuentas), ≥ 3:1."""

    bg: str  # fondo del contenido
    side: str  # barra lateral y paneles
    head: str  # encabezados de grilla y pie
    border: str
    line: str  # separadores suaves
    text: str
    muted: str
    faint: str
    null: str  # NULL y marcadores de posición
    accent: str  # enlaces y foco
    accent_fill: str  # fondo del botón principal (con `on_accent` encima, ≥ 4,5:1)
    accent_hover: str
    accent_soft: str  # elemento elegido en listas
    selection: str  # texto seleccionado en el editor: se distingue bien (propietario, 2026-11-06)
    on_accent: str  # texto sobre `accent`
    row_selected: str
    chip_bg: str
    chip_border: str
    segment: str  # fondo del control segmentado
    ok: str
    warn: str
    error: str
    error_soft: str
    toast: str
    toast_text: str
    toast_link: str
    star: str


LIGHT = Colors(
    bg="#ffffff",
    side="#f6f7f9",
    head="#fbfbfc",
    border="#e4e6ea",
    line="#f0f1f4",
    text="#1d2026",
    muted="#5f6673",
    faint="#80868f",
    null="#a3a9b2",
    accent="#2f5fd0",
    accent_fill="#2f5fd0",
    accent_hover="#234aa6",
    accent_soft="#e7ecfa",
    selection="#bcd0fa",
    on_accent="#ffffff",
    row_selected="#eef2fd",
    chip_bg="#f3f6fe",
    chip_border="#c9d6f5",
    segment="#eef0f3",
    ok="#1a7f45",
    warn="#955b00",
    error="#c4320a",
    error_soft="#fdf0ec",
    toast="#1d2026",
    toast_text="#ffffff",
    toast_link="#a8c1ff",
    star="#d99a00",
)

DARK = Colors(
    bg="#16181d",
    side="#1b1e24",
    head="#1b1e24",
    border="#2a2e36",
    line="#23262d",
    text="#e6e8ec",
    muted="#a3aab5",
    faint="#7f8793",
    null="#6b727d",
    accent="#5b84e6",
    accent_fill="#3b67d6",
    accent_hover="#4c78e0",
    accent_soft="#22304f",
    selection="#33508f",
    on_accent="#ffffff",
    row_selected="#1f2a44",
    chip_bg="#1d2740",
    chip_border="#33466f",
    segment="#23262d",
    ok="#34c46e",
    warn="#e0a43a",
    error="#f07a5c",
    error_soft="#3a2019",
    toast="#e6e8ec",
    toast_text="#16181d",
    toast_link="#2f5fd0",
    star="#f0b429",
)

#: Familias preferidas, en orden: la del sistema en Windows, macOS y Linux. Se usa la primera instalada.
FONT_FAMILIES = ("Segoe UI", "SF Pro Text", "Inter", "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans")
MONO_FAMILIES = (
    "Cascadia Mono",
    "Consolas",
    "SF Mono",
    "JetBrains Mono",
    "Noto Sans Mono",
    "DejaVu Sans Mono",
)


@dataclass(frozen=True)
class Metrics:
    """Tamaños en píxeles."""

    font: int = 13
    font_small: int = 12
    font_tiny: int = 11
    font_title: int = 15
    space_xs: int = 4
    space_sm: int = 8
    space_md: int = 12
    space_lg: int = 16
    space_xl: int = 24
    radius: int = 7
    radius_sm: int = 5
    radius_lg: int = 10
    pill: int = 15
    control: int = 30  # alto de botones, campos y chips
    row: int = 32  # alto de fila de la grilla
    header: int = 34  # alto del encabezado de la grilla
    bar: int = 52  # alto de la barra de pestañas y de la cabecera lateral
    sidebar: int = 264
    detail: int = 300
    #: Duración de las transiciones (ms): breves y medidas (§10)
    motion: int = 150


METRICS = Metrics()


def contrast(fg: str, bg: str) -> float:
    """Relación de contraste WCAG 2.x entre dos colores `#rrggbb`."""

    def luminance(color: str) -> float:
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)
