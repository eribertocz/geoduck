# SPDX-License-Identifier: GPL-2.0-or-later
"""Enviar capas de QGIS a DuckDB: la escritura por lotes en el worker (G8 · E1; qgis-import-spec §4, §5.3).

Una operación serial del worker recibe lotes Arrow de un `BatchChannel` (los produce, en E2, una `QgsTask`
que lee las capas) y los escribe en **una transacción**:

1. comprueba que la sesión no tenga una transacción del usuario abierta (un `BEGIN` dentro de otra la
   aborta: F-30) y hace `BEGIN`;
2. el primer lote de cada capa crea la tabla con `CREATE [OR REPLACE] TABLE … AS SELECT` (sin `spatial` no se
   puede declarar `GEOMETRY('EPSG:…')`, pero `ST_SetCRS` sí: F-115) o, al añadir, `INSERT … BY NAME`; los
   demás lotes, `INSERT … BY NAME`;
3. comprueba que cada tabla tenga exactamente las filas enviadas (al añadir: las de antes más las enviadas);
4. `COMMIT`. Ante cualquier error, cancelación o abandono del productor: `ROLLBACK` y nada cambia.

Cada lote del canal es `(índice de la capa, pyarrow.RecordBatch)`. Toda capa envía al menos un lote (vacío
si no tiene entidades), para que su tabla se cree con sus columnas.
"""

from __future__ import annotations

import contextlib
import queue
import re
from typing import TYPE_CHECKING, Any

import pyarrow as pa

from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.errors import EngineError, InvalidArgumentError, TransactionError
from geoduck.domain.i18n import tr
from geoduck.domain.importing import (
    BATCH_VIEW,
    SELECTION_VIEW,
    ImportedTable,
    ImportJob,
    ImportMode,
    ImportReport,
)
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.engine.sql import run_in_database
from geoduck.engine.transactions import probe_transaction

if TYPE_CHECKING:
    from geoduck.domain.channel import BatchChannel
    from geoduck.engine.worker import CancelToken, ConnectionHandle

_WAIT = 0.05


def stores_geometry_crs(handle: ConnectionHandle, database: str) -> bool:
    """La base guarda el SRC de una geometría. Un archivo con formato `v1.0.0+` (el que crea DuckDB 1.5.x por
    defecto) no puede (F-120): «GEOMETRY columns with coordinate reference system identifiers are not
    supported in storage versions prior v1.5.0». Las bases en memoria y las temporales, sí."""
    rows = handle.execute(
        "SELECT tags['storage_version'] FROM duckdb_databases() WHERE database_name = "
        + quote_string_literal(database),
        max_rows=1,
    ).rows
    version = str(rows[0][0]) if rows and rows[0][0] is not None else ""
    match = re.match(r"v(\d+)\.(\d+)", version)
    return match is None or (int(match.group(1)), int(match.group(2))) >= (1, 5)


def _write_from_sql(handle: ConnectionHandle, job: ImportJob) -> int:
    """Escribe una capa del camino SQL en la base de su consulta; devuelve las filas de la consulta."""
    assert job.source_sql is not None
    source = job.source_sql

    def write() -> int:
        rows = handle.execute(f"SELECT count(*) FROM ({source}) AS __geoduck_src", max_rows=1).rows
        handle.execute(job.source_write_sql(), max_rows=1)
        return int(str(rows[0][0]))

    if job.selection is not None:  # la selección, como tabla Arrow unida con `JOIN` (F-119)
        with handle.registered(SELECTION_VIEW, job.selection):
            return run_in_database(handle, job.source_database, write)

    return run_in_database(handle, job.source_database, write)


def _count(handle: ConnectionHandle, job: ImportJob) -> int:
    rows = handle.execute(f"SELECT count(*) FROM {job.qualified}", max_rows=1).rows
    return int(str(rows[0][0]))


def import_batches(
    handle: ConnectionHandle,
    token: CancelToken,
    jobs: list[ImportJob],
    channel: BatchChannel[Any],
) -> ImportReport:
    if probe_transaction(handle).is_open:
        channel.abandon()
        raise TransactionError(
            tr("The session has an open transaction: commit or roll it back before sending layers")
        )
    # Antes de escribir nada: un SRC que la base no puede guardar es una decisión del usuario (F-120)
    for job in jobs:
        has_crs = job.geometry is not None and bool(job.geometry.crs)
        if has_crs and not job.temporary and not stores_geometry_crs(handle, job.database):
            channel.abandon()
            raise InvalidArgumentError(
                tr(
                    "The database «{0}» uses an older file format that cannot store the CRS of a "
                    "geometry: send the layer without CRS or choose another database"
                ).format(job.database)
            )
    handle.execute("BEGIN")
    try:
        before = {i: _count(handle, job) for i, job in enumerate(jobs) if job.mode is ImportMode.APPEND}
        sent = dict.fromkeys(range(len(jobs)), 0)
        started: set[int] = set()
        for i, job in enumerate(jobs):  # camino SQL: DuckDB copia sin pasar por QGIS (§5.1, §5.2)
            if job.by_sql:
                token.raise_if_cancelled()
                sent[i] = _write_from_sql(handle, job)
                started.add(i)
        while True:
            token.raise_if_cancelled()
            try:
                more, item = channel.get(timeout=_WAIT)
            except queue.Empty:
                continue
            if not more:
                break
            assert item is not None
            index, batch = item
            job = jobs[index]
            table = pa.Table.from_batches([batch]) if isinstance(batch, pa.RecordBatch) else batch
            sql = job.next_batch_sql() if index in started else job.first_batch_sql()
            with handle.registered(BATCH_VIEW, table):
                handle.execute(sql, max_rows=1)
            started.add(index)
            sent[index] += table.num_rows
        missing = [job.layer_name for i, job in enumerate(jobs) if i not in started]
        if missing:
            raise EngineError(tr("No data arrived for: {0}").format(", ".join(missing)))
        tables = []
        for i, job in enumerate(jobs):  # 3. conteo: nunca éxito con filas de más o de menos
            expected = before.get(i, 0) + sent[i]
            got = _count(handle, job)
            if got != expected:
                raise EngineError(
                    tr("Row count mismatch in {0}: {1} expected, {2} found").format(
                        job.display, expected, got
                    )
                )
            tables.append(ImportedTable(job.display, job.qualified, job.mode, sent[i]))
        crs_lost = _geometry_without_crs(handle, jobs)
        handle.execute("COMMIT")
    except BaseException:
        channel.abandon()  # el productor deja de leer la capa
        with contextlib.suppress(Exception):  # el worker verifica la conexión después de cada operación
            handle.execute("ROLLBACK")
        raise
    return ImportReport(tuple(tables), tuple(crs_lost))


def _geometry_without_crs(handle: ConnectionHandle, jobs: list[ImportJob]) -> list[str]:
    """Avisos de tablas cuya geometría quedó sin SRC porque la capa no tenía (nunca se inventa: C4)."""
    out = []
    for job in jobs:
        if job.geometry is None or job.geometry.crs:
            continue
        column = quote_identifier(job.geometry.name)
        rows = handle.execute(f"DESCRIBE SELECT {column} FROM {job.qualified}", max_rows=1).rows
        if rows and is_geometry_type(str(rows[0][1])) and "(" not in str(rows[0][1]):
            out.append(tr("{0}: the geometry has no CRS (the layer had none)").format(job.display))
    return out
