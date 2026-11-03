# SPDX-License-Identifier: GPL-2.0-or-later
"""Cuadernos de celdas SQL (G7 · Notebook, GD-NB-001..005; sql-editor-spec §7 «G7 · Notebook»).

Modelo sin Qt: qué celdas hay, en qué orden, con qué SQL y qué base. La ejecución la hace la sesión única
(`SessionCoordinator.execute_sql(..., database=celda.database)`); «Ejecutar todo» la ordena
`geoduck.app.notebook_runner`. Nada aquí ejecuta SQL ni se guarda en disco (GD-SQL-008).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from geoduck.domain.catalog import CatalogSnapshot, catalog_key
from geoduck.domain.errors import InvalidArgumentError
from geoduck.domain.i18n import tr

_ids = itertools.count(1)


@dataclass
class Cell:
    """Una celda: su SQL y su base (`None`: la base en uso de la sesión)."""

    sql: str = ""
    database: str | None = None
    id: int = field(default_factory=lambda: next(_ids))

    def database_problem(self, catalog: CatalogSnapshot | None) -> str | None:
        """Motivo por el que la celda no se puede ejecutar con su base, o `None` si se puede."""
        if self.database is None:
            return None
        if catalog is None or catalog.get(self.database) is None:
            return tr("The database «{0}» of the cell is no longer attached: choose another one").format(
                self.database
            )
        return None

    def follow_use(self, current_database: str | None, catalog: CatalogSnapshot | None) -> None:
        """Tras ejecutarla: si un `USE` escrito en la celda cambió la base, el selector lo refleja."""
        if current_database is None or self.database is None:
            return
        if catalog_key(current_database) != catalog_key(self.database):
            listed = catalog.get(current_database) if catalog is not None else None
            self.database = listed.name if listed is not None else current_database


@dataclass
class Notebook:
    """Cuaderno: nombre y celdas en orden. Siempre tiene al menos una celda."""

    name: str
    cells: list[Cell] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.cells:
            self.cells.append(Cell())

    def index_of(self, cell_id: int) -> int:
        for i, cell in enumerate(self.cells):
            if cell.id == cell_id:
                return i
        raise InvalidArgumentError(f"La celda {cell_id} no está en el cuaderno")

    def insert(self, index: int, database: str | None = None, sql: str = "") -> Cell:
        """Celda nueva en `index` (0 = la primera; `len(cells)` = al final)."""
        cell = Cell(sql=sql, database=database)
        self.cells.insert(max(0, min(index, len(self.cells))), cell)
        return cell

    def duplicate(self, cell_id: int) -> Cell:
        source = self.cells[self.index_of(cell_id)]
        return self.insert(self.index_of(cell_id) + 1, source.database, source.sql)

    def move(self, cell_id: int, target: int) -> None:
        """Mueve la celda a la posición `target` (texto, base y resultado van con ella; nada se ejecuta)."""
        cell = self.cells.pop(self.index_of(cell_id))
        self.cells.insert(max(0, min(target, len(self.cells))), cell)

    def remove(self, cell_id: int) -> Cell:
        """Quita la celda; si era la última, queda una vacía con la misma base."""
        cell = self.cells.pop(self.index_of(cell_id))
        if not self.cells:
            self.cells.append(Cell(database=cell.database))
        return cell
