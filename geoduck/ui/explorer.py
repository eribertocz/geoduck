# SPDX-License-Identifier: GPL-2.0-or-later
"""Explorador del catálogo de la sesión: bases, esquemas, tablas y vistas (GD-CAT-001, AT-CAT-001).

Solo muestra la instantánea que publica la capa de aplicación, leída de DuckDB después de cada operación
con éxito; nunca la modifica por su cuenta ni la anticipa.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QMenu, QTreeWidget, QTreeWidgetItem, QWidget

from geoduck.domain.catalog import AccessMode, CatalogObject, CatalogSnapshot, ObjectKind
from geoduck.domain.sql_text import quote_identifier
from geoduck.ui.i18n import tr

_DATABASE_ROLE = int(Qt.ItemDataRole.UserRole)
_OBJECT_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 2


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

    def show_catalog(self, catalog: CatalogSnapshot | None) -> None:
        self._catalog = catalog
        self.clear()
        if catalog is None:
            return
        for db in catalog.databases:
            notes = []
            if catalog.is_root(db.name):
                notes.append(tr("raíz"))
            if catalog.default_database.key == db.key:
                notes.append(tr("en uso"))
            if db.access is AccessMode.READ_ONLY:
                notes.append(tr("solo lectura"))
            label = db.name + (f" · {', '.join(notes)}" if notes else "")
            item = QTreeWidgetItem([label])
            item.setData(0, _DATABASE_ROLE, db.name)
            item.setToolTip(0, db.path or tr("En memoria"))
            for schema in catalog.schemas_of(db.name):
                schema_item = QTreeWidgetItem([schema])
                schema_item.setData(0, _DATABASE_ROLE, db.name)
                for obj in catalog.objects_in(db.name, schema):
                    schema_item.addChild(self._object_item(obj, db.name))
                item.addChild(schema_item)
            self.addTopLevelItem(item)
            item.setExpanded(True)
        if catalog.temporaries:
            temp = QTreeWidgetItem([tr("Temporales de la sesión")])
            for obj in catalog.temporaries:
                temp.addChild(self._object_item(obj, None))
            self.addTopLevelItem(temp)

    @staticmethod
    def _object_item(obj: CatalogObject, database: str | None) -> QTreeWidgetItem:
        kind = tr("tabla") if obj.kind is ObjectKind.TABLE else tr("vista")
        item = QTreeWidgetItem([f"{obj.name} ({kind})"])
        item.setData(0, _DATABASE_ROLE, database)
        item.setData(0, _OBJECT_ROLE, object_sql(obj))
        kind = "table" if obj.kind is ObjectKind.TABLE else "view"
        item.setData(0, _SOURCE_ROLE, (obj.database, obj.schema, obj.name, kind))
        return item

    def _context_menu(self, pos: object) -> None:
        item = self.itemAt(pos)  # type: ignore[arg-type]
        sql = item.data(0, _OBJECT_ROLE) if item is not None else None
        if not sql:
            return
        menu = QMenu(self)
        action = menu.addAction(tr("Cargar en QGIS…"))
        action.setEnabled(self.loading_enabled)
        name = item.text(0).rsplit(" (", 1)[0]
        source = item.data(0, _SOURCE_ROLE)
        action.triggered.connect(lambda: self.load_requested.emit(sql, name, source))
        menu.exec(self.viewport().mapToGlobal(pos))  # type: ignore[arg-type]

    def _double_clicked(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        """Doble clic sobre una tabla o vista: lo mismo que «Cargar en QGIS…» (issue #67). Sobre una base o
        un esquema no hace nada más que expandir o contraer, como siempre."""
        sql = item.data(0, _OBJECT_ROLE) if item is not None else None
        if not sql or not self.loading_enabled:
            return
        name = item.text(0).rsplit(" (", 1)[0]
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


def object_sql(obj: CatalogObject) -> str:
    """Consulta de lectura de una tabla o vista del catálogo, con identificadores citados."""
    parts = [obj.database, obj.schema, obj.name]
    return "SELECT * FROM " + ".".join(quote_identifier(p) for p in parts)
