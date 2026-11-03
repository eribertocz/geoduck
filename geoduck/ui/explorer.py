# SPDX-License-Identifier: GPL-2.0-or-later
"""Explorador del catálogo de la sesión: bases, esquemas, tablas y vistas (GD-CAT-001, AT-CAT-001).

Solo muestra la instantánea que publica la capa de aplicación, leída de DuckDB después de cada operación
con éxito; nunca la modifica por su cuenta ni la anticipa. G5 (ui-ux-spec §8, AT-UX-006): objetos agrupados
en «Tablas (n)» y «Vistas (n)» por esquema, temporales en «Tablas temporales (n)» / «Vistas temporales (n)»
bajo la base raíz, acceso de cada base y búsqueda sobre esa instantánea (nunca lee filas ni consulta DuckDB).
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from geoduck.domain.catalog import AccessMode, AttachedDatabase, CatalogObject, CatalogSnapshot, ObjectKind
from geoduck.domain.sql_text import quote_identifier
from geoduck.ui import theme
from geoduck.ui.i18n import tr

_DATABASE_ROLE = int(Qt.ItemDataRole.UserRole)
_OBJECT_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 2
_NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 3
_GROUP_ROLE = int(Qt.ItemDataRole.UserRole) + 4


class _DatabaseDelegate(QStyledItemDelegate):
    """Base: nombre en negrita y « · raíz, en uso» en gris (inventario V14). El texto del elemento no cambia
    (lo leen la búsqueda, la accesibilidad y las pruebas); solo cómo se dibuja."""

    def __init__(self, muted: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._muted = QColor(muted)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: Any) -> None:
        name = index.data(_NAME_ROLE)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if index.parent().isValid() or not name or not str(text).startswith(str(name)):
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, widget)
        strong = QFont(opt.font)
        strong.setBold(True)
        notes = str(text)[len(str(name)) :]
        painter.save()
        painter.setFont(strong)
        painter.setPen(opt.palette.color(QPalette.ColorRole.Text))
        align = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        painter.drawText(rect, align, str(name))
        rect.setLeft(rect.left() + QFontMetrics(strong).horizontalAdvance(str(name)))
        painter.setFont(opt.font)
        painter.setPen(self._muted)
        painter.drawText(rect, align, notes)
        painter.restore()


class CatalogExplorer(QTreeWidget):
    #: (consulta de lectura, nombre propuesto, `(base, esquema, nombre, "table"|"view")`) al elegir
    #: «Cargar en QGIS…».
    load_requested = pyqtSignal(str, str, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemDoubleClicked.connect(self._double_clicked)
        self.loading_enabled = False
        self.setHeaderHidden(True)
        self.setAccessibleName(tr("Explorador de bases de datos"))
        self.setMinimumHeight(140)
        self._catalog: CatalogSnapshot | None = None
        self._filter = ""
        self.setItemDelegate(_DatabaseDelegate(theme.palette_for(self).muted, self))
        #: Acciones del menú contextual de una base (las pone el workspace).
        self.database_actions: list[QAction] = []

    def show_catalog(self, catalog: CatalogSnapshot | None) -> None:
        self._catalog = catalog
        self._groups: list[QTreeWidgetItem] = []
        self.clear()
        if catalog is None:
            return
        temporaries = catalog.temporaries
        temp_placed = False
        for db in catalog.databases:
            item = QTreeWidgetItem([database_label(catalog, db)])
            item.setData(0, _DATABASE_ROLE, db.name)
            item.setData(0, _NAME_ROLE, db.name)
            item.setToolTip(0, db.path or tr("En memoria"))
            for schema in catalog.schemas_of(db.name):
                schema_item = QTreeWidgetItem([schema])
                schema_item.setData(0, _DATABASE_ROLE, db.name)
                schema_item.setData(0, _NAME_ROLE, schema)
                objects = catalog.objects_in(db.name, schema)
                tables = [o for o in objects if o.kind is ObjectKind.TABLE]
                views = [o for o in objects if o.kind is ObjectKind.VIEW]
                self._add_group(schema_item, tr("Tablas"), tables, db.name, "tables")
                self._add_group(schema_item, tr("Vistas"), views, db.name, "views")
                if catalog.is_root(db.name) and schema == "main" and temporaries:
                    self._add_temporaries(schema_item, temporaries)
                    temp_placed = True
                item.addChild(schema_item)
            self.addTopLevelItem(item)
        if temporaries and not temp_placed:  # sin esquema «main» en la raíz: grupos en la raíz del árbol
            holder = QTreeWidgetItem([tr("Temporales de la sesión")])
            self._add_temporaries(holder, temporaries)
            self.addTopLevelItem(holder)
        # Como la maqueta (V18): bases, esquemas y «Tablas (n)» abiertos; vistas y temporales, cerrados
        self.expandToDepth(1)
        for group in self._groups:
            group.setExpanded(group.data(0, _GROUP_ROLE) == "tables")
        self.set_filter(self._filter)

    def _add_temporaries(self, parent: QTreeWidgetItem, temporaries: tuple[CatalogObject, ...]) -> None:
        tables = [o for o in temporaries if o.kind is ObjectKind.TABLE]
        views = [o for o in temporaries if o.kind is ObjectKind.VIEW]
        self._add_group(parent, tr("Tablas temporales"), tables, None, "temp")
        self._add_group(parent, tr("Vistas temporales"), views, None, "temp")

    def _add_group(
        self,
        parent: QTreeWidgetItem,
        title: str,
        objects: list[CatalogObject],
        database: str | None,
        kind: str,
    ) -> None:
        if not objects:
            return
        group = QTreeWidgetItem([f"{title} ({len(objects)})"])
        group.setData(0, _DATABASE_ROLE, database)
        group.setData(0, _GROUP_ROLE, kind)
        self._groups.append(group)
        for obj in objects:
            group.addChild(self._object_item(obj, database))
        parent.addChild(group)

    @staticmethod
    def _object_item(obj: CatalogObject, database: str | None) -> QTreeWidgetItem:
        kind = tr("tabla") if obj.kind is ObjectKind.TABLE else tr("vista")
        item = QTreeWidgetItem([obj.name])
        # La ayuda de carga va en cada tabla y vista (decisión del propietario, 2026-11-02)
        item.setToolTip(
            0,
            f"{kind} {obj.database}.{obj.schema}.{obj.name}\n"
            + tr("Doble clic o clic derecho → Cargar en QGIS…"),
        )
        item.setData(0, _DATABASE_ROLE, database)
        item.setData(0, _NAME_ROLE, obj.name)
        item.setData(0, _OBJECT_ROLE, object_sql(obj))
        kind = "table" if obj.kind is ObjectKind.TABLE else "view"
        item.setData(0, _SOURCE_ROLE, (obj.database, obj.schema, obj.name, kind))
        return item

    # -- búsqueda (AT-UX-006): solo sobre la instantánea mostrada --------------------------------------

    def set_filter(self, text: str) -> None:
        """Muestra las bases, esquemas y objetos cuyo nombre contiene `text` (sin distinguir mayúsculas),
        con su camino; si coincide una base o un esquema, todo su contenido."""
        self._filter = text
        needle = text.strip().casefold()
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if top is not None:
                self._apply_filter(top, needle, False)

    def _apply_filter(self, item: QTreeWidgetItem, needle: str, parent_matches: bool) -> bool:
        name = item.data(0, _NAME_ROLE)
        own = bool(needle) and name is not None and needle in str(name).casefold()
        show_all = not needle or parent_matches or own
        any_child = False
        for i in range(item.childCount()):
            if self._apply_filter(item.child(i), needle, show_all):
                any_child = True
        visible = show_all or any_child
        item.setHidden(not visible)
        if needle and any_child:
            item.setExpanded(True)
        return visible

    def database_menu(self, item: QTreeWidgetItem) -> QMenu | None:
        """Menú de una base (ui-ux-spec §8): sus acciones, p. ej. «Desadjuntar» con las protecciones de G3.
        Selecciona antes la base, para que las acciones se apliquen a ella."""
        if item.parent() is not None or not item.data(0, _DATABASE_ROLE) or not self.database_actions:
            return None
        self.setCurrentItem(item)
        menu = QMenu(self)
        menu.addActions(self.database_actions)
        return menu

    def _context_menu(self, pos: object) -> None:
        item = self.itemAt(pos)  # type: ignore[arg-type]
        if item is not None and (menu := self.database_menu(item)) is not None:
            menu.exec(self.viewport().mapToGlobal(pos))  # type: ignore[arg-type]
            return
        sql = item.data(0, _OBJECT_ROLE) if item is not None else None
        if not sql:
            return
        menu = QMenu(self)
        action = menu.addAction(tr("Cargar en QGIS…"))
        action.setEnabled(self.loading_enabled)
        name = str(item.data(0, _NAME_ROLE))
        source = item.data(0, _SOURCE_ROLE)
        action.triggered.connect(lambda: self.load_requested.emit(sql, name, source))
        menu.exec(self.viewport().mapToGlobal(pos))  # type: ignore[arg-type]

    def _double_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        """Doble clic sobre una tabla o vista: lo mismo que «Cargar en QGIS…» (issue #67). Sobre una base o
        un esquema no hace nada más que expandir o contraer, como siempre."""
        sql = item.data(0, _OBJECT_ROLE) if item is not None else None
        if not sql or not self.loading_enabled:
            return
        name = str(item.data(0, _NAME_ROLE))
        self.load_requested.emit(sql, name, item.data(0, _SOURCE_ROLE))

    def selected_database(self) -> str | None:
        """Base a la que pertenece el elemento seleccionado; `None` si no hay o es un temporal."""
        items = self.selectedItems()
        if not items:
            return None
        value = items[0].data(0, _DATABASE_ROLE)
        return str(value) if value else None

    def select_database(self, name: str) -> None:
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item is not None and item.data(0, _DATABASE_ROLE) == name:
                self.setCurrentItem(item)
                return


def database_label(catalog: CatalogSnapshot, db: AttachedDatabase) -> str:
    """«nombre · raíz, en uso, lectura y escritura». Las bases en memoria no muestran acceso (siempre
    escribibles y temporales), como en la maqueta."""
    notes = []
    if catalog.is_root(db.name):
        notes.append(tr("raíz"))
    if catalog.default_database.key == db.key:
        notes.append(tr("en uso"))
    if db.access is AccessMode.READ_ONLY:
        notes.append(tr("solo lectura"))
    elif not db.in_memory:
        notes.append(tr("lectura y escritura"))
    return db.name + (f" · {', '.join(notes)}" if notes else "")


def object_sql(obj: CatalogObject) -> str:
    """Consulta de lectura de una tabla o vista del catálogo, con identificadores citados."""
    parts = [obj.database, obj.schema, obj.name]
    return "SELECT * FROM " + ".".join(quote_identifier(p) for p in parts)
