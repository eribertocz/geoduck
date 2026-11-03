# SPDX-License-Identifier: GPL-2.0-or-later
"""Traducción de los textos de GeoDuck (G6 · E4, GD-I18N-001, issue #68; ui-ux-spec §5).

Los textos del código están en inglés; el español llega por el catálogo de Qt (`geoduck/i18n/geoduck_es.ts`,
compilado a `.qm`). Este módulo no depende de Qt (ADR-0010): la interfaz instala el traductor al arrancar
(`geoduck.ui.i18n.install`), antes de importar el resto de la interfaz, y así también se traducen los mensajes
del motor y del puente con QGIS. Sin traductor, los textos salen en inglés, nunca vacíos.
"""

from __future__ import annotations

from collections.abc import Callable

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


def N_(text: str) -> str:  # noqa: N802 - convención de gettext/Qt para marcar sin traducir aún
    """Marca un texto para el catálogo sin traducirlo aquí (constantes que se traducen al usarse)."""
    return text
