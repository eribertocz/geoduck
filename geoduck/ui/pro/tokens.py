# SPDX-License-Identifier: GPL-2.0-or-later
"""Tokens del sistema de diseño de Workspace Pro (workspace-pro-spec §10; ADR-0016; spike E0b aprobado).

Un solo lugar para colores, tipografía, tamaños, espacios, radios y duraciones. Los estilos (`style`) y los
iconos (`icons`) se generan de aquí: cambiar un color es cambiar una línea.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

#: Marca de GeoDuck (#142): turquesa lago; en oscuro, uno más claro; el hondo para texto y el ojo del pato.
#: El turquesa solo marca lo de GeoDuck: logo, ▶, pestaña activa y selección. Lo neutro sale de QGIS.
BRAND = "#0e8a87"
BRAND_DARK = "#3fc1bc"
BRAND_DEEP = "#0a5e5c"
#: El pico del pato: ámbar, también el punto de «sin guardar».
BEAK = "#f2a33a"


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
    selection: str  # texto seleccionado en el editor: se distingue bien
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
    dark: bool = False  # tema oscuro de QGIS (el editor y los iconos lo siguen)


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
    accent="#0b7c79",
    accent_fill="#0b7c79",
    accent_hover="#0a5e5c",
    accent_soft="#e3f3f2",
    selection="#b5e2df",
    on_accent="#ffffff",
    row_selected="#ecf7f6",
    chip_bg="#f0f8f8",
    chip_border="#bfe0de",
    segment="#eef0f3",
    ok="#1a7f45",
    warn="#955b00",
    error="#c4320a",
    error_soft="#fdf0ec",
    toast="#1d2026",
    toast_text="#ffffff",
    toast_link="#7fdad5",
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
    accent="#3fc1bc",
    accent_fill="#127c78",
    accent_hover="#16918c",
    accent_soft="#183a3a",
    selection="#1f5856",
    on_accent="#ffffff",
    row_selected="#173030",
    chip_bg="#172e2e",
    chip_border="#265a58",
    segment="#23262d",
    ok="#34c46e",
    warn="#e0a43a",
    error="#f07a5c",
    error_soft="#3a2019",
    toast="#e6e8ec",
    toast_text="#16181d",
    toast_link="#0a5e5c",
    star="#f0b429",
    dark=True,
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


def mix(fg: str, bg: str, amount: float) -> str:
    """`fg` sobre `bg` con opacidad `amount` (0 = `bg`, 1 = `fg`), en `#rrggbb`."""
    channels = (
        round(int(bg[i : i + 2], 16) + (int(fg[i : i + 2], 16) - int(bg[i : i + 2], 16)) * amount)
        for i in (1, 3, 5)
    )
    return "#" + "".join(f"{c:02x}" for c in channels)


def _readable(fg: str, backgrounds: tuple[str, ...], ratio: float, start: float) -> str:
    """El tono de `fg` más suave (mezclado con el primer fondo) que aún llega a `ratio` sobre todos."""
    amount = start
    while amount < 1:
        candidate = mix(fg, backgrounds[0], amount)
        if all(contrast(candidate, b) >= ratio for b in backgrounds):
            return candidate
        amount += 0.02
    return fg


def _fit(color: str, toward: str, backgrounds: tuple[str, ...], ratio: float = 4.6) -> str:
    """`color` tal cual si se lee sobre todos los fondos; si no, acercado a `toward` (el texto) lo justo."""
    amount = 0.0
    while amount <= 1:
        candidate = mix(toward, color, amount)
        if all(contrast(candidate, b) >= ratio for b in backgrounds):
            return candidate
        amount += 0.05
    return toward


def meets_aa(c: Colors) -> bool:
    """Las reglas de contraste de los tokens (workspace-pro-spec §10): texto y acciones ≥ 4,5:1 sobre cada
    fondo; lo tenue ≥ 3:1; el texto del botón principal y de los avisos ≥ 4,5:1."""
    for background in (c.bg, c.side, c.head):
        if any(
            contrast(getattr(c, name), background) < 4.5
            for name in ("text", "muted", "accent", "error", "ok")
        ):
            return False
        if contrast(c.faint, background) < 3.0:
            return False
    pairs = ((c.on_accent, c.accent_fill), (c.toast_text, c.toast), (c.toast_link, c.toast))
    return all(contrast(fg, bg) >= 4.5 for fg, bg in pairs)


def _lightness(color: str) -> int:
    """Luminosidad HSL de Qt (0–255), la que usa `style.is_dark`."""
    channels = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    return (max(channels) + min(channels)) // 2


def from_palette(base: str, window: str, text: str, *, dark: bool) -> Colors:
    """Los colores de GeoDuck dentro del tema de QGIS (#142): los neutros (fondos, bordes, grises) salen de la
    paleta de QGIS —solo se leen, nunca se cambian (ADR-0011)—; el turquesa y los colores fijos (ámbar sin
    guardar, rojo error, verde bien) son de GeoDuck. Si la paleta no deja leer bien algo (contraste AA), se
    usan los tokens propios del tema."""
    tokens = DARK if dark else LIGHT
    if any(len(v) != 7 or not v.startswith("#") for v in (base, window, text)):
        return tokens
    base, window, text = base.lower(), window.lower(), text.lower()
    if (_lightness(base) < 128) != dark:  # paleta a medias (fondo claro en tema oscuro…): los tokens propios
        return tokens
    head = mix(window, base, 0.5)
    backs = (base, window, head)
    accent = _fit(tokens.accent, text, backs)

    colors = replace(
        tokens,
        bg=base,
        side=window,
        head=head,
        border=mix(text, base, 0.16 if dark else 0.13),
        line=mix(text, base, 0.08 if dark else 0.06),
        text=text,
        muted=_readable(text, backs, 4.6, 0.55),
        faint=_readable(text, backs, 3.1, 0.4),
        null=mix(text, base, 0.42),
        accent_soft=mix(accent, base, 0.2 if dark else 0.12),
        selection=mix(accent, base, 0.4 if dark else 0.3),
        row_selected=mix(accent, base, 0.13 if dark else 0.08),
        chip_bg=mix(accent, base, 0.1 if dark else 0.06),
        chip_border=mix(accent, base, 0.35 if dark else 0.28),
        segment=mix(text, window, 0.08),
        toast=text,
        toast_text=base,
        accent=accent,
        ok=_fit(tokens.ok, text, backs),
        error=_fit(tokens.error, text, backs),
        warn=_fit(tokens.warn, text, backs),
        error_soft=mix(tokens.error, base, 0.14 if dark else 0.07),
    )
    if contrast(colors.toast_link, colors.toast) < 4.5:
        # el aviso es del color del texto: su enlace, el turquesa que se lea sobre él
        link = BRAND_DARK if contrast(BRAND_DARK, text) >= 4.6 else _fit(BRAND_DEEP, base, (text,))
        colors = replace(colors, toast_link=link)
    return colors if meets_aa(colors) else tokens


#: Campos de color (para pruebas y para recorrer el tema).
COLOR_FIELDS = tuple(f.name for f in fields(Colors) if f.type in ("str", str))
