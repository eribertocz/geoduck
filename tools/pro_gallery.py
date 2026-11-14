# SPDX-License-Identifier: GPL-2.0-or-later
"""Galería del sistema de diseño de Workspace Pro (G9 · E1): todas las piezas en tema claro y oscuro.

    QT_QPA_PLATFORM=offscreen python tools/pro_gallery.py <carpeta>

Escribe `galeria-claro-<qt>.png` y `galeria-oscuro-<qt>.png`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QT_VERSION_STR, Qt
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


def section(title: str) -> QLabel:
    from geoduck.ui.pro.widgets import label

    return label(title.upper(), "section")


def gallery(dark: bool) -> QWidget:  # noqa: PLR0915 - la galería entera, de arriba abajo
    from geoduck.ui.pro import icons, style
    from geoduck.ui.pro.tokens import DARK, LIGHT
    from geoduck.ui.pro.widgets import (
        Chip,
        SearchField,
        Segmented,
        StatusDot,
        Toast,
        add_chip_button,
        button,
        icon_button,
        label,
    )

    root = QWidget()
    palette = root.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#16181d" if dark else "#f0f0f0"))
    root.setPalette(palette)
    colors = style.apply(root)
    assert colors is (DARK if dark else LIGHT)
    root.resize(1180, 760)
    page = QVBoxLayout(root)
    page.setContentsMargins(28, 24, 28, 24)
    page.setSpacing(14)
    page.addWidget(label("GeoDuck · sistema de diseño", "title"))
    page.addWidget(label("Workspace Pro (G9 · E1) — tokens, tipografía, piezas e iconos", "muted"))

    page.addWidget(section("Colores"))
    swatches = QHBoxLayout()
    for name in (
        "bg",
        "side",
        "border",
        "text",
        "muted",
        "faint",
        "accent",
        "accent_fill",
        "ok",
        "warn",
        "error",
    ):
        box = QVBoxLayout()
        chip = QFrame()
        chip.setFixedSize(76, 34)
        chip.setStyleSheet(
            f"background: {getattr(colors, name)}; border: 1px solid {colors.border}; border-radius: 6px;"
        )
        box.addWidget(chip)
        box.addWidget(label(name, "faint"))
        swatches.addLayout(box)
    swatches.addStretch(1)
    page.addLayout(swatches)

    page.addWidget(section("Tipografía"))
    type_row = QHBoxLayout()
    for text, kind in (
        ("Título 15", "title"),
        ("Texto 13", None),
        ("Secundario", "muted"),
        ("tipo · 11", "faint"),
        ("12 345,67", "mono"),
        ("NULL", "null"),
        ("Error claro", "error"),
        ("Enlace", "link"),
        ("Ctrl K", "kbd"),
        ("1,1 M", "badge"),
    ):
        type_row.addWidget(label(text, kind))
        type_row.addSpacing(10)
    type_row.addStretch(1)
    page.addLayout(type_row)

    page.addWidget(section("Botones"))
    buttons = QHBoxLayout()
    buttons.addWidget(button("Cargar en QGIS ▾", "primary", icon="layers", colors=colors))
    buttons.addWidget(button("Acoplar a QGIS", icon="dock", colors=colors))
    buttons.addWidget(button("Ver SQL", "ghost"))
    buttons.addWidget(button("Deshacer envío", "danger"))
    off = button("Enviar", "primary")
    off.setEnabled(False)
    buttons.addWidget(off)
    buttons.addWidget(icon_button("refresh", "Releer las bases", colors))
    buttons.addWidget(icon_button("more", "Más acciones", colors))
    buttons.addStretch(1)
    page.addLayout(buttons)

    page.addWidget(section("Campos, filtros y vistas"))
    fields = QHBoxLayout()
    search = SearchField("Buscar tablas…", colors, shortcut="Ctrl K")
    search.setFixedWidth(240)
    fields.addWidget(search)
    edit = QLineEdit("consumidores")
    edit.setFixedWidth(160)
    fields.addWidget(edit)
    combo = QComboBox()
    combo.addItems(["db · main", "memory · main", "Tabla temporal"])
    fields.addWidget(combo)
    fields.addWidget(Chip("CodigoMunicipio", "=", "0201", colors, remove_tip="Quitar filtro"))
    fields.addWidget(Chip("ConsumoKwh", ">", "50", colors, remove_tip="Quitar filtro"))
    fields.addWidget(add_chip_button("Filtro", "Añadir un filtro"))
    fields.addStretch(1)
    page.addLayout(fields)
    more = QHBoxLayout()
    more.addWidget(Segmented(["Datos", "Estructura"], accessible_name="Vista"))
    more.addWidget(Segmented(["Copia", "Conectada"], accessible_name="Cargar como"))
    check = QCheckBox("Abrir la tabla al terminar")
    check.setChecked(True)
    more.addWidget(check)
    for state, text in (("ok", "Lista"), ("busy", "Ocupada"), ("error", "Error"), ("off", "Sin sesión")):
        more.addSpacing(8)
        more.addWidget(StatusDot(colors, state))
        more.addWidget(label(text, "muted"))
    more.addStretch(1)
    page.addLayout(more)

    page.addWidget(section("Iconos"))
    grid = QGridLayout()
    grid.setHorizontalSpacing(18)
    grid.setVerticalSpacing(6)
    for i, name in enumerate(icons.PATHS):
        cell = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(icons.pixmap(name, colors.star if name.startswith("star") else colors.text, 18))
        cell.addWidget(pic)
        cell.addWidget(label(name, "faint"))
        cell.addStretch(1)
        holder = QWidget()
        holder.setLayout(cell)
        grid.addWidget(holder, i // 7, i % 7)
    page.addLayout(grid)
    page.addStretch(1)

    toast = Toast(root, "Tabla <b>zonas</b> creada en db.main · 412 filas", seconds=0)
    toast.add_action("Abrir", lambda: None)
    toast.add_action("Deshacer", lambda: None)
    toast.show_at_corner(bottom=24)
    toast._fade.setCurrentTime(toast._fade.duration())  # la captura, con el aviso ya visible
    return root


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    qt = f"qt{QT_VERSION_STR.split('.')[0]}"
    for dark, name in ((False, "claro"), (True, "oscuro")):
        widget = gallery(dark)
        widget.show()
        app.processEvents()
        widget.grab().save(str(out / f"galeria-{name}-{qt}.png"))
        widget.close()
    print(out)
    os._exit(0)


if __name__ == "__main__":
    _ = Qt
    main()
