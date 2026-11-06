# SPDX-License-Identifier: GPL-2.0-or-later
"""Maqueta de E4 (G9) para aprobar antes de construir: pestaña de consulta, «Cargar en QGIS», guardar el
proyecto con copias y GeoDuck sin DuckDB iniciado.

    QT_QPA_PLATFORM=offscreen python docs/evidence/g9/consulta/maqueta.py <carpeta>

Usa las piezas reales de Workspace Pro (barra lateral, pestañas, grilla de E3, editor SQL de QGIS) con datos
de ejemplo; los botones de la consulta aún no hacen nada. No es código del complemento.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from qgis.core import QgsApplication, QgsSettings
from qgis.PyQt.QtCore import QT_VERSION_STR, Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tools.pro_shots import Store, settle, shoot, theme, wait

SQL = """-- Consumo medio por municipio, noviembre
SELECT m.nombre,
       count(*)        AS suministros,
       avg(l.kwh)      AS kwh_medio,
       m.geom
FROM lecturas l
JOIN municipios m USING (codigo)
WHERE l.mes >= '2025-11-01'
GROUP BY ALL
ORDER BY kwh_medio DESC;
"""

ROWS = [
    ("El Alto", 48_312, 182.4, "MULTIPOLYGON (((-68.2 -16.5, …)))"),
    ("La Paz", 41_907, 171.3, "MULTIPOLYGON (((-68.1 -16.4, …)))"),
    ("Viacha", 6_204, 143.8, "MULTIPOLYGON (((-68.3 -16.6, …)))"),
    ("Achocalla", 2_118, 139.5, "MULTIPOLYGON (((-68.2 -16.6, …)))"),
    ("Mecapaca", 1_506, 121.0, "MULTIPOLYGON (((-68.0 -16.7, …)))"),
    ("Palca", 902, 117.6, "MULTIPOLYGON (((-67.9 -16.6, …)))"),
    ("Laja", 1_384, 112.2, "MULTIPOLYGON (((-68.4 -16.5, …)))"),
    ("Pucarani", 1_120, 108.9, "MULTIPOLYGON (((-68.5 -16.4, …)))"),
]


def query_page(colors, place, *, messages=False):  # noqa: PLR0915 - una maqueta, de arriba abajo
    from qgis.gui import QgsCodeEditorSQL

    from geoduck.domain.catalog import ColumnInfo
    from geoduck.ui.pro.style import ui_font
    from geoduck.ui.pro.table_page import PageModel, TypeHeader
    from geoduck.ui.pro.tokens import METRICS
    from geoduck.ui.pro.widgets import Segmented, button, icon_button, label, spacer

    page = QWidget()
    page.place = place
    box = QVBoxLayout(page)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(0)
    bar = QFrame()
    bar.setProperty("pro", "rule-bottom")
    row = QHBoxLayout(bar)
    row.setContentsMargins(12, 8, 12, 8)
    row.setSpacing(6)
    run = button("Ejecutar", "primary", icon="play", colors=colors)
    row.addWidget(run)
    row.addWidget(label("Ctrl+Intro", "kbd"), 0, Qt.AlignmentFlag.AlignVCenter)
    row.addSpacing(6)
    row.addWidget(button("Todo", tooltip="Ctrl+Mayús+Intro"))
    stop = button("Cancelar", "ghost", icon="stop", colors=colors)
    stop.setEnabled(False)
    row.addWidget(stop)
    row.addWidget(spacer(), 1)
    row.addWidget(label("Base", "muted"))
    base = QComboBox()
    base.addItems(["db", "memory"])
    row.addWidget(base)
    row.addWidget(icon_button("more", "Abrir, guardar, guardar como…", colors))
    box.addWidget(bar)

    split = QSplitter(Qt.Orientation.Vertical)
    split.setHandleWidth(1)
    editor = QgsCodeEditorSQL()
    editor.setLineNumbersVisible(True)
    editor.setText(SQL)
    editor.setFrameShape(QFrame.Shape.NoFrame)
    from geoduck.ui.pro import editor as pro_editor
    from geoduck.ui.pro.style import is_dark

    pro_editor.paint(editor, colors, dark=is_dark(page) or colors.bg.lower() < "#808080")
    split.addWidget(editor)

    results = QWidget()
    rbox = QVBoxLayout(results)
    rbox.setContentsMargins(0, 0, 0, 0)
    rbox.setSpacing(0)
    head = QFrame()
    head.setProperty("pro", "rule-bottom")
    hrow = QHBoxLayout(head)
    hrow.setContentsMargins(12, 6, 12, 6)
    hrow.setSpacing(10)
    views = Segmented(["Resultado", "Mensajes"], accessible_name="Resultado o mensajes")
    views.set_current(1 if messages else 0)
    hrow.addWidget(views)
    hrow.addWidget(label("8 filas · 412 ms", "muted"))
    hrow.addWidget(spacer(), 1)
    hrow.addWidget(button("Exportar", "ghost", icon="export", colors=colors))
    load = button("Cargar en QGIS", "primary", icon="layers", colors=colors)
    hrow.addWidget(load)
    rbox.addWidget(head)
    if messages:
        log = QWidget()
        lbox = QVBoxLayout(log)
        lbox.setContentsMargins(16, 10, 28, 10)
        lbox.setSpacing(6)
        for ok, text, where in (
            (True, "CREATE TABLE zonas_borrador · 0,02 s", ""),
            (
                False,
                "Binder Error: no existe la columna «kwh_mes» en la tabla «l»",
                "línea 3, columna 12 · Ir",
            ),
            (True, "SELECT · 8 filas · 0,41 s", ""),
        ):
            line = QHBoxLayout()
            mark = label("✓" if ok else "✕", None if ok else "error")
            mark.setFont(ui_font(bold=True))
            mark.setStyleSheet(f"color: {colors.ok};" if ok else "")
            line.addWidget(mark)
            text_label = label(text, None if ok else "error")
            line.addWidget(text_label, 1)
            if where:
                line.addWidget(label(where, "link"))
            lbox.addLayout(line)
        lbox.addStretch(1)
        rbox.addWidget(log, 1)
    else:
        from qgis.PyQt.QtWidgets import QAbstractItemView, QHeaderView, QTableView

        columns = (
            ColumnInfo("nombre", "VARCHAR", True),
            ColumnInfo("suministros", "BIGINT", True),
            ColumnInfo("kwh_medio", "DOUBLE", True),
            ColumnInfo("geom", "GEOMETRY('EPSG:4326')", True),
        )
        model = PageModel(colors)
        model.set_page(columns, tuple(ROWS), 0)
        grid = QTableView()
        grid.setProperty("pro", "grid")
        grid.setModel(model)
        header = TypeHeader(model, colors)
        grid.setHorizontalHeader(header)
        grid.setShowGrid(False)
        grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        grid.verticalHeader().setDefaultSectionSize(METRICS.row)
        grid.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        grid.verticalHeader().setMinimumWidth(40)
        grid.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for i, width in enumerate((200, 140, 140, 360)):
            grid.setColumnWidth(i, width)
        rbox.addWidget(grid, 1)
    split.addWidget(results)
    split.setSizes([330, 420])
    box.addWidget(split, 1)
    return page, load


def load_menu(colors):
    """«Cargar en QGIS ▾»: dos opciones con su explicación de una línea."""
    from geoduck.ui.pro import icons, style
    from geoduck.ui.pro.style import ui_font
    from geoduck.ui.pro.widgets import label

    menu = QFrame()
    style.apply(menu)
    menu.setProperty("pro", "popup")
    box = QVBoxLayout(menu)
    box.setContentsMargins(6, 6, 6, 6)
    box.setSpacing(2)
    for icon, title, text, hot in (
        ("layers", "Copia", "Rápida e independiente de DuckDB", True),
        ("database", "Conectada", "En vivo y editable en DuckDB", False),
    ):
        item = QFrame()
        item.setProperty("pro", "card" if hot else None)
        if hot:
            item.setStyleSheet(
                f"QFrame {{ background: {colors.accent_soft}; border: 0; border-radius: 6px; }}"
            )
        row = QHBoxLayout(item)
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
        box.addWidget(item)
    menu.setFixedWidth(300)
    return menu


def save_prompt(colors):
    """Al guardar el proyecto con capas «Copia» (§7)."""
    from geoduck.ui.pro import icons, style
    from geoduck.ui.pro.widgets import button, label

    card = QFrame()
    style.apply(card)
    box = QVBoxLayout(card)
    box.setContentsMargins(22, 20, 22, 18)
    box.setSpacing(10)
    top = QHBoxLayout()
    glyph = QLabel()
    glyph.setPixmap(icons.pixmap("info", colors.accent, 22))
    top.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
    texts = QVBoxLayout()
    texts.setSpacing(6)
    texts.addWidget(label("2 capas son «Copia»", "title"))
    body = label(
        "Viven en memoria y no se guardan con el proyecto: al reabrirlo no estarán. "
        "Guárdalas en un archivo junto al proyecto y se abrirán siempre.",
        "muted",
    )
    body.setWordWrap(True)
    texts.addWidget(body)
    files = label("consumidores_ElAlto.gpkg, consumo_por_municipio.gpkg → proyecto_geoduck.gpkg", "faint")
    files.setWordWrap(True)
    texts.addWidget(files)
    top.addLayout(texts, 1)
    box.addLayout(top)
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(button("No, gracias"))
    row.addWidget(button("Guardar las copias junto al proyecto", "primary"))
    box.addLayout(row)
    card.setFixedWidth(520)
    return card


def main() -> None:  # noqa: PLR0915 - todas las capturas, en orden
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    settings = QgsSettings()
    settings.setValue("locale/overrideFlag", True)
    settings.setValue("locale/userLocale", "es_ES")
    from geoduck.ui import i18n

    i18n.install()
    from geoduck.app.coordinator import SessionCoordinator
    from geoduck.domain.session import SessionState
    from geoduck.domain.sql import RunScope
    from geoduck.plugin import make_memory_engine
    from geoduck.ui.dispatcher import QtDispatcher
    from geoduck.ui.pro.places import QUERY, Place
    from geoduck.ui.pro.workspace import ProWorkspace

    qt = "qt" + QT_VERSION_STR[0]
    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher())
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    coordinator.execute_sql(
        "CREATE TABLE lecturas(codigo VARCHAR, mes DATE, kwh DOUBLE); CREATE TABLE municipios(codigo VARCHAR,"
        " nombre VARCHAR); CREATE TABLE consumidores(id INT);",
        RunScope.ALL,
    )
    wait(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    wait(lambda: any(o.name == "municipios" for o in coordinator.catalog.objects))
    for dark in (False, True):
        name = "oscuro" if dark else "claro"
        theme(dark)
        holder: dict = {}

        def factory(place, ws_holder=holder, messages=False):
            if place.kind == QUERY:
                page, load = query_page(ws_holder["ws"].colors, place, messages=messages)
                ws_holder["load"] = load
                return page
            return QWidget()

        ws = ProWorkspace(coordinator, lambda: None, Store(), page_factory=lambda p: factory(p))
        holder["ws"] = ws
        ws.resize(1440, 900)
        ws.show()
        ws.tabs.open_place(Place(QUERY, "Consumo por municipio"))
        ws._render()
        ws.notify("Consulta guardada en consumo.sql")
        shoot(ws, out / f"consulta-{name}-{qt}.png")
        if not dark:
            ws.tabs.close_current()
            ws.tabs.open_place = ws.tabs.open_place  # misma pestaña, con «Mensajes»
            page, _ = query_page(ws.colors, Place(QUERY, "Consumo por municipio"), messages=True)
            ws.tabs.page_factory = lambda _p, page=page: page
            ws.tabs.open_place(Place(QUERY, "Consumo por municipio"))
            ws._render()
            shoot(ws, out / f"consulta-mensajes-{name}-{qt}.png")
            menu = load_menu(ws.colors)
            menu.show()
            shoot(menu, out / f"cargar-en-qgis-{name}-{qt}.png")
            prompt = save_prompt(ws.colors)
            prompt.show()
            shoot(prompt, out / f"guardar-copias-{name}-{qt}.png")
        ws.detach_coordinator()
        ws.deleteLater()
        settle()
    coordinator.shutdown(10)
    theme(False)
    idle = SessionCoordinator(make_memory_engine, QtDispatcher())
    ws = ProWorkspace(idle, lambda: None, Store())
    ws.start_button.setText("Iniciar DuckDB")  # E4: nombre nuevo (propietario, 2026-11-06)
    ws.state_title.setText("DuckDB no está iniciado")
    ws.sidebar.status.setText("No iniciado")
    ws.sidebar.tree.topLevelItem(1).setText(0, "Inicia DuckDB para ver tus bases")
    ws.search_button.setEnabled(False)
    for widget in (ws.sidebar.search, ws.sidebar.add_button, ws.sidebar.tree, ws.sidebar.session_button):
        widget.setEnabled(False)  # E4: todo en gris sin DuckDB, salvo iniciar, abrir, crear y ayuda
    ws.resize(1440, 900)
    ws.show()
    shoot(ws, out / f"sin-duckdb-claro-{qt}.png")
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    app.exitQgis()


if __name__ == "__main__":
    main()
