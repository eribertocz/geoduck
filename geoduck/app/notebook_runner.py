# SPDX-License-Identifier: GPL-2.0-or-later
"""Ejecución de celdas de un cuaderno (G7 · E1, GD-NB-001/002; sql-editor-spec §7 «G7 · Notebook»).

Cada celda se ejecuta como un script (`RunScope.ALL`) con su base: el coordinador hace `USE` de ella y luego
el SQL, en una sola operación del worker. «Ejecutar todo» recorre las celdas en orden y se detiene en la
primera que falla, se rechaza o se cancela; las siguientes quedan sin ejecutar. La siguiente celda se encola
con el `dispatcher`, después de que el coordinador termine de procesar la anterior (p. ej. releer el
catálogo tras `CREATE` o tras el cambio de base).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import AppEvent, ScriptFinished, ScriptRejected
from geoduck.app.ports import Dispatcher
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.notebook import Cell
from geoduck.domain.sql import DEFAULT_PREVIEW_LIMIT, RunScope, ScriptRun


@dataclass
class CellOutcome:
    cell: Cell
    run: ScriptRun | None = None
    #: Motivo si la celda no llegó a ejecutarse (base desadjuntada, petición rechazada…).
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.run is not None and not self.run.failed


@dataclass
class _Batch:
    cells: list[Cell]
    preview_limit: int
    outcomes: list[CellOutcome] = field(default_factory=list)


class NotebookRunner:
    """Ejecuta una celda o varias en orden. Las respuestas llegan por `on_cell` (cada celda) y `on_done`
    (todas: la lista de resultados, más corta que las celdas si se detuvo)."""

    def __init__(self, coordinator: SessionCoordinator, dispatcher: Dispatcher) -> None:
        self._coordinator = coordinator
        self._dispatcher = dispatcher
        self._batch: _Batch | None = None
        self._current: Cell | None = None
        self.on_cell: Callable[[CellOutcome], None] = lambda _o: None
        self.on_done: Callable[[list[CellOutcome]], None] = lambda _o: None
        self._unsubscribe = coordinator.subscribe(self._on_event)

    @property
    def running(self) -> bool:
        return self._batch is not None

    def run(self, cells: Sequence[Cell], *, preview_limit: int = DEFAULT_PREVIEW_LIMIT) -> bool:
        """Ejecuta `cells` en orden (una sola: «Ejecutar celda»). Las vacías se saltan. Devuelve si empezó."""
        if self._batch is not None:
            return False
        self._batch = _Batch([c for c in cells if c.sql.strip()], preview_limit)
        self._next()
        return True

    def _next(self) -> None:
        batch = self._batch
        if batch is None:
            return
        if len(batch.outcomes) == len(batch.cells):
            self._finish()
            return
        cell = batch.cells[len(batch.outcomes)]
        problem = cell.database_problem(self._coordinator.catalog)
        if problem is not None:
            self._record(CellOutcome(cell, error=problem))
            return
        self._current = cell
        try:
            self._coordinator.execute_sql(
                cell.sql, RunScope.ALL, preview_limit=batch.preview_limit, database=cell.database
            )
        except GeoDuckError as exc:  # p. ej. sesión ocupada o DETACH con capas Conectadas sin guardar
            self._current = None
            self._record(CellOutcome(cell, error=exc.message))

    def _on_event(self, event: AppEvent) -> None:
        cell = self._current
        if cell is None:
            return
        if isinstance(event, ScriptFinished):
            self._current = None
            cell.follow_use(event.run.current_database, self._coordinator.catalog)
            self._record(CellOutcome(cell, run=event.run))
        elif isinstance(event, ScriptRejected):
            self._current = None
            self._record(CellOutcome(cell, error=event.message))

    def _record(self, outcome: CellOutcome) -> None:
        batch = self._batch
        if batch is None:
            return
        batch.outcomes.append(outcome)
        self.on_cell(outcome)
        if not outcome.ok:
            self._finish()
            return
        self._dispatcher.post(self._next)  # tras lo que el coordinador haga con esta celda

    def _finish(self) -> None:
        batch, self._batch = self._batch, None
        if batch is not None:
            self.on_done(batch.outcomes)

    def detach(self) -> None:
        self._unsubscribe()
