# SPDX-License-Identifier: GPL-2.0-or-later
"""Lotes Arrow de DuckDB sin tipos de extensión registrados por otros (F-121).

DuckDB entrega la geometría como `binary` con los metadatos GeoArrow en el campo (`ARROW:extension:name`
= `geoarrow.wkb` y `ARROW:extension:metadata` con el SRC). Si otro componente del mismo proceso registró
`geoarrow.wkb` en la biblioteca Arrow que comparte con pyarrow —GDAL lo hace al abrir un GeoParquet en
QGIS instalado con conda—, pyarrow convierte esa columna en un tipo de extensión: los cálculos sobre
`binary` fallan y los metadatos (el SRC) dejan de verse en el campo.

`plain_batch` devuelve el lote como lo entrega DuckDB sin ese registro: la columna con su almacenamiento
(`binary`) y los metadatos de nuevo en el campo. Los metadatos se leen por la interfaz C de Arrow (el
`ArrowSchema` del campo), que siempre los lleva; pyarrow no los expone para un tipo registrado en C++.
No se toca el registro ajeno (ADR-0011).
"""

from __future__ import annotations

import ctypes
import struct
from typing import Any

import pyarrow as pa

_NAME = b"ARROW:extension:name"
_METADATA = b"ARROW:extension:metadata"


class _ArrowSchema(ctypes.Structure):
    """`struct ArrowSchema` de la interfaz C de Arrow (solo se leen `metadata` y los campos previos)."""


_ArrowSchema._fields_ = [
    ("format", ctypes.c_char_p),
    ("name", ctypes.c_char_p),
    ("metadata", ctypes.c_void_p),
    ("flags", ctypes.c_int64),
    ("n_children", ctypes.c_int64),
    ("children", ctypes.c_void_p),
    ("dictionary", ctypes.c_void_p),
    ("release", ctypes.c_void_p),
    ("private_data", ctypes.c_void_p),
]

_get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
_get_pointer.restype = ctypes.c_void_p
_get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]


def _c_metadata(field: pa.Field) -> dict[bytes, bytes]:
    """Metadatos del campo tal como los exporta Arrow por la interfaz C (incluye los de la extensión)."""
    capsule = field.__arrow_c_schema__()  # se libera con la cápsula
    schema = _ArrowSchema.from_address(_get_pointer(capsule, b"arrow_schema"))
    out: dict[bytes, bytes] = {}
    if not schema.metadata:
        return out
    address = schema.metadata
    (count,) = struct.unpack("<i", ctypes.string_at(address, 4))
    address += 4
    for _ in range(count):
        (size,) = struct.unpack("<i", ctypes.string_at(address, 4))
        key = ctypes.string_at(address + 4, size)
        address += 4 + size
        (size,) = struct.unpack("<i", ctypes.string_at(address, 4))
        value = ctypes.string_at(address + 4, size)
        address += 4 + size
        out[key] = value
    return out


def plain_field(field: pa.Field) -> pa.Field:
    if not isinstance(field.type, pa.BaseExtensionType):
        return field
    metadata = dict(field.metadata or {})
    metadata.update(_c_metadata(field))
    metadata.setdefault(_NAME, field.type.extension_name.encode())
    return pa.field(field.name, field.type.storage_type, field.nullable, metadata)


def plain_batch(batch: Any) -> Any:
    """El lote sin tipos de extensión: cada uno, su almacenamiento con sus metadatos en el campo."""
    if not any(isinstance(f.type, pa.BaseExtensionType) for f in batch.schema):
        return batch
    fields = [plain_field(f) for f in batch.schema]
    arrays = [c.storage if isinstance(c.type, pa.BaseExtensionType) else c for c in batch.columns]
    return pa.RecordBatch.from_arrays(arrays, schema=pa.schema(fields, metadata=batch.schema.metadata))
