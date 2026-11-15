# SPDX-License-Identifier: GPL-2.0-or-later
"""La guía de uso (#150; maqueta `150`): viene dentro del complemento y se abre en el navegador, también
sin internet, en español con QGIS en español y en inglés con cualquier otro idioma.

La construye `tools/build_guide.py` en `geoduck/guide/<idioma>/<página>.html` desde `docs/guide/`.
"""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QDesktopServices

from geoduck.ui.i18n import language

FOLDER = Path(__file__).resolve().parent.parent / "guide"

#: Las páginas que GeoDuck abre (los mismos nombres en los dos idiomas).
START = "index"
SHORTCUTS = "shortcuts"
WHATS_NEW = "whats-new"
REPORT = "report-a-problem"
ERRORS = "errors"
EXPLORE_TABLE = "explore-table"
SQL_EDITOR = "sql-editor"
PERFORMANCE = "performance"

#: Clase de error del motor → sección de «Errores frecuentes» (la tarjeta lleva «Más información»).
ERROR_SECTIONS = {
    "Catalog Error": "not-found",
    "Binder Error": "not-found",
    "Parser Error": "syntax",
    "Syntax Error": "syntax",
    "Conversion Error": "conversion",
    "IO Error": "files",
    "Out of Memory Error": "memory",
    "Constraint Error": "constraint",
    "TransactionContext Error": "transaction",
}


def guide_language() -> str:
    return "es" if language() == "es" else "en"


def page_path(page: str, lang: str | None = None) -> Path:
    return FOLDER / (lang or guide_language()) / f"{page}.html"


def available() -> bool:
    """Si esta instalación trae la guía (el ZIP siempre; una copia de desarrollo, tras construirla)."""
    return page_path(START).is_file()


def page_url(page: str, section: str = "") -> QUrl | None:
    """La dirección de una página (y su sección), o None si la guía no está."""
    path = page_path(page)
    if not path.is_file():
        return None
    url = QUrl.fromLocalFile(str(path))
    if section:
        url.setFragment(section)
    return url


def open_page(page: str = START, section: str = "") -> bool:
    """Abre la página en el navegador del sistema. False si la guía no está en esta instalación."""
    url = page_url(page, section)
    return url is not None and QDesktopServices.openUrl(url)
