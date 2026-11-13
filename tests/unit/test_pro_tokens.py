# SPDX-License-Identifier: GPL-2.0-or-later
"""Tokens de Workspace Pro (G9 · E1): contraste AA en los dos temas (workspace-pro-spec §10)."""

from __future__ import annotations

import pytest

from geoduck.ui.pro.tokens import (
    BEAK,
    BRAND,
    BRAND_DARK,
    BRAND_DEEP,
    COLOR_FIELDS,
    DARK,
    LIGHT,
    METRICS,
    contrast,
    from_palette,
    meets_aa,
    mix,
)


@pytest.mark.parametrize("colors", [LIGHT, DARK], ids=["claro", "oscuro"])
def test_text_and_actions_reach_aa_on_every_background(colors):
    for background in (colors.bg, colors.side, colors.head):
        for name in ("text", "muted", "accent", "error", "ok"):
            assert contrast(getattr(colors, name), background) >= 4.5, (name, background)
        assert contrast(colors.faint, background) >= 3.0  # solo información que se repite en otro sitio
    assert contrast(colors.on_accent, colors.accent_fill) >= 4.5
    assert contrast(colors.toast_text, colors.toast) >= 4.5
    assert contrast(colors.toast_link, colors.toast) >= 4.5


def test_contrast_is_the_wcag_ratio():
    assert round(contrast("#000000", "#ffffff"), 1) == 21.0
    assert contrast("#777777", "#777777") == 1.0


def test_motion_is_brief():
    assert METRICS.motion <= 150


# #142: identidad visual — turquesa de GeoDuck, neutros del tema de QGIS

#: Paletas de temas de QGIS (fondo de campos, ventana, texto): por defecto, «Night Mapping», «Blend of Gray»,
#: Windows claro y uno oscuro de sistema.
QGIS_THEMES = {
    "por defecto": ("#ffffff", "#efefef", "#000000", False),
    "night mapping": ("#191919", "#353535", "#dddddd", True),
    "blend of gray": ("#232629", "#31363b", "#eff0f1", True),
    "windows claro": ("#ffffff", "#f0f0f0", "#1f1f1f", False),
    "oscuro de sistema": ("#2b2b2b", "#3c3f41", "#bbbbbb", True),
}


def test_the_brand_is_lake_turquoise():
    assert (BRAND, BRAND_DARK, BRAND_DEEP, BEAK) == ("#0e8a87", "#3fc1bc", "#0a5e5c", "#f2a33a")
    assert LIGHT.accent_hover == BRAND_DEEP and DARK.accent == BRAND_DARK
    for colors in (LIGHT, DARK):  # nada del azul anterior
        assert not {"#2f5fd0", "#5b84e6", "#3b67d6"} & {getattr(colors, f) for f in COLOR_FIELDS}


@pytest.mark.parametrize("theme", list(QGIS_THEMES))
def test_neutrals_come_from_the_qgis_theme_and_stay_readable(theme):
    base, window, text, dark = QGIS_THEMES[theme]
    colors = from_palette(base, window, text, dark=dark)
    assert (colors.bg, colors.side, colors.text, colors.dark) == (base, window, text, dark)
    assert meets_aa(colors)
    tokens = DARK if dark else LIGHT
    # el turquesa sigue siendo turquesa (a lo sumo, un poco más hondo para leerse) y los fijos, fijos
    assert colors.accent_fill == tokens.accent_fill and colors.star == tokens.star
    red, green, blue = (int(colors.accent[i : i + 2], 16) for i in (1, 3, 5))
    assert green > red and blue > red


def test_a_palette_that_cannot_be_read_falls_back_to_geoduck_tokens():
    assert from_palette("#ffffff", "#ffffff", "#eeeeee", dark=False) is LIGHT  # texto ilegible
    assert from_palette("#ffffff", "#16181d", "#000000", dark=True) is DARK  # tema a medias
    assert from_palette("white", "#efefef", "#000000", dark=False) is LIGHT


def test_mix_blends_two_colors():
    assert mix("#000000", "#ffffff", 0) == "#ffffff"
    assert mix("#000000", "#ffffff", 1) == "#000000"
    assert mix("#000000", "#ffffff", 0.5) == "#808080"
