# SPDX-License-Identifier: GPL-2.0-or-later
"""«Reproyectar a…» en las copias (spatial-spec §4; decisión del propietario D4, 2026-11-02).

La reproyección es de QGIS/PROJ (`QgsCoordinateTransform` con el contexto de transformación del
proyecto), nunca de DuckDB: no usa `ST_Transform` ni necesita `spatial`. Solo Memoria e Instantánea; la
Conectada no transforma (QGIS reproyecta al vuelo). Asignar un CRS no mueve coordenadas; reproyectar sí.
Si una geometría no se puede transformar, la carga falla sin publicar nada (sin pérdidas silenciosas).
"""

from __future__ import annotations

import pyarrow as pa
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsCsException,
    QgsGeometry,
    QgsProject,
)

from geoduck.domain.errors import ErrorCode, GeoDuckError


def _label(crs: QgsCoordinateReferenceSystem) -> str:
    return crs.authid() or crs.description() or "SRC personalizado"


class Reprojector:
    """Transforma geometrías de `source` a `target`. Se puede usar en el hilo del worker."""

    def __init__(
        self,
        source: QgsCoordinateReferenceSystem,
        target: str,
        context: QgsCoordinateTransformContext | None = None,
    ) -> None:
        if not source.isValid():
            raise GeoDuckError(
                "Para reproyectar, la capa necesita un SRC de origen: elija uno o desactive «Reproyectar a…»",
                code=ErrorCode.INVALID_ARGUMENT,
            )
        self.target = QgsCoordinateReferenceSystem(target)
        if not self.target.isValid():
            raise GeoDuckError(f"SRC de destino no reconocido: {target}", code=ErrorCode.INVALID_ARGUMENT)
        self.source = source
        ctx = context if context is not None else QgsProject.instance().transformContext()
        self._transform = QgsCoordinateTransform(source, self.target, ctx)

    @property
    def note(self) -> str:
        return f"Reproyectada de {_label(self.source)} a {_label(self.target)}"

    def geometry(self, g: QgsGeometry, row: int) -> QgsGeometry:
        """La misma geometría en el SRC de destino. `row`: número de fila para el error (1 = primera)."""
        out = QgsGeometry(g)
        try:
            result = out.transform(self._transform)
        except QgsCsException as exc:
            raise self._error(row, str(exc)) from exc
        if result != Qgis.GeometryOperationResult.Success:
            raise self._error(row, str(result))
        return out

    def batch(self, batch: pa.RecordBatch, column: str, offset: int) -> pa.RecordBatch:
        """El lote con la columna WKB transformada; el campo conserva su tipo y metadatos."""
        index = batch.schema.get_field_index(column)
        values = batch.column(index).to_pylist()
        out: list[bytes | None] = []
        for i, wkb in enumerate(values):
            if wkb is None:
                out.append(None)
                continue
            g = QgsGeometry()
            g.fromWkb(wkb)
            if g.isNull() or g.isEmpty():
                out.append(wkb)
                continue
            out.append(bytes(self.geometry(g, offset + i + 1).asWkb()))
        field = batch.schema.field(index)
        storage = batch.column(index).type
        storage = getattr(storage, "storage_type", storage)
        arrays = list(batch.columns)
        arrays[index] = pa.array(out, type=storage)
        if isinstance(batch.column(index).type, pa.ExtensionType):
            arrays[index] = pa.ExtensionArray.from_storage(batch.column(index).type, arrays[index])
        return pa.RecordBatch.from_arrays(arrays, schema=batch.schema.set(index, field))

    def _error(self, row: int, detail: str) -> GeoDuckError:
        return GeoDuckError(
            f"No se pudo reproyectar la geometría de la fila {row} de {_label(self.source)} a "
            f"{_label(self.target)}: no se cargó nada ({detail})",
            code=ErrorCode.INVALID_ARGUMENT,
        )
