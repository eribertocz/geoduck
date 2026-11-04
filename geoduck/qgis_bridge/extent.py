# SPDX-License-Identifier: GPL-2.0-or-later
"""Extensión de la geometría de una capa Conectada (qgis-bridge-spec §5), en el worker.

- Con `spatial` cargada (solo si el usuario la activó, ADR-0011): `ST_Extent_Agg`, exacta y rápida.
- Sin ella, para una tabla entera: `stats(geom)` de la columna (instantánea). Ojo: son las estadísticas de
  la columna, no de la consulta: con un `WHERE` dan la extensión de **toda** la tabla (verificado en DuckDB
  1.5.0 y 2.0.0). Por eso, para lo filtrado (Capa → Filtrar…), un recorrido de la geometría de las filas
  filtradas.
"""

from __future__ import annotations

import math
import re
from typing import Any

from qgis.core import QgsGeometry

Box = tuple[float, float, float, float]
_STATS_AXIS = re.compile(r"(?P<axis>[XY]): \[(?P<lo>[^,\]]+), (?P<hi>[^\]]+)\]")


def extent_from_stats(value: Any) -> Box | None:
    """Extensión desde `stats(geom)`: dict en DuckDB 2.x, texto en 1.5."""
    try:
        if isinstance(value, dict):
            e = value.get("extent") or {}
            box = (float(e["x_min"]), float(e["y_min"]), float(e["x_max"]), float(e["y_max"]))
        else:
            axes = {m["axis"]: (float(m["lo"]), float(m["hi"])) for m in _STATS_AXIS.finditer(str(value))}
            box = (axes["X"][0], axes["Y"][0], axes["X"][1], axes["Y"][1])
    except (KeyError, TypeError, ValueError):
        return None
    finite = all(math.isfinite(v) for v in box)
    return box if finite and box[0] <= box[2] and box[1] <= box[3] else None


def scan_extent(handle: Any, token: Any, sql: str) -> Box | None:
    """Extensión exacta recorriendo la geometría (primera columna de `sql`) una vez; ignora nulas y vacías."""
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    with handle.arrow_batches(sql, batch_size=65_536) as reader:
        for batch in reader:
            token.raise_if_cancelled()
            for wkb in batch.column(0).to_pylist():
                if wkb is None:
                    continue
                g = QgsGeometry()
                g.fromWkb(wkb)
                if g.isNull() or g.isEmpty():
                    continue
                box = g.boundingBox()
                xmin, ymin = min(xmin, box.xMinimum()), min(ymin, box.yMinimum())
                xmax, ymax = max(xmax, box.xMaximum()), max(ymax, box.yMaximum())
    finite = all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax))
    return (xmin, ymin, xmax, ymax) if finite else None


def spatial_loaded(handle: Any) -> bool:
    out = handle.execute(
        "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'", max_rows=1
    )
    return bool(out.rows and out.rows[0][0])


def filtered_extent(handle: Any, token: Any, base: str, column: str) -> Box | None:
    """Extensión exacta de la columna de geometría `column` (ya citada) de las filas de `base`."""
    if spatial_loaded(handle):
        box = handle.execute(
            f"SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM "
            f"(SELECT ST_Extent_Agg({column}) AS e FROM (\n{base}\n) AS __geoduck_e)",
            max_rows=1,
        ).rows[0]
        return tuple(float(v) for v in box) if None not in box else None  # type: ignore[return-value]
    return scan_extent(handle, token, f"SELECT {column} FROM (\n{base}\n) AS __geoduck_e")
