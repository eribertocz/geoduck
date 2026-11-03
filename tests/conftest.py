# SPDX-License-Identifier: GPL-2.0-or-later
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def spanish_catalog() -> dict[str, str]:
    """Traducciones del catálogo español (`geoduck/i18n/geoduck_es.ts`), sin Qt."""
    from geoduck.domain.i18n import load_catalog

    return load_catalog(ROOT / "geoduck" / "i18n" / "geoduck_es.ts")


# G6 · E4: las pruebas ven GeoDuck en español, como hasta G5 (los textos del código están en inglés). Las de
# GD-I18N-001 comprueban aparte el inglés y el catálogo real de Qt (.qm).
from geoduck.domain.i18n import set_translator  # noqa: E402

_CATALOG = spanish_catalog()
set_translator(lambda text: _CATALOG.get(text) or text)
