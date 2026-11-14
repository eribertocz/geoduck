# SPDX-License-Identifier: GPL-2.0-or-later
"""Cuaderno como archivo `.sql` (G7; ADR-0014).

Un archivo SQL normal: cada celda empieza con una línea de comentario que marca la celda y su base.

    -- %% cell · database: db
    SELECT consumidor, medidor FROM main.consumidores LIMIT 3;

    -- %% cell · database: memory
    SELECT * FROM db.main.tabla2;

Como las marcas son comentarios, el archivo se abre en cualquier editor y corre tal cual en DuckDB. Al leerlo
también se aceptan `celda` y `base` (en español). Un `.sql` sin marcas se abre como una sola celda; el texto
antes de la primera marca, si lo hay, es una celda sin base. Una línea del SQL que empiece por `-- %% cell`
partiría la celda al volver a abrirla.
"""

from __future__ import annotations

import re

from geoduck.domain.notebook import Cell, Notebook

#: Extensión de los cuadernos guardados.
SUFFIX = ".sql"
_MARKER = re.compile(r"^--\s*%%\s*(?:cell|celda)\b(?P<rest>.*)$", re.IGNORECASE)
_DATABASE = re.compile(r"(?:database|base)\s*:\s*(?P<name>.+?)\s*$", re.IGNORECASE)


def dumps(notebook: Notebook) -> str:
    """El texto del archivo: una marca y el SQL de cada celda, separadas por una línea en blanco."""
    parts = []
    for cell in notebook.cells:
        marker = "-- %% cell" + (f" · database: {cell.database}" if cell.database else "")
        parts.append(marker + "\n" + cell.sql.strip("\n") + "\n")
    return "\n".join(parts)


def loads(text: str, name: str) -> Notebook:
    """El cuaderno de un archivo (`name`: su nombre, p. ej. el del archivo sin extensión)."""
    cells: list[Cell] = []
    database: str | None = None
    lines: list[str] = []
    started = False

    def close() -> None:
        sql = "\n".join(lines).strip("\n")
        if started or sql.strip():
            cells.append(Cell(sql=sql, database=database))

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _MARKER.match(line.strip())
        if match is None:
            lines.append(line)
            continue
        close()
        started = True
        lines = []
        found = _DATABASE.search(match.group("rest"))
        database = found.group("name") if found else None
    close()
    return Notebook(name, cells or [Cell()])
