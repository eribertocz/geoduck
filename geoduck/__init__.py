# SPDX-License-Identifier: GPL-2.0-or-later
"""GeoDuck: sesión DuckDB dentro de QGIS y entrega de resultados como capas de memoria."""

from __future__ import annotations

from typing import Any

__version__ = "0.1.0a1"


def classFactory(iface: Any) -> Any:  # noqa: N802 - nombre exigido por QGIS
    """Punto de entrada de QGIS. Importa Qt y QGIS solo aquí, para que el núcleo sea importable sin ellos."""
    from geoduck.plugin import GeoDuckPlugin  # noqa: PLC0415

    return GeoDuckPlugin(iface)
