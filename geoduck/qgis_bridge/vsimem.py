# SPDX-License-Identifier: GPL-2.0-or-later
"""Ciclo de vida de los archivos `/vsimem` de la modalidad Instantánea (qgis-bridge-spec §4).

Cada carga escribe un GeoPackage en `/vsimem/geoduck/<id>.gpkg`. El archivo vive en la RAM de GDAL hasta
que alguien lo libera. Medido en G3/E3: liberarlo mientras una capa lo usa deja la capa sin entidades.
Por eso se libera solo cuando QGIS ya quitó la **última** capa cuya fuente es ese archivo (las capas
duplicadas comparten la fuente). En error o cancelación, la carga lo libera de inmediato.

Al descargar GeoDuck no se libera nada: las capas presentes son de QGIS.
"""

from __future__ import annotations

import contextlib

from osgeo import gdal
from qgis.core import QgsProject

PREFIX = "/vsimem/geoduck/"


def unlink(path: str) -> None:
    if path.startswith(PREFIX) and gdal.VSIStatL(path) is not None:
        gdal.Unlink(path)


def exists(path: str) -> bool:
    return gdal.VSIStatL(path) is not None


class VsimemRegistry:
    """Sigue los archivos `/vsimem` de GeoDuck y los libera cuando ninguna capa los usa."""

    def __init__(self, project: QgsProject | None = None) -> None:
        self._project = project or QgsProject.instance()
        self._paths: set[str] = set()
        self._project.layersRemoved.connect(self._on_layers_removed)

    def track(self, path: str) -> None:
        self._paths.add(path)

    def release(self, path: str) -> None:
        """Libera un archivo cuyas capas nunca se publicaron (carga múltiple descartada)."""
        if path in self._paths and path not in self._in_use():
            unlink(path)
            self._paths.discard(path)

    @property
    def tracked(self) -> frozenset[str]:
        return frozenset(self._paths)

    def _in_use(self) -> set[str]:
        used = set()
        for layer in self._project.mapLayers().values():
            source = layer.source().split("|")[0]
            if source in self._paths:
                used.add(source)
        return used

    def _on_layers_removed(self, _ids: list[str]) -> None:
        for path in self._paths - self._in_use():
            unlink(path)
            self._paths.discard(path)

    def disconnect(self) -> None:
        """Al descargar GeoDuck: deja de seguir los archivos sin liberarlos (son de capas de QGIS)."""
        with contextlib.suppress(TypeError):
            self._project.layersRemoved.disconnect(self._on_layers_removed)
        self._paths.clear()
