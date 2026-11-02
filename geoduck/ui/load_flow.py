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
    LoadMode.MEMORY: tr("Copia en memoria"),
    LoadMode.SNAPSHOT: tr("Copia rápida"),
    LoadMode.CONNECTED: tr("Conectada"),
}


def _count(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def finished_message(report: LoadReport) -> str:
    """Mensaje al terminar una carga: capa, modalidad y entidades; origen y acceso; avisos."""
    lines = [
        tr("Capa «{}» cargada · {} · {} entidades").format(
            report.layer_name, _MODES[report.mode], _count(report.rows)
        )
    ]
    if report.origin:
        access = (
            report.access[:1].upper() + report.access[1:]
            if report.mode is not LoadMode.CONNECTED
            else tr("Acceso: ") + report.access
        )
        lines.append(tr("Origen: {}").format(report.origin) + (f" · {access}" if report.access else ""))
    if report.warnings:
        lines.append(tr("Avisos: ") + "; ".join(report.warnings))
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
        self._names: dict[int, str] = {}
        self._kinds: dict[int, str | None] = {}
        self._kind: str | None = None
        self.loading = False
        self._unsubscribe = coordinator.subscribe(self._on_event)

    def start(self, sql: str, title: str, source: tuple[str, str, str] | None = None) -> None:
        """Comienza el flujo para una consulta de lectura repetible (o una tabla/vista del explorador,
        con su `source`)."""
        try:
            token = self._coordinator.prepare_load(sql)
        except GeoDuckError as exc:
            self._on_message(exc.message)
            return
        self._pending[token] = (sql, title, tuple(source) if source else None)  # type: ignore[arg-type]
        self._kinds[token] = source[3] if source and len(source) > 3 else None

    def detach(self) -> None:
        self._unsubscribe()

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, LoadPrepared) and event.token in self._pending:
            sql, title, source = self._pending.pop(event.token)
            self._kind = self._kinds.pop(event.token, None)
            self._ask(sql, title, event.plan, tuple(source[:3]) if source else None)  # type: ignore[arg-type]
        elif isinstance(event, LoadPrepareFailed) and event.token in self._pending:
            self._pending.pop(event.token)
            self._on_message(tr("No se puede cargar: ") + event.message)
            self._kinds.pop(event.token, None)
        elif isinstance(event, LoadStarted):
            self.loading = True
            self._names[event.load_id] = event.request.layer_name
            self._on_message(tr("Cargando «{}»…").format(event.request.layer_name))
        elif isinstance(event, LoadProgressed):
            name = self._names.get(event.load_id, "")
            self._on_message(tr("Cargando «{}»: {} entidades…").format(name, _count(event.rows)))
        elif isinstance(event, LoadFinished):
            self.loading = False
            self._on_message(finished_message(event.report))
        elif isinstance(event, LoadFailed):
            self.loading = False
            self._on_message(
                tr("Carga cancelada.") if event.cancelled else tr("Error al cargar: ") + event.message
            )

    def _ask(self, sql: str, title: str, plan: LoadPlan, source: tuple[str, str, str] | None = None) -> None:
        dialog = self._dialog_factory(sql, title, plan, self._coordinator.load_modes(), self._parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._coordinator.load(replace(dialog.request(), source=source, source_kind=self._kind))
        except GeoDuckError as exc:
            self._on_message(tr("No se puede cargar: ") + exc.message)
