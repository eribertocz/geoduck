# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G9-A (E0b): la pestaña de tabla de la maqueta, hecha con Qt Widgets y un sistema de diseño propio.

No es código de GeoDuck: es una prueba de que Qt Widgets alcanza el aspecto de la maqueta aprobada
(`docs/g8/maqueta/1-tabla.dc.html`) en Qt 5 y Qt 6, en tema claro y oscuro, y de que una grilla por páginas
sobre 1 millón de filas responde. Lee DuckDB directamente (en GeoDuck lo hará el worker).

    QT_QPA_PLATFORM=offscreen python g9a_tabla.py <carpeta de salida>

Escribe `tabla-claro-<qt>.png`, `tabla-oscuro-<qt>.png` y `medidas-<qt>.txt`.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import duckdb
from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# -- tokens del sistema de diseño (un solo lugar) -------------------------------------------------------

LIGHT = {
    "bg": "#ffffff",
    "side": "#f6f7f9",
    "border": "#e4e6ea",
    "line": "#f0f1f4",
    "head": "#fbfbfc",
    "text": "#1d2026",
    "muted": "#6b7280",
    "faint": "#9aa1ab",
    "null": "#b0b6bf",
    "accent": "#2f5fd0",
    "accent_soft": "#e7ecfa",
    "row_sel": "#eef2fd",
    "chip_bg": "#f3f6fe",
    "chip_border": "#c9d6f5",
    "ok": "#1f9d55",
    "toast": "#1d2026",
    "toast_text": "#ffffff",
    "toast_link": "#a8c1ff",
    "seg": "#eef0f3",
}
DARK = {
    "bg": "#16181d",
    "side": "#1b1e24",
    "border": "#2a2e36",
    "line": "#23262d",
    "head": "#1b1e24",
    "text": "#e6e8ec",
    "muted": "#9aa1ab",
    "faint": "#7c838e",
    "null": "#5c636e",
    "accent": "#5b84e6",
    "accent_soft": "#22304f",
    "row_sel": "#1f2a44",
    "chip_bg": "#1d2740",
    "chip_border": "#33466f",
    "ok": "#34c46e",
    "toast": "#e6e8ec",
    "toast_text": "#16181d",
    "toast_link": "#2f5fd0",
    "seg": "#23262d",
}
FONT = "Segoe UI, Inter, Noto Sans, sans-serif"
MONO = "Cascadia Mono, JetBrains Mono, DejaVu Sans Mono, monospace"
RADIUS = 7
PAGE = 100


def stylesheet(t: dict[str, str]) -> str:
    """Estilos generados de los tokens; en GeoDuck se aplicarán solo a sus widgets (ADR-0011)."""
    return f"""
    QWidget {{ font-family: "{family(FONT)}"; font-size: 13px; color: {t["text"]}; }}
    QTableCornerButton::section {{ background: {t["head"]}; border: 0; border-bottom: 1px solid {t["border"]}; }}
    QWidget#gd {{ background: {t["bg"]}; color: {t["text"]}; }}
    QFrame#side {{ background: {t["side"]}; border-right: 1px solid {t["border"]}; }}
    QFrame#bar {{ border-bottom: 1px solid {t["border"]}; }}
    QFrame#filters {{ border-bottom: 1px solid {t["line"]}; }}
    QFrame#foot {{ background: {t["head"]}; border-top: 1px solid {t["border"]}; }}
    QFrame#detail {{ border-left: 1px solid {t["border"]}; }}
    QLabel[role="muted"] {{ color: {t["muted"]}; }}
    QLabel[role="faint"] {{ color: {t["faint"]}; font-size: 11px; }}
    QLabel[role="section"] {{ color: {t["muted"]}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
    QLabel[role="mono"] {{ font-family: "{family(MONO)}"; font-size: 12px; }}
    QLineEdit {{ background: {t["bg"]}; border: 1px solid {t["border"]}; border-radius: {RADIUS}px;
        padding: 5px 9px; color: {t["text"]}; selection-background-color: {t["accent"]}; }}
    QLineEdit:focus {{ border-color: {t["accent"]}; }}
    QPushButton {{ border: 1px solid {t["border"]}; border-radius: {RADIUS}px; background: {t["bg"]};
        color: {t["text"]}; padding: 6px 12px; }}
    QPushButton:hover {{ border-color: {t["muted"]}; }}
    QPushButton[kind="primary"] {{ background: {t["accent"]}; border-color: {t["accent"]}; color: #ffffff;
        font-weight: 600; padding: 7px 14px; }}
    QPushButton[kind="ghost"] {{ border: 0; background: transparent; color: {t["muted"]}; }}
    QPushButton[kind="addchip"] {{ border: 1px dashed {t["null"]}; border-radius: 15px; background: transparent;
        color: {t["muted"]}; padding: 5px 11px; }}
    QPushButton[kind="seg-on"] {{ border: 0; border-radius: 5px; background: {t["bg"]}; font-weight: 600;
        padding: 4px 12px; }}
    QPushButton[kind="seg-off"] {{ border: 0; background: transparent; color: {t["muted"]}; padding: 4px 12px; }}
    QPushButton[kind="page"] {{ padding: 2px 8px; border-radius: 6px; }}
    QFrame#seg {{ background: {t["seg"]}; border-radius: 7px; }}
    QFrame[kind="search"] {{ background: {t["bg"]}; border: 1px solid {t["border"]}; border-radius: {RADIUS}px; }}
    QTreeWidget {{ show-decoration-selected: 0; }}
    QTreeWidget::branch, QTreeWidget::branch:selected {{ background: transparent; border: 0; image: none; }}
    QFrame[kind="chip"] {{ background: {t["chip_bg"]}; border: 1px solid {t["chip_border"]}; border-radius: 15px; }}
    QToolButton {{ border: 0; background: transparent; color: {t["muted"]}; }}
    QFrame[kind="tab-on"] {{ background: {t["bg"]}; border: 1px solid {t["border"]}; border-bottom: 0;
        border-top-left-radius: 8px; border-top-right-radius: 8px; }}
    QFrame[kind="tab-off"] {{ background: transparent; }}
    QFrame#toast {{ background: {t["toast"]}; border-radius: 10px; }}
    QFrame#toast QLabel {{ color: {t["toast_text"]}; }}
    QFrame#toast QLabel[role="link"] {{ color: {t["toast_link"]}; }}
    QLabel[role="link"] {{ color: {t["accent"]}; }}
    QTreeWidget {{ background: transparent; color: {t["text"]}; border: 0; outline: 0; }}
    QTreeWidget::item {{ height: 28px; border-radius: 6px; padding-left: 2px; }}
    QTreeWidget::item:selected {{ background: {t["accent_soft"]}; color: {t["text"]}; font-weight: 600; }}
    QTableView {{ background: {t["bg"]}; color: {t["text"]}; border: 0; gridline-color: {t["line"]}; outline: 0;
        selection-background-color: {t["row_sel"]}; selection-color: {t["text"]}; }}
    QHeaderView::section {{ background: {t["head"]}; border: 0; border-bottom: 1px solid {t["border"]};
        border-left: 1px solid {t["line"]}; padding: 0 10px; height: 34px; font-weight: 600; color: {t["text"]}; }}
    QScrollBar:vertical {{ width: 10px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: {t["border"]}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ height: 10px; background: transparent; }}
    QScrollBar::handle:horizontal {{ background: {t["border"]}; border-radius: 5px; min-width: 30px; }}
    """


def _qt6() -> bool:
    from qgis.PyQt.QtCore import QT_VERSION_STR  # noqa: PLC0415

    return QT_VERSION_STR.startswith("6")


def family(candidates: str) -> str:
    """La primera familia instalada de la lista (las hojas de estilo de Qt 5 no admiten varias)."""
    from qgis.PyQt.QtGui import QFontDatabase  # noqa: PLC0415

    # Qt 6: métodos estáticos; Qt 5: hace falta una instancia
    installed = set(
        QFontDatabase.families()
        if not hasattr(QFontDatabase, "__init__") or _qt6()
        else QFontDatabase().families()
    )
    names = [n.strip() for n in candidates.split(",")]
    return next((n for n in names if n in installed), names[-1])


def ui_font(px: int = 13) -> QFont:
    """La fuente del sistema (Segoe UI en Windows); en Linux, Inter o Noto Sans. Tamaño en píxeles."""
    f = QFont()
    if hasattr(f, "setFamilies"):
        f.setFamilies([n.strip() for n in FONT.split(",")])
    else:
        f.setFamily(FONT.split(",", maxsplit=1)[0])
    f.setPixelSize(px)
    return f


def label(text: str, role: str | None = None) -> QLabel:
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    return w


def button(text: str, kind: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def frame(name: str | None = None, kind: str | None = None) -> QFrame:
    f = QFrame()
    if name:
        f.setObjectName(name)
    if kind:
        f.setProperty("kind", kind)
    return f


# -- datos: una tabla de DuckDB leída por páginas ------------------------------------------------------


class PagedModel(QAbstractTableModel):
    """Una página de 100 filas pedida a DuckDB (`LIMIT/OFFSET` sobre el orden y el filtro de la pestaña)."""

    def __init__(self, con: duckdb.DuckDBPyConnection, table: str, where: str, theme: dict[str, str]) -> None:
        super().__init__()
        self.con, self.table, self.where, self.t = con, table, where, theme
        self.columns = [
            (r[0], r[1].lower().split("(")[0]) for r in con.execute(f"DESCRIBE {table}").fetchall()
        ]
        self.rows: list[tuple] = []
        self.offset = 0
        self.total = 0

    def count(self) -> int:
        self.total = self.con.execute(f"SELECT count(*) FROM {self.table} WHERE {self.where}").fetchone()[0]
        return self.total

    def load(self, offset: int) -> None:
        names = ", ".join(f'"{c}"' if t != "geometry" else f'"{c}"::VARCHAR' for c, t in self.columns)
        sql = f'SELECT {names} FROM {self.table} WHERE {self.where} ORDER BY "Consumidor" LIMIT {PAGE} OFFSET {offset}'
        self.beginResetModel()
        self.rows = self.con.execute(sql).fetchall()
        self.offset = offset
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802, B008
        return len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        value = self.rows[index.row()][index.column()]
        kind = self.columns[index.column()][1]
        if role == Qt.ItemDataRole.DisplayRole:
            if value is None:
                return "NULL"
            if kind == "geometry":
                return str(value).split(" ")[0]
            if kind == "double":
                return f"{value:,.2f}".replace(",", " ").replace(".", ",")
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric = kind in ("bigint", "integer", "double")
            h = Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft
            return int(h | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            if value is None:
                return QColor(self.t["null"])
            if kind == "geometry":
                return QColor(self.t["muted"])
        if role == Qt.ItemDataRole.FontRole:
            f = QFont()
            if value is None:
                f.setItalic(True)
            elif kind in ("bigint", "integer", "double"):
                f.setFamily(MONO.split(",", maxsplit=1)[0])
                f.setStyleHint(QFont.StyleHint.Monospace)
                f.setPointSizeF(9.5)
            return f
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self.columns[section][0]
            return str(self.offset + section + 1)
        return None


class HeaderWithType(QHeaderView):
    """Encabezado en una línea: nombre en negrita y el tipo en gris y monoespaciado (como la maqueta)."""

    def __init__(self, model: PagedModel, theme: dict[str, str]) -> None:
        super().__init__(Qt.Orientation.Horizontal)
        self.m, self.t = model, theme
        self.setSectionsClickable(True)
        self.setHighlightSections(False)

    def paintSection(self, painter: QPainter, rect: QRect, index: int) -> None:  # noqa: N802
        painter.save()
        painter.fillRect(rect, QColor(self.t["head"]))
        painter.setPen(QPen(QColor(self.t["border"])))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setPen(QPen(QColor(self.t["line"])))
        painter.drawLine(rect.topLeft(), rect.bottomLeft())
        name, kind = self.m.columns[index]
        bold = QFont(self.font())
        bold.setBold(True)
        painter.setFont(bold)
        painter.setPen(QColor(self.t["text"]))
        r = rect.adjusted(10, 0, -6, 0)
        painter.drawText(r, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), name)
        width = painter.fontMetrics().horizontalAdvance(name)
        mono = QFont(MONO.split(",", maxsplit=1)[0])
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSizeF(8)
        painter.setFont(mono)
        painter.setPen(QColor(self.t["faint"]))
        painter.drawText(r.adjusted(width + 6, 1, 0, 0), int(Qt.AlignmentFlag.AlignVCenter), kind)
        painter.restore()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(super().sizeHint().width(), 34)


class RowDelegate(QStyledItemDelegate):
    """Celdas con margen interior y solo líneas horizontales suaves."""

    def __init__(self, theme: dict[str, str]) -> None:
        super().__init__()
        self.t = theme

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        opt.rect = option.rect.adjusted(10, 0, -10, 0)
        super().paint(painter, opt, index)
        painter.save()
        painter.setPen(QPen(QColor(self.t["line"])))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.drawLine(option.rect.topLeft(), option.rect.bottomLeft())
        painter.restore()


# -- la pantalla -----------------------------------------------------------------------------------------


def sidebar(t: dict[str, str]) -> QFrame:
    side = frame("side")
    side.setFixedWidth(264)
    box = QVBoxLayout(side)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(0)
    head = QHBoxLayout()
    head.setContentsMargins(14, 0, 10, 0)
    dot = label("●")
    dot.setStyleSheet(f"color: {t['ok']}; font-size: 10px;")
    titles = QVBoxLayout()
    titles.setSpacing(0)
    titles.addWidget(label("<b>Sesión DuckDB</b>"))
    titles.addWidget(label("2.0.0 · en memoria", "muted"))
    head.addWidget(dot)
    head.addSpacing(6)
    head.addLayout(titles, 1)
    head.addWidget(QToolButton(text="⋯"))
    top = QWidget()
    top.setFixedHeight(52)
    top.setLayout(head)
    top.setStyleSheet(f"border-bottom: 1px solid {t['border']};")
    box.addWidget(top)
    search_box = frame(kind="search")
    srow = QHBoxLayout(search_box)
    srow.setContentsMargins(8, 0, 6, 0)
    srow.setSpacing(6)
    srow.addWidget(label("⌕", "muted"))
    search = QLineEdit()
    search.setPlaceholderText("Buscar tablas…")
    search.setStyleSheet("border: 0; padding: 4px 0; background: transparent;")
    srow.addWidget(search, 1)
    badge = label("Ctrl K", "faint")
    badge.setStyleSheet(f"border: 1px solid {t['border']}; border-radius: 4px; padding: 0 4px;")
    srow.addWidget(badge)
    search_box.setFixedHeight(32)
    wrap = QVBoxLayout()
    wrap.setContentsMargins(12, 10, 12, 6)
    wrap.addWidget(search_box)
    box.addLayout(wrap)
    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.setHeaderHidden(True)
    tree.header().setStretchLastSection(False)
    tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    tree.setIndentation(14)
    tree.setRootIsDecorated(False)
    sec = QTreeWidgetItem(["RECIENTES"])
    sec.setFlags(Qt.ItemFlag.NoItemFlags)
    tree.addTopLevelItem(sec)
    for star, name, where in (("★", "consumidores", "db"), ("☆", "Consumo por municipio", "SQL")):
        it = QTreeWidgetItem([f"{star}  {name}", where])
        it.setForeground(1, QColor(t["faint"]))
        tree.addTopLevelItem(it)
    tree.addTopLevelItem(QTreeWidgetItem([""]))
    bases = QTreeWidgetItem(["BASES"])
    bases.setFlags(Qt.ItemFlag.NoItemFlags)
    tree.addTopLevelItem(bases)
    db = QTreeWidgetItem(["▾ db  · lectura y escritura"])
    tree.addTopLevelItem(db)
    for name, rows in (
        ("consumidores", "1,0 M"),
        ("lecturas", "68 M"),
        ("medidores", "1,2 M"),
        ("municipios", "339"),
        ("zonas", "412"),
    ):
        it = QTreeWidgetItem([f"▦  {name}", rows])
        it.setForeground(1, QColor(t["faint"]))
        db.addChild(it)
    db.addChild(QTreeWidgetItem(["▸ Vistas (2)"]))
    tree.addTopLevelItem(QTreeWidgetItem(["▸ memory  · en uso"]))
    tree.addTopLevelItem(QTreeWidgetItem(["▸ ventas  · solo lectura"]))
    tree.expandAll()
    tree.setCurrentItem(db.child(0))
    for item in (sec, bases):
        f = QFont()
        f.setBold(True)
        f.setPointSizeF(8)
        item.setFont(0, f)
        item.setForeground(0, QColor(t["muted"]))
    for i in range(tree.topLevelItemCount()):
        it = tree.topLevelItem(i)
        if it.text(0).startswith(("▾", "▸")):
            f = QFont()
            f.setBold(True)
            it.setFont(0, f)
    trees = QVBoxLayout()
    trees.setContentsMargins(8, 4, 8, 4)
    trees.addWidget(tree)
    box.addLayout(trees, 1)
    foot = QHBoxLayout()
    foot.setContentsMargins(14, 10, 14, 10)
    foot.addWidget(label("Diagnóstico", "link"))
    foot.addSpacing(12)
    foot.addWidget(label("Acerca de", "link"))
    foot.addStretch(1)
    foot.addWidget(label("v0.10.0a1", "faint"))
    bottom = QWidget()
    bottom.setLayout(foot)
    bottom.setStyleSheet(f"border-top: 1px solid {t['border']};")
    box.addWidget(bottom)
    return side


def tab(kind: str, name: str, on: bool) -> QFrame:
    f = frame(kind="tab-on" if on else "tab-off")
    f.setFixedHeight(38)
    row = QHBoxLayout(f)
    row.setContentsMargins(14, 0, 12, 0)
    row.setSpacing(8)
    k = label(kind, "mono")
    k.setProperty("role", "faint")
    row.addWidget(k)
    n = label(f"<b>{name}</b>" if on else name, None if on else "muted")
    row.addWidget(n)
    row.addWidget(label("×", "faint"))
    return f


def chip(column: str, op: str, value: str) -> QFrame:
    f = frame(kind="chip")
    f.setFixedHeight(30)
    row = QHBoxLayout(f)
    row.setContentsMargins(10, 0, 4, 0)
    row.setSpacing(6)
    row.addWidget(label(column, "muted"))
    row.addWidget(label(op))
    row.addWidget(label(value, "mono"))
    row.addWidget(QToolButton(text="×"))
    return f


def detail_panel(t: dict[str, str], model: PagedModel, row: int) -> QFrame:
    d = frame("detail")
    d.setFixedWidth(300)
    box = QVBoxLayout(d)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(0)
    head = QHBoxLayout()
    head.setContentsMargins(14, 12, 10, 12)
    head.addWidget(label(f"<b>Fila {model.offset + row + 1}</b>"))
    head.addStretch(1)
    head.addWidget(QToolButton(text="×"))
    top = QWidget()
    top.setLayout(head)
    top.setStyleSheet(f"border-bottom: 1px solid {t['line']};")
    box.addWidget(top)
    body = QVBoxLayout()
    body.setContentsMargins(14, 6, 14, 6)
    for i, (name, kind) in enumerate(model.columns):
        value = model.rows[row][i]
        key = label(
            f"{name} <span style='color:{t['faint']}; font-family:{MONO.split(',', maxsplit=1)[0]}'>{kind}</span>",
            "muted",
        )
        key.setStyleSheet("font-size: 11px;")
        v = label("NULL" if value is None else str(value))
        v.setWordWrap(True)
        if value is None:
            v.setStyleSheet(f"color: {t['null']}; font-style: italic;")
        elif kind in ("bigint", "double", "geometry"):
            v.setProperty("role", "mono")
        cell = QVBoxLayout()
        cell.setSpacing(3)
        cell.addWidget(key)
        cell.addWidget(v)
        w = QWidget()
        w.setLayout(cell)
        w.setStyleSheet(f"border-bottom: 1px solid {t['line']}; padding: 4px 0;")
        body.addWidget(w)
    body.addStretch(1)
    box.addLayout(body, 1)
    return d


def screen(con: duckdb.DuckDBPyConnection, t: dict[str, str]) -> tuple[QWidget, dict[str, float]]:
    times: dict[str, float] = {}
    root = QWidget()
    root.setObjectName("gd")
    root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    root.setStyleSheet(stylesheet(t))
    root.setFont(ui_font())
    root.resize(1440, 900)
    outer = QHBoxLayout(root)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    outer.addWidget(sidebar(t))
    main = QVBoxLayout()
    main.setContentsMargins(0, 0, 0, 0)
    main.setSpacing(0)
    outer.addLayout(main, 1)

    bar = frame("bar")
    bar.setFixedHeight(52)
    tabs = QHBoxLayout(bar)
    tabs.setContentsMargins(12, 0, 12, 0)
    tabs.setSpacing(2)
    tabs.setAlignment(Qt.AlignmentFlag.AlignBottom)
    for kind, name, on in (
        ("T", "consumidores", True),
        ("SQL", "Consulta 1", False),
        ("T", "lecturas", False),
    ):
        tabs.addWidget(tab(kind, name, on), 0, Qt.AlignmentFlag.AlignBottom)
    plus = QToolButton(text="+")
    plus.setStyleSheet("font-size: 18px;")
    tabs.addWidget(plus, 0, Qt.AlignmentFlag.AlignBottom)
    tabs.addStretch(1)
    dock = button("◫  Acoplar a QGIS")
    tabs.addWidget(dock, 0, Qt.AlignmentFlag.AlignVCenter)
    main.addWidget(bar)

    filters = frame("filters")
    row = QHBoxLayout(filters)
    row.setContentsMargins(16, 10, 16, 10)
    row.setSpacing(8)
    row.addWidget(chip("CodigoMunicipio", "=", "0201"))
    row.addWidget(chip("ConsumoKwh", ">", "50"))
    row.addWidget(button("+ Filtro", "addchip"))
    find = QLineEdit()
    find.setPlaceholderText("Buscar en todas las columnas…")
    find.setFixedWidth(240)
    row.addSpacing(8)
    row.addWidget(find)
    row.addStretch(1)
    row.addWidget(button("Ver SQL", "ghost"))
    where = '"CodigoMunicipio" = \'0201\' AND "ConsumoKwh" > 50'
    model = PagedModel(con, "consumidores", where, t)
    start = time.perf_counter()
    model.load(0)
    times["primera página (100 filas, filtro y orden)"] = time.perf_counter() - start
    start = time.perf_counter()
    total = model.count()
    times["conteo con filtro"] = time.perf_counter() - start
    count = label(f"{total:,} filas".replace(",", " "), "muted")
    row.addWidget(count)
    main.addWidget(filters)

    body = QHBoxLayout()
    body.setSpacing(0)
    view = QTableView()
    view.setModel(model)
    view.setHorizontalHeader(HeaderWithType(model, t))
    view.setItemDelegate(RowDelegate(t))
    view.setShowGrid(False)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.verticalHeader().setDefaultSectionSize(32)
    view.verticalHeader().setFixedWidth(56)
    view.verticalHeader().setStyleSheet(
        f"QHeaderView::section {{ background: {t['bg']}; color: {t['faint']}; border: 0; "
        f"border-bottom: 1px solid {t['line']}; padding-right: 10px; font-size: 12px; }}"
    )
    view.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    widths = {
        "Consumidor": 150,
        "RazonSocial": 230,
        "Direccion": 200,
        "CodigoMunicipio": 175,
        "ConsumoKwh": 145,
        "geom": 140,
    }
    for i, (name, _) in enumerate(model.columns):
        view.setColumnWidth(i, widths.get(name, 140))
    view.selectRow(2)
    body.addWidget(view, 1)
    body.addWidget(detail_panel(t, model, 2))
    main.addLayout(body, 1)

    foot = frame("foot")
    foot.setFixedHeight(48)
    frow = QHBoxLayout(foot)
    frow.setContentsMargins(16, 0, 16, 0)
    frow.setSpacing(10)
    seg = frame("seg")
    srow = QHBoxLayout(seg)
    srow.setContentsMargins(2, 2, 2, 2)
    srow.setSpacing(0)
    srow.addWidget(button("Datos", "seg-on"))
    srow.addWidget(button("Estructura", "seg-off"))
    frow.addWidget(seg)
    frow.addWidget(label(f"1–{min(PAGE, total)} de {total:,}".replace(",", " "), "muted"))
    frow.addWidget(button("‹", "page"))
    frow.addWidget(button("›", "page"))
    frow.addStretch(1)
    frow.addWidget(label("Capa «consumidores» cargada · Conectada · ", "muted"))
    frow.addWidget(label("Ver en el mapa", "link"))
    frow.addWidget(button("◈  Cargar en QGIS ▾", "primary"))
    main.addWidget(foot)

    toast = frame("toast")
    toast.setParent(root)
    trow = QHBoxLayout(toast)
    trow.setContentsMargins(14, 10, 12, 10)
    trow.setSpacing(12)
    tdot = label("●")
    tdot.setStyleSheet("color: #4ade80; font-size: 10px;")
    trow.addWidget(tdot)
    trow.addWidget(label("Tabla <b>zonas</b> creada en db.main · 412 filas"))
    trow.addWidget(label("Abrir", "link"))
    trow.addWidget(label("Deshacer", "link"))
    toast.adjustSize()
    toast.move(1440 - 330 - toast.width(), 900 - 64 - toast.height())
    toast.raise_()

    # Desplazar la grilla página a página: lo que costaría ‹ › y una lectura por desplazamiento
    start = time.perf_counter()
    for page in range(1, 11):
        model.load(page * PAGE)
    times["10 páginas siguientes (media por página)"] = (time.perf_counter() - start) / 10
    model.load(0)
    view.selectRow(2)
    return root, times


def make_table(con: duckdb.DuckDBPyConnection, n: int) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TABLE consumidores AS
        SELECT 100000 + range AS "Consumidor",
               ['QUEA CONDORI RENE','SUAZNABAR VENEGAS SERGIO','SUPO HUAQUI FRANCISCA','KULJIS MERUVIA IVANKO',
                'VASQUEZ CORRO PATRICIA','MAMANI QUISPE JUAN','FLORES ROJAS ANA','CHOQUE LIMACHI LUIS'][range % 8 + 1]
                 AS "RazonSocial",
               CASE WHEN range % 7 = 3 THEN NULL ELSE 'AV. ' || (range % 900) || ', ZONA ' || (range % 31) END
                 AS "Direccion",
               lpad(((range // 7 % 37) + 180)::VARCHAR, 4, '0') AS "CodigoMunicipio",
               round(20 + (range * 37 % 4000) / 10.0, 2)::DOUBLE AS "ConsumoKwh",
               ST_SetCRS(('POINT(' || (-68.2 + (range % 1000) / 10000.0) || ' ' || (-16.55 + (range // 1000) / 100000.0)
                 || ')')::GEOMETRY, 'EPSG:4326') AS geom
        FROM range({n})
        """
    )


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    from qgis.PyQt.QtCore import QT_VERSION_STR  # noqa: PLC0415

    qt = f"qt{QT_VERSION_STR.split('.')[0]}"
    con = duckdb.connect()
    start = time.perf_counter()
    make_table(con, 1_000_000)
    lines = [
        f"Qt {QT_VERSION_STR} · DuckDB {duckdb.__version__} · tabla de 1 000 000 filas ({time.perf_counter() - start:.1f} s)"
    ]
    for name, theme in (("claro", LIGHT), ("oscuro", DARK)):
        start = time.perf_counter()
        widget, times = screen(con, theme)
        widget.show()
        app.processEvents()
        build = time.perf_counter() - start
        widget.grab().save(str(out / f"tabla-{name}-{qt}.png"))
        if name == "claro":
            lines.append(f"pantalla completa construida y pintada: {build * 1000:.0f} ms")
            lines += [f"{k}: {v * 1000:.0f} ms" for k, v in times.items()]
            start = time.perf_counter()
            view = widget.findChild(QTableView)
            for _ in range(50):
                view.verticalScrollBar().setValue(view.verticalScrollBar().value() + 3)
                app.processEvents()
            lines.append(
                f"50 pasos de desplazamiento pintados: {(time.perf_counter() - start) * 1000 / 50:.1f} ms por paso"
            )
        widget.close()
    (out / f"medidas-{qt}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    os._exit(0)


if __name__ == "__main__":
    main()
