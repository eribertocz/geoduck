# SPDX-License-Identifier: GPL-2.0-or-later
"""«Enviar a DuckDB»: del menú al aviso final (G8 · E3; qgis-import-spec §2–§4).

Puntos de entrada (§2): el menú de una o varias capas del panel de capas de QGIS y el «+» del workspace
(«Importar capas de QGIS…»). Los dos abren el mismo diálogo; solo cambia qué capas vienen marcadas.

El progreso y el resultado van en la barra de mensajes de QGIS, donde el usuario ya está mirando:
progreso con «Cancelar»; al terminar, «Abrir» (la tabla en el explorador de GeoDuck) y, solo si se creó
una tabla nueva, «Deshacer» (`DROP`). Reemplazar o añadir no se deshacen desde GeoDuck (§4).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import Qgis
from qgis.PyQt.QtWidgets import QProgressBar, QPushButton, QWidget

from geoduck.app.coordinator import SessionCoordinator
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

#: Segundos que se ve el aviso final (con «Abrir» y «Deshacer»).
DONE_SECONDS = 15

OpenTable = Callable[[ImportedTable], None]


def _count(n: int) -> str:
    return f"{n:,}".replace(",", " ")


class SendFlow:
    """Un único flujo por GeoDuck; se usa en el hilo principal."""

    def __init__(
        self,
        coordinator: SessionCoordinator,
        message_bar: Any,
        parent: QWidget | None,
        *,
        open_table: OpenTable,
        dialog_factory: Any = SendDialog,
    ) -> None:
        self._coordinator = coordinator
        self._bar = message_bar
        self._parent = parent
        self._open_table = open_table
        self.dialog_factory = dialog_factory
        self._open_after = False
        self._progress_item: Any = None
        self._progress: QProgressBar | None = None
        self._total = 0
        #: Entidades que leerá QGIS en este envío (para la barra de progreso); 0 = indeterminado.
        self._expected = 0
        self.last_report: ImportReport | None = None
        self._unsubscribe = coordinator.subscribe(self._on_event)

    # -- entrada ---------------------------------------------------------------------------------

    def open(
        self,
        layer_ids: list[str] | None,
        checked: list[str] | None = None,
        destination: tuple[str, str] | None = None,
    ) -> SendDialog | None:
        """Prepara el diálogo. `layer_ids`: las capas elegidas en el panel de capas (todas marcadas); None =
        el «+» del workspace: todas las capas del proyecto, marcadas solo las de `checked`."""
        if self._coordinator.state is not SessionState.READY:
            self._bar.pushMessage(
                tr("GeoDuck"),
                tr("Start a GeoDuck session to send layers to DuckDB."),
                Qgis.MessageLevel.Warning,
                8,
            )
            return None
        if self._coordinator.catalog is None:  # recién iniciada: aún no se conocen las bases destino
            self._bar.pushMessage(
                tr("GeoDuck"),
                tr("GeoDuck is still reading the databases; try again in a moment."),
                Qgis.MessageLevel.Info,
                5,
            )
            return None
        candidates = self._coordinator.send_candidates(layer_ids)
        if not any(c.problem is None for c in candidates):
            self._bar.pushMessage(
                tr("GeoDuck"), tr("There is no vector layer to send."), Qgis.MessageLevel.Info, 8
            )
            return None
        dialog = self.dialog_factory(
            candidates,
            self._coordinator.catalog,
            self._coordinator.read_import_target,
            self._parent,
            checked=set(layer_ids if layer_ids is not None else checked or []),
            **({"destination": destination} if destination is not None else {}),
        )
        return dialog

    def run(
        self,
        layer_ids: list[str] | None,
        checked: list[str] | None = None,
        destination: tuple[str, str] | None = None,
    ) -> None:
        """Menú de capa, «+» o capas soltadas sobre una base (G9 · E5, con su `destination`): el diálogo y,
        si el usuario confirma, el envío."""
        dialog = self.open(layer_ids, checked, destination)
        if dialog is None or not dialog.exec():
            return
        self.send(dialog)

    def send(self, dialog: SendDialog) -> None:
        request = dialog.request()
        if not request.items:
            return
        self._open_after = dialog.open_after.isChecked()
        self._expected = dialog.rows_read_by_qgis()
        self._coordinator.send_layers(request)

    # -- progreso y resultado ----------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, SendStarted):
            self._show_progress(event)
        elif isinstance(event, SendProgressed):
            if self._progress is not None and self._total > 0:
                self._progress.setValue(min(self._total, event.rows))
        elif isinstance(event, SendFinished):
            self._clear_progress()
            self._finished(event.report)
        elif isinstance(event, SendFailed):
            self._clear_progress()
            if event.cancelled:
                text = tr("Sending cancelled: nothing changed in DuckDB.")
                self._bar.pushMessage(tr("GeoDuck"), text, Qgis.MessageLevel.Info, 8)
            else:
                text = tr("Nothing was sent; DuckDB is unchanged.") + f" {event.message}"
                self._bar.pushMessage(tr("GeoDuck"), text, Qgis.MessageLevel.Critical, 0)
        elif isinstance(event, SendUndone):
            names = ", ".join(t.display for t in event.tables)
            self._bar.pushMessage(tr("GeoDuck"), tr("Undone: {0}").format(names), Qgis.MessageLevel.Info, 8)
        elif isinstance(event, SendUndoFailed):
            text = tr("It could not be undone:") + f" {event.message}"
            self._bar.pushMessage(tr("GeoDuck"), text, Qgis.MessageLevel.Critical, 0)

    def _show_progress(self, event: SendStarted) -> None:
        count = len(event.request.items)
        text = tr("Sending {0} layer(s) to DuckDB…").format(count)
        item = self._bar.createMessage(tr("GeoDuck"), text)
        self._progress = QProgressBar()
        self._progress.setMinimum(0)
        self._total = self._expected
        self._progress.setMaximum(self._total)  # 0 = indeterminado: DuckDB copia sin informar entidades
        item.layout().addWidget(self._progress)
        cancel = QPushButton(tr("Cancel"))
        cancel.setObjectName("geoduckSendCancel")
        cancel.clicked.connect(self._coordinator.cancel_current_operation)
        item.layout().addWidget(cancel)
        self._progress_item = item
        self._bar.pushWidget(item, Qgis.MessageLevel.Info)

    def _clear_progress(self) -> None:
        if self._progress_item is not None:
            self._bar.popWidget(self._progress_item)
        self._progress_item = None
        self._progress = None

    def _finished(self, report: ImportReport) -> None:
        self.last_report = report
        names = ", ".join(t.name or t.display for t in report.tables)  # corto: la base, en la ayuda
        text = tr("Sent to DuckDB: {0} · {1} rows").format(names, _count(report.rows))
        if report.warnings:
            text += " · ⚠ " + " · ".join(report.warnings)
        item = self._bar.createMessage(tr("GeoDuck"), text)
        item.setToolTip("\n".join(t.display for t in report.tables))
        first = report.tables[0]
        open_button = QPushButton(tr("Open"))
        open_button.setObjectName("geoduckSendOpen")
        open_button.clicked.connect(lambda: self._open_table(first))
        item.layout().addWidget(open_button)
        undoable = [t for t in report.tables if t.can_undo]
        if undoable:
            undo = QPushButton(tr("Undo"))
            undo.setObjectName("geoduckSendUndo")
            names = ", ".join(t.display for t in undoable)
            undo.setToolTip(tr("Deletes the new tables of this send: {0}").format(names))
            undo.clicked.connect(lambda: self._undo(item, undoable))
            item.layout().addWidget(undo)
        self._bar.pushWidget(item, Qgis.MessageLevel.Success, DONE_SECONDS)
        if self._open_after:
            self._open_table(first)

    def _undo(self, item: Any, tables: list[ImportedTable]) -> None:
        self._bar.popWidget(item)
        self._coordinator.undo_send(tables)

    def detach(self) -> None:
        self._unsubscribe()
