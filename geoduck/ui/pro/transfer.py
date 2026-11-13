# SPDX-License-Identifier: GPL-2.0-or-later
"""QGIS ↔ GeoDuck en un solo diálogo (#148, puntos 15, 16 y 25; maquetas `dialogo-unico` y
`flujo-completo`).

Los dos sentidos siguen los mismos pasos: **elegir → destino y nombres → progreso → listo**. Arriba, de dónde
a dónde («3 capas de QGIS → GeoDuck» o al revés); lo único que cambia es **«Destino»**: hacia GeoDuck, base y
esquema; hacia QGIS, Copia o Conectada. Cada fila tiene **un solo nombre**, el del destino, ya relleno;
debajo, en gris, «de: …». **Doble clic en el nombre** (o F2) para cambiarlo; Enter pasa al siguiente. El
origen nunca se renombra. Al pulsar Enviar o Cargar, el mismo diálogo pasa a la línea de tiempo
(`timeline.TimelineView`).

Aquí solo está la vista: qué se envía, los nombres que chocan y lo que se puede hacer lo deciden
`add_layers.AddLayers` (hacia GeoDuck) y `load_window.LoadWindow` (hacia QGIS).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.PyQt.QtCore import QEvent, Qt, pyqtSignal
from qgis.PyQt.QtGui import QGuiApplication
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons, style
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.timeline import TimelineView, set_footer
from geoduck.ui.pro.tokens import Colors
from geoduck.ui.pro.widgets import LOGO, button, label

FORM, PROGRESS = 0, 1
#: Choques de nombre hacia GeoDuck (#148, punto 16): otro nombre (por defecto), reemplazar o añadir filas.
RENAME, REPLACE, APPEND = "rename", "replace", "append"
#: Nota bajo una fila: un nombre que ya existe en DuckDB (con sus opciones), un aviso que no bloquea (QGIS) o
#: por qué no se puede.
CONFLICT, INFO, ERROR = "conflict", "info", "error"


class NameRow(QFrame):
    """Una fila: la casilla, el nombre en el destino (doble clic o F2 lo cambia) y «de: …» debajo."""

    #: El nombre o la casilla cambiaron.
    changed = pyqtSignal()
    #: Enter al terminar de escribir: pasar a la fila siguiente.
    next_requested = pyqtSignal()
    #: La opción elegida en el choque de nombres (`RENAME`, `REPLACE` o `APPEND`).
    choice_changed = pyqtSignal(str)
    #: Clic en la fila: queda como actual (F2 la edita).
    focused = pyqtSignal()

    def __init__(  # noqa: PLR0915 - la fila, en un solo lugar
        self, colors: Colors, name: str, origin: str, *, enabled: bool = True, checked: bool = True
    ) -> None:
        super().__init__()
        self.colors = colors
        self.setProperty("pro", "name-row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.choice = RENAME
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 8, 4, 8)
        row.setSpacing(10)
        self.check = QCheckBox()
        self.check.setChecked(checked and enabled)
        self.check.setEnabled(enabled)
        self.check.setAccessibleName(tr("Include {0}").format(name))
        self.check.toggled.connect(lambda _on: self.changed.emit())
        row.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(2)
        row.addLayout(column, 1)  # antes de sus widgets: sin padre, uno visible sería una ventana suelta
        self.names = QStackedWidget()
        self.shown = label(name)
        self.shown.setFont(ui_font(bold=True))
        self.shown.setMinimumWidth(1)
        self.shown.setToolTip(tr("Double-click (or F2) to change the name in the destination"))
        self.shown.installEventFilter(self)
        self.edit = QLineEdit(name)
        self.edit.setAccessibleName(tr("Name in the destination for {0}").format(origin))
        self.edit.installEventFilter(self)
        self.edit.returnPressed.connect(self._enter)
        self.names.addWidget(self.shown)
        self.names.addWidget(self.edit)
        column.addWidget(self.names)
        self.origin = label(tr("from: {0}").format(origin), "muted")
        self.origin.setWordWrap(True)
        self.origin.setMinimumWidth(1)
        column.addWidget(self.origin)
        self.note = QFrame()
        self.note.setProperty("pro", "name-note")
        self.note.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        note_row = QHBoxLayout(self.note)
        note_row.setContentsMargins(10, 6, 10, 6)
        note_row.setSpacing(6)
        self.note_icon = QLabel()
        note_row.addWidget(self.note_icon, 0, Qt.AlignmentFlag.AlignTop)
        self.note_text = label("")
        self.note_text.setWordWrap(True)
        self.note_text.setMinimumWidth(1)
        note_row.addWidget(self.note_text, 1)
        self.pills: dict[str, QPushButton] = {}
        for kind in (RENAME, REPLACE, APPEND):
            pill = QPushButton()
            pill.setProperty("pro", "name-pill")
            pill.setCheckable(True)
            pill.setCursor(Qt.CursorShape.PointingHandCursor)
            pill.clicked.connect(lambda _c=False, k=kind: self.set_choice(k, emit=True))
            pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)  # nunca recortada
            note_row.addWidget(pill)
            self.pills[kind] = pill
        self.note.hide()
        column.addWidget(self.note)
        if not enabled:
            self.setEnabled(True)
            self.shown.setEnabled(False)

    # -- nombre ---------------------------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.edit.text().strip()

    @property
    def included(self) -> bool:
        return self.check.isEnabled() and self.check.isChecked()

    @property
    def editing(self) -> bool:
        return self.names.currentWidget() is self.edit

    def start_edit(self) -> None:
        """Doble clic o F2: el campo, con el texto elegido."""
        if not self.check.isEnabled():
            return
        self._before = self.edit.text()
        self.names.setCurrentWidget(self.edit)
        self.edit.setFocus()
        self.edit.selectAll()

    def finish_edit(self, *, keep: bool = True) -> None:
        if not self.editing:
            return
        if not keep:
            self.edit.setText(getattr(self, "_before", self.edit.text()))
        if not self.edit.text().strip():
            self.edit.setText(getattr(self, "_before", ""))
        self.shown.setText(self.edit.text().strip())
        self.names.setCurrentWidget(self.shown)
        self.changed.emit()

    def _enter(self) -> None:
        self.finish_edit()
        self.next_requested.emit()

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        kind = event.type()
        if watched is self.shown and kind == QEvent.Type.MouseButtonDblClick:
            self.start_edit()
            return True
        if watched is self.edit and kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.finish_edit(keep=False)
            self.setFocus()
            return True
        if watched is self.edit and kind == QEvent.Type.FocusOut and self.editing:
            self.finish_edit()
        return False

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if event.key() == Qt.Key.Key_F2:
            self.start_edit()
            return
        if event.key() == Qt.Key.Key_Space and self.check.isEnabled():
            self.check.toggle()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        self.setFocus()
        self.focused.emit()
        super().mousePressEvent(event)

    # -- nota ------------------------------------------------------------------------------------------

    def set_choice(self, choice: str, *, emit: bool = False) -> None:
        self.choice = choice
        for kind, pill in self.pills.items():
            pill.setChecked(kind == choice)
        if emit:
            self.choice_changed.emit(choice)
            self.changed.emit()

    def set_note(self, kind: str | None, text: str = "", options: dict[str, str] | None = None) -> None:
        """`CONFLICT` con `options` (opción → texto de la píldora), `INFO`, `ERROR` o None (sin nota)."""
        self.note.setVisible(kind is not None)
        if kind is None:
            return
        self.note.setProperty("tone", kind)
        self.note.style().unpolish(self.note)
        self.note.style().polish(self.note)
        tone = {CONFLICT: self.colors.warn, ERROR: self.colors.error}.get(kind, self.colors.faint)
        self.note_icon.setPixmap(icons.pixmap("warning" if kind != INFO else "info", tone, 16))
        self.note_text.setText(text)
        self.note_text.setProperty("pro", "error" if kind == ERROR else None)
        self.note_text.style().unpolish(self.note_text)
        self.note_text.style().polish(self.note_text)
        for choice, pill in self.pills.items():
            shown = kind == CONFLICT and options is not None and choice in options
            pill.setVisible(shown)
            if shown and options is not None:
                pill.setText(options[choice])
        self.set_choice(self.choice)


class NameList(QScrollArea):
    """Las filas, una debajo de otra, con desplazamiento. Enter en un nombre pasa a editar el siguiente."""

    changed = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.box = QVBoxLayout(inner)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(0)
        self.box.addStretch(1)
        self.setWidget(inner)
        self.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        self.rows: list[NameRow] = []

    def clear(self) -> None:
        for row in self.rows:
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.rows = []

    def add(self, row: NameRow) -> NameRow:
        self.box.insertWidget(self.box.count() - 1, row)
        index = len(self.rows)
        self.rows.append(row)
        row.changed.connect(self.changed.emit)
        row.next_requested.connect(lambda i=index: self._edit_next(i))
        return row

    def _edit_next(self, index: int) -> None:
        for row in self.rows[index + 1 :]:
            if row.check.isEnabled():
                self.ensureWidgetVisible(row)
                row.start_edit()
                return
        if self.rows:
            self.rows[index].setFocus()


class TransferWindow(QDialog):
    """La ventana de los dos sentidos: el formulario (de dónde → a dónde, destino, nombres) y, al empezar, la
    línea de tiempo. `on_close` se llama al cerrarla; `on_escape`, con Esc (si no, cierra)."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.colors = style.apply(self)
        self.setWindowTitle(tr("GeoDuck"))
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 18)
        box.setSpacing(10)
        self.stack = QStackedWidget()
        box.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_form())
        self.timeline = TimelineView(self.colors)
        self.stack.addWidget(self.timeline)
        self.footer = QHBoxLayout()
        box.addLayout(self.footer)
        self.on_close: Callable[[], None] | None = None
        self.on_escape: Callable[[], None] | None = None
        self.resize(640, 560)
        self.setMinimumWidth(460)

    def _build_form(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        self.title = label("", "title")
        column.addWidget(self.title)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        column.addLayout(chips)
        self.source_chip = _chip(self.colors)
        chips.addWidget(self.source_chip)
        arrow = QLabel()
        arrow.setPixmap(icons.pixmap("chevron-right", self.colors.faint, 14))
        chips.addWidget(arrow)
        self.target_chip = _chip(self.colors)
        chips.addWidget(self.target_chip)
        chips.addStretch(1)
        destination = QHBoxLayout()
        destination.setSpacing(8)
        column.addLayout(destination)
        destination.addWidget(label(tr("Destination"), "muted"))
        self.destination = QHBoxLayout()
        self.destination.setSpacing(8)
        destination.addLayout(self.destination)
        destination.addStretch(1)
        section = label(tr("Name in the destination").upper(), "section")
        section.setContentsMargins(34, 6, 0, 0)
        column.addWidget(section)
        self.names = NameList()
        self.names.setProperty("pro", "name-list")
        column.addWidget(self.names, 1)
        self.extra = QVBoxLayout()
        self.extra.setSpacing(6)
        column.addLayout(self.extra)
        self.hint = label(
            tr("Double-click a name (or F2) to change it · Enter goes to the next one"), "faint"
        )
        self.hint.setWordWrap(True)
        column.addWidget(self.hint)
        self.empty = label("", "muted")
        self.empty.setWordWrap(True)
        self.empty.hide()
        column.insertWidget(column.indexOf(self.names), self.empty)
        return page

    def set_route(self, title: str, source: tuple[str, str], target: tuple[str, str]) -> None:
        """El título y «origen → destino»: cada lado, (icono, texto); el icono «logo» es el pato."""
        self.title.setText(title)
        for chip, (icon, text) in ((self.source_chip, source), (self.target_chip, target)):
            chip.glyph.setPixmap(_glyph(icon, self.colors))
            chip.text.setText(text)

    def set_footer(self, left: list[QWidget], right: list[QWidget]) -> None:
        set_footer(self.footer, left, right)

    def show_form(self) -> None:
        self.stack.setCurrentIndex(FORM)

    def show_progress(self) -> None:
        self.stack.setCurrentIndex(PROGRESS)

    def fit_screen(self) -> None:
        """Nunca más alto que la pantalla (los botones siempre a la vista)."""
        screen = self.screen() if hasattr(self, "screen") else QGuiApplication.primaryScreen()
        if screen is not None:
            room = screen.availableGeometry().height() - 60
            self.setMaximumHeight(max(320, room))
            if self.height() > room:
                self.resize(self.width(), room)

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if self.on_close is not None:
            self.on_close()
        super().closeEvent(event)

    def reject(self) -> None:  # Esc
        if self.on_escape is not None:
            self.on_escape()
            return
        if self.on_close is not None:
            self.on_close()
        super().reject()


def _chip(colors: Colors) -> QFrame:
    chip = QFrame()
    chip.setProperty("pro", "route-chip")
    chip.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    row = QHBoxLayout(chip)
    row.setContentsMargins(10, 4, 12, 4)
    row.setSpacing(6)
    chip.glyph = QLabel()  # type: ignore[attr-defined]
    row.addWidget(chip.glyph)  # type: ignore[attr-defined]
    chip.text = label("")  # type: ignore[attr-defined]
    row.addWidget(chip.text)  # type: ignore[attr-defined]
    return chip


def _glyph(icon: str, colors: Colors) -> Any:
    if icon == "logo":
        from qgis.PyQt.QtGui import QIcon  # noqa: PLC0415

        return QIcon(LOGO).pixmap(16, 16)
    return icons.pixmap(icon, colors.muted, 16)


def primary(text: str, slot: Callable[[], None]) -> QPushButton:
    item = button(text, "primary")
    item.setDefault(True)
    item.clicked.connect(lambda _c=False: slot())
    return item
