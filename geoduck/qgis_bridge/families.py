# SPDX-License-Identifier: GPL-2.0-or-later
"""Familias y dimensiones de geometría en la Copia en memoria (spatial-spec §6; F-96, F-97).

Una **familia** es punto, línea o polígono (`X` y `MultiX` son la misma); `GeometryCollection` es una
propia. El proveedor `memory` no admite `Unknown` (F-96) y acepta en silencio una geometría Z en una capa
2D sin cambiar el tipo de la capa (F-97), que se perdería al exportar. Por eso:

- cada familia va a su propia capa privada mientras se lee;
- al terminar, el tipo de cada capa se fija con **todas** las dimensiones y la multiplicidad presentes
  (si hace falta se reconstruye: las geometrías sin Z/M la reciben con NaN, con aviso);
- con una sola familia, las filas sin geometría quedan en esa capa (como G3); con varias, van a una capa
  «sin geometría», igual que la Copia rápida.

Con «Tipos mixtos: una capa por tipo» desactivado, una segunda familia es un error y no se publica nada.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsFields,
    QgsGeometry,
    QgsVectorLayer,
    QgsWkbTypes,
)

from geoduck.domain.errors import ErrorCode, GeoDuckError

_BY_GEOMETRY_TYPE = {
    QgsWkbTypes.geometryType(Qgis.WkbType.Point): "Point",
    QgsWkbTypes.geometryType(Qgis.WkbType.LineString): "LineString",
    QgsWkbTypes.geometryType(Qgis.WkbType.Polygon): "Polygon",
}
COLLECTION = "GeometryCollection"
NO_GEOMETRY = "sin geometría"


def family(t: Qgis.WkbType) -> str:
    """Familia de un tipo WKB: «Point», «LineString», «Polygon» o «GeometryCollection»."""
    if QgsWkbTypes.flatType(t) == Qgis.WkbType.GeometryCollection:
        return COLLECTION
    return _BY_GEOMETRY_TYPE.get(QgsWkbTypes.geometryType(t), COLLECTION)


def target_type(types: Iterable[Qgis.WkbType]) -> Qgis.WkbType:
    """Tipo de capa que admite todas las geometrías de una familia: Multi si alguna es múltiple (o si se
    mezclan tipos curvos y lineales) y con Z/M si alguna la tiene."""
    types = list(types)
    flats = {QgsWkbTypes.flatType(t) for t in types}
    if len(flats) == 1:
        base = next(iter(flats))
    elif len({QgsWkbTypes.singleType(f) for f in flats}) == 1:
        base = QgsWkbTypes.multiType(next(iter(flats)))
    elif family(types[0]) == "LineString":
        base = Qgis.WkbType.MultiCurve
    elif family(types[0]) == "Polygon":
        base = Qgis.WkbType.MultiSurface
    else:
        base = QgsWkbTypes.multiType(QgsWkbTypes.singleType(next(iter(flats))))
    if any(QgsWkbTypes.hasZ(t) for t in types):
        base = QgsWkbTypes.addZ(base)
    if any(QgsWkbTypes.hasM(t) for t in types):
        base = QgsWkbTypes.addM(base)
    return base


def fit_to(g: QgsGeometry, target: Qgis.WkbType) -> tuple[QgsGeometry, bool, bool]:
    """La geometría adaptada al tipo de la capa: Multi y dimensiones que falten (NaN). Devuelve también si
    se añadió Z o M."""
    out = QgsGeometry(g)
    if QgsWkbTypes.isMultiType(target) and not QgsWkbTypes.isMultiType(out.wkbType()):
        out.convertToMultiType()
    added_z = QgsWkbTypes.hasZ(target) and not QgsWkbTypes.hasZ(out.wkbType())
    added_m = QgsWkbTypes.hasM(target) and not QgsWkbTypes.hasM(out.wkbType())
    if added_z:
        out.get().addZValue(math.nan)
    if added_m:
        out.get().addMValue(math.nan)
    return out, added_z, added_m


class FamilyLayers:
    """Capas privadas de una Copia en memoria, una por familia. Solo en el hilo principal."""

    def __init__(
        self,
        name: str,
        fields: QgsFields,
        crs: QgsCoordinateReferenceSystem,
        *,
        split: bool,
    ) -> None:
        self._name = name
        self._fields = fields
        self._crs = crs
        self._split = split
        self.layers: dict[str | None, QgsVectorLayer] = {}  # None: filas sin geometría
        self.types: dict[str, set[Qgis.WkbType]] = defaultdict(set)

    @property
    def fields(self) -> QgsFields:
        """Campos tal como los dejó QGIS en la primera capa (para crear las entidades)."""
        first = next(iter(self.layers.values()), None)
        return first.fields() if first is not None else self._fields

    def add(self, features: list[QgsFeature]) -> None:
        groups: dict[str | None, list[QgsFeature]] = defaultdict(list)
        for f in features:
            g = f.geometry()
            key = None if g is None or g.isNull() else family(g.wkbType())
            if key is not None:
                self.types[key].add(g.wkbType())
            groups[key].append(f)
        if not self._split and len(self.types) > 1:
            names = ", ".join(sorted(QgsWkbTypes.displayString(t) for s in self.types.values() for t in s))
            raise GeoDuckError(
                f"Geometrías de tipos distintos ({names}) y la opción «Tipos mixtos: una capa por tipo» "
                "está desactivada: no se cargó nada",
                code=ErrorCode.INVALID_ARGUMENT,
            )
        for key, feats in groups.items():
            layer = self.layers.get(key) or self._create(key, feats[0])
            self._insert(layer, feats)

    def _create(self, key: str | None, sample: QgsFeature) -> QgsVectorLayer:
        uri = "None" if key is None else QgsWkbTypes.displayString(sample.geometry().wkbType())
        layer = self._new_layer(uri, self._name)
        self.layers[key] = layer
        return layer

    def _new_layer(self, uri: str, name: str) -> QgsVectorLayer:
        layer = QgsVectorLayer(uri, name, "memory")
        if uri != "None":
            layer.setCrs(self._crs)  # siempre explícito: sin CRS, QGIS asignaría uno en silencio (C4)
        if not layer.isValid():
            raise GeoDuckError("QGIS no pudo crear la capa en memoria")
        provider = layer.dataProvider()
        if self._fields.count() and not provider.addAttributes(list(self._fields)):
            raise GeoDuckError(f"QGIS rechazó los campos: {provider.lastError()}")
        layer.updateFields()
        return layer

    @staticmethod
    def _insert(layer: QgsVectorLayer, features: list[QgsFeature]) -> None:
        provider = layer.dataProvider()
        ok, _ = provider.addFeatures(features)
        if not ok:
            raise GeoDuckError(f"QGIS rechazó entidades: {provider.lastError() or 'sin detalle'}")

    def finish(self) -> tuple[list[QgsVectorLayer], list[str]]:
        """Capas definitivas (privadas) y avisos. Fija el tipo de cada capa con sus dimensiones."""
        warnings: list[str] = []
        families = [k for k in self.layers if k is not None]
        nogeom = self.layers.get(None)
        if not families:
            return [nogeom or self._new_layer("None", self._name)], warnings
        final: dict[str, QgsVectorLayer] = {}
        added_z = added_m = 0
        for key in families:
            layer, z, m = self._normalized(self.layers[key], self.types[key])
            final[key] = layer
            added_z, added_m = added_z + z, added_m + m
        if added_z:
            warnings.append(f"Z añadida con valor NaN a {added_z} geometrías sin Z")
        if added_m:
            warnings.append(f"M añadida con valor NaN a {added_m} geometrías sin M")
        if len(final) == 1:
            layer = next(iter(final.values()))
            if nogeom is not None and nogeom.featureCount():  # una familia: las nulas quedan con ella
                self._insert(layer, list(nogeom.getFeatures()))
            return [layer], warnings
        for key, layer in final.items():
            layer.setName(f"{self._name} — {key}")
        layers = list(final.values())
        if nogeom is not None and nogeom.featureCount():
            nogeom.setName(f"{self._name} — {NO_GEOMETRY}")
            layers.append(nogeom)
        warnings.append(f"Tipos de geometría mixtos: {len(final)} capas, una por tipo")
        return layers, warnings

    def _normalized(self, layer: QgsVectorLayer, types: set[Qgis.WkbType]) -> tuple[QgsVectorLayer, int, int]:
        """La capa con el tipo que admite todas sus geometrías (se reconstruye si hace falta)."""
        target = target_type(types)
        if layer.wkbType() == target and types == {target}:
            return layer, 0, 0
        rebuilt = self._new_layer(QgsWkbTypes.displayString(target), layer.name())
        features: list[QgsFeature] = []
        added_z = added_m = 0
        for f in layer.getFeatures():
            g, z, m = fit_to(f.geometry(), target)
            added_z += z
            added_m += m
            f.setGeometry(g)
            features.append(f)
        self._insert(rebuilt, features)
        return rebuilt, added_z, added_m
