# SPDX-License-Identifier: GPL-2.0-or-later
"""Idioma de la interfaz (G6 · E4, GD-I18N-001, issue #68; ui-ux-spec §5).

El idioma es el de QGIS: con QGIS en español se usa `geoduck/i18n/geoduck_es.ts`; en cualquier otro idioma,
los textos en inglés del código. GeoDuck no tiene una opción de idioma propia ni cambia el de QGIS. No
instala un `QTranslator` (F-106, F-107): traduce con un diccionario, también desde el hilo del motor.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from qgis.core import QgsApplication

from geoduck.domain.i18n import (
    CONTEXT,
    N_,
    get_language,
    get_translator,
    load_catalog,
    set_language,
    set_translator,
    tr,
)

__all__ = ["CONTEXT", "N_", "install", "language", "tr", "uninstall"]

#: Idiomas con catálogo, además del inglés del código.
TRANSLATIONS = ("es",)
FOLDER = Path(__file__).resolve().parent.parent / "i18n"

#: Traductor de textos que había antes de `install` (se restaura al descargar GeoDuck).
_previous: list[tuple[Callable[[str], str] | None, str]] = []


def language() -> str:
    """Idioma de QGIS (`es`, `en`, …): el de la opción «Idioma» de QGIS, o el del sistema."""
    locale = QgsApplication.locale() or "en"
    return locale.replace("-", "_").split("_")[0].lower()


def install() -> str:
    """Traduce GeoDuck al idioma de QGIS si hay catálogo; devuelve el idioma usado. Se llama al cargar el
    complemento, antes de importar la interfaz (los textos de los módulos se traducen al importarse)."""
    _previous.append((get_translator(), get_language()))
    lang = language()
    path = FOLDER / f"geoduck_{lang}.ts"
    if lang in TRANSLATIONS and path.is_file():
        catalog = load_catalog(path)
        set_translator(lambda text: catalog.get(text, text))
        set_language(lang)
        return lang
    set_translator(None)
    set_language(lang)  # sin catálogo, los textos en inglés; los números, como en inglés
    return "en"


def uninstall() -> None:
    """Al descargar GeoDuck vuelve el traductor anterior."""
    if _previous:
        translator, lang = _previous.pop()
        set_translator(translator)
        set_language(lang)
