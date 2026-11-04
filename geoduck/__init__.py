# SPDX-License-Identifier: GPL-2.0-or-later
"""GeoDuck: sesión DuckDB dentro de QGIS y entrega de resultados como capas de memoria."""

from __future__ import annotations

from typing import Any

__version__ = "0.8.0a1"


def classFactory(iface: Any) -> Any:  # noqa: N802 - nombre exigido por QGIS
    """Punto de entrada de QGIS. Importa Qt y QGIS solo aquí, para que el núcleo sea importable sin ellos."""
    from geoduck.ui.i18n import install  # noqa: PLC0415

    install()  # antes de importar la interfaz: sus textos se traducen al importarse (G6 · E4)
    from geoduck.plugin import GeoDuckPlugin  # noqa: PLC0415

    return GeoDuckPlugin(iface)
