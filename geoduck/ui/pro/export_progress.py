# SPDX-License-Identifier: GPL-2.0-or-later
"""«Exportar ▾» con la misma línea de tiempo que importar y cargar (#148, punto 19; maqueta
`progreso-traza`, panel 3): **Consulta → DuckDB escribe el archivo → Archivo**, cada paso con su tiempo.
Mientras escribe, «Cancelar · Esc»; al terminar, «Abrir carpeta», «Cargar en QGIS» y «Cerrar». Todo lo
escribe DuckDB, nunca QGIS."""

from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable
from pathlib import Path

from qgis.PyQt.QtCore import QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QWidget

from geoduck.app.events import ExportFailed, ExportFinished, ExportStarted
from geoduck.domain.i18n import decimal
from geoduck.domain.i18n import rows as rows_text
from geoduck.domain.sql_errors import explain
from geoduck.ui.i18n import tr
from geoduck.ui.pro.error_card import ErrorCardView
from geoduck.ui.pro.timeline import (
    DONE,
    FAILED,
    RUNNING,
    SKIPPED,
    WAITING,
    Step,
    TimelineWindow,
    seconds_text,
)
from geoduck.ui.pro.widgets import button

#: Lo que se ve de la consulta en el primer paso.
SQL_PREVIEW = 120


def size_text(path: str) -> str:
    """«84 MB», «12 KB» (vacío si el archivo no está)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{decimal(size)} {unit}"
        size /= 1024
    return ""


def sql_preview(sql: str) -> str:
    """La consulta en una línea, recortada («SELECT zona, geom … FROM lecturas»)."""
    text = " ".join(sql.split())
    return text if len(text) <= SQL_PREVIEW else text[: SQL_PREVIEW - 1] + "…"


class ExportProgress:
    """Una exportación en curso: su ventana con la línea de tiempo. `cancel` detiene; `load` carga el archivo
    en QGIS."""

    def __init__(
        self,
        parent: QWidget | None,
        event: ExportStarted,
        *,
        cancel: Callable[[], None],
        load: Callable[[str], None],
    ) -> None:
        self.request = event.request
        self.started = time.monotonic()
        self._cancel = cancel
        self._load = load
        self.done = False
        path = Path(self.request.path)
        self.window = TimelineWindow(parent, tr("Export"))
        self.row = self.window.view.add_row(path.name)
        self.row.set_open(True)
        self.row.user_set = True
        self.steps = [
            Step("code", tr("Query"), sql_preview(self.request.sql), DONE),
            Step("database", tr("GeoDuck writes the file"), self._how(), RUNNING),
            Step("file", tr("File"), str(path), WAITING),
        ]
        self.window.on_escape = self.cancel
        stop = button(tr("Cancel") + " · Esc")
        stop.clicked.connect(self.cancel)
        self.window.set_footer([], [stop])
        self._clock = QTimer(self.window)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._render)
        self._clock.start()
        self._render()
        self.window.show()

    def _how(self) -> str:
        fmt = self.request.format
        parts = [f"COPY … (FORMAT {fmt.label})"]
        if fmt.needs_spatial:
            parts.append(tr("«spatial» extension"))
        parts.append(tr("without going through QGIS"))
        return " · ".join(parts)

    def _render(self, rows: int | None = None) -> None:
        name = Path(self.request.path).name
        seconds = time.monotonic() - self.started
        view = self.window.view
        if not self.done:
            self.steps[1].seconds = seconds
            view.set_header(tr("Exporting: {0}").format(name), self.request.format.label, seconds)
            view.set_total(None)
            self.row.set_status(tr("Writing…"), "accent")
        self.row.set_steps(self.steps)

    def cancel(self) -> None:
        if self.done:
            self.window.close()
            return
        self._cancel()

    def finish(self, event: ExportFinished | ExportFailed) -> None:
        self.done = True
        self._clock.stop()
        seconds = time.monotonic() - self.started
        view = self.window.view
        name = Path(self.request.path).name
        self.window.on_escape = None
        close = button(tr("Close"), "primary")
        close.clicked.connect(self.window.close)
        if isinstance(event, ExportFinished):
            report = event.report
            self.steps[1] = Step("database", tr("GeoDuck writes the file"), self._how(), DONE, seconds)
            detail = " · ".join(p for p in (report.path, size_text(report.path)) if p)
            self.steps[2] = Step("file", tr("File"), detail, DONE)
            lines = [rows_text(report.rows)]
            view.set_header(tr("Exported: {0}").format(name), " · ".join([*lines, seconds_text(seconds)]))
            self.row.set_status("✓ " + rows_text(report.rows), "ok")
            if report.warnings:
                self.steps[2].detail += "\n⚠ " + "; ".join(report.warnings)
            folder = str(Path(report.path).parent)
            show = button(tr("Open folder"))
            show.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
            load = button(tr("Load in QGIS"))
            load.clicked.connect(lambda: self._load(report.path))
            self.window.set_footer([show, load], [close])
        else:
            card = None
            if not event.cancelled:
                card = ErrorCardView(explain("", event.message, "", None), self.window.colors)
                card.go_button.hide()
            self.steps[1] = Step(
                "database",
                tr("GeoDuck writes the file"),
                self._how(),
                SKIPPED if event.cancelled else FAILED,
                seconds,
                card=card,
            )
            view.set_header(
                tr("Export cancelled") if event.cancelled else tr("Cannot export: {0}").format(name), ""
            )
            self.row.set_status(
                tr("Cancelled") if event.cancelled else tr("Error"), None if event.cancelled else "error"
            )
            self.window.set_footer([], [close])
        with contextlib.suppress(RuntimeError):
            self.row.set_steps(self.steps)
