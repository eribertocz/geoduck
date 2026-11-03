# SPDX-License-Identifier: GPL-2.0-or-later
"""Flujo «Cargar en QGIS» común al panel SQL y al explorador (GD-BRD-012).

1. Pide el plan de carga al coordinador (sin leer datos).
2. Muestra `LoadDialog` con las modalidades disponibles, la geometría, el CRS y los avisos.
3. Lanza la carga y comunica el progreso y el resultado.

La cancelación es la de la sesión (`cancel_current_operation`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from qgis.PyQt.QtWidgets import QDialog, QWidget

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    AppEvent,
    LoadFailed,
    LoadFinished,
    LoadPrepared,
    LoadPrepareFailed,
    LoadProgressed,
    LoadStarted,
)
from geoduck.domain.bridge_types import LoadPlan
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.load import LoadMode, LoadReport
from geoduck.ui.i18n import tr
from geoduck.ui.load_dialog import LoadDialog

_MODES = {
    LoadMode.MEMORY: tr("Memory copy"),
    LoadMode.SNAPSHOT: tr("Fast copy"),
    LoadMode.CONNECTED: tr("Connected"),
}


def _count(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def finished_message(report: LoadReport) -> str:
    """Mensaje al terminar una carga: capa, modalidad y entidades; origen y acceso; avisos."""
    if len(report.layers) > 1:  # una capa por geometría (spatial-spec §7)
        names = ", ".join(f"«{name}»" for _, name in report.layers)
        lines = [
            (
                tr("Layers {} loaded · {} · {} features each")
                if report.rows_each
                else tr("Layers {} loaded · {} · {} features in total")
            ).format(names, _MODES[report.mode], _count(report.rows))
        ]
    else:
        lines = [
            tr("Layer «{}» loaded · {} · {} features").format(
                report.layer_name, _MODES[report.mode], _count(report.rows)
            )
        ]
    if report.origin:
        access = (
            report.access[:1].upper() + report.access[1:]
            if report.mode is not LoadMode.CONNECTED
            else tr("Access: ") + report.access
        )
        lines.append(tr("Source: {}").format(report.origin) + (f" · {access}" if report.access else ""))
    if report.warnings:
        lines.append(tr("Warnings: ") + "; ".join(report.warnings))
    return "\n".join(lines)


DialogFactory = Callable[[str, str, LoadPlan, dict, QWidget | None], LoadDialog]


class LoadFlow:
    def __init__(
        self,
        coordinator: SessionCoordinator,
        on_message: Callable[[str], None],
        parent: QWidget | None = None,
        *,
        dialog_factory: DialogFactory | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._on_message = on_message
        self._parent = parent
        self._dialog_factory = dialog_factory or LoadDialog
        self._pending: dict[int, tuple[str, str, tuple[str, str, str] | None]] = {}
        self._modes: dict[int, LoadMode | None] = {}
        self._names: dict[int, str] = {}
        self._databases: dict[int, str | None] = {}
        self._kinds: dict[int, str | None] = {}
        self._kind: str | None = None
        self.loading = False
        self._unsubscribe = coordinator.subscribe(self._on_event)

    def start(
        self,
        sql: str,
        title: str,
        source: tuple[str, str, str] | None = None,
        mode: LoadMode | None = None,
        database: str | None = None,
    ) -> None:
        """Comienza el flujo para una consulta de lectura repetible (o una tabla/vista del explorador,
        con su `source`). Con `mode` («Cargar en QGIS ▾»), el diálogo se abre con esa modalidad marcada.
        `database` (G7): base donde se ejecutó el resultado de la celda; la consulta se repite en ella."""
        try:
            token = self._coordinator.prepare_load(sql, database=database)
        except GeoDuckError as exc:
            self._on_message(exc.message)
            return
        self._pending[token] = (sql, title, tuple(source) if source else None)  # type: ignore[arg-type]
        self._databases[token] = database
        self._kinds[token] = source[3] if source and len(source) > 3 else None
        self._modes[token] = mode

    def detach(self) -> None:
        self._unsubscribe()

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, LoadPrepared) and event.token in self._pending:
            sql, title, source = self._pending.pop(event.token)
            self._kind = self._kinds.pop(event.token, None)
            mode = self._modes.pop(event.token, None)
            database = self._databases.pop(event.token, None)
            origin = tuple(source[:3]) if source else None
            self._ask(sql, title, event.plan, origin, mode, database=database)  # type: ignore[arg-type]
        elif isinstance(event, LoadPrepareFailed) and event.token in self._pending:
            self._pending.pop(event.token)
            self._on_message(tr("Cannot load: ") + event.message)
            self._kinds.pop(event.token, None)
            self._modes.pop(event.token, None)
            self._databases.pop(event.token, None)
        elif isinstance(event, LoadStarted):
            self.loading = True
            self._names[event.load_id] = event.request.layer_name
            self._on_message(tr("Loading «{}»…").format(event.request.layer_name))
        elif isinstance(event, LoadProgressed):
            name = self._names.get(event.load_id, "")
            self._on_message(tr("Loading «{}»: {} features…").format(name, _count(event.rows)))
        elif isinstance(event, LoadFinished):
            self.loading = False
            self._on_message(finished_message(event.report))
        elif isinstance(event, LoadFailed):
            self.loading = False
            self._on_message(
                tr("Loading cancelled.") if event.cancelled else tr("Loading error: ") + event.message
            )

    def _ask(
        self,
        sql: str,
        title: str,
        plan: LoadPlan,
        source: tuple[str, str, str] | None = None,
        mode: LoadMode | None = None,
        *,
        database: str | None = None,
    ) -> None:
        dialog = self._dialog_factory(sql, title, plan, self._coordinator.load_modes(), self._parent)
        if mode is not None:
            dialog.select_mode(mode)  # el resto del diálogo de G4 no cambia
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._coordinator.load(
                replace(dialog.request(), source=source, source_kind=self._kind, database=database)
            )
        except GeoDuckError as exc:
            self._on_message(tr("Cannot load: ") + exc.message)
