# SPDX-License-Identifier: GPL-2.0-or-later
"""«Ver en el mapa» (ui-ux-spec §8, AT-UX-008).

Trae QGIS al frente y selecciona en el panel de capas la (primera) capa de la última carga. Si las capas
tienen extensión válida (no nula, finita y transformable al SRC del proyecto con su contexto de
transformación), hace zoom a ella; si no, no hace zoom y lo dice. No modifica las capas ni la sesión.
"""

from __future__ import annotations

import math
from typing import Any

from qgis.core import QgsCoordinateTransform, QgsCsException, QgsProject, QgsRectangle

from geoduck.ui.i18n import N_, tr

NO_EXTENT = N_("The layer has no valid extent: it was selected without zooming")


def _finite(rect: QgsRectangle) -> bool:
    values = (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())
    return all(math.isfinite(v) for v in values) and rect.xMaximum() >= rect.xMinimum()


def valid_extent(layer: Any, project: QgsProject) -> QgsRectangle | None:
    """Extensión de la capa en el SRC del proyecto, o None si no sirve para hacer zoom."""
    if not hasattr(layer, "isSpatial") or not layer.isSpatial():
        return None  # tabla sin geometría
    extent = layer.extent()
    if extent.isNull() or not _finite(extent):
        return None  # sin geometrías o extensión desconocida
    # Puntos en una línea (un lado 0): QGIS no transforma ni hace zoom a un rectángulo así; se agranda antes
    if (extent.width() == 0) != (extent.height() == 0):
        extent = QgsRectangle(extent)
        extent.grow(0.05 * max(extent.width(), extent.height()))
    source, target = layer.crs(), project.crs()
    if source.isValid() and target.isValid() and source != target:
        transform = QgsCoordinateTransform(source, target, project.transformContext())
        try:
            if extent.width() == 0 and extent.height() == 0:  # un solo punto: se transforma el punto
                point = transform.transform(extent.center())
                extent = QgsRectangle(point.x(), point.y(), point.x(), point.y())
            else:
                extent = transform.transformBoundingBox(extent)
        except QgsCsException:
            return None  # no transformable
        if not _finite(extent):
            return None
    return QgsRectangle(extent)


class MapView:
    """Lleva al mapa las capas de la última carga de GeoDuck."""

    def __init__(self, iface: Any) -> None:
        self.iface = iface

    def show(self, layer_ids: list[str]) -> str | None:
        """Selecciona y, si se puede, hace zoom. Devuelve el aviso para el usuario, o None si hizo zoom."""
        project = QgsProject.instance()
        layers = [layer for layer in (project.mapLayer(i) for i in layer_ids) if layer is not None]
        if not layers:
            return tr("The layer is no longer in the project")
        main = self.iface.mainWindow()
        main.raise_()
        main.activateWindow()
        self.iface.setActiveLayer(layers[0])  # queda seleccionada en el panel de capas
        extent: QgsRectangle | None = None
        for layer in layers:
            rect = valid_extent(layer, project)
            if rect is None:
                continue
            if extent is None:
                extent = rect
            else:
                extent.combineExtentWith(rect)
        if extent is None:
            return tr(NO_EXTENT)
        canvas = self.iface.mapCanvas()
        if extent.width() == 0 and extent.height() == 0:  # un solo punto: se centra sin cambiar la escala
            canvas.setCenter(extent.center())
        else:
            canvas.setExtent(extent)
        canvas.refresh()
        return None
