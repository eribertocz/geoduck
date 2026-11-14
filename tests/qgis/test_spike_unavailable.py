# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike de #183: el estado «no disponible» nativo de QGIS para una capa de un proveedor de Python.

Un proveedor mínimo cuya validez depende de `AVAILABLE`. Se mide, en cada versión de QGIS:
1. `setDataSource` con el proveedor inválido deja la capa inválida, en el proyecto y en el árbol, con su
   nombre, estilo y SRC.
2. `setDataSource` otra vez, ya disponible, la vuelve válida con sus entidades.
3. Un proyecto guardado y reabierto con el proveedor inválido conserva la capa (inválida) y vuelve a ser
   válida con `setDataSource`.
"""

from __future__ import annotations

import json
import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsFeature,
    QgsFeatureIterator,
    QgsFeatureRequest,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsProviderMetadata,
    QgsProviderRegistry,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsVectorDataProvider,
    QgsVectorLayer,
)
from qgis.PyQt.QtGui import QColor

try:
    from qgis.core import Qgis

    POINT = Qgis.WkbType.Point
except AttributeError:  # pragma: no cover
    from qgis.core import QgsWkbTypes

    POINT = QgsWkbTypes.Point

from qgis.core import QgsAbstractFeatureIterator, QgsAbstractFeatureSource

KEY = "spike183"
AVAILABLE = {"on": True}
RESULT = os.environ.get("SPIKE183_OUT")


class _Iter(QgsAbstractFeatureIterator):
    def __init__(self, request):
        super().__init__(request)
        self._i = 0

    def fetchFeature(self, f):
        if not AVAILABLE["on"] or self._i >= 3:
            return False
        f.setFields(QgsFields())
        f.setId(self._i + 1)
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-68 + self._i, -16)))
        f.setValid(True)
        self._i += 1
        return True

    def rewind(self):
        self._i = 0
        return True

    def close(self):
        return True


class _Source(QgsAbstractFeatureSource):
    def getFeatures(self, request):
        return QgsFeatureIterator(_Iter(request))


class SpikeProvider(QgsVectorDataProvider):
    @classmethod
    def createProvider(cls, uri, options, flags=None):
        return SpikeProvider(uri, options, flags)

    def __init__(self, uri="", options=None, flags=None):
        if flags is None:
            super().__init__(uri, options or QgsDataProvider.ProviderOptions())
        else:
            super().__init__(uri, options or QgsDataProvider.ProviderOptions(), flags)
        self._valid = AVAILABLE["on"]

    def isValid(self):
        return self._valid

    def featureSource(self):
        return _Source()

    def getFeatures(self, request=QgsFeatureRequest()):  # noqa: B008
        return QgsFeatureIterator(_Iter(request))

    def fields(self):
        return QgsFields()

    def wkbType(self):
        return POINT

    def featureCount(self):
        return 3 if self._valid else -1

    def extent(self):
        return QgsRectangle(-68, -16, -66, -16)

    def crs(self):
        return QgsCoordinateReferenceSystem("EPSG:4326")

    def name(self):
        return KEY

    def description(self):
        return KEY

    def updateExtents(self):
        pass


def _register():
    registry = QgsProviderRegistry.instance()
    if KEY not in registry.providerList():
        registry.registerProvider(QgsProviderMetadata(KEY, KEY, SpikeProvider.createProvider))


def _reset(layer):
    layer.setDataSource(layer.source(), layer.name(), KEY, QgsDataProvider.ProviderOptions())


def test_spike_native_unavailable_state(qgis_app, tmp_path):
    _register()
    AVAILABLE["on"] = True
    project = QgsProject.instance()
    layer = QgsVectorLayer("base=catastro", "Predios", KEY)
    assert layer.isValid()
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setColor(QColor("#123456"))
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    project.addMapLayer(layer)
    out = {}

    AVAILABLE["on"] = False
    _reset(layer)
    out["1_invalid"] = not layer.isValid()
    out["1_in_project"] = project.mapLayer(layer.id()) is layer
    out["1_in_tree"] = project.layerTreeRoot().findLayer(layer.id()) is not None
    out["1_name"] = layer.name() == "Predios"
    out["1_style"] = layer.renderer() is not None and layer.renderer().symbol().color().name() == "#123456"
    out["1_crs"] = layer.crs().authid() == "EPSG:4326"
    out["1_no_features"] = sum(1 for _ in layer.getFeatures()) == 0

    AVAILABLE["on"] = True
    _reset(layer)
    out["2_valid"] = layer.isValid()
    out["2_features"] = sum(1 for _ in layer.getFeatures()) == 3
    out["2_style"] = layer.renderer().symbol().color().name() == "#123456"

    path = str(tmp_path / "p.qgz")
    project.write(path)
    project.clear()
    AVAILABLE["on"] = False
    project.read(path)
    again = project.mapLayersByName("Predios")
    out["3_kept"] = len(again) == 1
    if again:
        lyr = again[0]
        out["3_invalid"] = not lyr.isValid()
        out["3_style"] = lyr.renderer() is not None and lyr.renderer().symbol().color().name() == "#123456"
        AVAILABLE["on"] = True
        _reset(lyr)
        out["3_valid_after"] = lyr.isValid() and sum(1 for _ in lyr.getFeatures()) == 3
        out["3_style_after"] = lyr.renderer().symbol().color().name() == "#123456"
    project.clear()
    print("SPIKE183", json.dumps(out))
    if RESULT:
        with open(RESULT, "w", encoding="utf-8") as fh:
            json.dump(out, fh)
    assert all(out.values()), out
