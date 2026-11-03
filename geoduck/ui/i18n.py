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

#: Traductor de Qt instalado y su idioma. Se instala una vez y no se quita (como hace QGIS con los de sus
#: complementos): instalar o quitar un traductor envía «LanguageChange» a todos los widgets, también a los
#: que se están borrando al descargar GeoDuck, y en Qt 6 eso puede terminar en un fallo.
_installed: tuple[str, QTranslator] | None = None
#: Traductor de textos que había antes de `install` (se restaura al descargar GeoDuck).
_previous: list[Callable[[str], str] | None] = []


def language() -> str:
    """Idioma de QGIS (`es`, `en`, …): el de la opción «Idioma» de QGIS, o el del sistema."""
    locale = QgsApplication.locale() or "en"
    return locale.replace("-", "_").split("_")[0].lower()


def install() -> str:
    """Traduce GeoDuck al idioma de QGIS si hay catálogo; devuelve el idioma usado. Se llama al cargar el
    complemento, antes de importar la interfaz (los textos de los módulos se traducen al importarse)."""
    global _installed  # noqa: PLW0603 - un único traductor de Qt para todo el complemento
    _previous.append(get_translator())
    lang = language()
    used = "en"
    if lang in TRANSLATIONS:
        if _installed is not None and _installed[0] == lang:
            used = lang  # ya instalado (p. ej. el complemento se recargó): no se vuelve a instalar
        else:
            translator = QTranslator()
            if translator.load(str(FOLDER / f"geoduck_{lang}.qm")):
                if _installed is not None:
                    QCoreApplication.removeTranslator(_installed[1])
                QCoreApplication.installTranslator(translator)
                _installed = (lang, translator)
                used = lang
    elif _installed is not None:  # QGIS cambió a un idioma sin catálogo sin reiniciarse: caso raro
        QCoreApplication.removeTranslator(_installed[1])
        _installed = None
    set_translator(lambda text: QCoreApplication.translate(CONTEXT, text))
    return used


def uninstall() -> None:
    """Al descargar GeoDuck: vuelve el traductor de textos anterior. El de Qt se queda instalado (ver
    `_installed`); sin GeoDuck, nadie pide textos de su contexto."""
    if _previous:
        set_translator(_previous.pop())
