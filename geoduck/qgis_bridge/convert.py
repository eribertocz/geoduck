# SPDX-License-Identifier: GPL-2.0-or-later
"""Arrow → QGIS: campos, valores y geometría, en el hilo principal (qgis-bridge-spec §3, §7).

Los tipos ya llegan normalizados (`domain.bridge_types`); aquí solo se crean los objetos de QGIS de la
forma más barata medida en el spike: fechas desde enteros (F-43), WKB directo a `QgsGeometry`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QByteArray, QDate, QDateTime, QMetaType, Qt, QTime

from geoduck.domain.bridge_types import FieldKind, LoadPlan, unreadable_error
from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.i18n import tr

_JULIAN_EPOCH = 2440588  # día juliano del 1970-01-01
_UTC = Qt.TimeSpec.UTC

_QMETA = {
    FieldKind.BOOL: QMetaType.Type.Bool,
    FieldKind.INT: QMetaType.Type.Int,
    FieldKind.INT64: QMetaType.Type.LongLong,
    FieldKind.DOUBLE: QMetaType.Type.Double,
    FieldKind.TEXT: QMetaType.Type.QString,
    FieldKind.DATE: QMetaType.Type.QDate,
    FieldKind.DATETIME: QMetaType.Type.QDateTime,
    FieldKind.DATETIME_TZ: QMetaType.Type.QDateTime,
    FieldKind.TIME: QMetaType.Type.QTime,
    FieldKind.BINARY: QMetaType.Type.QByteArray,
}


def make_field(name: str, kind: FieldKind) -> QgsField:
    """`QgsField` con tipo `QMetaType` (QGIS ≥ 3.38) o `QVariant` (QGIS 3.34/3.36)."""
    try:
        return QgsField(name, _QMETA[kind])
    except TypeError:  # QGIS < 3.38: el constructor solo acepta QVariant.Type
        from qgis.PyQt.QtCore import QVariant  # noqa: PLC0415 - solo en QGIS antiguos

        legacy = {
            FieldKind.BOOL: QVariant.Bool,
            FieldKind.INT: QVariant.Int,
            FieldKind.INT64: QVariant.LongLong,
            FieldKind.DOUBLE: QVariant.Double,
            FieldKind.TEXT: QVariant.String,
            FieldKind.DATE: QVariant.Date,
            FieldKind.DATETIME: QVariant.DateTime,
            FieldKind.DATETIME_TZ: QVariant.DateTime,
            FieldKind.TIME: QVariant.Time,
            FieldKind.BINARY: QVariant.ByteArray,
        }
        return QgsField(name, legacy[kind])


def fields_for(plan: LoadPlan) -> QgsFields:
    fields = QgsFields()
    for f in plan.fields:
        fields.append(make_field(f.name, f.kind))
    return fields


def _dates(arr: pa.Array) -> list[Any]:
    days = arr.cast(pa.int32()).to_pylist()
    return [None if d is None else QDate.fromJulianDay(d + _JULIAN_EPOCH) for d in days]


def _datetimes(arr: pa.Array) -> list[Any]:
    """Instante en UTC con los mismos dígitos de reloj para TIMESTAMP sin zona (sin desplazar).

    La unidad se pasa a milisegundos en C++ (QDateTime no guarda más precisión).
    """
    ms = arr.cast(pa.timestamp("ms", tz=arr.type.tz), safe=False).cast(pa.int64()).to_pylist()
    return [None if v is None else QDateTime.fromMSecsSinceEpoch(v, _UTC) for v in ms]


def _times(arr: pa.Array) -> list[Any]:
    """Hora del día: microsegundos desde la medianoche → QTime (milisegundos, como guarda QGIS)."""
    micros = arr.cast(pa.time64("us")).cast(pa.int64()).to_pylist()
    return [None if v is None else QTime.fromMSecsSinceStartOfDay(v // 1000) for v in micros]


def _binary(arr: pa.Array) -> list[Any]:
    return [None if v is None else QByteArray(v) for v in arr.to_pylist()]


def column_converter(kind: FieldKind) -> Callable[[pa.Array], list[Any]]:
    if kind is FieldKind.DATE:
        return _dates
    if kind in (FieldKind.DATETIME, FieldKind.DATETIME_TZ):
        return _datetimes
    if kind is FieldKind.TIME:
        return _times
    if kind is FieldKind.BINARY:
        return _binary
    return lambda arr: arr.to_pylist()


# -- geometría -------------------------------------------------------------------------------------


def crs_from_field(field: pa.Field, override: str | None = None) -> QgsCoordinateReferenceSystem:
    """CRS desde el PROJJSON de GeoArrow (C4: sin reordenar ejes). Inválido si los datos no lo traen.

    `override`: elección del usuario cuando el CRS es desconocido ("" = continuar sin CRS).
    """
    if override is not None:
        return QgsCoordinateReferenceSystem(override) if override else QgsCoordinateReferenceSystem()
    meta = field.metadata or {}
    raw = meta.get(b"ARROW:extension:metadata") or b"{}"
    try:
        crs_info = json.loads(raw).get("crs")
    except ValueError:
        crs_info = None
    crs = QgsCoordinateReferenceSystem()
    if crs_info:
        crs.createFromUserInput(json.dumps(crs_info) if isinstance(crs_info, dict) else str(crs_info))
    return crs


def geometry_from_wkb(wkb: bytes | None) -> QgsGeometry | None:
    if wkb is None:
        return None
    g = QgsGeometry()
    g.fromWkb(wkb)
    return g


def layer_type_for(geometries: list[QgsGeometry | None]) -> Qgis.WkbType | None:
    """Tipo de capa para una muestra: X o MultiX (si hay alguna múltiple). None si no hay geometrías.

    Tipos de familias distintas no caben en una capa memory: error explícito (la Copia rápida sí los
    admite).
    """
    flat = {QgsWkbTypes.flatType(g.wkbType()) for g in geometries if g is not None and not g.isNull()}
    if not flat:
        return None
    singles = {QgsWkbTypes.singleType(t) for t in flat}
    if len(singles) > 1:
        names = ", ".join(sorted(QgsWkbTypes.displayString(t) for t in flat))
        raise GeoDuckError(
            tr(
                "Geometries of different types ({0}): a memory layer accepts a "
                "single type; use «Fast copy» or filter by type"
            ).format(names),
            code=ErrorCode.INVALID_ARGUMENT,
        )
    single = next(iter(singles))
    base = QgsWkbTypes.multiType(single) if any(QgsWkbTypes.isMultiType(t) for t in flat) else single
    sample = next(g for g in geometries if g is not None and not g.isNull())
    if QgsWkbTypes.hasZ(sample.wkbType()):
        base = QgsWkbTypes.addZ(base)
    if QgsWkbTypes.hasM(sample.wkbType()):
        base = QgsWkbTypes.addM(base)
    return base


def fit_geometry(g: QgsGeometry, layer_type: Qgis.WkbType) -> QgsGeometry:
    """Ajusta una geometría al tipo de la capa (X → MultiX). Error si no es compatible."""
    t = g.wkbType()
    if QgsWkbTypes.flatType(t) == QgsWkbTypes.flatType(layer_type):
        return g
    if QgsWkbTypes.isMultiType(layer_type) and QgsWkbTypes.singleType(
        QgsWkbTypes.flatType(layer_type)
    ) == QgsWkbTypes.flatType(t):
        g = QgsGeometry(g)
        g.convertToMultiType()
        return g
    raise GeoDuckError(
        tr("{0} geometry in a {1} layer: use «Fast copy» or filter by type").format(
            QgsWkbTypes.displayString(t), QgsWkbTypes.displayString(layer_type)
        ),
        code=ErrorCode.INVALID_ARGUMENT,
    )


def strip_unreadable(batch: pa.RecordBatch, plan: LoadPlan, offset: int) -> pa.RecordBatch:
    """Quita la columna auxiliar de geometría ilegible; si alguna fila la tiene, error con su número
    (1 = primera fila del resultado). Las copias no publican nada (spatial-spec §3)."""
    flag = plan.unreadable_flag
    if flag is None or plan.geometry is None:
        return batch
    index = batch.schema.get_field_index(flag)
    if index < 0:
        return batch
    column = batch.column(index)
    if pc.any(column).as_py():
        first = column.to_pylist().index(True)
        raise unreadable_error(plan.geometry, offset + first + 1)
    keep = [i for i in range(batch.num_columns) if i != index]
    return pa.RecordBatch.from_arrays(
        [batch.column(i) for i in keep], schema=pa.schema([batch.schema.field(i) for i in keep])
    )
