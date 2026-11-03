# SPDX-License-Identifier: GPL-2.0-or-later
"""Idioma de la interfaz (G6 · E4, GD-I18N-001, issue #68; ui-ux-spec §5).

El idioma es el de QGIS: con QGIS en español se carga `geoduck/i18n/geoduck_es.qm`; en cualquier otro idioma,
los textos en inglés del código. GeoDuck no tiene una opción de idioma propia ni cambia el de QGIS.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QCoreApplication, QTranslator

from geoduck.domain.i18n import CONTEXT, N_, get_translator, set_translator, tr

__all__ = ["CONTEXT", "N_", "install", "language", "tr", "uninstall"]

#: Idiomas con traducción, además del inglés del código.
TRANSLATIONS = ("es",)
FOLDER = Path(__file__).resolve().parent.parent / "i18n"

_installed: QTranslator | None = None
#: Traductor que había antes de `install` (se restaura al descargar GeoDuck).
_previous: list[Callable[[str], str] | None] = []


def language() -> str:
    """Idioma de QGIS (`es`, `en`, …): el de la opción «Idioma» de QGIS, o el del sistema."""
    locale = QgsApplication.locale() or "en"
    return locale.replace("-", "_").split("_")[0].lower()


def install() -> str:
    """Traduce GeoDuck al idioma de QGIS si hay catálogo; devuelve el idioma usado. Se llama una vez al cargar
    el complemento, antes de importar la interfaz (los textos de los módulos se traducen al importarse)."""
    uninstall()
    _previous.append(get_translator())
    lang = language()
    used = "en"
    if lang in TRANSLATIONS:
        translator = QTranslator()
        if translator.load(str(FOLDER / f"geoduck_{lang}.qm")):
            QCoreApplication.installTranslator(translator)
            global _installed  # noqa: PLW0603 - el traductor vive mientras GeoDuck esté cargado
            _installed = translator
            used = lang
    set_translator(lambda text: QCoreApplication.translate(CONTEXT, text))
    return used


def uninstall() -> None:
    """Quita el traductor de GeoDuck (al descargar el complemento). No toca los de QGIS."""
    global _installed  # noqa: PLW0603
    if _installed is not None:
        QCoreApplication.removeTranslator(_installed)
        _installed = None
    if _previous:
        set_translator(_previous.pop())
