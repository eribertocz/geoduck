# SPDX-License-Identifier: GPL-2.0-or-later
"""«Cargar en QGIS ▾» de Workspace Pro (workspace-pro-spec §7; GD-WSP-006; AT-WSP-007).

Dos opciones, en lenguaje simple: **Copia** (rápida, independiente de DuckDB) y **Conectada** (en vivo,
editable en DuckDB). Un clic carga; solo se pregunta lo que falta:

- La «Copia» es la Copia rápida (GeoPackage en `/vsimem`, ADR-0012); si GDAL no la permite, la Copia en
  memoria, sin preguntar. El usuario nunca elige entre las dos.
- Todas las geometrías de la consulta se cargan (una capa por columna, spatial-spec §7); con varias familias
  en una Copia, una capa por familia.
- El SRC sale de la columna (`GEOMETRY('EPSG:4326')`). **Solo si a alguna le falta**, una ventana pequeña
  pide uno para todas (con la opción de elegir por columna); cancelarla no carga nada.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

from qgis.core import QgsCoordinateReferenceSystem
from qgis.PyQt.QtCore import QPoint, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

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
from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.i18n import number as number_text
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons, style
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import Colors
from geoduck.ui.pro.widgets import button, label

COPY, CONNECTED = "copy", "connected"


def TEMPORARY_TEXT() -> str:  # noqa: N802 - un texto fijo, traducido al pedirlo
    return tr("Temporary tables disappear when the session closes: they only load as a Copy.")


def is_temporary(databases: list[str]) -> bool:
    """Alguna de las bases es la de las tablas temporales de la sesión."""
    return any(d.lower() == "temp" for d in databases)


#: «Más opciones…» (E6b): la misma carga, con la ventana de opciones antes.
OPTIONS = "options"

#: Columna → SRC elegido (authid o WKT; "" = sin SRC). `None`: el usuario canceló.
AskCrs = Callable[[list[str], QWidget], "dict[str, str] | None"]
#: (plan, nombre, modo inicial, ventana) → lo elegido en «Más opciones…» o None (canceló).
AskOptions = Callable[[LoadPlan, str, int, QWidget], "dict[str, Any] | None"]


def copy_mode(availability: dict[LoadMode, str | None]) -> LoadMode:
    """La «Copia»: la rápida si GDAL la permite; si no, la de memoria (respaldo automático, §7)."""
    return LoadMode.SNAPSHOT if availability.get(LoadMode.SNAPSHOT) is None else LoadMode.MEMORY


def unknown_crs(plan: LoadPlan) -> list[str]:
    """Columnas de geometría sin SRC declarado, o con uno que QGIS no reconoce."""
    columns = plan.geometries or ((plan.geometry,) if plan.geometry is not None else ())
    return [
        column.name
        for column in columns
        if not column.declared_crs or not QgsCoordinateReferenceSystem(column.declared_crs).isValid()
    ]


def build_request(
    plan: LoadPlan,
    sql: str,
    name: str,
    mode: LoadMode,
    overrides: dict[str, str],
    *,
    source: tuple[str, str, str] | None = None,
    source_kind: str | None = None,
    database: str | None = None,
    options: dict[str, Any] | None = None,
    expected_rows: int | None = None,
) -> LoadRequest:
    """La carga de un clic: todas las geometrías, con el SRC elegido donde faltaba. Con `options` («Más
    opciones…»), las geometrías elegidas, las columnas WKB/WKT, «Reproyectar a…» y «Separar por tipo»."""
    columns = [c.name for c in (plan.geometries or ((plan.geometry,) if plan.geometry is not None else ()))]
    if options is not None:
        columns = list(options["geometries"])
    geometry = columns[0] if columns else None
    return LoadRequest(
        sql=sql,
        mode=mode,
        layer_name=name,
        geometry=geometry,
        crs_override=overrides.get(geometry) if geometry is not None else None,
        source=source,
        source_kind=source_kind,
        database=database,
        geometries=tuple(columns) if len(columns) > 1 else (),
        crs_overrides=tuple(overrides.items()),
        split_families=True,
        formats=tuple(options["formats"]) if options else (),
        reproject_to=options["reproject_to"] if options else None,
        separate_types=bool(options and options["separate_types"]),
        expected_rows=expected_rows,
    )


def mode_text(mode: LoadMode) -> str:
    return tr("Connected") if mode is LoadMode.CONNECTED else tr("Copy (mode)")


def finished_headline(report: LoadReport) -> str:
    """La primera línea del aviso: qué se añadió y en qué sentido (DuckDB → QGIS)."""
    if len(report.layers) > 1:  # una capa por geometría (spatial-spec §7)
        names = ", ".join(f"«{name}»" for _, name in report.layers)
        return tr("Layers {} added to QGIS from GeoDuck").format(names)
    return tr("Layer «{}» added to QGIS from GeoDuck").format(report.layer_name)


def finished_detail(report: LoadReport) -> str:
    """Cómo se cargó y cuántas entidades."""
    rows = number_text(report.rows)
    if len(report.layers) > 1:
        count = tr("{} features each") if report.rows_each else tr("{} features in total")
    else:
        count = tr("{} features")
    return f"{mode_text(report.mode)} · {count.format(rows)}"


def finished_title(report: LoadReport) -> str:
    """La capa (o capas), cómo se cargó y cuántas entidades, en una línea."""
    return f"{finished_headline(report)} · {finished_detail(report)}"


def finished_lines(report: LoadReport) -> list[str]:
    """El aviso, una idea por línea: qué y en qué sentido; cómo y cuántas; origen; acceso; advertencias."""
    lines = [finished_headline(report), finished_detail(report)]
    if report.origin:
        lines.append(tr("Source: {}").format(report.origin))
        if report.access:
            lines.append(tr("Access: ") + report.access)
    if report.warnings:
        lines.append("⚠ " + "; ".join(report.warnings))
    return lines


def finished_text(report: LoadReport) -> str:
    """El aviso completo en una línea (en el pie): además, el origen y el acceso (decisión del 2026-11-02)."""
    return " · ".join(finished_lines(report))


class _Row(QFrame):
    """Una opción del menú: icono, título y una línea que la explica; clic o Intro la eligen."""

    picked = pyqtSignal()

    def __init__(self, icon: str, title: str, text: str, colors: Colors) -> None:
        super().__init__()
        self.setProperty("pro", "menu-row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"{title}: {text}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 14, 8)
        row.setSpacing(10)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon, colors.muted, 18))
        row.addWidget(glyph)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        name = label(title)
        name.setFont(ui_font(bold=True))
        texts.addWidget(name)
        texts.addWidget(label(text, "muted"))
        row.addLayout(texts, 1)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit()


def load_menu(
    parent: QWidget,
    colors: Colors,
    pick: Callable[[str], None],
    *,
    title: str = "",
    more: bool = False,
    name: Callable[[], str] | None = None,
    rename: Callable[[], None] | None = None,
    temporary: bool = False,
) -> QMenu:
    """«Cargar en QGIS ▾»: «Copia» y «Conectada», cada una con su explicación de una línea. Con `title`
    (tablas soltadas en el mapa, E5), una cabecera arriba («3 tablas · ¿cómo cargarlas?»). Con `more` (E6b),
    al final una línea discreta «Más opciones…» que llama a `pick(OPTIONS)`.

    #148, punto 15: con `name` (una tabla o un resultado), arriba el **nombre de la capa en QGIS**, ya
    relleno con lo que `name()` propone al abrir el menú (Enter = Copia; `menu.name_edit`); con varias
    geometrías, el nombre es el prefijo («Consumo · geom»). Con `rename` (varias tablas), «Nombres: los de
    las tablas · Cambiar nombres…», que abre el diálogo único."""
    menu = QMenu(parent)
    menu.setProperty("pro", "load-menu")
    menu.name_edit = None  # type: ignore[attr-defined]
    if title:
        head = QWidgetAction(menu)
        caption = label(title, "section")
        caption.setContentsMargins(10, 6, 10, 4)
        head.setDefaultWidget(caption)
        head.setEnabled(False)
        menu.addAction(head)
    if name is not None:
        menu.name_edit = _name_field(menu, name, lambda: (pick(COPY), menu.close()))  # type: ignore[attr-defined]
    if rename is not None:
        _rename_row(menu, rename)
    copy_text = tr("Copies the data into QGIS memory; it no longer depends on the database")
    connected_text = tr("Reads straight from the database without copying; edits are saved in the database")
    if temporary:
        connected_text = TEMPORARY_TEXT()
    for kind, icon, mode, text in (
        (COPY, "layers", tr("Copy (mode)"), copy_text),
        (CONNECTED, "database", tr("Connected"), connected_text),
    ):
        row = _Row(icon, mode, text, colors)
        action = QWidgetAction(menu)
        if kind == CONNECTED and temporary:  # #183: una tabla temporal desaparece con la sesión
            row.setEnabled(False)
            action.setEnabled(False)
        action.setDefaultWidget(row)
        action.setText(mode)
        action.triggered.connect(lambda _c=False, k=kind: pick(k))
        row.picked.connect(action.trigger)
        row.picked.connect(menu.close)
        menu.addAction(action)
    if more:
        menu.addSeparator()
        extra = menu.addAction(tr("More options…"))
        extra.setObjectName("geoduckLoadOptions")
        extra.setToolTip(tr("Choose geometries, use a WKB/WKT column, reproject or separate by type"))
        extra.triggered.connect(lambda _c=False: pick(OPTIONS))
    return menu


def layer_name(menu: QMenu, proposed: str) -> str:
    """El nombre escrito arriba del menú (#148), o el propuesto si no hay campo o quedó vacío."""
    edit = getattr(menu, "name_edit", None)
    text = edit.text().strip() if edit is not None else ""
    return text or proposed


def _name_field(menu: QMenu, name: Callable[[], str], enter: Callable[[], Any]) -> QLineEdit:
    box = QWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(10, 8, 10, 6)
    column.setSpacing(4)
    column.addWidget(label(tr("Layer name in QGIS"), "muted"))
    edit = QLineEdit()
    edit.setAccessibleName(tr("Layer name in QGIS"))
    edit.setToolTip(tr("With several geometries, the name is the prefix: «{0} · geom»").format(tr("name")))
    column.addWidget(edit)
    hint = label(tr("Proposed: the name of the tab (or of the table). Edit it or leave it."), "faint")
    hint.setWordWrap(True)
    column.addWidget(hint)
    action = QWidgetAction(menu)
    action.setDefaultWidget(box)
    menu.addAction(action)
    menu.addSeparator()
    edit.returnPressed.connect(enter)  # Enter = Copia

    def opened() -> None:
        edit.setText(name())
        edit.selectAll()
        QTimer.singleShot(0, edit.setFocus)

    menu.aboutToShow.connect(opened)
    return edit


def _rename_row(menu: QMenu, rename: Callable[[], None]) -> None:
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(10, 6, 10, 6)
    row.setSpacing(8)
    row.addWidget(label(tr("Names: those of the tables"), "muted"), 1)
    change = button(tr("Change names…"), "link")
    change.clicked.connect(lambda _c=False: (menu.close(), rename()))
    row.addWidget(change)
    action = QWidgetAction(menu)
    action.setDefaultWidget(box)
    menu.addAction(action)
    menu.addSeparator()


def popup_under(menu: QMenu, anchor: QWidget) -> None:
    menu.popup(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))


class CrsDialog(QDialog):
    """«N capas sin SRC»: un SRC para todas, o uno por columna si se despliega."""

    def __init__(self, columns: list[str], parent: QWidget | None = None) -> None:
        from qgis.gui import QgsProjectionSelectionWidget  # noqa: PLC0415

        super().__init__(parent)
        style.apply(self)
        self.setWindowTitle(tr("GeoDuck"))
        self.columns = columns
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 16)
        box.setSpacing(10)
        title = (
            tr("1 geometry has no CRS")
            if len(columns) == 1
            else tr("{} geometries have no CRS").format(len(columns))
        )
        box.addWidget(label(title, "title"))
        note = label(
            tr("Choose one so that QGIS places them on the map. Without a CRS they load anyway."), "muted"
        )
        note.setWordWrap(True)
        box.addWidget(note)

        def selector() -> Any:
            widget = QgsProjectionSelectionWidget()
            widget.setOptionVisible(QgsProjectionSelectionWidget.CrsOption.CrsNotSet, True)
            widget.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
            return widget

        self.common = selector()
        box.addWidget(self.common)
        self.each: dict[str, Any] = {}
        if len(columns) > 1:
            self.one_by_one = button(tr("Choose one per geometry…"), "ghost")
            self.per_column = QWidget()
            grid = QVBoxLayout(self.per_column)
            grid.setContentsMargins(0, 0, 0, 0)
            for column in columns:
                row = QHBoxLayout()
                row.addWidget(label(column, "mono"))
                widget = selector()
                self.each[column] = widget
                row.addWidget(widget, 1)
                grid.addLayout(row)
            self.per_column.hide()
            self.one_by_one.clicked.connect(self._one_by_one)
            box.addWidget(self.one_by_one, 0, Qt.AlignmentFlag.AlignLeft)
            box.addWidget(self.per_column)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = button(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        load = button(tr("Load"), "primary")
        load.setDefault(True)
        load.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(load)
        box.addLayout(actions)
        self.setMinimumWidth(460)

    def _one_by_one(self) -> None:
        crs = self.common.crs()
        for widget in self.each.values():
            widget.setCrs(crs)
        self.common.hide()
        self.one_by_one.hide()
        self.per_column.show()

    def choice(self) -> dict[str, str]:
        found = {}
        for column in self.columns:
            widget = self.each[column] if self.each and self.per_column.isVisible() else self.common
            crs = widget.crs()
            found[column] = (crs.authid() or crs.toWkt()) if crs.isValid() else ""
        return found

    @staticmethod
    def ask(columns: list[str], parent: QWidget) -> dict[str, str] | None:
        dialog = CrsDialog(columns, parent)
        return dialog.choice() if dialog.exec() == QDialog.DialogCode.Accepted else None


def _ask_options(plan: LoadPlan, name: str, kind_index: int, parent: QWidget) -> dict[str, Any] | None:
    from geoduck.ui.pro.load_options import LoadOptionsDialog  # noqa: PLC0415 - solo al pedirla

    return LoadOptionsDialog.ask(plan, name, kind_index, parent)


class QuickLoad:
    """Carga de un clic: pide el plan, pregunta el SRC solo si falta y carga. Avisa por `notify`.

    Varias tablas a la vez (soltadas en el mapa, E5): se piden todos los planes, el SRC que falte se pregunta
    **una sola vez** para todas, y se cargan una tras otra (la sesión carga de a una)."""

    def __init__(
        self,
        coordinator: Any,
        parent: QWidget,
        notify: Callable[[str], None],
        ask_crs: AskCrs | None = None,
        ask_options: AskOptions | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._ask_options = ask_options
        self._parent = parent
        self._notify = notify
        self._ask_crs = ask_crs or CrsDialog.ask
        #: token del plan → (lote, posición en el lote)
        self._pending: dict[int, tuple[dict[str, Any], int]] = {}
        #: (carga, lote, posición en el lote), en orden.
        self._queue: list[tuple[LoadRequest, dict[str, Any], int]] = []
        self._loads: set[int] = set()
        #: id de carga → (lote, posición): para avisar a quien mira el lote (la línea de tiempo, #148).
        self._jobs: dict[int, tuple[dict[str, Any], int]] = {}
        self._next_job: tuple[dict[str, Any], int] | None = None
        #: id de carga → su petición: para volver a cargar como Conectada si la Copia no cabe (#172).
        self._requests: dict[int, LoadRequest] = {}
        self._starting = False
        self.last_report: LoadReport | None = None
        #: Se llama con cada carga terminada (E6: el aviso con «Ver en el mapa»). Si devuelve True, ya avisó
        #: (y el pie no repite el mensaje, que quedaría desactualizado).
        self.on_loaded: Callable[[LoadReport], bool] | None = None
        self._unsubscribe = coordinator.subscribe(self._on_event)

    def start(
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
        """«Copia» o «Conectada» de `sql` (una tabla o vista con su `source`, o el resultado de una consulta
        con su `database`), con el nombre de capa `name`. `rows`: el total que ya se conoce (#172)."""
        job = {
            "sql": sql,
            "name": name,
            "source": source,
            "source_kind": source_kind,
            "database": database,
            "rows": rows,
        }
        self.start_many([job], kind)

    def start_many(self, jobs: list[dict[str, Any]], kind: str, *, watch: Any = None) -> None:
        """Varias cargas con el mismo modo. Cada `job`: `sql`, `name` y, opcionales, `source`, `source_kind`
        y `database` (como en `start`). Con `OPTIONS` (una sola carga), la ventana «Más opciones…» elige.
        `watch` (la línea de tiempo, #148) recibe `job_started(i, request)`, `job_progressed(i, filas)`,
        `job_finished(i, report)`, `job_failed(i, mensaje, cancelada)` y `batch_stopped()` (se canceló al
        preguntar el SRC o las opciones: no se carga nada)."""
        modes = self._coordinator.load_modes()
        mode = LoadMode.CONNECTED if kind == CONNECTED else copy_mode(modes)
        reason = modes.get(mode)
        if reason is not None and kind != OPTIONS:
            self._notify(tr("Cannot load: ") + reason)
            if watch is not None:
                for index in range(len(jobs)):
                    watch.job_failed(index, reason, False)
            return
        batch: dict[str, Any] = {
            "jobs": jobs,
            "mode": mode,
            "plans": [None] * len(jobs),
            "waiting": 0,
            "options": kind == OPTIONS,
            "watch": watch,
        }
        for index, job in enumerate(jobs):
            try:
                token = self._coordinator.prepare_load(job["sql"], database=job.get("database"))
            except GeoDuckError as exc:
                self._notify(tr("Cannot load: ") + exc.message)
                if watch is not None:
                    watch.job_failed(index, exc.message, False)
                continue
            self._pending[token] = (batch, index)
            batch["waiting"] += 1

    def _prepared(self, token: int, plan: LoadPlan | None) -> None:  # noqa: PLR0912 - en orden
        batch, index = self._pending.pop(token)
        batch["plans"][index] = plan
        batch["waiting"] -= 1
        if batch["waiting"]:
            return
        watch = batch.get("watch")
        ready = [(job, found) for job, found in zip(batch["jobs"], batch["plans"], strict=True) if found]
        places = [i for i, found in enumerate(batch["plans"]) if found]
        if not ready:
            return
        options: dict[str, Any] | None = None
        if batch["options"]:  # «Más opciones…»: primero la ventana, con el plan ya leído
            job, found = ready[0]
            ask = self._ask_options or _ask_options
            options = ask(found, job["name"], 1 if batch["mode"] is LoadMode.CONNECTED else 0, self._parent)
            if options is None:
                if watch is not None:
                    watch.batch_stopped()
                return  # canceló
            modes = self._coordinator.load_modes()
            batch["mode"] = LoadMode.CONNECTED if options["kind"] == CONNECTED else copy_mode(modes)
            reason = modes.get(batch["mode"])
            if reason is not None:
                self._notify(tr("Cannot load: ") + reason)
                return
        # el SRC que falte, una sola vez para todas («tabla · columna» si hay varias tablas)
        missing: list[tuple[int, str, str]] = []
        for i, (job, found) in enumerate(ready):
            unknown = unknown_crs(found)
            if options is not None:  # solo las elegidas; una columna WKB/WKT nunca trae SRC
                unknown = [c for c in unknown if c in options["geometries"]]
                unknown += [name for name, _fmt in options["formats"]]
            for column in unknown:
                missing.append((i, column, column if len(ready) == 1 else f"{job['name']} · {column}"))
        answer: dict[str, str] = {}
        if missing:
            chosen = self._ask_crs([text for _, _, text in missing], self._parent)
            if chosen is None:
                if watch is not None:
                    watch.batch_stopped()
                return  # canceló: no se carga nada
            answer = chosen
        for i, (job, found) in enumerate(ready):
            overrides = {column: answer[text] for j, column, text in missing if j == i and text in answer}
            request = build_request(
                found,
                job["sql"],
                (options or {}).get("name") or job["name"],
                batch["mode"],
                overrides,
                source=job.get("source"),
                source_kind=job.get("source_kind"),
                database=job.get("database"),
                options=options,
                expected_rows=job.get("rows"),
            )
            self._queue.append((request, batch, places[i]))
        self._next()

    def _next(self) -> None:
        """La siguiente carga de la cola, si la sesión está libre (las cargas ocupan la sesión)."""
        if not self._queue or self._loads:
            return
        request, batch, index = self._queue.pop(0)
        self._starting = True  # `LoadStarted` llega antes de que `load` devuelva su id
        self._next_job = (batch, index)
        try:
            load_id = self._coordinator.load(request)
            self._loads.add(load_id)
            self._jobs[load_id] = (batch, index)
        except GeoDuckError as exc:
            self._notify(tr("Cannot load: ") + exc.message)
            self._tell(batch, "job_failed", index, exc.message, False)
            QTimer.singleShot(0, self._next)
        finally:
            self._starting = False
            self._next_job = None

    @staticmethod
    def _tell(batch: dict[str, Any] | None, what: str, *args: Any) -> None:
        watch = batch.get("watch") if batch is not None else None
        if watch is not None:
            getattr(watch, what)(*args)

    def _job(self, load_id: int) -> tuple[dict[str, Any] | None, int]:
        return self._jobs.get(load_id, (None, -1))

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, LoadPrepared) and event.token in self._pending:
            self._prepared(event.token, event.plan)
        elif isinstance(event, LoadPrepareFailed) and event.token in self._pending:
            self._notify(tr("Cannot load: ") + event.message)
            batch, index = self._pending[event.token]
            self._tell(batch, "job_failed", index, event.message, False)
            self._prepared(event.token, None)
        elif isinstance(event, LoadStarted) and (self._starting or event.load_id in self._loads):
            self._loads.add(event.load_id)
            if self._next_job is not None:
                self._jobs[event.load_id] = self._next_job
            self._requests[event.load_id] = event.request
            batch, index = self._job(event.load_id)
            self._tell(batch, "job_started", index, event.request)
            self._notify(tr("Loading «{}»…").format(event.request.layer_name))
        elif isinstance(event, LoadProgressed) and event.load_id in self._loads:
            batch, index = self._job(event.load_id)
            self._tell(batch, "job_progressed", index, event.rows)
        elif isinstance(event, LoadFinished) and event.load_id in self._loads:
            self._loads.discard(event.load_id)
            batch, index = self._jobs.pop(event.load_id, (None, -1))
            self._requests.pop(event.load_id, None)
            self.last_report = event.report
            self._tell(batch, "job_finished", index, event.report)
            shown = self.on_loaded(event.report) if self.on_loaded is not None else False
            self._notify("" if shown else finished_text(event.report))
            QTimer.singleShot(0, self._next)  # cuando la sesión ya volvió a estar lista
        elif isinstance(event, LoadFailed) and event.load_id in self._loads:
            self._loads.discard(event.load_id)
            batch, index = self._jobs.pop(event.load_id, (None, -1))
            request = self._requests.pop(event.load_id, None)
            if (
                event.code is ErrorCode.MEMORY_BUDGET
                and request is not None
                and self._as_connected(request, event.message, batch, index)
            ):
                return
            self._tell(batch, "job_failed", index, event.message, event.cancelled)
            if event.cancelled:
                for _request, other, position in self._queue:  # «Cancelar» detiene todo el lote
                    self._tell(other, "job_failed", position, "", True)
                self._queue.clear()
            self._notify(
                tr("Loading cancelled.") if event.cancelled else tr("Loading error: ") + event.message
            )
            QTimer.singleShot(0, self._next)

    def _as_connected(
        self, request: LoadRequest, message: str, batch: dict[str, Any] | None, index: int
    ) -> bool:
        """#172: la Copia no cabe en memoria. Si «Conectada» se puede, se ofrece (dos botones); con «Cargar
        como Conectada» la misma capa vuelve primera a la cola (True). Si no se puede o se cancela, False."""
        if request.mode is LoadMode.CONNECTED or self._coordinator.load_modes().get(LoadMode.CONNECTED):
            return False
        if not ASK_CONNECTED(request.layer_name, message):
            return False
        retry = dataclasses.replace(request, mode=LoadMode.CONNECTED, reproject_to=None, expected_rows=None)
        if batch is not None:
            self._queue.insert(0, (retry, batch, index))
        else:
            self._queue.insert(0, (retry, {"jobs": [], "watch": None}, index))
        self._notify(tr("Loading «{}» as Connected…").format(request.layer_name))
        QTimer.singleShot(0, self._next)
        return True

    def detach(self) -> None:
        self._queue.clear()
        self._unsubscribe()


def export_menu(parent: QWidget, on_pick: Callable[[Any], None]) -> QMenu:
    """«Exportar ▾» (maqueta aprobada, 2026-11-07): Parquet, GeoPackage, CSV y FlatGeobuf a la vista; el resto
    en «Más formatos ▸». Cada opción dice en su ayuda qué pasará. Todo lo escribe DuckDB, nunca QGIS."""
    from geoduck.domain.export import ExportFormat  # noqa: PLC0415

    menu = QMenu(parent)
    menu.setToolTipsVisible(True)
    more = QMenu(tr("More formats"), menu)
    more.setToolTipsVisible(True)
    for fmt in ExportFormat:
        target = menu if fmt.main else more
        text = ("⚡ " if fmt.fast else "") + fmt.label + "…"
        action = target.addAction(text, lambda f=fmt: on_pick(f))
        action.setData(fmt.value)
        action.setToolTip(fmt.note)
    menu.addSeparator()
    menu.addMenu(more)
    return menu


def confirm_spatial(label_text: str, installed: bool) -> bool:
    """Permiso para instalar o cargar `spatial` antes de exportar a un formato de GDAL (spatial-spec §10)."""
    from qgis.PyQt.QtWidgets import QApplication, QMessageBox  # noqa: PLC0415

    box = QMessageBox(QApplication.activeWindow())
    box.setWindowTitle(tr("GeoDuck"))
    text = tr("«{0}» is written with the «spatial» extension (the fastest).").format(label_text)
    if installed:
        text += " " + tr("It is installed but not loaded: GeoDuck will load it now, for this session.")
        go = box.addButton(tr("Load and export"), QMessageBox.ButtonRole.AcceptRole)
    else:
        text += " " + tr("It is not installed: GeoDuck will install it now (only once, about 40 MB).")
        go = box.addButton(tr("Install and export"), QMessageBox.ButtonRole.AcceptRole)
    box.setText(text)
    box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(go)
    box.exec()
    return box.clickedButton() is go


def confirm_connected(name: str, message: str) -> bool:
    """#172: una Copia que no cabe en memoria. Dos botones (principios de interfaz): «Cancelar» y «Cargar como
    Conectada», que no copia nada. `message` dice cuánto ocuparía y cuánto hay libre."""
    from qgis.PyQt.QtWidgets import QApplication, QMessageBox  # noqa: PLC0415

    box = QMessageBox(QApplication.activeWindow())
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(tr("GeoDuck"))
    box.setText(tr("«{0}» does not fit as a Copy").format(name))
    box.setInformativeText(
        f"{message} {tr('As Connected, QGIS reads the data straight from the database, without copying it.')}"
    )
    box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
    go = box.addButton(tr("Load as Connected"), QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(go)
    box.exec()
    return box.clickedButton() is go


#: Pregunta de #172 cuando la Copia no cabe (las pruebas la reemplazan).
ASK_CONNECTED: Callable[[str, str], bool] = confirm_connected


#: Pregunta de `spatial` antes de exportar (las pruebas la reemplazan).
ASK_SPATIAL: Callable[[str, bool], bool] = confirm_spatial


def export_query(  # noqa: PLR0917 - una acción con su contexto completo
    coordinator: Any,
    sql: str,
    database: str | None,
    name: str,
    fmt: Any,
    ask_path: Callable[[str, str, str], str],
    notify: Callable[[str], None],
) -> None:
    """«Exportar ▾»: la consulta completa (no la vista previa), en el worker, siempre con DuckDB. Un formato
    de GDAL sin `spatial` cargada pide permiso antes (spatial-spec §10); sin ese sí, no se instala nada."""
    if not fmt.needs_spatial:
        _export(coordinator, sql, database, name, fmt, ask_path, notify, allow_spatial=False)
        return

    def checked(out: Any) -> None:
        if isinstance(out, BaseException):
            notify(tr("Cannot export: ") + str(out))
            return
        row = out.rows[0] if out.rows else (False, False)
        installed, loaded = bool(row[0]), bool(row[1])
        if not loaded and not ASK_SPATIAL(fmt.label, installed):
            return
        _export(coordinator, sql, database, name, fmt, ask_path, notify, allow_spatial=not loaded)

    try:
        coordinator.read_rows(
            "SELECT installed, loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'", 1, checked
        )
    except GeoDuckError as exc:
        notify(tr("Cannot export: ") + exc.message)


def _export(  # noqa: PLR0917 - una acción con su contexto completo
    coordinator: Any,
    sql: str,
    database: str | None,
    name: str,
    fmt: Any,
    ask_path: Callable[[str, str, str], str],
    notify: Callable[[str], None],
    *,
    allow_spatial: bool,
) -> None:
    from pathlib import Path  # noqa: PLC0415

    from geoduck.domain.export import ExportRequest  # noqa: PLC0415

    suffix = fmt.suffix
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in name).strip(" .") or "datos"
    path = ask_path(tr("Export"), Path(cleaned).stem + suffix, fmt.pattern)
    if not path:
        return
    if not path.lower().endswith(suffix):
        path += suffix
    try:
        coordinator.export(ExportRequest(sql, path, fmt, database, allow_spatial=allow_spatial))
    except GeoDuckError as exc:
        notify(tr("Cannot export: ") + exc.message)
        return
    notify(tr("Exporting the full query to {0}…").format(Path(path).name))
