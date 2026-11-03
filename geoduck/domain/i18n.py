# SPDX-License-Identifier: GPL-2.0-or-later
"""Traducción de los textos de GeoDuck (G6 · E4, GD-I18N-001, issue #68; ui-ux-spec §5).

Los textos del código están en inglés; el español está en el catálogo de Qt Linguist
`geoduck/i18n/geoduck_es.ts`. GeoDuck lo lee con la biblioteca estándar (`load_catalog`) y traduce con un
diccionario, sin llamar a Qt: así se traduce igual desde el hilo del motor, donde llamar a Qt no es seguro
(F-107). La interfaz elige el catálogo al arrancar (`geoduck.ui.i18n.install`), antes de importar el resto
de la interfaz. Sin catálogo, los textos salen en inglés, nunca vacíos. Este módulo no depende de Qt
(ADR-0010).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

#: Contexto de los textos en el catálogo de Qt.
CONTEXT = "GeoDuck"

_translate: Callable[[str], str] | None = None


def set_translator(translate: Callable[[str], str] | None) -> None:
    """Instala la función que traduce un texto (`None`: sin traducción, en inglés)."""
    global _translate  # noqa: PLW0603 - un único traductor para todo el complemento
    _translate = translate


def get_translator() -> Callable[[str], str] | None:
    return _translate


def tr(text: str) -> str:
    """El texto en el idioma de QGIS; si no hay traducción, el texto en inglés."""
    if _translate is None:
        return text
    return _translate(text) or text


def load_catalog(path: Path) -> dict[str, str]:
    """Texto inglés → traducción, de un `.ts` de Qt Linguist (las no terminadas no se usan)."""
    catalog: dict[str, str] = {}
    for message in ET.parse(path).getroot().iter("message"):
        translation = message.find("translation")
        if (
            translation is None
            or translation.get("type") in ("unfinished", "obsolete")
            or not translation.text
        ):
            continue
        catalog[message.findtext("source") or ""] = translation.text
    return catalog


def N_(text: str) -> str:  # noqa: N802 - convención de gettext/Qt para marcar sin traducir aún
    """Marca un texto para el catálogo sin traducirlo aquí (constantes que se traducen al usarse)."""
    return text
