# SPDX-License-Identifier: GPL-2.0-or-later
"""GeoDuck → QGIS en el diálogo único (#148, puntos 15, 19 y 25; maquetas `dialogo-unico` y `flujo-completo`).

«Cargar en QGIS ▸ Cambiar nombres…» con varias tablas: «N tablas de GeoDuck → QGIS», «Destino: Copia o
Conectada», una fila por tabla con el **nombre de la capa** (doble clic o F2 para cambiarlo) y «de:
memory.main.clientes» debajo. Si ya hay una capa con ese nombre en el proyecto, solo se avisa (se puede cargar
igual). Al pulsar «Cargar N capas», el mismo diálogo pasa a la línea de tiempo: origen → copia a QGIS (o capa
conectada) → capa en QGIS, cada una con su tiempo. La carga la hace `load.QuickLoad`, como siempre.
"""

from __future__ import annotations

import time
from typing import Any

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QWidget

from geoduck.domain.i18n import rows as rows_text
from geoduck.domain.load import LoadMode
from geoduck.domain.sql_errors import explain
from geoduck.ui.i18n import tr
from geoduck.ui.pro.error_card import ErrorCardView
from geoduck.ui.pro.load import CONNECTED, COPY, OPTIONS
from geoduck.ui.pro.timeline import DONE, FAILED, RUNNING, SKIPPED, WAITING, Step, count_text, seconds_text
from geoduck.ui.pro.transfer import INFO, NameRow, TransferWindow, primary
from geoduck.ui.pro.widgets import Segmented, button, label

#: Atajos de un clic (Copia o Conectada, #148): si la carga sigue tras este tiempo, se abre la línea de
#: tiempo; si termina antes, basta el aviso (propietario, 2026-11-13: la opción intermedia).
REVEAL_MS = 2000


def origin_text(job: dict[str, Any]) -> str:
    """«memory.main.clientes» (o «… · vista»), o «resultado de una consulta»."""
    source = job.get("source")
    if not source:
        return tr("query result")
    text = ".".join(source)
    if job.get("source_kind") == "view":
        text += " · " + tr("view")
    return text


class LoadWindow:
    """El diálogo hacia QGIS y su línea de tiempo. `host` es el workspace (`view_map`, `notify`)."""

    def __init__(self, host: Any, coordinator: Any, loader: Any) -> None:
        self._host = host
        self._coordinator = coordinator
        self._loader = loader
        self.window: TransferWindow | None = None
        self.jobs: list[dict[str, Any]] = []
        self.states: list[dict[str, Any]] = []
        self.running = False
        #: Atajo en marcha sin ventana todavía (se abre a los `REVEAL_MS`).
        self.quiet = False
        self._clock: QTimer | None = None
        self._reveal_timer: QTimer | None = None

    def showing(self) -> bool:
        """Si la ventana está a la vista (entonces el aviso de «capa cargada» sobra)."""
        return self.window is not None and self.window.isVisible()

    # -- atajo de un clic ----------------------------------------------------------------------------

    def quick(self, jobs: list[dict[str, Any]], kind: str) -> None:
        """«Copia» o «Conectada» directo desde el menú o al soltar: carga sin diálogo; si tarda más de
        `REVEAL_MS`, abre la línea de tiempo con lo que va. «Más opciones…» y una carga ya en curso siguen
        como siempre."""
        if kind == OPTIONS or self.running:
            self._loader.start_many(jobs, kind)
            return
        if self.window is not None:
            self.window.deleteLater()
            self.window = None
        self.chosen = [dict(job) for job in jobs]
        self.states = [{"state": WAITING, "rows": 0, "message": "", "report": None} for _ in jobs]
        self.timeline_rows = []
        self.running = True
        self.quiet = True
        self.started = time.monotonic()
        self.connected = kind == CONNECTED
        self._loader.start_many(self.chosen, kind, watch=self)

    def quick_one(
        self,
        sql: str,
        name: str,
        kind: str,
        *,
        source: tuple[str, str, str] | None = None,
        source_kind: str | None = None,
        database: str | None = None,
        rows: int | None = None,
    ) -> None:
        """El atajo para una sola carga, con la firma de `QuickLoad.start` (pestañas de tabla y consulta)."""
        job = {
            "sql": sql,
            "name": name,
            "source": source,
            "source_kind": source_kind,
            "database": database,
            "rows": rows,
        }
        self.quick([job], kind)

    def _arm_reveal(self) -> None:
        """El reloj de los `REVEAL_MS` corre desde que empieza la carga (no mientras se pregunta el SRC)."""
        if not self.quiet or self._reveal_timer is not None:
            return
        parent = self._host if isinstance(self._host, QWidget) else None
        timer = QTimer(parent)
        timer.setSingleShot(True)
        timer.timeout.connect(self._reveal)
        timer.start(REVEAL_MS)
        self._reveal_timer = timer

    def _stop_reveal(self) -> None:
        if self._reveal_timer is not None:
            self._reveal_timer.stop()
            self._reveal_timer.deleteLater()
            self._reveal_timer = None

    def _reveal(self) -> None:
        self._stop_reveal()
        if not (self.quiet and self.running):
            return
        self.quiet = False
        window = self._new_window(len(self.chosen))
        self._progress(window)
        window.fit_screen()
        window.show()
        window.raise_()

    def _new_window(self, count: int) -> TransferWindow:
        window = TransferWindow(self._host if isinstance(self._host, QWidget) else None)
        if self.window is not None:
            self.window.deleteLater()
        self.window = window
        window.set_route(
            tr("Load in QGIS"),
            ("logo", tr("1 GeoDuck table") if count == 1 else tr("{0} GeoDuck tables").format(count)),
            ("qgis-layers", tr("QGIS")),
        )
        return window

    # -- destino y nombres ------------------------------------------------------------------------------

    def open(self, jobs: list[dict[str, Any]], kind: str = COPY) -> None:
        if self.running and self.window is not None:
            self.window.show()
            self.window.raise_()
            return
        self.jobs = [dict(job) for job in jobs]
        self.quiet = False
        window = self._new_window(len(jobs))
        self.mode = Segmented([tr("Copy (mode)"), tr("Connected")], accessible_name=tr("How to load"))
        modes = self._coordinator.load_modes()
        reason = modes.get(LoadMode.CONNECTED)
        self.mode.buttons[1].setEnabled(reason is None)
        if reason:
            self.mode.buttons[1].setToolTip(reason)
        self.mode.buttons[1 if kind == CONNECTED and reason is None else 0].setChecked(True)
        self.mode.buttons[0].setToolTip(
            tr("Copies the data into QGIS memory; it no longer depends on DuckDB")
        )
        if reason is None:
            self.mode.buttons[1].setToolTip(
                tr("Reads straight from DuckDB without copying; edits are saved in DuckDB")
            )
        window.destination.addWidget(self.mode)
        self.rows: list[NameRow] = []
        for job in self.jobs:
            row = NameRow(window.colors, job["name"], origin_text(job))
            row.changed.connect(self.sync)
            window.names.add(row)
            self.rows.append(row)
        self.count = label("", "muted")
        cancel = button(tr("Cancel"))
        cancel.clicked.connect(window.close)
        self.load_button = primary("", self.start)
        window.set_footer([self.count], [cancel, self.load_button])
        window.show_form()
        window.fit_screen()
        self.sync()
        window.show()
        window.raise_()
        window.activateWindow()

    def sync(self) -> None:
        """Avisos («ya hay una capa con este nombre»: no bloquea) y el botón «Cargar N capas»."""
        taken = {layer.name() for layer in QgsProject.instance().mapLayers().values()}
        for row in self.rows:
            if row.included and row.name in taken:
                row.set_note(
                    INFO,
                    tr("There is already a layer with this name in the project (it can be loaded anyway)"),
                )
            else:
                row.set_note(None)
        chosen = sum(1 for row in self.rows if row.included and row.name)
        self.count.setText(tr("1 table chosen") if chosen == 1 else tr("{0} tables chosen").format(chosen))
        self.load_button.setText(tr("Load 1 layer") if chosen == 1 else tr("Load {0} layers").format(chosen))
        self.load_button.setEnabled(chosen > 0)

    @property
    def kind(self) -> str:
        return CONNECTED if self.mode.buttons[1].isChecked() else COPY

    # -- progreso ------------------------------------------------------------------------------------

    def start(self) -> None:
        window = self.window
        if window is None or not self.load_button.isEnabled():
            return
        chosen = [
            dict(job, name=row.name) for job, row in zip(self.jobs, self.rows, strict=True) if row.included
        ]
        self.chosen = chosen
        self.states = [{"state": WAITING, "rows": 0, "message": "", "report": None} for _ in chosen]
        self.running = True
        self.started = time.monotonic()
        self.connected = self.kind == CONNECTED
        self._progress(window)
        self._loader.start_many(chosen, self.kind, watch=self)

    def _progress(self, window: TransferWindow) -> None:
        """El diálogo pasa a la línea de tiempo de `self.chosen`, con «Cancelar · Esc» y su reloj."""
        view = window.timeline
        view.clear()
        self.timeline_rows = [view.add_row(job["name"]) for job in self.chosen]
        window.show_progress()
        stop = button(tr("Cancel") + " · Esc")
        stop.clicked.connect(self.cancel)
        window.on_escape = self.cancel
        window.set_footer([], [stop])
        self._clock = QTimer(window)
        self._clock.setInterval(250)
        self._clock.timeout.connect(self._render)
        self._clock.start()
        self._render()

    def cancel(self) -> None:
        if self.running:
            self._coordinator.cancel_current_operation()
            return
        if self.window is not None:
            self.window.close()

    def job_started(self, index: int, request: Any) -> None:
        # #172: una Copia que no cabía puede volver a empezar como Conectada
        mode = getattr(request, "mode", None)
        if mode is not None:
            self.states[index]["connected"] = mode is LoadMode.CONNECTED
        self.states[index]["state"] = RUNNING
        self.states[index]["started"] = time.monotonic()
        self._arm_reveal()
        self._render()

    def job_progressed(self, index: int, rows: int) -> None:
        self.states[index]["rows"] = rows
        self._render()

    def job_finished(self, index: int, report: Any) -> None:
        state = self.states[index]
        state["state"] = DONE
        state["report"] = report
        state["rows"] = report.rows
        state["seconds"] = time.monotonic() - state.get("started", time.monotonic())
        self._check_done()

    def job_failed(self, index: int, message: str, cancelled: bool) -> None:
        if not 0 <= index < len(self.states):
            return
        state = self.states[index]
        state["state"] = "cancelled" if cancelled else "failed"
        state["message"] = message
        if "started" in state:
            state["seconds"] = time.monotonic() - state["started"]
        self._check_done()

    def batch_stopped(self) -> None:
        for state in self.states:
            if state["state"] == WAITING:
                state["state"] = "cancelled"
        self._check_done()

    def _check_done(self) -> None:
        if all(s["state"] not in (WAITING, RUNNING) for s in self.states):
            self.running = False
            self._stop_reveal()
            if self.quiet:  # terminó antes de `REVEAL_MS`: el aviso basta
                self.quiet = False
                return
            if self._clock is not None:
                self._clock.stop()
            self._final_footer()
        self._render()

    def _steps(self, index: int) -> list[Step]:
        job = self.chosen[index]
        s = self.states[index]
        state = s["state"]
        connected = s.get("connected", self.connected)
        origin = Step("database", tr("Source"), origin_text(job), DONE if state != WAITING else WAITING)
        if connected:
            move = Step("database", tr("Connected layer"), tr("Reads straight from DuckDB without copying"))
        else:
            move = Step("layers", tr("Copy to QGIS"))
        layer = Step("map", tr("Layer in QGIS"), f"«{job['name']}»")
        if state == RUNNING:
            move.state = RUNNING
            move.seconds = time.monotonic() - s["started"]
            if s["rows"] and not connected:
                move.detail = rows_text(s["rows"])
        elif state == DONE:
            move.state = layer.state = DONE
            move.seconds = s.get("seconds")
            report = s["report"]
            if not connected:
                move.detail = rows_text(s["rows"])
            names = [name for _id, name in getattr(report, "layers", ())] or [report.layer_name]
            layer.detail = " · ".join(f"«{n}»" for n in names)
            if report.warnings:
                layer.detail += "\n⚠ " + "; ".join(report.warnings)
        elif state == "failed":
            move.state = FAILED
            move.seconds = s.get("seconds")
            if s.get("card") is None:
                card = ErrorCardView(
                    explain("", s["message"] or tr("Unknown error"), "", None), self.window.colors
                )
                card.go_button.hide()
                s["card"] = card
            move.card = s["card"]
            layer.state = SKIPPED
        elif state == "cancelled":
            move.state = layer.state = SKIPPED
        return [origin, move, layer]

    def _status(self, index: int) -> tuple[str, str | None]:
        s = self.states[index]
        if s["state"] == RUNNING:
            text = tr("Copying…") if not self.connected else tr("Connecting…")
            return text + (f" {count_text(s['rows'])}" if s["rows"] else ""), "accent"
        if s["state"] == DONE:
            text = "✓ " + rows_text(s["rows"])
            return text + " · " + seconds_text(s.get("seconds")), "ok"
        if s["state"] == "failed":
            return tr("Error"), "error"
        if s["state"] == "cancelled":
            return tr("Cancelled"), None
        return tr("Waiting"), None

    def _render(self) -> None:
        window = self.window
        if window is None or not self.states or self.quiet:
            return
        view = window.timeline
        current = None
        for i, row in enumerate(self.timeline_rows):
            row.set_steps(self._steps(i))
            text, tone = self._status(i)
            row.set_status(text, tone)
            if self.states[i]["state"] in (RUNNING, "failed") and current is None:
                current = row
        total = len(self.states)
        finished = sum(1 for s in self.states if s["state"] not in (WAITING, RUNNING))
        seconds = time.monotonic() - self.started
        how = tr("Connected") if self.connected else tr("Copy (mode)")
        if self.running:
            view.set_header(
                tr("GeoDuck → QGIS"),
                how + " · " + tr("{0} of {1}").format(min(finished + 1, total), total),
                seconds,
            )
            view.set_total(finished / total if total else None)
        else:
            added = sum(1 for s in self.states if s["state"] == DONE)
            rows = sum(s["rows"] for s in self.states if s["state"] == DONE)
            title = (
                tr("Done: 1 layer in QGIS") if added == 1 else tr("Done: {0} layers in QGIS").format(added)
            )
            if added < total:
                title = tr("{0} of {1} layers in QGIS").format(added, total)
            view.set_header(title, f"{how} · " + rows_text(rows) + f" · {seconds_text(seconds)}")
            view.set_total(None)
        view.follow(current)

    def _final_footer(self) -> None:
        window = self.window
        if window is None:
            return
        window.on_escape = None
        ids = []
        for s in self.states:
            report = s.get("report")
            if report is not None:
                ids += [layer_id for layer_id, _ in report.layers] or [report.layer_id]
        show = button(tr("View on map"))
        show.setEnabled(bool(ids))
        show.clicked.connect(lambda: self._host.view_map(ids))
        close = button(tr("Close"), "primary")
        close.clicked.connect(window.close)
        window.set_footer([show], [close])

    def detach(self) -> None:
        self._stop_reveal()
        self.quiet = False
        if self.window is not None:
            self.window.on_close = None
            self.window.hide()
            self.window.deleteLater()
            self.window = None
