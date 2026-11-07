# SPDX-License-Identifier: GPL-2.0-or-later
"""«Cargar en QGIS ▾» de Workspace Pro (workspace-pro-spec §7; GD-WSP-006; AT-WSP-007).

Dos opciones, en lenguaje simple: **Copia** (rápida, independiente de DuckDB) y **Conectada** (en vivo,
editable en DuckDB). Un clic carga; solo se pregunta lo que falta (propietario, 2026-11-06):

- La «Copia» es la Copia rápida (GeoPackage en `/vsimem`, ADR-0012); si GDAL no la permite, la Copia en
  memoria, sin preguntar. El usuario nunca elige entre las dos.
- Todas las geometrías de la consulta se cargan (una capa por columna, spatial-spec §7); con varias familias
  en una Copia, una capa por familia.
- El SRC sale de la columna (`GEOMETRY('EPSG:4326')`). **Solo si a alguna le falta**, una ventana pequeña
  pide uno para todas (con la opción de elegir por columna); cancelarla no carga nada.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsCoordinateReferenceSystem
from qgis.PyQt.QtCore import QPoint, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
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
    LoadStarted,
)
from geoduck.domain.bridge_types import LoadPlan
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.load import LoadMode, LoadReport, LoadRequest
from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons, style
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import Colors
from geoduck.ui.pro.widgets import button, label

COPY, CONNECTED = "copy", "connected"
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
    )


def mode_text(mode: LoadMode) -> str:
    return tr("Connected") if mode is LoadMode.CONNECTED else tr("Copy (mode)")


def finished_headline(report: LoadReport) -> str:
    """La primera línea del aviso: qué se añadió y en qué sentido (DuckDB → QGIS)."""
    if len(report.layers) > 1:  # una capa por geometría (spatial-spec §7)
        names = ", ".join(f"«{name}»" for _, name in report.layers)
        return tr("Layers {} added to QGIS from DuckDB").format(names)
    return tr("Layer «{}» added to QGIS from DuckDB").format(report.layer_name)


def finished_detail(report: LoadReport) -> str:
    """Cómo se cargó y cuántas entidades."""
    rows = f"{report.rows:,}".replace(",", " ")
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
) -> QMenu:
    """«Cargar en QGIS ▾»: «Copia» y «Conectada», cada una con su explicación de una línea. Con `title`
    (tablas soltadas en el mapa, E5), una cabecera arriba («3 tablas · ¿cómo cargarlas?»). Con `more` (E6b),
    al final una línea discreta «Más opciones…» que llama a `pick(OPTIONS)`."""
    menu = QMenu(parent)
    menu.setProperty("pro", "load-menu")
    if title:
        head = QWidgetAction(menu)
        caption = label(title, "section")
        caption.setContentsMargins(10, 6, 10, 4)
        head.setDefaultWidget(caption)
        head.setEnabled(False)
        menu.addAction(head)
    copy_text = tr("Copies the data into QGIS memory; it no longer depends on DuckDB")
    connected_text = tr("Reads straight from DuckDB without copying; edits are saved in DuckDB")
    for kind, icon, name, text in (
        (COPY, "layers", tr("Copy (mode)"), copy_text),
        (CONNECTED, "database", tr("Connected"), connected_text),
    ):
        row = _Row(icon, name, text, colors)
        action = QWidgetAction(menu)
        action.setDefaultWidget(row)
        action.setText(name)
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
        self._queue: list[LoadRequest] = []
        self._loads: set[int] = set()
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
    ) -> None:
        """«Copia» o «Conectada» de `sql` (una tabla o vista con su `source`, o el resultado de una consulta
        con su `database`), con el nombre de capa `name`."""
        job = {"sql": sql, "name": name, "source": source, "source_kind": source_kind, "database": database}
        self.start_many([job], kind)

    def start_many(self, jobs: list[dict[str, Any]], kind: str) -> None:
        """Varias cargas con el mismo modo. Cada `job`: `sql`, `name` y, opcionales, `source`, `source_kind`
        y `database` (como en `start`). Con `OPTIONS` (una sola carga), la ventana «Más opciones…» elige."""
        modes = self._coordinator.load_modes()
        mode = LoadMode.CONNECTED if kind == CONNECTED else copy_mode(modes)
        reason = modes.get(mode)
        if reason is not None and kind != OPTIONS:
            self._notify(tr("Cannot load: ") + reason)
            return
        batch: dict[str, Any] = {
            "jobs": jobs,
            "mode": mode,
            "plans": [None] * len(jobs),
            "waiting": 0,
            "options": kind == OPTIONS,
        }
        for index, job in enumerate(jobs):
            try:
                token = self._coordinator.prepare_load(job["sql"], database=job.get("database"))
            except GeoDuckError as exc:
                self._notify(tr("Cannot load: ") + exc.message)
                continue
            self._pending[token] = (batch, index)
            batch["waiting"] += 1

    def _prepared(self, token: int, plan: LoadPlan | None) -> None:
        batch, index = self._pending.pop(token)
        batch["plans"][index] = plan
        batch["waiting"] -= 1
        if batch["waiting"]:
            return
        ready = [(job, found) for job, found in zip(batch["jobs"], batch["plans"], strict=True) if found]
        if not ready:
            return
        options: dict[str, Any] | None = None
        if batch["options"]:  # «Más opciones…»: primero la ventana, con el plan ya leído
            job, found = ready[0]
            ask = self._ask_options or _ask_options
            options = ask(found, job["name"], 1 if batch["mode"] is LoadMode.CONNECTED else 0, self._parent)
            if options is None:
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
                return  # canceló: no se carga nada
            answer = chosen
        for i, (job, found) in enumerate(ready):
            overrides = {column: answer[text] for j, column, text in missing if j == i and text in answer}
            self._queue.append(
                build_request(
                    found,
                    job["sql"],
                    job["name"],
                    batch["mode"],
                    overrides,
                    source=job.get("source"),
                    source_kind=job.get("source_kind"),
                    database=job.get("database"),
                    options=options,
                )
            )
        self._next()

    def _next(self) -> None:
        """La siguiente carga de la cola, si la sesión está libre (las cargas ocupan la sesión)."""
        if not self._queue or self._loads:
            return
        request = self._queue.pop(0)
        self._starting = True  # `LoadStarted` llega antes de que `load` devuelva su id
        try:
            self._loads.add(self._coordinator.load(request))
        except GeoDuckError as exc:
            self._notify(tr("Cannot load: ") + exc.message)
            QTimer.singleShot(0, self._next)
        finally:
            self._starting = False

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, LoadPrepared) and event.token in self._pending:
            self._prepared(event.token, event.plan)
        elif isinstance(event, LoadPrepareFailed) and event.token in self._pending:
            self._notify(tr("Cannot load: ") + event.message)
            self._prepared(event.token, None)
        elif isinstance(event, LoadStarted) and (self._starting or event.load_id in self._loads):
            self._loads.add(event.load_id)
            self._notify(tr("Loading «{}»…").format(event.request.layer_name))
        elif isinstance(event, LoadFinished) and event.load_id in self._loads:
            self._loads.discard(event.load_id)
            self.last_report = event.report
            shown = self.on_loaded(event.report) if self.on_loaded is not None else False
            self._notify("" if shown else finished_text(event.report))
            QTimer.singleShot(0, self._next)  # cuando la sesión ya volvió a estar lista
        elif isinstance(event, LoadFailed) and event.load_id in self._loads:
            self._loads.discard(event.load_id)
            if event.cancelled:
                self._queue.clear()  # «Cancelar» detiene todo el lote
            self._notify(
                tr("Loading cancelled.") if event.cancelled else tr("Loading error: ") + event.message
            )
            QTimer.singleShot(0, self._next)

    def detach(self) -> None:
        self._queue.clear()
        self._unsubscribe()


def export_query(  # noqa: PLR0917 - una acción con su contexto completo
    coordinator: Any,
    sql: str,
    database: str | None,
    name: str,
    fmt: Any,
    ask_path: Callable[[str, str, str], str],
    notify: Callable[[str], None],
) -> None:
    """«Exportar ▾»: la consulta completa (no la vista previa) a CSV o Parquet, en el worker."""
    from pathlib import Path  # noqa: PLC0415

    from geoduck.domain.export import ExportFormat, ExportRequest  # noqa: PLC0415

    suffix = fmt.suffix
    pattern = tr("CSV files (*.csv)") if fmt is ExportFormat.CSV else tr("Parquet files (*.parquet)")
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in name).strip(" .") or "datos"
    path = ask_path(tr("Export"), Path(cleaned).stem + suffix, pattern)
    if not path:
        return
    if not path.lower().endswith(suffix):
        path += suffix
    try:
        coordinator.export(ExportRequest(sql, path, fmt, database))
    except GeoDuckError as exc:
        notify(tr("Cannot export: ") + exc.message)
        return
    notify(tr("Exporting the full query to {0}…").format(Path(path).name))
