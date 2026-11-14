# SPDX-License-Identifier: GPL-2.0-or-later
"""La tarjeta de un error de DuckDB en «Mensajes» (#145, punto 13; maqueta `errores-tipos`).

Siempre en el mismo orden: qué pasó (el título, traducido) → dónde (línea y palabra, archivo u objeto) → por
qué y la sugerencia de DuckDB → los botones para arreglarlo (el primero, el principal), «Ir» y «Copiar error»
→ el mensaje original de DuckDB, plegable. Lo que cada botón hace lo decide la pestaña de consulta: los
arreglos solo cambian el texto del editor (cargar `spatial` pide permiso).
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout

from geoduck.domain.sql_errors import ErrorCard, Fix
from geoduck.ui.i18n import tr
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import button, icon_button, label


class ErrorCardView(QFrame):
    """Una tarjeta. `fix_requested(Fix)` al pulsar un arreglo; `go_requested()` con «Ir»."""

    fix_requested = pyqtSignal(object)
    go_requested = pyqtSignal()

    def __init__(self, card: ErrorCard, colors: Colors) -> None:
        super().__init__()
        self.card = card
        self.setProperty("pro", "error-card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName(card.title)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(6)
        self.title = label(card.title, "error")
        self.title.setFont(ui_font(METRICS.font_title - 1, bold=True))
        self.title.setWordWrap(True)
        box.addWidget(self.title)
        if card.where:
            self.where = label(card.where)
            self.where.setWordWrap(True)
            box.addWidget(self.where)
        if card.explanation:
            self.explanation = label(card.explanation, "muted")
            self.explanation.setWordWrap(True)
            self.explanation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(self.explanation)
        self._buttons(box, card, colors)
        self.toggle = button("▸ " + tr("Original DuckDB message"), "link")
        self.toggle.setCheckable(True)
        self.toggle.toggled.connect(self._toggled)
        box.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.original = label(card.original, "mono")
        self.original.setProperty("pro", "code-block")
        self.original.setWordWrap(True)
        self.original.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.original.setTextFormat(Qt.TextFormat.PlainText)
        self.original.hide()
        box.addWidget(self.original)

    def _buttons(self, box: QVBoxLayout, card: ErrorCard, colors: Colors) -> None:
        """Los arreglos (el primero, el principal), «Ir» y «Copiar error»."""
        row = QHBoxLayout()
        row.setSpacing(8)
        box.addLayout(row)  # antes de sus botones: sin padre, uno visible sería una ventana suelta
        self.fix_buttons: list[QPushButton] = []
        for index, fix in enumerate(card.fixes):
            item = button(fix.label, "primary" if index == 0 else None)
            item.setToolTip(_fix_help(fix))
            item.clicked.connect(lambda _c=False, f=fix: self.fix_requested.emit(f))
            row.addWidget(item)
            self.fix_buttons.append(item)
        self.go_button = button(tr("Go"))
        self.go_button.setToolTip(tr("Goes to the error in the editor"))
        self.go_button.clicked.connect(self.go_requested.emit)
        self.go_button.setVisible(card.line is not None)
        row.addWidget(self.go_button)
        # solo el ícono, en la ventana y en el panel (propietario, 2026-11-13); la ayuda dice qué copia
        self.copy_button = icon_button(
            "copy", tr("Copies DuckDB's original message (to search for it or report it)"), colors
        )
        self.copy_button.clicked.connect(lambda: QGuiApplication.clipboard().setText(card.original))
        row.addWidget(self.copy_button)
        row.addStretch(1)

    def _toggled(self, open_: bool) -> None:
        self.original.setVisible(open_)
        self.toggle.setText(("▾ " if open_ else "▸ ") + tr("Original DuckDB message"))


def _fix_help(fix: Fix) -> str:
    if fix.kind == "extension":
        return tr("Asks before installing or loading the extension (only for this session)")
    if fix.kind == "folder":
        return fix.value
    return tr("Only changes the text in the editor; nothing runs until you press ▶")
