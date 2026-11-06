# SPDX-License-Identifier: GPL-2.0-or-later
"""Archivos y copia de recuperación de las consultas de Workspace Pro (workspace-pro-spec §5; ADR-0014).

- `read_query(ruta)`: el SQL de un `.sql`. Un cuaderno de G7 (con marcas `-- %% cell`) se abre como **una**
  consulta: sus celdas en orden y la base de cada una como comentario; la base de la consulta es la de la
  primera celda.
- `QueryRecovery`: la copia de recuperación de G7, ahora por consulta, **activada por defecto**. Tras cada
  cambio (con una espera breve) guarda el SQL y la base de cada consulta abierta en la carpeta del perfil de
  QGIS; al cerrar bien se borra. Si al abrir GeoDuck queda la copia de un QGIS que se cerró por un fallo, un
  aviso ofrece «Recuperar» o «Descartar». Solo el SQL y la base: nunca resultados ni datos.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import QObject, QTimer

from geoduck.domain.notebook import Cell, Notebook
from geoduck.domain.notebook_file import loads
from geoduck.ui.i18n import tr

#: La misma opción que la copia de los cuadernos de G7 (ADR-0014): activada salvo que el usuario la apague.
RECOVERY_SETTING = "geoduck/notebooks/recovery"
#: Espera tras el último cambio antes de copiar.
DELAY_MS = 1500
_MARKER = "-- %% cell"


def as_query(notebook: Notebook) -> tuple[str, str | None]:
    """Un cuaderno como una sola consulta: SQL y base."""
    if len(notebook.cells) == 1:
        cell = notebook.cells[0]
        return cell.sql, cell.database
    parts = []
    for cell in notebook.cells:
        head = f"-- {tr('database')}: {cell.database}\n" if cell.database else ""
        parts.append(head + cell.sql.strip("\n"))
    first = next((c.database for c in notebook.cells if c.database), None)
    return "\n\n".join(parts) + "\n", first


def read_query(path: str) -> tuple[str, str | None]:
    """SQL y base de un `.sql` (un cuaderno de G7, como una sola consulta)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    if _MARKER not in text:
        return text, None
    return as_query(loads(text, Path(path).stem))


class QueryRecovery(QObject):
    """La copia de recuperación de las consultas abiertas en un workspace."""

    def __init__(self, workspace: Any, store: Any = None) -> None:
        super().__init__(workspace)
        self._workspace = workspace
        enabled = str(QgsSettings().value(RECOVERY_SETTING, "true")).lower() not in ("false", "0")
        if store is None and enabled:
            from geoduck.ui.notebook_store import RecoveryStore  # noqa: PLC0415

            store = RecoveryStore()
        self.store = store
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DELAY_MS)
        self._timer.timeout.connect(self.save)
        self.toast: Any = None

    def schedule(self) -> None:
        if self.store is not None:
            self._timer.start()

    def save(self) -> None:
        """Copia el SQL y la base de cada consulta abierta que tenga texto."""
        if self.store is None:
            return
        notebooks = [
            Notebook(
                page.place.name,
                [Cell(sql=page.editor.text(), database=page.database)],
                page.place.path or None,
            )
            for page in self._workspace.query_pages()
            if page.editor.text().strip()
        ]
        with contextlib.suppress(OSError):
            self.store.save(notebooks)

    def offer(self) -> None:
        """Si quedó la copia de un QGIS que se cerró por un fallo, un aviso con «Recuperar» y «Descartar»."""
        if self.store is None:
            return
        orphans = self.store.orphans()
        if not orphans:
            return
        from geoduck.ui.pro.widgets import Toast  # noqa: PLC0415

        count = sum(len(self.store.read(folder)) for folder in orphans)
        if not count:
            for folder in orphans:
                self.store.discard(folder)
            return
        toast = Toast(
            self._workspace,
            tr("{} queries were not saved when QGIS closed unexpectedly").format(count),
            kind="busy",
            seconds=0,
        )
        toast.add_action(tr("Recover"), lambda: self.recover(orphans))
        toast.add_action(tr("Discard"), lambda: self.discard(orphans))
        toast.show_at_corner()
        self.toast = toast

    def recover(self, folders: list[Path]) -> None:
        """Abre cada consulta recuperada en una pestaña y borra la copia vieja."""
        for folder in folders:
            for notebook in self.store.read(folder):
                sql, database = as_query(notebook)
                self._workspace.open_recovered(notebook.name, sql, database, notebook.path)
            self.store.discard(folder)
        self.save()

    def discard(self, folders: list[Path]) -> None:
        for folder in folders:
            self.store.discard(folder)

    def stop(self) -> None:
        """Cierre normal: se borra la copia de esta sesión."""
        self._timer.stop()
        if self.store is not None:
            self.store.stop()
