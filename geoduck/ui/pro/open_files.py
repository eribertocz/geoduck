# SPDX-License-Identifier: GPL-2.0-or-later
"""«Abrir en QGIS»: un archivo que GeoDuck no importa (no está en la lista de formatos, qgis-import-spec
§10) lo abre QGIS con todas sus capas; después se añade a DuckDB como cualquier capa de QGIS."""

from __future__ import annotations

import os

from qgis.core import QgsProject, QgsProviderRegistry, QgsVectorLayer


def open_in_qgis(paths: list[str]) -> tuple[int, list[str]]:
    """Abre cada archivo en el proyecto (todas sus capas vectoriales). Devuelve cuántas capas se abrieron y
    los archivos que QGIS no pudo abrir."""
    opened = 0
    failed: list[str] = []
    project = QgsProject.instance()
    for path in paths:
        layers = []
        for sub in QgsProviderRegistry.instance().querySublayers(path):
            if sub.providerKey() != "ogr":
                continue
            layer = QgsVectorLayer(sub.uri(), sub.name() or os.path.basename(path), "ogr")
            if layer.isValid():
                layers.append(layer)
        if not layers:
            failed.append(path)
            continue
        for layer in layers:
            project.addMapLayer(layer)
        opened += len(layers)
    return opened, failed
