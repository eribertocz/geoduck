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
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import QLineEdit, QPlainTextEdit, QStackedWidget, QTabBar, QVBoxLayout, QWidget

from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons
from geoduck.ui.pro.places import QUERY, Place, icon_name
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import BEAK, Colors
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
    #: Doble clic en el nombre y Enter (#143, punto 6): (página, nombre nuevo). Quien escucha renombra.
    rename_requested = pyqtSignal(object, str)

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
        #: Antes de cerrar una pestaña (p. ej. preguntar si guardar una consulta): `False` la deja abierta.
        self.can_close: Callable[[QWidget], bool] = lambda _page: True
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
        # Clic derecho en una pestaña: su archivo; el menú, del área de trabajo
        self.bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bar.tabBarDoubleClicked.connect(self.start_rename)
        self.stack = QStackedWidget()
        self.rename_editor: QLineEdit | None = None
        self._modified: set[int] = set()  # id() de las páginas con cambios sin guardar

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
        if not self.can_close(page):
            return
        if hasattr(page, "close_page"):
            page.close_page()  # deja de escuchar a la sesión antes de borrarse
        self._modified.discard(id(page))
        self.cancel_rename()
        self.bar.removeTab(index)
        self.stack.removeWidget(page)
        page.deleteLater()
        self.changed.emit()

    def retitle(self, page: QWidget, *, modified: bool = False) -> None:
        """El nombre de la pestaña de `page` (tras guardar o renombrar) y, con cambios sin guardar, el ●
        ámbar en lugar de su icono (#143, punto 4)."""
        index = self.index_of_page(page)
        if index < 0:
            return
        place: Place = page.place  # type: ignore[attr-defined]
        self.bar.setTabText(index, place.name)
        if modified:
            self._modified.add(id(page))
            self.bar.setTabIcon(index, _dot(BEAK))
        else:
            self._modified.discard(id(page))
            self.bar.setTabIcon(index, icons.icon(icon_name(place), self.colors.muted, 14))
        tip = place.path or f"{place.location} · {place.name}"
        self.bar.setTabToolTip(index, tip + ("\n● " + tr("Unsaved changes") if modified else ""))
        self.changed.emit()

    def index_of_page(self, page: QWidget) -> int:
        return next((i for i in range(self.bar.count()) if self.page(i) is page), -1)

    def is_modified(self, index: int) -> bool:
        """La pestaña `index` tiene el ● de «sin guardar»."""
        return 0 <= index < self.bar.count() and id(self.page(index)) in self._modified

    def start_rename(self, index: int) -> None:
        """Doble clic en el nombre (#143, punto 6): un campo encima de la pestaña; Enter renombra, Esc o
        salir del campo lo deja como estaba. Solo las consultas se renombran."""
        if not 0 <= index < self.bar.count() or not hasattr(self.page(index), "rename"):
            return
        self.cancel_rename()
        page = self.page(index)
        editor = QLineEdit(page.place.name, self.bar)  # type: ignore[attr-defined]
        editor.setAccessibleName(tr("Tab name"))
        editor.setGeometry(self.bar.tabRect(index).adjusted(4, 4, -4, -4))
        editor.selectAll()
        editor.installEventFilter(self)
        editor.returnPressed.connect(lambda: self._finish_rename(page, editor))
        editor.show()
        editor.setFocus()
        self.rename_editor = editor

    def _finish_rename(self, page: QWidget, editor: QLineEdit) -> None:
        name = editor.text().strip()
        self.cancel_rename()
        if name and name != page.place.name:  # type: ignore[attr-defined]
            self.rename_requested.emit(page, name)

    def cancel_rename(self) -> None:
        editor, self.rename_editor = self.rename_editor, None
        if editor is not None:
            editor.removeEventFilter(self)
            editor.hide()
            editor.deleteLater()

    def close_all(self) -> None:
        """«Cerrar todas las pestañas»: de la última a la primera; una consulta con
        cambios pregunta antes (`can_close`) y, si el usuario la deja abierta, se detiene ahí."""
        for index in range(self.bar.count() - 1, -1, -1):
            count = self.bar.count()
            self.close_tab(index)
            if self.bar.count() == count:
                return

    def close_current(self) -> None:
        self.close_tab(self.bar.currentIndex())

    def _show(self, index: int) -> None:
        if index >= 0:
            self.stack.setCurrentWidget(self.page(index))
        self.changed.emit()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - API de Qt
        if watched is self.rename_editor:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:  # type: ignore[attr-defined]
                self.cancel_rename()
                return True
            if event.type() == QEvent.Type.FocusOut:
                self.cancel_rename()
            return False
        if (
            watched is getattr(self, "bar", None)  # al destruirse, Qt aún puede llamar al filtro
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.MiddleButton  # type: ignore[attr-defined]
        ):
            self.close_tab(self.bar.tabAt(event.pos()))  # type: ignore[attr-defined]
            return True
        return False


def _dot(color: str, size: int = 14) -> QIcon:
    """El ● de «sin guardar» (ámbar, como el pico del pato)."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(size - 7, size - 7, 14, 14)
    painter.end()
    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)
