# SPDX-License-Identifier: GPL-2.0-or-later
"""Capas de QGIS soltadas sobre GeoDuck: «Enviar a DuckDB» sin pasos de más (G9 · E5; workspace-pro-spec §9).

Lo decidido para que sea fácil (2026-11-06):

1. **Sin diálogo si no hay nada que decidir.** Si todas las capas serán tablas nuevas, sin selección y con
   SRC, se envían directamente. El diálogo de G8 (con el estilo nuevo) solo se abre si hay algo que decidir:
   una tabla que ya existe, una capa que no se puede, una selección o el SRC.
2. **Progreso en el pie**, con una barra fina y «Cancelar»; sin otra ventana.
3. **Al terminar, un aviso** «N capas enviadas a db · Abrir · Deshacer» («Deshacer» borra solo las tablas
   nuevas de este envío, §4).

El diálogo y el envío son los de G8 (`SendDialog`, `send_layers`): aquí no cambia qué se escribe en DuckDB.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QDialog, QWidget

from geoduck.app.events import (
    AppEvent,
    SendFailed,
    SendFinished,
    SendProgressed,
    SendStarted,
    SendUndoFailed,
    SendUndone,
)
from geoduck.domain.importing import ImportedTable, ImportReport
from geoduck.domain.session import SessionState
from geoduck.ui.i18n import tr
from geoduck.ui.send_dialog import SendDialog

#: Segundos que se ve el aviso final.
DONE_SECONDS = 12


def done_text(report: ImportReport) -> str:
    """«3 capas enviadas a db» / «Capa «x» enviada a db»."""
    tables = report.tables
    where = tables[0].database if tables else ""
    if len(tables) == 1:
        return tr("Layer «{0}» sent to {1}").format(tables[0].name or tables[0].display, where)
    return tr("{0} layers sent to {1}").format(len(tables), where)


class QuickSend:
    """Un envío a la vez; se usa en el hilo principal. `host` es el workspace: su pie (`show_progress`,
    `set_progress`, `hide_progress`), `notify`, `toast` y `open_table`."""

    def __init__(self, coordinator: Any, host: Any, dialog_factory: Callable[..., SendDialog] = SendDialog):
        self._coordinator = coordinator
        self._host = host
        self.dialog_factory = dialog_factory
        self.dialog: SendDialog | None = None
        self._mine = False
        self._undoing = False
        self._expected = 0
        self._open_after = False
        #: Para las pruebas: si el último envío abrió el diálogo y su resultado.
        self.asked = False
        self.last_report: ImportReport | None = None
        self._unsubscribe = coordinator.subscribe(self._on_event)

    # -- entrada ----------------------------------------------------------------------------------------

    def send(self, layer_ids: list[str], destination: tuple[str, str] | None = None) -> None:
        """Las capas soltadas, a `destination` (base, esquema) o, sin ella, a la base actual."""
        coordinator = self._coordinator
        if coordinator.state is not SessionState.READY or coordinator.catalog is None:
            self._host.notify(tr("Start DuckDB to send layers."))
            return
        if self.dialog is not None or self._mine:
            self._host.notify(tr("A send is already in progress."))
            return
        candidates = coordinator.send_candidates(layer_ids)
        if not any(c.problem is None for c in candidates):
            self._host.notify(tr("There is no vector layer to send."))
            return
        dialog = self.dialog_factory(
            candidates,
            coordinator.catalog,
            coordinator.read_import_target,
            self._host if isinstance(self._host, QWidget) else None,
            checked=set(layer_ids),
            destination=destination,
            pro=True,
        )
        self.dialog = dialog
        self.asked = False
        if dialog.target_ready:  # ya se sabe qué hay en el destino (p. ej. la tabla temporal)
            QTimer.singleShot(0, self._decide)
        else:
            dialog.on_target = lambda: QTimer.singleShot(0, self._decide)

    def _decide(self) -> None:
        dialog = self.dialog
        if dialog is None:
            return
        dialog.on_target = None
        try:
            if dialog.needs_decision():
                self.asked = True
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
            self._send(dialog)
        finally:
            self.dialog = None
            dialog.deleteLater()

    def _send(self, dialog: SendDialog) -> None:
        request = dialog.request()
        if not request.items:
            return
        self._open_after = self.asked and dialog.open_after.isChecked()  # sin diálogo, «Abrir» en el aviso
        self._expected = dialog.rows_read_by_qgis()
        self._mine = True  # `SendStarted` llega antes de que `send_layers` devuelva
        try:
            self._coordinator.send_layers(request)
        except Exception as exc:  # se informa en el pie; DuckDB no cambió
            self._mine = False
            self._host.notify(tr("Nothing was sent; DuckDB is unchanged.") + f" {exc}")

    def cancel(self) -> None:
        self._coordinator.cancel_current_operation()

    # -- progreso y resultado ---------------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, SendStarted) and self._mine:
            count = len(event.request.items)
            self._host.show_progress(tr("Sending {0} layer(s) to DuckDB…").format(count), self._expected)
        elif isinstance(event, SendProgressed) and self._mine:
            self._host.set_progress(event.rows)
        elif isinstance(event, SendFinished) and self._mine:
            self._mine = False
            self._host.hide_progress()
            self._finished(event.report)
        elif isinstance(event, SendFailed) and self._mine:
            self._mine = False
            self._host.hide_progress()
            if event.cancelled:
                self._host.notify(tr("Sending cancelled: nothing changed in DuckDB."))
            else:
                self._host.notify(tr("Nothing was sent; DuckDB is unchanged.") + f" {event.message}")
        elif isinstance(event, SendUndone) and self._undoing:
            self._undoing = False
            self._host.notify(tr("Undone: {0}").format(", ".join(t.display for t in event.tables)))
        elif isinstance(event, SendUndoFailed) and self._undoing:
            self._undoing = False
            self._host.notify(tr("It could not be undone:") + f" {event.message}")

    def _finished(self, report: ImportReport) -> None:
        self.last_report = report
        if not report.tables:
            return
        rows = f"{report.rows:,}".replace(",", " ")
        text = done_text(report)
        notice = f"{text} · {rows} " + tr("rows")
        if report.warnings:
            notice += " · ⚠ " + " · ".join(report.warnings)
        self._host.notify(notice)
        first = report.tables[0]
        actions: list[tuple[str, Callable[[], None]]] = [(tr("Open"), lambda: self._host.open_table(first))]
        undoable = [t for t in report.tables if t.can_undo]
        if undoable:
            actions.append((tr("Undo"), lambda: self.undo(undoable)))
        self._host.toast(text, actions, DONE_SECONDS)
        if self._open_after:
            self._host.open_table(first)

    def undo(self, tables: list[ImportedTable]) -> None:
        self._undoing = True
        try:
            self._coordinator.undo_send(tables)
        except Exception as exc:  # se informa en el pie
            self._undoing = False
            self._host.notify(tr("It could not be undone:") + f" {exc}")

    def detach(self) -> None:
        self._unsubscribe()
        if self.dialog is not None:
            self.dialog.on_target = None
            self.dialog.deleteLater()
            self.dialog = None
