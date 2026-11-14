# SPDX-License-Identifier: GPL-2.0-or-later
"""«Reproyectar a…» en las copias (spatial-spec §4).

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
from geoduck.domain.i18n import tr


def _label(crs: QgsCoordinateReferenceSystem) -> str:
    return crs.authid() or crs.description() or tr("Custom CRS")


class Reprojector:
    """Transforma geometrías de `source` a `target`. Se puede usar en el hilo del worker."""

    def __init__(
        self,
        source: QgsCoordinateReferenceSystem,
        target: str,
        context: QgsCoordinateTransformContext | None = None,
        *,
        sending: bool = False,
    ) -> None:
        #: «Enviar a DuckDB» (G8): el error dice que no se envió nada (no que no se cargó).
        self._sending = sending
        if not source.isValid():
            raise GeoDuckError(
                tr("To reproject, the layer needs a source CRS: choose one or turn off «Reproject to…»"),
                code=ErrorCode.INVALID_ARGUMENT,
            )
        self.target = QgsCoordinateReferenceSystem(target)
        if not self.target.isValid():
            raise GeoDuckError(
                tr("Target CRS not recognized: {0}").format(target), code=ErrorCode.INVALID_ARGUMENT
            )
        self.source = source
        ctx = context if context is not None else QgsProject.instance().transformContext()
        self._transform = QgsCoordinateTransform(source, self.target, ctx)

    @property
    def note(self) -> str:
        return tr("Reprojected from {0} to {1}").format(_label(self.source), _label(self.target))

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
        if self._sending:
            return GeoDuckError(
                tr("Feature {0} could not be reprojected from {1} to {2}: nothing was sent ({3})").format(
                    row, _label(self.source), _label(self.target), detail
                ),
                code=ErrorCode.INVALID_ARGUMENT,
            )
        return GeoDuckError(
            tr(
                "The geometry of row {0} could not be reprojected from {1} to {2}: nothing was loaded ({3})"
            ).format(row, _label(self.source), _label(self.target), detail),
            code=ErrorCode.INVALID_ARGUMENT,
        )
