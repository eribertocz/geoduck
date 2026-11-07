# SPDX-License-Identifier: GPL-2.0-or-later
"""«Capas de QGIS → DuckDB»: una sola ventana de tres pasos para las tres formas de añadir capas
(observaciones de la prueba en Windows, F-131; propietario, 2026-11-06; workspace-pro-spec §9).

- Arrastrar capas a GeoDuck → paso 1 con esas capas (y la base donde se soltaron, ya elegida en el paso 2).
- Clic derecho en QGIS › «Añadir a DuckDB…» → paso 1 con las capas seleccionadas.
- «+» o Ctrl+K › «Añadir capas de QGIS a DuckDB…» → paso 1 con todas las capas del proyecto.

1. **Capas:** agrupadas en puntos, líneas, polígonos y tablas sin geometría, con el icono de QGIS, cuántas
   entidades y el SRC; las que no se pueden, en gris con su motivo. Sin capas, la ventana lo dice.
2. **Dónde:** base y esquema (se pueden cambiar), qué pasará con cada capa y una frase de lo que ocurrirá
   (el diálogo de G8 con el estilo nuevo, dentro de esta ventana).
3. **Progreso:** cada capa con su estado; «×» quita una capa en espera o detiene la que se copia; «Cancelar
   todo»; «Seguir en segundo plano». Al terminar: qué pasó con cada una, «Deshacer», «Abrir» y «Cerrar».

**Cada capa se guarda por separado** (una transacción por capa): las que terminaron quedan aunque se cancelen
las demás; «Deshacer» borra las tablas nuevas. DuckDB escribe de a una cosa: las capas van una tras otra.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from qgis.core import QgsIconUtils, QgsProject
from qgis.PyQt.QtCore import QSize, Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from geoduck.app.events import AppEvent, SendFailed, SendFinished, SendProgressed, SendUndoFailed, SendUndone
from geoduck.domain.errors import GeoDuckError, SessionStateError
from geoduck.domain.importing import PATH_QGIS, ImportedTable, SendCandidate, SendRequest
from geoduck.domain.session import SessionState
from geoduck.ui.i18n import tr
from geoduck.ui.pro import style
from geoduck.ui.pro.widgets import button, label, lines_html
from geoduck.ui.send_dialog import SendDialog

CHOOSE, WHERE, PROGRESS = 0, 1, 2
#: Estado de cada capa en el paso 3.
WAITING, RUNNING, DONE, CANCELLED, FAILED = "waiting", "running", "done", "cancelled", "failed"
#: Segundos que se ve el aviso final cuando la ventana está cerrada.
DONE_SECONDS = 15


def _count(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def group_of(candidate: SendCandidate) -> int:
    """0 puntos, 1 líneas, 2 polígonos, 3 tablas sin geometría, 4 no se puede."""
    if candidate.problem is not None:
        return 4
    kind = (candidate.geometry_type or "").lower()
    if not kind:
        return 3
    if "point" in kind:
        return 0
    if "line" in kind or "curve" in kind:
        return 1
    return 2


def group_titles() -> list[str]:
    return [tr("Points"), tr("Lines"), tr("Polygons"), tr("Tables without geometry"), tr("Cannot be added")]


class AddLayersWindow(QDialog):
    """La ventana de tres pasos. La maneja `AddLayers` (que envía y recibe los eventos)."""

    def __init__(self, flow: AddLayers, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.flow = flow
        self.setModal(False)
        self.colors = style.apply(self)
        self.setWindowTitle(tr("GeoDuck"))
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 18)
        box.setSpacing(10)
        self.title = label("", "title")
        box.addWidget(self.title)
        self.subtitle = label("", "muted")
        self.subtitle.setWordWrap(True)
        box.addWidget(self.subtitle)
        self.stack = QStackedWidget()
        box.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_choose())
        self.where_page = QWidget()
        self.where_box = QVBoxLayout(self.where_page)
        self.where_box.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.where_page)
        self.progress_page = QWidget()
        self.stack.addWidget(self.progress_page)
        self.footer = QHBoxLayout()
        box.addLayout(self.footer)
        self.send_dialog: SendDialog | None = None
        self.resize(640, 520)
        self.setMinimumWidth(560)

    # -- paso 1 ---------------------------------------------------------------------------------------

    def _build_choose(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setAccessibleName(tr("QGIS layers"))
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(lambda *_: self.flow.choice_changed())
        column.addWidget(self.tree, 1)
        self.empty = label(
            tr("Your QGIS project has no vector layers. Add one in QGIS and come back here."), "muted"
        )
        self.empty.setWordWrap(True)
        self.empty.setVisible(False)
        column.addWidget(self.empty)
        return page

    def fill(self, candidates: list[SendCandidate], checked: set[str]) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        self.rows: dict[str, QTreeWidgetItem] = {}
        titles = group_titles()
        for group in range(5):
            members = [c for c in candidates if group_of(c) == group]
            if not members:
                continue
            head = QTreeWidgetItem([titles[group], ""])
            font = head.font(0)
            font.setBold(True)
            head.setFont(0, font)
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(head)
            for c in members:
                detail = c.problem if c.problem else tr("{0} features").format(_count(max(c.features, 0)))
                if c.problem is None and c.crs_label:
                    detail += f" · {c.crs_label}"
                item = QTreeWidgetItem([c.name, detail])
                layer = QgsProject.instance().mapLayer(c.layer_id)
                if layer is not None:
                    item.setIcon(0, QgsIconUtils.iconForLayer(layer))
                item.setForeground(1, self.palette().placeholderText())
                if c.problem is None:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    state = Qt.CheckState.Checked if c.layer_id in checked else Qt.CheckState.Unchecked
                    item.setCheckState(0, state)
                else:
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setData(0, Qt.ItemDataRole.UserRole, c.layer_id)
                self.tree.addTopLevelItem(item)
                self.rows[c.layer_id] = item
        self.tree.blockSignals(False)
        self.tree.setVisible(bool(candidates))
        self.empty.setVisible(not any(c.problem is None for c in candidates))

    def chosen(self) -> list[str]:
        return [
            layer_id
            for layer_id, item in self.rows.items()
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.checkState(0) == Qt.CheckState.Checked
        ]

    # -- pies y títulos -----------------------------------------------------------------------------------

    def set_step(self, step: int, subtitle: str) -> None:
        self.stack.setCurrentIndex(step)
        self.title.setText(tr("QGIS layers → DuckDB") + f"  ·  {step + 1} " + tr("of") + " 3")
        self.subtitle.setText(subtitle)

    def set_footer(self, left: list[QWidget], right: list[QWidget]) -> None:
        while self.footer.count():
            item = self.footer.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for widget in left:
            self.footer.addWidget(widget)
        self.footer.addStretch(1)
        for widget in right:
            self.footer.addWidget(widget)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        """Cerrar con la X de la ventana: en el paso 3 en curso es «Seguir en segundo plano»."""
        self.flow.window_closed()
        super().closeEvent(event)

    def reject(self) -> None:  # Esc
        self.flow.window_closed()
        super().reject()


class AddLayers:
    """El flujo «Capas de QGIS → DuckDB» y su único envío a la vez. `host` es el workspace: su pie
    (`show_progress`, `set_progress`, `hide_progress`, `progress_text`), `notify`, `toast` y `open_table`."""

    def __init__(self, coordinator: Any, host: Any) -> None:
        self._coordinator = coordinator
        self._host = host
        self.window: AddLayersWindow | None = None
        self._candidates: list[SendCandidate] = []
        self._destination: tuple[str, str] | None = None
        self.request: SendRequest | None = None
        #: Por capa del envío: estado, filas copiadas, total esperado (-1 = no se sabe) y mensaje.
        self.states: list[dict[str, Any]] = []
        self._current: int | None = None
        self._mine = False
        self._stop_all = False
        self._undoing = False
        self.tables: list[ImportedTable] = []
        self.running = False
        self._unsubscribe = coordinator.subscribe(self._on_event)

    # -- abrir ------------------------------------------------------------------------------------------

    def open(
        self,
        layer_ids: list[str] | None,
        destination: tuple[str, str] | None = None,
        *,
        checked: list[str] | None = None,
    ) -> None:
        """Paso 1 con `layer_ids` (arrastradas o del clic derecho) o, con None, todas las capas del proyecto
        (marcadas las de `checked`). Si ya hay capas copiándose, muestra ese progreso."""
        if self.running:
            self.show_window()
            self._host.notify(tr("Finish or cancel these layers to add more."))
            return
        coordinator = self._coordinator
        if coordinator.state is not SessionState.READY or coordinator.catalog is None:
            self._host.notify(tr("Start DuckDB to add layers."))
            return
        self._candidates = coordinator.send_candidates(layer_ids)
        self._destination = destination
        marked = set(layer_ids) if layer_ids is not None else set(checked or [])
        window = self._window()
        window.fill(self._candidates, marked)
        self._show_choose()
        window.show()
        window.raise_()
        window.activateWindow()

    def _window(self) -> AddLayersWindow:
        if self.window is None:
            self.window = AddLayersWindow(self, self._host if isinstance(self._host, QWidget) else None)
        return self.window

    def show_window(self) -> None:
        """Volver a la ventana (pie, Ctrl+K): en el paso en que quedó."""
        if self.window is not None:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def window_closed(self) -> None:
        if not self.running:
            self._drop_send_dialog()

    # -- paso 1 -----------------------------------------------------------------------------------------

    def _show_choose(self) -> None:
        window = self._window()
        window.set_step(
            CHOOSE,
            tr("Choose the layers to add to DuckDB. The ones selected in QGIS are already checked."),
        )
        self.count_label = label("", "muted")
        cancel = button(tr("Cancel"))
        cancel.clicked.connect(window.reject)
        self.next_button = button(tr("Next") + "  ›", "primary")
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self._show_where)
        window.set_footer([self.count_label], [cancel, self.next_button])
        self.choice_changed()

    def choice_changed(self) -> None:
        if self.window is None or self.window.stack.currentIndex() != CHOOSE:
            return
        count = len(self.window.chosen())
        self.count_label.setText(
            tr("1 layer chosen") if count == 1 else tr("{0} layers chosen").format(count)
        )
        self.next_button.setEnabled(count > 0)

    # -- paso 2 -----------------------------------------------------------------------------------------

    def _show_where(self) -> None:
        window = self._window()
        chosen = set(window.chosen())
        if not chosen:
            return
        self._drop_send_dialog()
        candidates = [c for c in self._candidates if c.layer_id in chosen]
        coordinator = self._coordinator
        dialog = SendDialog(
            candidates,
            coordinator.catalog,
            coordinator.read_import_target,
            window,
            checked=chosen,
            destination=self._destination,
            pro=True,
        )
        dialog.tidy_columns = False
        dialog.tree.setColumnHidden(2, False)
        dialog.setWindowFlags(Qt.WindowType.Widget)
        dialog.layout().setContentsMargins(0, 0, 0, 0)
        for widget in (dialog.send_button, dialog.cancel_button, dialog.open_after):
            widget.hide()
        window.send_dialog = dialog
        window.where_box.addWidget(dialog)
        window.set_step(WHERE, tr("Choose the DuckDB database and schema where to save them."))
        back = button("‹  " + tr("Back"))
        back.clicked.connect(self._show_choose_again)
        cancel = button(tr("Cancel"))
        cancel.clicked.connect(window.reject)
        self.add_button = button("", "primary")
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.start)
        window.set_footer([back], [cancel, self.add_button])
        self._sync_timer = QTimer(window)
        self._sync_timer.setInterval(150)
        self._sync_timer.timeout.connect(self._sync_add)
        self._sync_timer.start()
        self._sync_add()

    def _sync_add(self) -> None:
        dialog = self.window.send_dialog if self.window is not None else None
        if dialog is None:
            return
        count = len(dialog.request().items) if dialog.target_ready else 0
        text = tr("Add 1 layer to DuckDB") if count == 1 else tr("Add {0} layers to DuckDB").format(count)
        self.add_button.setText(text)
        self.add_button.setEnabled(dialog.send_button.isEnabled() and count > 0)

    def _show_choose_again(self) -> None:
        self._drop_send_dialog()
        self._show_choose()

    def _drop_send_dialog(self) -> None:
        if getattr(self, "_sync_timer", None) is not None:
            self._sync_timer.stop()
        window = self.window
        if window is not None and window.send_dialog is not None:
            window.send_dialog.hide()
            window.send_dialog.setParent(None)
            window.send_dialog.deleteLater()
            window.send_dialog = None

    # -- paso 3: enviar capa por capa --------------------------------------------------------------------

    def start(self) -> None:
        window = self._window()
        dialog = window.send_dialog
        if dialog is None or not self.add_button.isEnabled():
            return
        request = dialog.request()
        only = request.only_selected
        by_id = {c.layer_id: c for c in self._candidates}
        self.request = request
        self.states = []
        for item in request.items:
            c = by_id[item.layer_id]
            total = (
                c.rows_for(only) if c.path_for(only, request.reproject_to is not None) == PATH_QGIS else -1
            )
            self.states.append({"state": WAITING, "rows": 0, "total": total, "name": c.name, "message": ""})
        self.tables = []
        self._stop_all = False
        self.running = True
        self._sync_timer.stop()
        self._build_progress()
        self._host.show_progress(self.progress_text(), 0)
        QTimer.singleShot(0, self._next)

    def _next(self, attempt: int = 0) -> None:
        if not self.running:
            return
        waiting = [i for i, s in enumerate(self.states) if s["state"] == WAITING]
        if self._stop_all or not waiting:
            self._finish()
            return
        index = waiting[0]
        assert self.request is not None
        single = dataclasses.replace(self.request, items=(self.request.items[index],))
        self._current = index
        self.states[index]["state"] = RUNNING
        self._mine = True  # `SendStarted` llega antes de que `send_layers` devuelva
        try:
            self._coordinator.send_layers(single)
        except SessionStateError:
            self._mine = False
            self.states[index]["state"] = WAITING
            if attempt < 50:  # la sesión aún relee el catálogo de la capa anterior
                QTimer.singleShot(100, lambda: self._next(attempt + 1))
                return
            self._mark(index, FAILED, tr("DuckDB is busy"))
            QTimer.singleShot(0, self._next)
        except GeoDuckError as exc:
            self._mine = False
            self._mark(index, FAILED, exc.message)
            QTimer.singleShot(0, self._next)
        self._refresh()

    def _mark(self, index: int, state: str, message: str = "") -> None:
        self.states[index]["state"] = state
        self.states[index]["message"] = message
        if self._current == index and state != RUNNING:
            self._current = None

    def remove(self, index: int) -> None:
        """«×» de una capa: quita la que espera o detiene la que se copia (esa no queda en DuckDB)."""
        state = self.states[index]["state"]
        if state == WAITING:
            self._mark(index, CANCELLED)
            self._refresh()
        elif state == RUNNING:
            self._coordinator.cancel_current_operation()

    def cancel_all(self) -> None:
        self._stop_all = True
        for i, s in enumerate(self.states):
            if s["state"] == WAITING:
                self._mark(i, CANCELLED)
        if self._current is not None:
            self._coordinator.cancel_current_operation()
        else:
            self._finish()
        self._refresh()

    def _on_event(self, event: AppEvent) -> None:
        index = self._current
        if isinstance(event, SendProgressed) and self._mine and index is not None:
            self.states[index]["rows"] = event.rows
            self._refresh()
        elif isinstance(event, SendFinished) and self._mine and index is not None:
            self._mine = False
            rows = sum(t.rows for t in event.report.tables)
            self.states[index]["rows"] = rows
            self._mark(index, DONE, " · ".join(event.report.warnings))
            self.tables.extend(event.report.tables)
            QTimer.singleShot(0, self._next)
            self._refresh()
        elif isinstance(event, SendFailed) and self._mine and index is not None:
            self._mine = False
            self._mark(
                index, CANCELLED if event.cancelled else FAILED, "" if event.cancelled else event.message
            )
            QTimer.singleShot(0, self._next)
            self._refresh()
        elif isinstance(event, SendUndone) and self._undoing:
            self._undoing = False
            self._host.notify(tr("Undone: {0}").format(", ".join(t.display for t in event.tables)))
            self.tables = [t for t in self.tables if t not in event.tables]
            self._refresh()
        elif isinstance(event, SendUndoFailed) and self._undoing:
            self._undoing = False
            self._host.notify(tr("It could not be undone:") + f" {event.message}")

    def _finish(self) -> None:
        if not self.running:
            return
        self.running = False
        self._current = None
        self._host.hide_progress()
        self._refresh()
        text = lines_html(self.done_lines())
        # un solo aviso: el resumen del paso 3 o, con la ventana cerrada, el aviso con «×»; nada en el pie,
        # que quedaría desactualizado (observación del propietario, 2026-11-06)
        self._host.notify("")
        if self.window is None or not self.window.isVisible():
            actions: list[tuple[str, Callable[[], None]]] = []
            if self.tables:
                actions.append((tr("Open"), lambda: self._host.open_table(self.tables[0])))
            if any(t.can_undo for t in self.tables):
                actions.append((tr("Undo"), self.undo))
            self._host.toast(text, actions, DONE_SECONDS)

    def done_lines(self) -> list[str]:
        """El resumen, una idea por línea: cuántas y en qué sentido; en qué base; canceladas; con error."""
        added = sum(1 for s in self.states if s["state"] == DONE)
        where = self.request.database if self.request is not None else ""
        if added == 1:
            lines = [tr("1 QGIS layer added to DuckDB")]
        else:
            lines = [tr("{0} QGIS layers added to DuckDB").format(added)]
        lines.append(tr("Database: {0}").format(where))
        cancelled = [s["name"] for s in self.states if s["state"] == CANCELLED]
        failed = [s["name"] for s in self.states if s["state"] == FAILED]
        if cancelled:
            lines.append(tr("{0} cancelled ({1})").format(len(cancelled), ", ".join(cancelled)))
        if failed:
            lines.append(tr("{0} with error ({1})").format(len(failed), ", ".join(failed)))
        return lines

    def done_text(self) -> str:
        return " · ".join(self.done_lines())

    def progress_text(self) -> str:
        """La línea del pie: «⟳ Añadiendo 2 de 4 · redes_bt 62 %» (clic: vuelve al paso 3)."""
        total = len(self.states)
        done = sum(1 for s in self.states if s["state"] in (DONE, CANCELLED, FAILED))
        index = self._current
        text = "⟳ " + tr("Adding {0} of {1} to DuckDB").format(min(done + 1, total), total)
        if index is not None:
            s = self.states[index]
            text += f" · {s['name']}"
            if s["total"] > 0:
                text += f" {min(100, s['rows'] * 100 // s['total'])} %"
        return text

    def undo(self) -> None:
        undoable = [t for t in self.tables if t.can_undo]
        if not undoable:
            return
        self._undoing = True
        try:
            self._coordinator.undo_send(undoable)
        except GeoDuckError as exc:
            self._undoing = False
            self._host.notify(tr("It could not be undone:") + f" {exc.message}")

    # -- paso 3: la vista ---------------------------------------------------------------------------------

    def _build_progress(self) -> None:  # noqa: PLR0915 - la grilla, fila a fila
        window = self._window()
        self._drop_send_dialog()
        old = window.progress_page.layout()
        if old is not None:
            QWidget().setLayout(old)  # suelta la grilla anterior
        grid = QGridLayout(window.progress_page)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        by_id = {c.layer_id: c for c in self._candidates}
        assert self.request is not None
        self.marks: list[QLabel] = []
        self.details: list[QLabel] = []
        self.bars: list[QProgressBar] = []
        self.removes: list[QWidget] = []
        for i, item in enumerate(self.request.items):
            mark = QLabel()
            grid.addWidget(mark, i, 0)
            icon = QLabel()
            layer = QgsProject.instance().mapLayer(item.layer_id)
            if layer is not None:
                icon.setPixmap(QgsIconUtils.iconForLayer(layer).pixmap(18, 18))
            grid.addWidget(icon, i, 1)
            grid.addWidget(QLabel(by_id[item.layer_id].name), i, 2)
            cell = QWidget()
            row = QHBoxLayout(cell)
            row.setContentsMargins(0, 0, 0, 0)
            bar = QProgressBar()
            bar.setProperty("pro", "thin")
            bar.setTextVisible(False)
            bar.setFixedWidth(160)
            row.addWidget(bar)
            detail = label("", "muted")
            row.addWidget(detail, 1)
            grid.addWidget(cell, i, 3)
            remove = button("×", "ghost")
            remove.setAccessibleName(tr("Remove this layer"))
            remove.clicked.connect(lambda _c=False, index=i: self.remove(index))
            grid.addWidget(remove, i, 4)
            self.marks.append(mark)
            self.details.append(detail)
            self.bars.append(bar)
            self.removes.append(remove)
        grid.setColumnStretch(3, 1)
        grid.setRowStretch(len(self.request.items), 1)
        self.background = button(tr("Continue in the background"))
        self.background.clicked.connect(window.hide)
        self.cancel_all_button = button(tr("Cancel all"))
        self.cancel_all_button.clicked.connect(self.cancel_all)
        window.set_footer([self.background], [self.cancel_all_button])
        window.set_step(PROGRESS, "")
        self._refresh()

    def _refresh(self) -> None:
        window = self.window
        if window is None or self.request is None or not hasattr(self, "marks"):
            return
        colors = window.colors
        for i, s in enumerate(self.states):
            state = s["state"]
            mark, detail, bar, remove = self.marks[i], self.details[i], self.bars[i], self.removes[i]
            symbol, color = {
                DONE: ("✓", colors.ok),
                CANCELLED: ("✕", colors.error),
                FAILED: ("✕", colors.error),
                RUNNING: ("⟳", colors.accent),
                WAITING: ("○", colors.muted),
            }[state]
            mark.setText(symbol)
            mark.setStyleSheet(f"color: {color}; font-weight: 600;")
            bar.setVisible(state == RUNNING)
            if state == RUNNING:
                if s["total"] > 0:
                    bar.setRange(0, s["total"])
                    bar.setValue(min(s["rows"], s["total"]))
                    detail.setText(f"{min(100, s['rows'] * 100 // s['total'])} %")
                else:
                    bar.setRange(0, 0)  # DuckDB copia sin informar entidades
                    detail.setText("")
            elif state == DONE:
                text = tr("{0} features").format(_count(s["rows"]))
                detail.setText(text + (f" · ⚠ {s['message']}" if s["message"] else ""))
            elif state == CANCELLED:
                detail.setText(tr("cancelled"))
            elif state == FAILED:
                detail.setText(tr("error: {0}").format(s["message"]))
                detail.setToolTip(s["message"])
            else:
                detail.setText(tr("waiting"))
            remove.setVisible(self.running and state in (WAITING, RUNNING))
            remove.setToolTip(tr("Remove this layer") if state == WAITING else tr("Stop this layer"))
        where = self.request.database
        if self.running:
            window.subtitle.setText(tr("Adding {0} layers to DuckDB · {1}…").format(len(self.states), where))
            self._host.set_progress(self.progress_text())
        else:
            window.subtitle.setText(tr("Done:") + " " + self.done_text())
            self._final_footer()

    def _final_footer(self) -> None:
        window = self._window()
        if getattr(self, "_final_shown", None) is self.request:
            return
        self._final_shown = self.request
        undo = button(tr("Undo"))
        undo.setEnabled(any(t.can_undo for t in self.tables))
        undo.clicked.connect(self.undo)
        undo.clicked.connect(lambda: undo.setEnabled(False))
        open_button = button(tr("Open"))
        open_button.setEnabled(bool(self.tables))
        open_button.clicked.connect(lambda: self.tables and self._host.open_table(self.tables[0]))
        close = button(tr("Close"), "primary")
        close.clicked.connect(window.hide)
        window.set_footer([undo], [open_button, close])

    def detach(self) -> None:
        self._unsubscribe()
        if self.window is not None:
            self._drop_send_dialog()
            self.window.hide()
            self.window.deleteLater()
            self.window = None
