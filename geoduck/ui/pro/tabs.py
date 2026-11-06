# SPDX-License-Identifier: GPL-2.0-or-later
"""Pestañas de tabla y de consulta de Workspace Pro (workspace-pro-spec §3; GD-WSP-002).

`TabArea` tiene la barra de pestañas (para la cabecera del workspace) y las páginas. Abrir un lugar que ya
está abierto lo trae al frente, nunca lo duplica. Las pestañas se reordenan arrastrando, se cierran con ×,
clic central o Ctrl+W, y «+» abre una consulta nueva. La página de cada lugar la crea `page_factory`: en E2,
una página de presentación; la de tabla llega en E3 y la de consulta en E4.
"""

from __future__ import annotations

from collections.abc import Callable

from qgis.PyQt.QtCore import QEvent, QObject, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QPlainTextEdit, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons
from geoduck.ui.pro.places import QUERY, Place, icon_name
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import Colors
from geoduck.ui.pro.widgets import label


class PlacePage(QWidget):
    """Página de presentación de una consulta (E2, E3): icono, nombre y, si llega de «Ver SQL», su texto. La
    pestaña de consulta llega en E4."""

    def __init__(self, place: Place, colors: Colors) -> None:
        super().__init__()
        self.place = place
        box = QVBoxLayout(self)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(6)
        glyph = label("")
        glyph.setPixmap(icons.pixmap(icon_name(place), colors.faint, 32))
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name = label(place.name, "title")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        where = label(place.path or place.location, "muted")
        where.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for widget in (glyph, name, where):
            box.addWidget(widget)
        self.sql = QPlainTextEdit()
        self.sql.setProperty("pro", "code")
        self.sql.setReadOnly(True)
        self.sql.setMinimumSize(520, 160)
        self.sql.hide()
        box.addWidget(self.sql, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_sql(self, text: str) -> None:
        self.sql.setPlainText(text)
        self.sql.setVisible(bool(text))


class TabArea(QObject):
    """Las pestañas abiertas: `bar` (barra) y `stack` (páginas), siempre en el mismo orden."""

    #: Cambió el conjunto, el orden o la pestaña activa (para recordarlas).
    changed = pyqtSignal()

    def __init__(
        self,
        colors: Colors,
        page_factory: Callable[[Place], QWidget] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)  # con padre: Qt la borra en el hilo de la interfaz, nunca el recolector
        self.colors = colors
        self.page_factory = page_factory or (lambda place: PlacePage(place, colors))
        self._queries = 0
        self.bar = QTabBar()
        self.bar.setProperty("pro", "tabs")
        self.bar.setFont(ui_font())
        self.bar.setMovable(True)
        self.bar.setTabsClosable(True)
        self.bar.setExpanding(False)
        self.bar.setDocumentMode(True)
        self.bar.setDrawBase(False)
        self.bar.setUsesScrollButtons(True)
        self.bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.bar.setAccessibleName(tr("Open tabs"))
        self.bar.tabCloseRequested.connect(self.close_tab)
        self.bar.currentChanged.connect(self._show)
        self.bar.tabMoved.connect(lambda _a, _b: self.changed.emit())
        self.bar.installEventFilter(self)
        self.stack = QStackedWidget()

    # -- consultas ------------------------------------------------------------------------------------

    def __len__(self) -> int:
        return self.bar.count()

    def page(self, index: int) -> QWidget:
        return self.bar.tabData(index)  # type: ignore[no-any-return]

    def places(self) -> list[Place]:
        return [self.page(i).place for i in range(self.bar.count())]  # type: ignore[attr-defined]

    @property
    def current(self) -> Place | None:
        index = self.bar.currentIndex()
        return self.page(index).place if index >= 0 else None  # type: ignore[attr-defined]

    def index_of(self, place: Place) -> int:
        return next((i for i, p in enumerate(self.places()) if p.key == place.key), -1)

    # -- acciones -------------------------------------------------------------------------------------

    def open_place(self, place: Place, *, activate: bool = True) -> QWidget:
        """Abre `place` en una pestaña, o trae al frente la que ya lo tiene."""
        index = self.index_of(place)
        if index < 0:
            page = self.page_factory(place)
            self.stack.addWidget(page)
            self.bar.blockSignals(True)  # la primera pestaña pasa a ser la actual antes de tener su página
            index = self.bar.addTab(icons.icon(icon_name(place), self.colors.muted, 14), place.name)
            self.bar.setTabData(index, page)
            self.bar.blockSignals(False)
            if self.bar.count() == 1:
                self.stack.setCurrentWidget(page)
            self.bar.setTabToolTip(index, place.path or f"{place.location} · {place.name}")
            close = self.bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if close is not None:
                close.setToolTip(tr("Close tab (Ctrl+W)"))
                close.setAccessibleName(tr("Close {}").format(place.name))
            self.changed.emit()
        if activate:
            self.bar.setCurrentIndex(index)
        return self.page(index)

    def new_query(self, sql: str = "") -> QWidget:
        """«+»: una consulta nueva, «Consulta N» (con `sql`, el de «Ver SQL»)."""
        names = {p.name for p in self.places() if p.kind == QUERY}
        while True:
            self._queries += 1
            name = tr("Query {}").format(self._queries)
            if name not in names:
                break
        page = self.open_place(Place(QUERY, name))
        if sql and hasattr(page, "set_sql"):
            page.set_sql(sql)
        return page

    def close_tab(self, index: int) -> None:
        if not 0 <= index < self.bar.count():
            return
        page = self.page(index)
        if hasattr(page, "close_page"):
            page.close_page()  # deja de escuchar a la sesión antes de borrarse
        self.bar.removeTab(index)
        self.stack.removeWidget(page)
        page.deleteLater()
        self.changed.emit()

    def close_current(self) -> None:
        self.close_tab(self.bar.currentIndex())

    def _show(self, index: int) -> None:
        if index >= 0:
            self.stack.setCurrentWidget(self.page(index))
        self.changed.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - API de Qt
        if (
            watched is getattr(self, "bar", None)  # al destruirse, Qt aún puede llamar al filtro
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.MiddleButton  # type: ignore[attr-defined]
        ):
            self.close_tab(self.bar.tabAt(event.pos()))  # type: ignore[attr-defined]
            return True
        return False
