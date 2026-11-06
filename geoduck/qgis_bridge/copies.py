# SPDX-License-Identifier: GPL-2.0-or-later
"""Capas «Copia» de GeoDuck y «Guardar las copias junto al proyecto» (workspace-pro-spec §7; GD-WSP-006).

Una «Copia» vive en memoria (Copia rápida: GeoPackage en `/vsimem`; Copia en memoria: proveedor `memory`) y
**no** sobrevive a reabrir el proyecto (spike E0b). GeoDuck marca sus copias con la propiedad `geoduck/copy`
(nunca toca otras capas en memoria del usuario, ADR-0011). `save_copies` las escribe en un GeoPackage junto al
proyecto y cada capa pasa a leer ese archivo: conserva su nombre, su estilo y su lugar en el panel.
"""

from __future__ import annotations

import re
from pathlib import Path

from qgis.core import (
    QgsCoordinateTransformContext,
    QgsMapLayer,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from geoduck.qgis_bridge.vsimem import PREFIX, unlink

COPY_PROPERTY = "geoduck/copy"


def mark_copy(layer: QgsMapLayer) -> None:
    layer.setCustomProperty(COPY_PROPERTY, "1")


def is_copy(layer: QgsMapLayer) -> bool:
    return str(layer.customProperty(COPY_PROPERTY, "")) == "1"


def copies(project: QgsProject) -> list[QgsVectorLayer]:
    """Las capas «Copia» de GeoDuck del proyecto que aún viven en memoria."""
    return [
        layer
        for layer in project.mapLayers().values()
        if isinstance(layer, QgsVectorLayer) and is_copy(layer) and _in_memory(layer)
    ]


def _in_memory(layer: QgsVectorLayer) -> bool:
    return bool(layer.providerType() == "memory" or str(layer.source()).startswith(PREFIX))


def target_for(project: QgsProject) -> Path | None:
    """El GeoPackage junto al proyecto: `<proyecto>_geoduck.gpkg`; `None` si el proyecto no tiene archivo."""
    path = project.fileName()
    if not path:
        return None
    file = Path(path)
    return file.with_name(f"{file.stem}_geoduck.gpkg")


def _table_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[^\w]+", "_", name, flags=re.UNICODE).strip("_").lower() or "capa"
    candidate, number = base, 2
    while candidate in used:
        candidate, number = f"{base}_{number}", number + 1
    used.add(candidate)
    return candidate


def save_copies(project: QgsProject, layers: list[QgsVectorLayer] | None = None) -> tuple[Path, list[str]]:
    """Escribe las copias en el GeoPackage junto al proyecto y cada capa pasa a leerlo. Devuelve el archivo
    y los errores (`capa: motivo`). No guarda el proyecto: lo hace quien llama."""
    target = target_for(project)
    if target is None:
        raise ValueError("el proyecto no tiene archivo")
    pending = copies(project) if layers is None else layers
    used: set[str] = set()
    errors: list[str] = []
    context = project.transformContext() if project is not None else QgsCoordinateTransformContext()
    for layer in pending:
        table = _table_name(layer.name(), used)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = table
        options.fileEncoding = "UTF-8"
        options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            if target.exists()
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        )
        result = QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(target), context, options)
        code, message = result[0], result[1]
        if code != QgsVectorFileWriter.WriterError.NoError:
            errors.append(f"{layer.name()}: {message}")
            continue
        old = layer.source()
        layer.setDataSource(f"{target}|layername={table}", layer.name(), "ogr")
        layer.removeCustomProperty(COPY_PROPERTY)
        if old.startswith(PREFIX) and not any(
            other.source() == old for other in project.mapLayers().values() if other is not layer
        ):
            unlink(old.split("|", 1)[0])  # el archivo en RAM ya no lo usa nadie
    return target, errors
