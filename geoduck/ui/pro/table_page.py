# SPDX-License-Identifier: GPL-2.0-or-later
"""Pestaña de tabla de Workspace Pro (workspace-pro-spec §4; GD-WSP-003; AT-WSP-003, 004).

Solo lectura. **Datos:** la grilla compartida (`grid.DataGrid`, #144): páginas de 100 filas que DuckDB lee
bajo demanda, filtros (casillas bajo los encabezados, chips, clic derecho, barra `WHERE`), orden con ⇅,
selección como en una hoja de cálculo, detalle de la fila y resumen de la columna; aquí, además, la búsqueda
en las columnas de texto, «1–100 de 48 312» con el total contado aparte, «Ver SQL», exportar y cargar.
**Estructura:** columnas (nombre, tipo, nulos, clave), filas, tamaño aproximado y la sentencia `CREATE`.

Toda lectura va al worker por `SessionCoordinator.read_rows` (SQL de `domain.browse`) y vuelve en el hilo de
la interfaz; una respuesta vieja (de antes de otro filtro u orden) se descarta.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from geoduck.app.events import (
    AppEvent,
    CatalogChanged,
    ColumnsListed,
    ColumnsUnavailable,
    PreviewsInvalidated,
    SessionStateChanged,
)
from geoduck.domain.browse import Browse, Filter, page_label, size_sql, structure_sql
from geoduck.domain.catalog import ColumnInfo
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.export import ExportFormat
from geoduck.domain.i18n import decimal
from geoduck.domain.i18n import rows as rows_text
from geoduck.domain.operations import StatementOutcome
from geoduck.domain.session import SessionState
from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons
from geoduck.ui.pro.grid import GRID, DataGrid
from geoduck.ui.pro.load import (
    export_menu,
    export_query,
    is_temporary,
    layer_name,
    load_menu,
    popup_under,
)
from geoduck.ui.pro.places import VIEW, Place
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import SearchField, Segmented, button, icon_button, label

# -- estructura ------------------------------------------------------------------------------------------


class StructureView(QWidget):
    """«Estructura»: columnas (nombre, tipo, nulos, clave), filas, tamaño aproximado y `CREATE`."""

    def __init__(self, colors: Colors) -> None:
        super().__init__()
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(10)
        self.summary = label("", "muted")
        box.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setProperty("pro", "list")
        self.table.setHorizontalHeaderLabels([tr("Column"), tr("Type"), tr("Nulls"), tr("Key")])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.table.verticalHeader().setDefaultSectionSize(METRICS.row)
        box.addWidget(self.table, 3)
        row = QHBoxLayout()
        row.addWidget(label(tr("Definition"), "section"))
        row.addStretch(1)
        self.copy_button = button(tr("Copy"), "ghost", icon="copy", colors=colors)
        self.copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.create.toPlainText())
        )
        row.addWidget(self.copy_button)
        box.addLayout(row)
        self.create = QPlainTextEdit()
        self.create.setProperty("pro", "code")
        self.create.setReadOnly(True)
        self.create.setAccessibleName(tr("Definition"))
        box.addWidget(self.create, 2)

    def show_structure(
        self,
        columns: tuple[ColumnInfo, ...],
        keys: dict[str, str],
        rows: int | None,
        size: int | None,
        sql: str,
    ) -> None:
        self.table.setRowCount(len(columns))
        for i, column in enumerate(columns):
            nulls = "" if column.nullable is None else (tr("yes") if column.nullable else tr("no"))
            for j, text in enumerate((column.name, column.data_type, nulls, keys.get(column.name, ""))):
                self.table.setItem(i, j, QTableWidgetItem(text))
        parts = [tr("{} columns").format(len(columns))]
        if rows is not None:
            parts.append(rows_text(rows))
        if size:
            parts.append(tr("about {}").format(_size(size)))
        self.summary.setText(" · ".join(parts))
        self.create.setPlainText(sql)


def _size(rows_bytes: int) -> str:
    value = float(rows_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{decimal(value)} {unit}"
        value /= 1024
    return ""


# -- la pestaña ------------------------------------------------------------------------------------------


class TablePage(QWidget):
    """La pestaña de una tabla o vista. `view_sql(texto)` abre «Ver SQL» en una consulta nueva.

    Los datos, sus filtros, la selección y el detalle son la `DataGrid` (#144); la pestaña pone las columnas
    de la tabla, la búsqueda, la estructura, el pie (páginas, exportar, cargar) y escucha a la sesión."""

    def __init__(
        self,
        place: Place,
        coordinator: Any,
        colors: Colors,
        view_sql: Callable[[str], object] | None = None,
        *,
        loader: Callable[..., None] | None = None,
        ask_path: Callable[[str, str, str], str] | None = None,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.place = place
        self.colors = colors
        self._coordinator = coordinator
        self._view_sql = view_sql
        self._loader = loader
        self._ask_path = ask_path
        self._notify = notify or (lambda _text: None)
        self.source = (place.database, place.schema, place.name)
        self.is_view = place.kind == VIEW
        self._closed = False
        self._structure_loaded = False
        self.compact = False
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.data = DataGrid(
            colors,
            self._read_rows,
            name=place.name,
            notify=self._notify,
            offer_export=lambda: popup_under(self.export_menu, self.export_button),
            view_sql=view_sql,
        )
        self.data.changed.connect(self._update_range)
        self._build_tools()
        self.views = QStackedWidget()
        self.views.addWidget(self.data)
        self.structure = StructureView(colors)
        self.views.addWidget(self.structure)
        box.addWidget(self.views, 1)
        box.addWidget(self._build_footer())
        # la barra de filtros va arriba también en «Estructura» (sus botones de estructura y detalle)
        box.insertWidget(0, self.data.filter_bar)
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self.data.show_message(tr("Loading…"))
        self.load()

    # -- lo que las pruebas y el área de trabajo ven de la grilla ---------------------------------------

    @property
    def browse(self) -> Browse | None:
        return self.data.browse

    @browse.setter
    def browse(self, value: Browse | None) -> None:
        self.data.browse = value

    @property
    def total(self) -> int | None:
        return self.data.total

    @property
    def offset(self) -> int:
        return self.data.offset

    @property
    def grid(self) -> Any:
        return self.data.grid

    @property
    def model(self) -> Any:
        return self.data.model

    @property
    def header(self) -> Any:
        return self.data.header

    @property
    def detail(self) -> Any:
        return self.data.detail

    @property
    def body(self) -> Any:
        return self.data.body

    @property
    def message(self) -> Any:
        return self.data.message

    @property
    def retry_button(self) -> Any:
        return self.data.retry_button

    @property
    def clear_button(self) -> Any:
        return self.data.clear_button

    @property
    def chips(self) -> Any:
        return self.data.chips

    @property
    def sql_button(self) -> Any:
        return self.data.sql_button

    @property
    def detail_open(self) -> bool:
        return self.data.detail_open

    # -- construcción ---------------------------------------------------------------------------------

    def _build_tools(self) -> None:
        """A la derecha de los chips: la búsqueda, «Estructura» (compacto) y el detalle ◫."""
        self.search = SearchField(
            tr("Search in text columns…"), self.colors, accessible_name=tr("Search in the table")
        )
        self.search.setFixedWidth(240)
        self.search.edit.returnPressed.connect(self._search_changed)
        self.search.edit.textChanged.connect(lambda text: self._search_changed() if not text else None)
        self.data.add_tool(self.search)
        # «Estructura» como ícono, solo en el modo compacto (el pie no tiene sitio para «Datos | Estructura»)
        self.structure_button = icon_button("info", tr("Structure: columns, types and keys"), self.colors)
        self.structure_button.setCheckable(True)
        self.structure_button.toggled.connect(self._structure_toggled)
        self.structure_button.hide()
        self.data.add_tool(self.structure_button)
        self.detail_button = icon_button("dock", tr("Show or hide the row detail"), self.colors)
        self.detail_button.setIcon(icons.toggle("dock", self.colors.muted, self.colors.accent))
        self.detail_button.setCheckable(True)
        self.detail_button.setChecked(True)
        self.detail_button.toggled.connect(self.set_detail_open)
        self.data.add_tool(self.detail_button)

    def _build_footer(self) -> QWidget:
        foot = QFrame()
        foot.setProperty("pro", "rule-top")
        foot.setFixedHeight(METRICS.bar - 4)
        row = QHBoxLayout(foot)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(10)
        self.mode = Segmented([tr("Data"), tr("Structure")], accessible_name=tr("Data or structure"))
        self.mode.changed.connect(self.show_mode)
        row.addWidget(self.mode)
        self.range_label = label("", "muted")
        row.addWidget(self.range_label)
        # #170: sin ‹ ›; las filas se recorren desplazándose (el contador dice cuáles se ven)
        self.column_summary = label("", "muted")
        self.column_summary.setFont(ui_font(METRICS.font_small, mono=True))
        row.addWidget(self.column_summary, 1)
        # Solo iconos, en la ventana y en el panel, como la barra «Resultado»
        self.export_button = icon_button(
            "export", tr("Exports the table with its filters, search and order"), self.colors
        )
        self.export_menu = export_menu(self, self.export)
        self.export_button.clicked.connect(lambda: popup_under(self.export_menu, self.export_button))
        row.addWidget(self.export_button)
        self.load_button = icon_button(
            "layers", tr("Loads the table into QGIS (with its filters and search, if any)"), self.colors
        )
        self.load_menu = load_menu(
            self,
            self.colors,
            self.load_in_qgis,
            more=True,
            name=lambda: self.place.name,
            temporary=is_temporary([self.place.database]),
        )
        self.load_button.clicked.connect(lambda: popup_under(self.load_menu, self.load_button))
        row.addWidget(self.load_button)
        return foot

    def _query_sql(self) -> str:
        """La consulta de «Cargar en QGIS» y «Exportar»: la tabla con sus filtros, búsqueda y orden."""
        return self.browse.display_sql() if self.browse is not None else ""

    def load_in_qgis(self, kind: str) -> None:
        """«Cargar en QGIS ▾». Sin filtros ni búsqueda, la tabla misma (una «Conectada» se puede editar);
        con filtros o búsqueda, solo esas filas."""
        if self.browse is None or self._loader is None:
            return
        whole = not self.browse.filtered
        self._loader(
            self._query_sql(),
            layer_name(self.load_menu, self.place.name),
            kind,
            source=self.source if whole else None,
            source_kind=("view" if self.is_view else "table") if whole else None,
            rows=self.total,  # #172: para saber antes si una Copia cabe en memoria
        )

    def export(self, fmt: ExportFormat) -> None:
        if self.browse is None or self._ask_path is None:
            return
        export_query(
            self._coordinator, self._query_sql(), None, self.place.name, fmt, self._ask_path, self._notify
        )

    # -- lecturas -------------------------------------------------------------------------------------

    def _read_rows(self, sql: str, max_rows: int, done: Callable[[Any], None]) -> bool:
        if self._closed:
            return False
        try:
            self._coordinator.read_rows(sql, max_rows, done)
        except GeoDuckError:
            return False
        return True

    def _read(
        self,
        sql: str,
        max_rows: int,
        done: Callable[[StatementOutcome], None],
        fresh: Callable[[], bool] | None = None,
    ) -> bool:
        """Lecturas de la estructura (las de los datos son de la grilla)."""
        return self.data._read(sql, max_rows, done, fresh)

    def load(self) -> None:
        """Columnas (si aún no se tienen) y la página actual."""
        if self._closed:
            return
        self.data.pending = True
        state = self._coordinator.state
        if self._coordinator.engine_info is None or state is SessionState.DISCONNECTED:
            self.data.show_message(tr("Start GeoDuck to see this table."))
            self._update_range()
            return
        if state is not SessionState.READY:
            self.data.show_message(self.data.busy_text)
            return
        known = self._coordinator.known_columns().get(self.source)
        if known is not None:
            self._columns_ready(known)
            return
        self.data.show_message(tr("Loading…"))
        try:
            self._coordinator.list_columns(self.source)
        except GeoDuckError:
            self.data.show_message(self.data.busy_text)

    def _columns_ready(self, columns: tuple[ColumnInfo, ...]) -> None:
        old = self.browse
        if old is None or old.columns != columns:
            names = {c.name for c in columns}
            browse = Browse(*self.source, columns, has_rowid=not self.is_view)
            if old is not None:  # los filtros y el orden de las columnas que siguen ahí
                browse = replace(
                    browse,
                    filters=tuple(f for f in old.filters if f.column in names),
                    search=old.search,
                    order=old.order if old.order and old.order[0] in names else None,
                    boxes=tuple((n, t) for n, t in old.boxes if n in names),
                    where=old.where,
                )
            self.data.browse = browse
            self.data.where_edit.set_columns([c.name for c in columns])
        self.reload(keep_offset=True)

    def reload(self, *, keep_offset: bool = False) -> None:
        """Vuelve a leer la página (y el total) con los filtros, la búsqueda y el orden actuales."""
        if self.browse is None:
            self.load()
            return
        self.data.reload(keep_offset=keep_offset)
        if self._structure_loaded:
            self._structure_loaded = False
            if self.mode.current == 1:
                self._load_structure()

    def go(self, offset: int) -> None:
        self.data.go(offset)

    def _update_range(self) -> None:
        shown = self.model.rowCount()
        browse = self.browse
        if browse is None or self.body.currentIndex() != GRID:
            self.range_label.setText("" if browse is None or not browse.filtered else self.range_label.text())
        else:
            text = page_label(self.offset, shown, self.total, estimate=self.data.estimate)
            self.range_label.setText(text)
            self.range_label.setToolTip(text)
        self.column_summary.setText(self.data.summary)
        self.column_summary.setToolTip(self.data.summary)

    # -- acciones -------------------------------------------------------------------------------------

    def add_filter(self, item: Filter) -> None:
        self.data.add_filter(item)

    def remove_filter(self, index: int) -> None:
        self.data.remove_filter(index)

    def clear_filters(self) -> None:
        self.search.edit.blockSignals(True)
        self.search.edit.clear()
        self.search.edit.blockSignals(False)
        self.data.clear_filters()

    def _search_changed(self) -> None:
        if self.browse is not None and self.browse.search != self.search.edit.text().strip():
            self.data.browse = self.browse.with_search(self.search.edit.text())
            self.reload()

    def view_sql(self) -> None:
        self.data.view_sql()

    def set_detail_open(self, open_: bool) -> None:
        self.data.set_detail_open(open_)

    def copy_selection(self) -> None:
        self.data.copy_selection()

    def _structure_toggled(self, on: bool) -> None:
        index = 1 if on else 0
        if self.mode.current != index:
            self.mode.set_current(index)
        if self.views.currentIndex() != index:
            self.show_mode(index)

    def set_compact(self, compact: bool) -> None:
        """Modo compacto (panel acoplado o ventana angosta): las mismas opciones, con
        ícono y tooltip donde no cabe el texto; «Estructura» pasa a un ícono arriba; el detalle, cerrado.
        «Exportar», «Cargar en QGIS» y «Ver SQL» son siempre solo iconos."""
        self.compact = compact
        self.data.set_compact(compact)
        self.search.setFixedWidth(110 if compact else 240)
        self.mode.setVisible(not compact)
        self.structure_button.setVisible(compact)
        self.structure_button.setChecked(self.mode.current == 1)
        self.detail_button.setChecked(not compact)
        self.column_summary.setVisible(not compact)
        tighten(self.range_label.parentWidget().layout(), compact, (16, 0, 16, 0), 10)

    def show_mode(self, index: int) -> None:
        """«Datos» o «Estructura»."""
        self.views.setCurrentIndex(index)
        if self.structure_button.isChecked() != (index == 1):
            self.structure_button.setChecked(index == 1)
        data = index == 0
        for widget in (self.search, self.data.sql_button, self.detail_button, self.data.funnel_button):
            widget.setVisible(data)
        self.data.where_row.setVisible(data and self.data.filters_open)
        for i in range(self.chips.count()):
            item = self.chips.itemAt(i).widget()
            if item is not None:
                item.setVisible(data)
        self.data.count_label.setVisible(data and bool(self.data.count_label.text()))
        for widget in (self.range_label, self.column_summary):
            widget.setVisible(data)
        if index == 1 and not self._structure_loaded:
            self._load_structure()

    def _load_structure(self) -> None:
        browse = self.browse
        if browse is None:
            return
        self._structure_loaded = True
        found: dict[str, Any] = {"keys": {}, "definition": "", "rows": None, "size": None}

        def show() -> None:
            self.structure.show_structure(
                browse.columns, found["keys"], found["rows"], found["size"], found["definition"]
            )

        def described(result: StatementOutcome) -> None:
            for kind, text, _value, columns in result.rows:
                if kind == "definition":
                    found["definition"] = str(text or "")
                elif columns:
                    for name in columns:  # type: ignore[attr-defined]
                        keys = found["keys"]
                        keys[str(name)] = (keys.get(str(name), "") + " " + _key_text(str(text))).strip()
            show()

        def counted(result: StatementOutcome) -> None:
            found["rows"] = int(result.rows[0][0]) if result.rows else None
            show()

        def measured(result: StatementOutcome | BaseException) -> None:
            if (
                not self._closed
                and not isinstance(result, BaseException)
                and result.rows
                and result.rows[0][0]
            ):
                found["size"] = int(result.rows[0][0])
                show()

        fresh = lambda: self.browse is browse  # noqa: E731 - misma tabla, filtros y orden
        self._read(structure_sql(*self.source), 200, described, fresh)
        self._read(Browse(*self.source, browse.columns).count_sql(), 1, counted, fresh)  # filas de la tabla
        if not self.is_view:  # tamaño en disco; en memoria o sin guardar aún, no se muestra
            with contextlib.suppress(GeoDuckError):
                self._coordinator.read_rows(size_sql(*self.source), 1, measured)

    # -- eventos --------------------------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if self._closed:
            return
        if isinstance(event, ColumnsListed) and event.source == self.source:
            self._columns_ready(event.columns)
        elif isinstance(event, ColumnsUnavailable) and event.source == self.source:
            self.data.show_message(tr("The table could not be read.") + f"\n{event.message}", retry=True)
        elif isinstance(event, PreviewsInvalidated) and self.browse is not None:
            self.reload(keep_offset=True)  # SQL del usuario cambió datos
        elif isinstance(event, CatalogChanged):
            self.data.pending = True  # las columnas pueden haber cambiado: se releen
            if event.catalog is not None and self._coordinator.state is SessionState.READY:
                self.load()
        elif isinstance(event, SessionStateChanged):
            if event.current is SessionState.READY and self.data.pending:
                self.load()
            elif event.current is SessionState.DISCONNECTED:
                self.data.clear(tr("Start GeoDuck to see this table."))
                self._update_range()

    def close_page(self) -> None:
        """La pestaña se cierra: deja de escuchar y descarta las respuestas que lleguen después."""
        self._closed = True
        self.data.close_grid()
        self._unsubscribe()


def _key_text(kind: str) -> str:
    return {"PRIMARY KEY": tr("primary"), "UNIQUE": tr("unique")}.get(kind, kind.lower())


def tighten(
    layout: Any,
    compact: bool,
    margins: tuple[int, int, int, int],
    spacing: int,
    *,
    tight: tuple[int, int] = (8, 4),
) -> None:
    """En el modo compacto, márgenes y separaciones más cortos (`tight`: margen a los lados y
    separación), para que el panel baje a 320 px sin montar nada (#147, punto 28)."""
    left, top, right, bottom = margins
    if compact:
        side, gap = tight
        layout.setContentsMargins(side, top, side, bottom)
        layout.setSpacing(gap)
    else:
        layout.setContentsMargins(left, top, right, bottom)
        layout.setSpacing(spacing)
