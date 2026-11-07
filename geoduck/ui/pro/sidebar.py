# SPDX-License-Identifier: GPL-2.0-or-later
"""Barra lateral de Workspace Pro (workspace-pro-spec §3, §8; GD-WSP-002, 007).

De arriba abajo: la sesión (punto de estado, «DuckDB 2.0.0» y «Lista · en memoria»), el filtro y «+» (abrir
o crear base, añadir capas de QGIS), **★ Favoritos** y **Bases** (bases, esquemas, tablas,
vistas y temporales), y al pie «Diagnóstico», «Acerca de» y la versión. Doble clic o Intro abre una tabla o
vista; el menú contextual marca favoritos y cierra bases. No ejecuta nada: emite señales que atiende el
workspace.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.PyQt.QtCore import QMimeData, QModelIndex, QObject, QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from geoduck import __version__
from geoduck.domain.catalog import AccessMode, CatalogSnapshot, ObjectKind, catalog_key
from geoduck.ui.i18n import tr
from geoduck.ui.pro import fuzzy, icons
from geoduck.ui.pro.drag import LAYERS_MIME, PLACES_MIME, layer_ids, places_mime
from geoduck.ui.pro.places import Place, Places, icon_name, missing_reason, place_of
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import ElidedLabel, SearchField, StatusDot, icon_button, label

#: Qué es cada fila del árbol (rol `ROLE`): una sección, una base, un esquema, un grupo o un lugar.
ROLE = Qt.ItemDataRole.UserRole
#: Texto secundario de una fila, en gris a la derecha («db», «solo lectura»).
META = Qt.ItemDataRole.UserRole + 1
#: (base, esquema) donde se envían las capas soltadas sobre esta fila (solo bases y esquemas escribibles).
TARGET = Qt.ItemDataRole.UserRole + 2
SECTION, DATABASE, SCHEMA, GROUP, PLACE = "section", "database", "schema", "group", "place"


def _access_text(access: AccessMode, in_memory: bool) -> str:
    if in_memory:
        return tr("in memory")
    return tr("read only") if access is AccessMode.READ_ONLY else tr("read and write")


class _NavDelegate(QStyledItemDelegate):
    """Fila del árbol con su texto secundario (`META`) en gris a la derecha; el nombre se recorta antes."""

    def __init__(self, colors: Colors, parent: QObject) -> None:
        super().__init__(parent)
        self.colors = colors
        self.small = ui_font(METRICS.font_small)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        self._paint(painter, option, index)
        tree = option.widget  # type: ignore[attr-defined]
        target = getattr(tree, "drop_item", None)
        if target is not None and tree.itemFromIndex(index) is target:  # E5: la base donde se soltarán
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(self.colors.accent))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.drawRoundedRect(QRectF(option.rect).adjusted(1, 1, -1, -1), 5, 5)  # type: ignore[attr-defined]
            painter.restore()

    def _paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        meta = index.data(META)
        if not meta:
            super().paint(painter, option, index)
            return
        rect = option.rect  # type: ignore[attr-defined]
        width = QFontMetrics(self.small).horizontalAdvance(meta) + 10
        full = QStyleOptionViewItem(option)
        self.initStyleOption(full, index)
        full.text = ""
        full.icon = QIcon()
        style = full.widget.style() if full.widget is not None else None
        if style is not None:  # el fondo (hover, elegida) en toda la fila
            style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, full, painter, full.widget)
        narrow = QStyleOptionViewItem(option)
        narrow.rect = QRect(rect.x(), rect.y(), max(0, rect.width() - width), rect.height())
        super().paint(painter, narrow, index)
        painter.save()
        painter.setFont(self.small)
        painter.setPen(QColor(self.colors.faint))
        painter.drawText(
            QRect(rect.right() - width, rect.y(), width - 4, rect.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
            meta,
        )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(hint.height(), 28))


class NavTree(QTreeWidget):
    """El árbol de la barra lateral, con arrastre en los dos sentidos (E5, workspace-pro-spec §9):
    capas de QGIS soltadas sobre una base (resaltada con un borde) y tablas arrastradas hacia QGIS."""

    #: (ids de capas, (base, esquema) o None = la base actual)
    layers_dropped = pyqtSignal(list, object)
    #: Texto para el pie mientras se arrastra («Suelta para enviar 3 capas a «db»»); "" al salir.
    drop_hint = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.drop_item: QTreeWidgetItem | None = None
        self.current_target: Callable[[], tuple[str, str] | None] = lambda: None
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    # -- hacia QGIS -----------------------------------------------------------------------------------

    def mimeTypes(self) -> list[str]:  # noqa: N802 - API de Qt
        return [PLACES_MIME]

    def mimeData(self, items: Any) -> QMimeData:  # noqa: N802 - API de Qt
        places = []
        for item in items:
            data = item.data(0, ROLE)
            if data and data[0] == PLACE and not data[1].is_query:
                places.append(data[1])
        return places_mime(places)

    def startDrag(self, actions: Any) -> None:  # noqa: N802 - API de Qt
        if any((d := i.data(0, ROLE)) and d[0] == PLACE and not d[1].is_query for i in self.selectedItems()):
            super().startDrag(Qt.DropAction.CopyAction)

    # -- desde QGIS -----------------------------------------------------------------------------------

    def target_item(self, pos: QPoint) -> QTreeWidgetItem | None:
        """La base (o el esquema) bajo `pos` donde se puede escribir; una tabla cuenta como su base."""
        item = self.itemAt(pos)
        while item is not None:
            if item.data(0, TARGET):
                return item
            item = item.parent()
        return None

    def _target(self, pos: QPoint) -> tuple[QTreeWidgetItem | None, tuple[str, str] | None]:
        item = self.target_item(pos)
        if item is not None:
            return item, tuple(item.data(0, TARGET))
        return None, self.current_target()

    def _set_drop(self, item: QTreeWidgetItem | None) -> None:
        if item is not self.drop_item:
            self.drop_item = item
            self.viewport().update()

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if event.mimeData().hasFormat(LAYERS_MIME) and self.isEnabled():
            event.acceptProposedAction()
            self.dragMoveEvent(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if not event.mimeData().hasFormat(LAYERS_MIME):
            event.ignore()
            return
        item, target = self._target(_pos(event))
        self._set_drop(item)
        count = len(layer_ids(event.mimeData()))
        where = target[0] if target else tr("the current database")
        self.drop_hint.emit(tr("Drop to send {0} layer(s) to «{1}»").format(count, where))
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        self._set_drop(None)
        self.drop_hint.emit("")
        super().dragLeaveEvent(event)

    def dropEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        ids = layer_ids(event.mimeData())
        _item, target = self._target(_pos(event))
        self._set_drop(None)
        self.drop_hint.emit("")
        if not ids:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.layers_dropped.emit(ids, target)


def _pos(event: Any) -> QPoint:
    """Posición de un evento de arrastre en Qt5 (`pos`) y Qt6 (`position`)."""
    return event.position().toPoint() if hasattr(event, "position") else event.pos()


class Sidebar(QFrame):
    """La barra lateral. `render(catalog)` la rehace desde el catálogo; `places` da recientes y favoritos."""

    open_requested = pyqtSignal(object)  # Place
    #: El menú «Cargar en QGIS ▸» para unas tablas (lo pone el workspace: Copia / Conectada / Más opciones…).
    make_load_menu: Callable[[QWidget, list[Place]], QMenu] | None = None
    favorite_requested = pyqtSignal(object)  # Place
    detach_requested = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    close_session_requested = pyqtSignal()
    open_database_requested = pyqtSignal()
    create_database_requested = pyqtSignal()
    send_layers_requested = pyqtSignal()
    diagnostics_requested = pyqtSignal()
    about_requested = pyqtSignal()
    start_requested = pyqtSignal()

    def __init__(self, colors: Colors, places: Places) -> None:
        super().__init__()
        self.colors = colors
        self.places = places
        self.catalog: CatalogSnapshot | None = None
        self._collapsed: set[tuple[str, ...]] = set()
        self._opened: set[tuple[str, ...]] = set()
        self._quiet = False
        self.setProperty("pro", "side")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(METRICS.sidebar)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        #: La sesión arriba («DuckDB 2.0.0», «Lista · en memoria», «⋯»); en el panel la lleva su cabecera.
        self.session_head = self._build_header()
        box.addWidget(self.session_head)
        box.addLayout(self._build_filter())
        self.tree = self._build_tree()
        trees = QVBoxLayout()
        trees.setContentsMargins(8, 2, 8, 4)
        trees.addWidget(self.tree)
        box.addLayout(trees, 1)
        box.addWidget(self._build_footer())
        self.render(None)

    # -- piezas ---------------------------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        head = QFrame()
        head.setProperty("pro", "rule-bottom")
        head.setFixedHeight(METRICS.bar)
        row = QHBoxLayout(head)
        row.setContentsMargins(14, 0, 8, 0)
        row.setSpacing(9)
        # el logo dice el estado de la sesión, y un clic abre su menú (marca, 2026-11-07)
        self.dot = StatusDot(self.colors, logo=True)
        self.dot.clicked.connect(lambda: self._popup(self.session_menu, self.dot))
        row.addWidget(self.dot)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = label("DuckDB")
        self.title.setFont(ui_font(bold=True))
        self.status = ElidedLabel(tr("Not started"), "muted")
        self.status.setFont(ui_font(METRICS.font_small))
        titles.addWidget(self.title)
        titles.addWidget(self.status)
        row.addLayout(titles, 1)
        self.session_button = icon_button("more", tr("Session"), self.colors)
        # El menú de la sesión: solo lo que aplica (propietario, 2026-11-07): sin sesión, «Iniciar DuckDB»;
        # con sesión, «Cerrar sesión»; nunca un «Iniciar» en gris.
        self.session_menu = QMenu(self)
        self.start_action = self.session_menu.addAction(tr("Start DuckDB"))
        self.start_action.triggered.connect(self.start_requested.emit)
        self.session_open_db = self.session_menu.addAction(tr("Open database…"))
        self.session_open_db.triggered.connect(self.open_database_requested.emit)
        self.session_create_db = self.session_menu.addAction(tr("Create database…"))
        self.session_create_db.triggered.connect(self.create_database_requested.emit)
        self.refresh_action = self.session_menu.addAction(tr("Refresh"))
        self.refresh_action.triggered.connect(self.refresh_requested.emit)
        self.session_menu.addSeparator()
        self.close_action = self.session_menu.addAction(tr("Close session"))
        self.close_action.triggered.connect(self.close_session_requested.emit)
        self.session_menu.addSeparator()
        self.session_menu.addAction(tr("Environment diagnostics"), self.diagnostics_requested.emit)
        self.session_menu.addAction(tr("About GeoDuck"), self.about_requested.emit)
        self.session_button.clicked.connect(lambda: self._popup(self.session_menu, self.session_button))
        row.addWidget(self.session_button)
        return head

    def _build_filter(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(12, 10, 8, 6)
        row.setSpacing(4)
        self.search = SearchField(tr("Filter tables…"), self.colors, accessible_name=tr("Filter tables"))
        self.search.edit.textChanged.connect(self._apply_filter)
        self.search.edit.returnPressed.connect(self._open_first_match)
        row.addWidget(self.search, 1)
        self.add_button = icon_button(
            "plus", tr("Open or create a database, or send QGIS layers"), self.colors
        )
        self.add_menu = QMenu(self)
        self.open_db_action = self.add_menu.addAction(tr("Open database…"))
        self.open_db_action.triggered.connect(self.open_database_requested.emit)
        self.create_db_action = self.add_menu.addAction(tr("Create database…"))
        self.create_db_action.triggered.connect(self.create_database_requested.emit)
        self.add_menu.addSeparator()
        self.send_action = self.add_menu.addAction(tr("Add QGIS layers to DuckDB…"))
        self.send_action.triggered.connect(self.send_layers_requested.emit)
        self.add_button.clicked.connect(lambda: self._popup(self.add_menu, self.add_button))
        row.addWidget(self.add_button)
        return row

    def _build_tree(self) -> NavTree:
        tree = NavTree()
        tree.current_target = self.current_target
        tree.setProperty("pro", "nav")
        tree.setColumnCount(1)
        tree.setHeaderHidden(True)
        self.delegate = _NavDelegate(self.colors, tree)  # la vista no se queda con él: se guarda aquí
        tree.setItemDelegate(self.delegate)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tree.setIndentation(14)
        tree.setUniformRowHeights(True)
        tree.setExpandsOnDoubleClick(False)
        # varias tablas a la vez (Ctrl o Mayús) para cargarlas juntas en QGIS (propietario, 2026-11-06)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setAccessibleName(tr("Databases and favorites"))
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._context_menu)
        tree.itemActivated.connect(self._activated)
        tree.itemExpanded.connect(lambda item: self._remember_expanded(item, True))
        tree.itemCollapsed.connect(lambda item: self._remember_expanded(item, False))
        return tree

    def _build_footer(self) -> QWidget:
        foot = QFrame()
        foot.setProperty("pro", "rule-top")
        row = QHBoxLayout(foot)
        row.setContentsMargins(8, 6, 14, 6)
        row.setSpacing(0)
        self.diagnostics_button = self._link(tr("Diagnostics"), tr("Checks Python, QGIS, DuckDB and PyArrow"))
        self.diagnostics_button.clicked.connect(self.diagnostics_requested.emit)
        self.about_button = self._link(tr("About"), tr("Version, license and components"))
        self.about_button.clicked.connect(self.about_requested.emit)
        row.addWidget(self.diagnostics_button)
        row.addWidget(self.about_button)
        row.addStretch(1)
        row.addWidget(label(f"v{__version__}", "faint"))
        return foot

    def _link(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("pro", "ghost")
        button.setToolTip(tooltip)
        button.setAccessibleName(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _popup(menu: QMenu, under: QWidget) -> None:
        menu.popup(under.mapToGlobal(QPoint(0, under.height())))

    # -- estado ---------------------------------------------------------------------------------------

    def set_session(self, dot: str, engine: str, text: str, *, ready: bool) -> None:
        """Punto de estado, motor («DuckDB 2.0.0») y estado («Lista · en memoria»)."""
        self.dot.set_state(dot)
        self.title.setText(engine)
        self.status.setText(text)
        self.refresh_action.setEnabled(ready)
        self.refresh_action.setVisible(dot != "off")
        self.close_action.setVisible(dot != "off")
        self.start_action.setVisible(dot == "off")
        for action in (self.session_open_db, self.session_create_db):
            action.setEnabled(ready or dot == "off")
        for action in (self.open_db_action, self.create_db_action):
            action.setEnabled(ready or dot == "off")
        self.send_action.setEnabled(ready)
        # Sin DuckDB, todo en gris salvo iniciar, abrir o crear una base, Diagnóstico y Acerca de
        # (propietario, 2026-11-06)
        started = dot != "off"
        for widget in (self.search, self.tree):
            widget.setEnabled(started)

    def current_target(self) -> tuple[str, str] | None:
        """La base actual para capas soltadas fuera de una base: la de la fila elegida, si es escribible."""
        item = self.tree.currentItem()
        while item is not None:
            if item.data(0, TARGET):
                return tuple(item.data(0, TARGET))
            item = item.parent()
        return None

    def render(self, catalog: CatalogSnapshot | None) -> None:
        """Rehace el árbol (favoritos y bases; sin «Recientes», 2026-11-06), con lo plegado y el filtro."""
        self.catalog = catalog
        tree = self.tree
        tree.setUpdatesEnabled(False)
        tree.clear()
        self._add_places("★ " + tr("Favorites"), "favorites", self.places.favorites)
        self._section(tr("Databases"), "databases")
        if catalog is None:
            hint = QTreeWidgetItem([tr("Start DuckDB to see your databases")])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setForeground(0, QColor(self.colors.faint))
            tree.addTopLevelItem(hint)
        else:
            for db in catalog.databases:
                writable = db.in_memory or db.access is not AccessMode.READ_ONLY
                self._add_database(catalog, db.name, _access_text(db.access, db.in_memory), writable)
            if catalog.temporaries:
                temp = self._node(None, tr("Temporary"), (GROUP, "temp"), GROUP, bold=True)
                for obj in sorted(catalog.temporaries, key=lambda o: o.name.casefold()):
                    self._add_object(temp, place_of(obj.database, obj.schema, obj.name, obj.kind))
        self._apply_filter(self.search.edit.text())
        tree.setUpdatesEnabled(True)

    def _section(self, text: str, key: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text.upper()])
        item.setData(0, ROLE, (SECTION, key))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = ui_font(METRICS.font_tiny, bold=True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        item.setFont(0, font)
        item.setForeground(0, QColor(self.colors.muted))
        self.tree.addTopLevelItem(item)
        return item

    def _add_places(self, title: str, key: str, places: list[Place]) -> None:
        if not places:
            return
        self._section(title, key)
        for place in places:
            reason = missing_reason(place, self.catalog)
            item = QTreeWidgetItem([place.name])
            item.setData(0, META, place.location)
            item.setData(0, ROLE, (PLACE, place))
            item.setIcon(
                0, icons.icon(icon_name(place), self.colors.faint if reason else self.colors.muted, 14)
            )
            if reason:
                item.setForeground(0, QColor(self.colors.null))
                item.setToolTip(0, f"{place.name}: {reason}")
            else:
                item.setToolTip(0, f"{place.location} · {place.name}" if not place.is_query else place.path)
            self.tree.addTopLevelItem(item)

    def _node(
        self,
        parent: QTreeWidgetItem | None,
        text: str,
        key: tuple[str, ...],
        kind: str,
        *,
        bold: bool = False,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setData(0, ROLE, (kind, key))
        if bold:
            item.setFont(0, ui_font(bold=True))
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        self._quiet = True
        item.setExpanded(self._is_open(key))
        self._quiet = False
        return item

    def _add_database(self, catalog: CatalogSnapshot, name: str, access: str, writable: bool = True) -> None:
        db = self._node(None, name, (DATABASE, catalog_key(name)), DATABASE, bold=True)
        db.setIcon(0, icons.icon("database", self.colors.muted, 14))
        db.setData(0, META, access)
        db.setToolTip(0, f"{name} · {access}")
        schemas = catalog.schemas_of(name)
        if writable and schemas:  # capas soltadas sobre la base: a `main` o a su único esquema
            db.setData(0, TARGET, (name, "main" if "main" in schemas else schemas[0]))
        for schema in schemas:
            parent = db
            if len(schemas) > 1 or schema != "main":
                parent = self._node(db, schema, (SCHEMA, catalog_key(name), schema), SCHEMA)
                if writable:
                    parent.setData(0, TARGET, (name, schema))
            objects = sorted(catalog.objects_in(name, schema), key=lambda o: o.name.casefold())
            for obj in objects:
                if obj.kind is ObjectKind.TABLE:
                    self._add_object(parent, place_of(obj.database, obj.schema, obj.name, obj.kind))
            views = [o for o in objects if o.kind is ObjectKind.VIEW]
            if views:
                group = self._node(
                    parent,
                    tr("Views") + f" ({len(views)})",
                    (GROUP, "views", catalog_key(name), schema),
                    GROUP,
                )
                for obj in views:
                    self._add_object(group, place_of(obj.database, obj.schema, obj.name, obj.kind))

    def _add_object(self, parent: QTreeWidgetItem, place: Place) -> None:
        item = QTreeWidgetItem([place.name])
        item.setData(0, ROLE, (PLACE, place))
        item.setIcon(0, icons.icon(icon_name(place), self.colors.muted, 14))
        item.setToolTip(0, f"{place.location} · {place.name}")
        parent.addChild(item)

    def _is_open(self, key: tuple[str, ...]) -> bool:
        """Las bases y esquemas, abiertos salvo que el usuario los pliegue; los grupos de vistas, al revés."""
        if key[:2] == (GROUP, "views"):
            return key in self._opened
        return key not in self._collapsed

    def _remember_expanded(self, item: QTreeWidgetItem, expanded: bool) -> None:
        data = item.data(0, ROLE)
        if self._quiet or not data or data[0] not in (DATABASE, SCHEMA, GROUP):
            return
        key = data[1]
        if key[:2] == (GROUP, "views"):
            (self._opened.add if expanded else self._opened.discard)(key)
        else:
            (self._collapsed.discard if expanded else self._collapsed.add)(key)

    # -- filtro y apertura ----------------------------------------------------------------------------

    def _apply_filter(self, text: str) -> None:
        """Con texto, solo las tablas y vistas de «Bases» que coinciden (letras en orden, sin acentos)."""
        query = fuzzy.fold(text.strip())
        self._quiet = True

        def visit(item: QTreeWidgetItem) -> bool:
            data = item.data(0, ROLE)
            if not data:
                return True
            if data[0] == PLACE:
                visible = not query or fuzzy.score(query, fuzzy.fold(item.text(0))) is not None
                item.setHidden(not visible)
                return visible
            any_child = False
            for index in range(item.childCount()):
                any_child = visit(item.child(index)) or any_child
            item.setHidden(bool(query) and not any_child)
            item.setExpanded(any_child if query else self._is_open(data[1]))
            return any_child

        section = None
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            data = item.data(0, ROLE)
            if data and data[0] == SECTION:
                section = data[1]
                item.setHidden(bool(query) and section != "databases")
            elif section != "databases":
                item.setHidden(bool(query))
            else:
                visit(item)
        self._quiet = False

    def visible_places(self) -> list[Place]:
        """Los lugares visibles con el filtro actual, en orden (para Intro y para las pruebas)."""
        found: list[Place] = []

        def visit(item: QTreeWidgetItem) -> None:
            if item.isHidden():
                return
            data = item.data(0, ROLE)
            if data and data[0] == PLACE:
                found.append(data[1])
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))
        return found

    def _open_first_match(self) -> None:
        if not self.search.edit.text().strip():
            return
        matches = self.visible_places()
        if matches:
            self.open_requested.emit(matches[0])

    def _activated(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, ROLE)
        if not data:
            return
        if data[0] == PLACE:
            self.open_requested.emit(data[1])
        elif data[0] in (DATABASE, SCHEMA, GROUP):
            item.setExpanded(not item.isExpanded())

    def selected_places(self) -> list[Place]:
        """Las tablas y vistas elegidas en el árbol (las consultas no se cargan desde aquí)."""
        places: list[Place] = []
        for item in self.tree.selectedItems():
            data = item.data(0, ROLE)
            if data and data[0] == PLACE and not data[1].is_query:
                places.append(data[1])
        return places

    def _context_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        data = item.data(0, ROLE) if item is not None else None
        if not data:
            return
        menu = QMenu(self)
        if data[0] == PLACE:
            place: Place = data[1]
            menu.addAction(tr("Open"), lambda: self.open_requested.emit(place))
            chosen = self.selected_places() if item.isSelected() else []
            tables = chosen or ([place] if not place.is_query else [])
            if tables and self.make_load_menu is not None:
                load = self.make_load_menu(menu, tables)
                load.setTitle(
                    tr("Load in QGIS")
                    if len(tables) == 1
                    else tr("Load {} tables in QGIS").format(len(tables))
                )
                load.setIcon(icons.icon("layers", self.colors.muted, 14))
                menu.addMenu(load)
            if place.remembered:
                text = (
                    tr("Remove from favorites") if self.places.is_favorite(place) else tr("Add to favorites")
                )
                menu.addAction(text, lambda: self.favorite_requested.emit(place))
        elif data[0] == DATABASE and self.catalog is not None:
            db = self.catalog.get(item.text(0))
            if db is None or self.catalog.is_root(db.name):
                return
            menu.addAction(tr("Close database"), lambda: self.detach_requested.emit(db.name))
        else:
            return
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(self.tree.viewport().mapToGlobal(pos))
