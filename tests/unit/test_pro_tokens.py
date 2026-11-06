# SPDX-License-Identifier: GPL-2.0-or-later
"""Tokens de Workspace Pro (G9 · E1): contraste AA en los dos temas (workspace-pro-spec §10)."""

from __future__ import annotations

import pytest

from geoduck.ui.pro.tokens import DARK, LIGHT, METRICS, contrast


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
