# SPDX-License-Identifier: GPL-2.0-or-later
"""Lista de cuadernos de la sesión (G7 · E3, GD-NB-005; ui-ux-spec §10).

En la ventana, la tarjeta «Cuadernos» (lista, «+» nuevo, renombrar, cerrar) va encima de «Bases de datos». En
el panel acoplado, un selector compacto encima del cuaderno. Las dos muestran las mismas pestañas
(`SqlPanel.editor_tabs`, sin su barra); no guardan nada en disco (GD-SQL-008).
"""

from __future__ import annotations

from collections.abc import Callable

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QShortcut,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.i18n import tr


def _menu_button(menu: QMenu) -> QToolButton:
    button = QToolButton()
    button.setText("⋯")
    button.setProperty("geoduck", "more")  # sin la flecha del menú pegada al «⋯»
    button.setAutoRaise(True)
    button.setToolTip(tr("Open, save and recovery of the notebooks"))
    button.setAccessibleName(tr("Notebook menu"))
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    button.setMenu(menu)
    return button


def _new_button(on_new: Callable[[], None]) -> QToolButton:
    button = QToolButton()
    button.setText("+")
    button.setAutoRaise(True)
    button.setToolTip(tr("New notebook (Ctrl+T)"))
    button.setAccessibleName(tr("New notebook"))
    button.clicked.connect(lambda _c=False: on_new())
    return button


class NotebookList(QFrame):
    """Tarjeta «Cuadernos» de la ventana. Doble clic o F2 renombra; Supr o el menú contextual cierra."""

    def __init__(
        self,
        tabs: QTabWidget,
        *,
        on_new: Callable[[], None],
        on_rename: Callable[[int, str], None],
        on_close: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tabs = tabs
        self._on_rename = on_rename
        self._on_close = on_close
        self._filling = False
        self.setProperty("geoduck", "card")
        self.setObjectName("geoduckNotebooksCard")
        box = QVBoxLayout(self)
        box.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)  # nunca más estrecha que su título
        box.setContentsMargins(12, 12, 12, 8)
        box.setSpacing(6)
        title = QHBoxLayout()
        label = QLabel(tr("Notebooks"))
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        title.addWidget(label, 1)
        self.new_button = _new_button(on_new)
        title.addWidget(self.new_button)
        self._title = title
        self.menu_button: QToolButton | None = None
        self._on_save: Callable[[int], object] | None = None
        box.addLayout(title)
        self.list = QListWidget()
        self.list.setObjectName("geoduckNotebookList")
        self.list.setAccessibleName(tr("Notebooks"))
        self.list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.list.currentRowChanged.connect(self._chosen)
        self.list.itemChanged.connect(self._renamed)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        close = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.list)
        close.setContext(Qt.ShortcutContext.WidgetShortcut)
        close.activated.connect(self._close_current)
        box.addWidget(self.list, 1)
        tabs.currentChanged.connect(lambda _i: self.refresh())

    def set_menu(self, menu: QMenu, *, on_save: Callable[[int], object]) -> None:
        """«⋯» con Abrir, Guardar, Guardar como y la copia de recuperación (ADR-0014)."""
        self.menu_button = _menu_button(menu)
        self._title.addWidget(self.menu_button)
        self._on_save = on_save

    def _close_current(self) -> None:
        if self.list.currentRow() >= 0:
            self._on_close(self.list.currentRow())

    def refresh(self) -> None:
        """Vuelve a mostrar los cuadernos (nombres y el activo) desde las pestañas."""
        self._filling = True
        try:
            self.list.clear()
            for i in range(self._tabs.count()):
                item = QListWidgetItem(self._tabs.tabText(i))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(tr("Double-click or F2 to rename; Delete to close"))
                self.list.addItem(item)
            self.list.setCurrentRow(self._tabs.currentIndex())
        finally:
            self._filling = False

    def names(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def _chosen(self, row: int) -> None:
        if not self._filling and 0 <= row < self._tabs.count():
            self._tabs.setCurrentIndex(row)

    def _renamed(self, item: QListWidgetItem) -> None:
        if self._filling:
            return
        row = self.list.row(item)
        name = item.text().strip()
        if name and name != self._tabs.tabText(row):
            self._on_rename(row, name)
        else:
            self.refresh()  # vacío o igual: vuelve el nombre de antes

    def _menu(self, pos: object) -> None:
        item = self.list.itemAt(pos)  # type: ignore[arg-type]
        if item is None:
            return
        row = self.list.row(item)
        menu = QMenu(self.list)
        menu.addAction(tr("Rename"), lambda: self.list.editItem(item))
        if self._on_save is not None:
            on_save = self._on_save
            menu.addAction(tr("Save notebook"), lambda: on_save(row))
        menu.addAction(tr("Close"), lambda: self._on_close(row))
        menu.exec(self.list.viewport().mapToGlobal(pos))  # type: ignore[arg-type]


class NotebookSelector(QWidget):
    """Selector del panel acoplado: el cuaderno activo y «+», en una sola fila (panel minimalista)."""

    def __init__(
        self, tabs: QTabWidget, *, on_new: Callable[[], None], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._tabs = tabs
        self._filling = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.combo = QComboBox()
        self.combo.setObjectName("geoduckNotebookSelector")
        self.combo.setAccessibleName(tr("Notebook"))
        self.combo.setToolTip(tr("Notebook"))
        self.combo.currentIndexChanged.connect(self._chosen)
        row.addWidget(self.combo, 1)
        self.new_button = _new_button(on_new)
        row.addWidget(self.new_button)
        self._row = row
        self.menu_button: QToolButton | None = None
        tabs.currentChanged.connect(lambda _i: self.refresh())

    def set_menu(self, menu: QMenu) -> None:
        self.menu_button = _menu_button(menu)
        self._row.addWidget(self.menu_button)

    def refresh(self) -> None:
        self._filling = True
        try:
            self.combo.clear()
            for i in range(self._tabs.count()):
                self.combo.addItem(self._tabs.tabText(i))
            self.combo.setCurrentIndex(self._tabs.currentIndex())
        finally:
            self._filling = False

    def _chosen(self, index: int) -> None:
        if not self._filling and 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)
