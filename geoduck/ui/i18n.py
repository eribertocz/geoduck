# SPDX-License-Identifier: GPL-2.0-or-later
"""Traducción de textos de la interfaz (spec/specs/ui-ux-spec.md §5: español inicial, catálogos Qt)."""

from __future__ import annotations

from qgis.PyQt.QtCore import QCoreApplication

CONTEXT = "GeoDuck"


def tr(text: str) -> str:
    return str(QCoreApplication.translate(CONTEXT, text))
