# SPDX-License-Identifier: GPL-2.0-or-later
"""«Exportar ▾» con la consulta completa, siempre con el motor de DuckDB (G7 · E3, GD-NB-007; G9:
qgis-import-spec §10, decisión del propietario, 2026-11-07; `geoduck.domain.export`).

- CSV, JSON y Parquet: `COPY (<consulta>) TO … (FORMAT …)`, incluidos en DuckDB.
- Arrow/Feather: el lector Arrow de DuckDB escrito por PyArrow, por lotes.
- GeoPackage, FlatGeobuf, Shapefile, GeoJSON, KML, Geodatabase y Excel: `COPY … (FORMAT gdal, DRIVER …)` de
  la extensión `spatial`. Si no está cargada, solo con el permiso del usuario (`allow_spatial`, spatial-spec
  §10). Con un SRC en la geometría, DuckDB 2.0 exige fijar `geometry_always_xy`: si el usuario no lo fijó,
  GeoDuck lo pone en `true` (orden este-norte, el de DuckDB) **solo durante la exportación** y lo deja como
  estaba (decisión del propietario, 2026-11-07); si el usuario lo fijó, no se toca.

Todo se escribe primero en una carpeta temporal junto al destino y, si termina bien, se mueve al lugar
elegido (un Shapefile son varios archivos; una Geodatabase, una carpeta): si se cancela o falla, no queda
nada a medias y lo que ya existía no se toca hasta el final (la confirmación la pide el diálogo de archivo).
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.completion import blank_code
from geoduck.domain.errors import InvalidArgumentError
from geoduck.domain.export import (
    GEOMETRY_TYPES,
    ExportFormat,
    ExportReport,
    ExportRequest,
    copy_options,
    gdal_select,
)
from geoduck.domain.i18n import tr
from geoduck.domain.sql_text import load_sql, quote_identifier, quote_string_literal
from geoduck.engine.bridge_read import describe_query
from geoduck.engine.spatial import activate_spatial, spatial_state

if TYPE_CHECKING:
    from geoduck.engine.worker import CancelToken, ConnectionHandle

#: Filas por lote al escribir Arrow.
ARROW_BATCH = 100_000
#: Archivos que acompañan a un Shapefile.
SHP_PARTS = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx")


def temporary_path(target: Path) -> Path:
    """Archivo temporal oculto junto al destino (mismo disco, para que el renombrado sea atómico)."""
    return target.with_name(f".{target.name}.geoduck-{uuid.uuid4().hex[:8]}.tmp")


def _replace_into(written: Path, target: Path) -> None:
    """Mueve lo escrito en la carpeta temporal a su destino (archivo, carpeta o las partes del Shapefile)."""
    if written.is_dir():  # Geodatabase
        if target.exists():
            shutil.rmtree(target)
        os.replace(written, target)
        return
    if target.suffix.lower() == ".shp":
        for part in SHP_PARTS:
            source = written.with_suffix(part)
            old = target.with_suffix(part)
            if source.exists():
                os.replace(source, old)
            elif old.exists():  # una parte vieja que ya no corresponde (p. ej. otro .prj)
                old.unlink()
        return
    os.replace(written, target)


def _geometry_type(handle: ConnectionHandle, body: str, column: str) -> str:
    """El tipo único de la geometría (GDAL lo exige en una Geodatabase)."""
    rows = handle.execute(
        f"SELECT DISTINCT upper(ST_GeometryType({quote_identifier(column)})::VARCHAR) "
        f"FROM (\n{body}\n) AS geoduck_q WHERE {quote_identifier(column)} IS NOT NULL LIMIT 3",
        max_rows=3,
    ).rows
    kinds = sorted({str(r[0]) for r in rows})
    if len(kinds) > 1:
        raise InvalidArgumentError(
            tr("The geometry mixes types ({0}): this format accepts only one").format(", ".join(kinds))
        )
    return GEOMETRY_TYPES.get(kinds[0], "GEOMETRY") if kinds else "GEOMETRY"


_ORDER_BY = re.compile(r"\border\s+by\b", re.IGNORECASE)


def has_order_by(sql: str) -> bool:
    """La consulta pide un orden: `ORDER BY` fuera de comentarios y cadenas, en cualquier nivel."""
    return bool(_ORDER_BY.search(blank_code(sql)[0]))


def _insertion_order(handle: ConnectionHandle) -> bool:
    rows = handle.execute(
        "SELECT value FROM duckdb_settings() WHERE name = 'preserve_insertion_order'", max_rows=1
    ).rows
    return not rows or str(rows[0][0]).lower() == "true"


def _axis_setting(handle: ConnectionHandle) -> str | None:
    rows = handle.execute(
        "SELECT value FROM duckdb_settings() WHERE name = 'geometry_always_xy'", max_rows=1
    ).rows
    return None if not rows or rows[0][0] is None else str(rows[0][0])


def _write_arrow(handle: ConnectionHandle, token: CancelToken, body: str, path: Path) -> int:
    import pyarrow as pa  # noqa: PLC0415 - solo al exportar Arrow

    rows = 0
    with (
        handle.arrow_batches(body, batch_size=ARROW_BATCH) as reader,
        pa.OSFile(str(path), "wb") as sink,
        pa.ipc.new_file(sink, reader.schema) as writer,
    ):
        for batch in reader:
            token.raise_if_cancelled()
            writer.write_batch(batch)
            rows += batch.num_rows
    return rows


def export_query(handle: ConnectionHandle, token: CancelToken, request: ExportRequest) -> ExportReport:
    body = load_sql(request.sql)  # sin el `;` ni los comentarios finales de la sentencia de la celda
    fmt = request.format
    if fmt.needs_spatial:
        state = spatial_state(handle)
        if not state.loaded:
            if not request.allow_spatial:
                raise InvalidArgumentError(
                    tr("{0} is written with the «spatial» extension, which is not loaded").format(fmt.label)
                )
            activate_spatial(handle, install=not state.installed)  # el usuario lo aceptó (spatial-spec §10)
    columns = describe_query(handle, body)
    options, warnings = copy_options(columns, fmt)
    target = Path(request.path)
    # Sin el nombre del destino: GDAL confunde una carpeta «….xlsx.…» con el archivo (Excel no se guarda)
    folder = target.with_name(f".geoduck-export-{uuid.uuid4().hex[:8]}")
    folder.mkdir()
    written = folder / target.name
    restore_axis = False
    # Cancelar al instante (performance-spec §3; medido: 4 ms–3,3 s con orden, 14–77 ms sin orden): mantener
    # el orden de inserción hace que los hilos de DuckDB se esperen entre sí al cancelar. Sin `ORDER BY`, SQL
    # no garantiza un orden, así que se apaga **solo durante la exportación** y se deja como estaba (decisión
    # del propietario, 2026-11-12); con `ORDER BY`, DuckDB lo respeta igual. Si el usuario lo apagó, queda.
    restore_order = fmt is not ExportFormat.ARROW and not has_order_by(body) and _insertion_order(handle)
    if restore_order:
        handle.execute("SET preserve_insertion_order = false", max_rows=1)
    try:
        token.raise_if_cancelled()
        if fmt is ExportFormat.ARROW:
            rows = _write_arrow(handle, token, body, written)
        else:
            select = body
            if fmt.needs_spatial:
                select = gdal_select(body, columns, fmt)
                geometries = [name for name, kind in columns if is_geometry_type(kind)]
                if fmt is ExportFormat.GDB and geometries:
                    kind = _geometry_type(handle, body, geometries[0])
                    options += f", GEOMETRY_TYPE {quote_string_literal(kind)}"
                with_crs = any("(" in kind for name, kind in columns if is_geometry_type(kind))
                if with_crs and _axis_setting(handle) is None:
                    handle.execute("SET geometry_always_xy = true", max_rows=1)
                    restore_axis = True
            out = handle.execute(
                f"COPY (\n{select}\n) TO {quote_string_literal(str(written))} ({options})", max_rows=1
            )
            count = out.rows[0][0] if out.rows and out.rows[0] else None  # COPY devuelve las filas escritas
            rows = int(str(count)) if count is not None else 0
        token.raise_if_cancelled()
        _replace_into(written, target)
    finally:
        if restore_order:
            handle.execute("SET preserve_insertion_order = true", max_rows=1)
        if restore_axis:
            handle.execute("RESET geometry_always_xy", max_rows=1)  # como estaba: sin fijar
        shutil.rmtree(folder, ignore_errors=True)
    return ExportReport(str(target), fmt, rows, warnings)
