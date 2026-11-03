# SPDX-License-Identifier: GPL-2.0-or-later
"""«Exportar ▾» a CSV o Parquet con la consulta completa (G7 · E3, GD-NB-007; `geoduck.domain.export`).

`COPY (<consulta>) TO <temporal>` en la misma carpeta y, si termina bien, se renombra al archivo elegido: si
se cancela o falla, no queda un archivo a medias y uno que ya existía no se toca (DuckDB sobrescribe sin
avisar; la confirmación la pide el diálogo de archivo). Parquet viene incluido en DuckDB: no se instala
ni carga nada (ADR-0011).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from geoduck.domain.export import ExportReport, ExportRequest, copy_options
from geoduck.domain.sql_text import load_sql, quote_string_literal
from geoduck.engine.bridge_read import describe_query

if TYPE_CHECKING:
    from geoduck.engine.worker import CancelToken, ConnectionHandle


def temporary_path(target: Path) -> Path:
    """Archivo temporal oculto junto al destino (mismo disco, para que el renombrado sea atómico)."""
    return target.with_name(f".{target.name}.geoduck-{uuid.uuid4().hex[:8]}.tmp")


def export_query(handle: ConnectionHandle, token: CancelToken, request: ExportRequest) -> ExportReport:
    body = load_sql(request.sql)  # sin el `;` ni los comentarios finales de la sentencia de la celda
    options, warnings = copy_options(describe_query(handle, body), request.format)
    target = Path(request.path)
    partial = temporary_path(target)
    try:
        token.raise_if_cancelled()
        out = handle.execute(
            f"COPY (\n{body}\n) TO {quote_string_literal(str(partial))} ({options})", max_rows=1
        )
        token.raise_if_cancelled()
        os.replace(partial, target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    count = out.rows[0][0] if out.rows and out.rows[0] else None  # COPY devuelve las filas escritas
    rows = int(str(count)) if count is not None else 0
    return ExportReport(str(target), request.format, rows, warnings)
