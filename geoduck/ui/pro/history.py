# SPDX-License-Identifier: GPL-2.0-or-later
"""«Historial» de Workspace Pro (G9 · E6): lo ejecutado en esta sesión de QGIS, como el registro de G6.

Una fila por sentencia: hora, estado (✓ OK, ✕ Error, Cancelada, Omitida), la sentencia en una línea, cuánto
tardó y el mensaje. «Todo / OK / Error» filtra. Doble clic (o Intro) abre la sentencia en una consulta nueva,
sin ejecutarla. Se abre desde Ctrl+K › «Historial» y no se recuerda entre reinicios: solo vive en memoria.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from geoduck.app.events import AppEvent, StatementFinished
from geoduck.domain.sql import StatementStatus
from geoduck.ui.i18n import tr
from geoduck.ui.pro.tokens import Colors
from geoduck.ui.pro.widgets import Segmented, button, label

#: Sentencias que se guardan (las más antiguas se descartan).
MAX_ENTRIES = 1000
ALL, OK, ERROR = 0, 1, 2
TIME, STATUS, STATEMENT, DURATION, MESSAGE = range(5)


@dataclass(frozen=True)
class Entry:
    when: str
    status: StatementStatus
    sql: str
    duration_ms: float
    message: str
    database: str | None


def status_text(status: StatementStatus) -> str:
    return {
        StatementStatus.OK: "✓ " + tr("OK"),
        StatementStatus.FAILED: "✕ " + tr("Error"),
        StatementStatus.CANCELLED: tr("Cancelled"),
        StatementStatus.SKIPPED: tr("Skipped"),
    }[status]


class History(QObject):
    """Escucha al coordinador y guarda cada sentencia terminada. `added` avisa a la pestaña abierta."""

    added = pyqtSignal(object)  # Entry

    def __init__(self, coordinator: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.entries: list[Entry] = []
        self._unsubscribe = coordinator.subscribe(self._on_event)

    def _on_event(self, event: AppEvent) -> None:
        if not isinstance(event, StatementFinished):
            return
        result = event.result
        entry = Entry(
            time.strftime("%H:%M:%S"),
            result.status,
            result.statement.text.strip(),
            result.duration_ms,
            result.message,
            result.database,
        )
        self.entries.append(entry)
        del self.entries[:-MAX_ENTRIES]
        self.added.emit(entry)

    def clear(self) -> None:
        self.entries.clear()

    def detach(self) -> None:
        with contextlib.suppress(Exception):
            self._unsubscribe()


class HistoryPage(QWidget):
    """La pestaña «Historial». `open_sql(sql, database)` abre una sentencia en una consulta nueva."""

    def __init__(
        self,
        place: Any,
        history: History,
        colors: Colors,
        open_sql: Callable[[str, str | None], None],
    ) -> None:
        super().__init__()
        self.place = place
        self.history = history
        self.colors = colors
        self._open_sql = open_sql
        self._filter = ALL
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        bar = QFrame()
        bar.setProperty("pro", "rule-bottom")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(10)
        self.filter = Segmented([tr("All"), tr("OK"), tr("Error")], accessible_name=tr("Filter the history"))
        self.filter.changed.connect(self.set_filter)
        row.addWidget(self.filter)
        self.counts = label("", "muted")
        self.counts.setMinimumWidth(1)  # por debajo de su texto: se recorta en vez de ensanchar el panel
        row.addWidget(self.counts)
        row.addStretch(1)
        self.hint = label(tr("Double-click: open in a new query"), "faint")
        row.addWidget(self.hint)
        self.clear_button = button(tr("Clear"), "ghost")
        self.clear_button.clicked.connect(self.clear)
        row.addWidget(self.clear_button)
        box.addWidget(bar)
        self.table = QTableWidget(0, 5)
        self.table.setProperty("pro", "list")
        titles = [tr("Time"), tr("Status"), tr("Statement"), tr("Duration"), tr("Message")]
        self.table.setHorizontalHeaderLabels(titles)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setAccessibleName(tr("Execution history"))
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column, mode in (
            (TIME, QHeaderView.ResizeMode.ResizeToContents),
            (STATUS, QHeaderView.ResizeMode.ResizeToContents),
            (STATEMENT, QHeaderView.ResizeMode.Stretch),
            (DURATION, QHeaderView.ResizeMode.ResizeToContents),
            (MESSAGE, QHeaderView.ResizeMode.Interactive),
        ):
            header.setSectionResizeMode(column, mode)
        header.resizeSection(MESSAGE, 320)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.open_row(r))
        self.table.activated.connect(lambda index: self.open_row(index.row()))
        box.addWidget(self.table, 1)
        for entry in history.entries:
            self._add(entry)
        history.added.connect(self._add)
        self._update_counts()
        self.table.scrollToBottom()

    def set_compact(self, compact: bool) -> None:
        """Modo compacto (#147, punto 28): sin la ayuda del doble clic (sigue en la ayuda de cada fila) y con
        márgenes cortos, para que el panel baje a 320 px."""
        from geoduck.ui.pro.table_page import tighten  # noqa: PLC0415

        self.hint.setVisible(not compact)
        self.filter.set_compact(compact)
        tighten(self.filter.parentWidget().layout(), compact, (16, 8, 16, 8), 10)

    def _add(self, entry: Entry) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        timed = entry.status in (StatementStatus.OK, StatementStatus.FAILED)
        duration = f"{entry.duration_ms:.0f} ms" if timed else ""
        values = (entry.when, status_text(entry.status), " ".join(entry.sql.split()), duration, entry.message)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == STATEMENT:
                item.setToolTip(entry.sql)
                item.setData(Qt.ItemDataRole.UserRole, entry)
            elif column == MESSAGE:
                item.setToolTip(entry.message)
            if column in (TIME, DURATION, MESSAGE) or entry.status in (
                StatementStatus.CANCELLED,
                StatementStatus.SKIPPED,
            ):
                item.setForeground(QColor(self.colors.muted))
            if column == STATUS and entry.status is StatementStatus.OK:
                item.setForeground(QColor(self.colors.ok))
            elif column == STATUS and entry.status is StatementStatus.FAILED:
                item.setForeground(QColor(self.colors.error))
            self.table.setItem(row, column, item)
        self.table.setRowHidden(row, not self._shown(entry))
        self._update_counts()
        at_end = self.table.verticalScrollBar().value() >= self.table.verticalScrollBar().maximum() - 40
        if at_end:
            self.table.scrollToBottom()

    def _shown(self, entry: Entry) -> bool:
        if self._filter == OK:
            return entry.status is StatementStatus.OK
        if self._filter == ERROR:
            return entry.status is StatementStatus.FAILED
        return True

    def entry(self, row: int) -> Entry | None:
        item = self.table.item(row, STATEMENT)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def set_filter(self, index: int) -> None:
        self._filter = index
        for row in range(self.table.rowCount()):
            entry = self.entry(row)
            self.table.setRowHidden(row, entry is None or not self._shown(entry))

    def _update_counts(self) -> None:
        entries = self.history.entries
        errors = sum(e.status is StatementStatus.FAILED for e in entries)
        text = tr("{0} statements").format(len(entries))
        if errors:
            text += " · " + tr("{0} with error").format(errors)
        self.counts.setText(text)

    def open_row(self, row: int) -> None:
        entry = self.entry(row)
        if entry is not None:
            self._open_sql(entry.sql, entry.database)

    def clear(self) -> None:
        self.history.clear()
        self.table.setRowCount(0)
        self._update_counts()

    def close_page(self) -> None:
        with contextlib.suppress(TypeError, RuntimeError):
            self.history.added.disconnect(self._add)
