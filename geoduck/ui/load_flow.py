# SPDX-License-Identifier: GPL-2.0-or-later
"""Flujo «Cargar en QGIS» común al panel SQL y al explorador (GD-BRD-012).

1. Pide el plan de carga al coordinador (sin leer datos).
2. Muestra `LoadDialog` con las modalidades disponibles, la geometría, el CRS y los avisos.
3. Lanza la carga y comunica el progreso y el resultado.

La cancelación es la de la sesión (`cancel_current_operation`).
"""

from __future__ import annotations

from collections.abc import Callable

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
from geoduck.ui.i18n import tr
from geoduck.ui.load_dialog import LoadDialog

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
        self._pending: dict[int, tuple[str, str]] = {}
        self._names: dict[int, str] = {}
        self.loading = False
        self._unsubscribe = coordinator.subscribe(self._on_event)

    def start(self, sql: str, title: str) -> None:
        """Comienza el flujo para una consulta de lectura repetible (o una tabla/vista del explorador)."""
        try:
            token = self._coordinator.prepare_load(sql)
        except GeoDuckError as exc:
            self._on_message(exc.message)
            return
        self._pending[token] = (sql, title)

    def detach(self) -> None:
        self._unsubscribe()

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, LoadPrepared) and event.token in self._pending:
            sql, title = self._pending.pop(event.token)
            self._ask(sql, title, event.plan)
        elif isinstance(event, LoadPrepareFailed) and event.token in self._pending:
            self._pending.pop(event.token)
            self._on_message(tr("No se puede cargar: ") + event.message)
        elif isinstance(event, LoadStarted):
            self.loading = True
            self._names[event.load_id] = event.request.layer_name
            self._on_message(tr("Cargando «{}»…").format(event.request.layer_name))
        elif isinstance(event, LoadProgressed):
            name = self._names.get(event.load_id, "")
            self._on_message(tr("Cargando «{}»: {} filas…").format(name, f"{event.rows:,}".replace(",", " ")))
        elif isinstance(event, LoadFinished):
            self.loading = False
            report = event.report
            text = tr("Capa «{}» cargada: {} filas.").format(
                report.layer_name, f"{report.rows:,}".replace(",", " ")
            )
            if report.warnings:
                text += " " + tr("Avisos: ") + "; ".join(report.warnings)
            self._on_message(text)
        elif isinstance(event, LoadFailed):
            self.loading = False
            self._on_message(
                tr("Carga cancelada.") if event.cancelled else tr("La carga falló: ") + event.message
            )

    def _ask(self, sql: str, title: str, plan: LoadPlan) -> None:
        dialog = self._dialog_factory(sql, title, plan, self._coordinator.load_modes(), self._parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._coordinator.load(dialog.request())
        except GeoDuckError as exc:
            self._on_message(tr("No se puede cargar: ") + exc.message)
