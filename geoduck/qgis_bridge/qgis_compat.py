# SPDX-License-Identifier: GPL-2.0-or-later
"""Diferencias de la API de QGIS entre 3.34 (mínimo soportado, D8) y 3.40+ / 4.x.

QGIS 3.36–3.40 movieron varias enumeraciones a `Qgis` (`Qgis.FeatureRequestFlag`,
`Qgis.FeatureRequestFilterType`, `Qgis.VectorProviderCapability`, `Qgis.DataProviderReadFlags`) y añadieron
`QgsFeatureRequest.calculateTransform`. En QGIS 4 solo existen las formas nuevas; en 3.34, solo las
antiguas. Este módulo da un único nombre para cada una (hallazgo en Windows con QGIS 3.34.15, 2026-11-02).
"""

from __future__ import annotations

from typing import Any

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsDataProvider,
    QgsFeatureRequest,
    QgsVectorDataProvider,
)


def _enum(new: str, old_owner: Any, names: tuple[str, ...], old_names: tuple[str, ...]) -> Any:
    holder = getattr(Qgis, new, None)
    if holder is not None:
        return type("_", (), {n: getattr(holder, n) for n in names})
    return type("_", (), {n: getattr(old_owner, o) for n, o in zip(names, old_names, strict=True)})


#: Banderas de una petición: `SubsetOfAttributes`, `NoGeometry`, `ExactIntersect`.
RequestFlag = _enum(
    "FeatureRequestFlag",
    QgsFeatureRequest,
    ("SubsetOfAttributes", "NoGeometry", "ExactIntersect"),
    ("SubsetOfAttributes", "NoGeometry", "ExactIntersect"),
)

#: Tipo de filtro de una petición: `Fid`, `Fids`, `Expression`.
FilterType = _enum(
    "FeatureRequestFilterType",
    QgsFeatureRequest,
    ("Fid", "Fids", "Expression"),
    ("FilterFid", "FilterFids", "FilterExpression"),
)

#: Capacidades de un proveedor vectorial.
ProviderCapability = _enum(
    "VectorProviderCapability",
    QgsVectorDataProvider,
    ("SelectAtId", "AddFeatures", "DeleteFeatures", "ChangeAttributeValues", "ChangeGeometries"),
    ("SelectAtId", "AddFeatures", "DeleteFeatures", "ChangeAttributeValues", "ChangeGeometries"),
)


def read_flags() -> Any:
    """Banderas vacías de lectura de un proveedor."""
    if hasattr(Qgis, "DataProviderReadFlags"):
        return Qgis.DataProviderReadFlags()
    return QgsDataProvider.ReadFlags()


def calculate_transform(request: QgsFeatureRequest, source_crs: Any) -> QgsCoordinateTransform:
    """Transformación del CRS de la capa al de la petición (vacía si la petición no pide otro CRS)."""
    if hasattr(request, "calculateTransform"):
        return request.calculateTransform(source_crs)
    destination = request.destinationCrs()
    if not destination.isValid() or not source_crs.isValid() or destination == source_crs:
        return QgsCoordinateTransform()
    return QgsCoordinateTransform(source_crs, destination, request.transformContext())
