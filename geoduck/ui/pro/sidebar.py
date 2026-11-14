# SPDX-License-Identifier: GPL-2.0-or-later
"""Barra lateral de Workspace Pro (workspace-pro-spec §3, §8; GD-WSP-002, 007).

De arriba abajo: la sesión (punto de estado, «GeoDuck» y «Activo»), el filtro y «+» (abrir
o crear base, añadir capas de QGIS), **★ Favoritos** y **Bases** (bases, esquemas, tablas,
vistas y temporales), y al pie «Diagnóstico», «Acerca de» y la versión. Doble clic o Intro abre una tabla o
vista; el menú contextual marca favoritos y cierra bases. No ejecuta nada: emite señales que atiende el
workspace.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

from qgis.PyQt.QtCore import (
    QMimeData,
    QModelIndex,
    QObject,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from qgis.PyQt.QtGui import QColor, QDrag, QFont, QFontMetrics, QIcon, QPainter, QPen
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
from geoduck.domain.catalog import AccessMode, CatalogSnapshot, ColumnInfo, ObjectKind, catalog_key
from geoduck.domain.sql_text import sql_name
from geoduck.ui.i18n import tr
from geoduck.ui.pro import fuzzy, icons
from geoduck.ui.pro.drag import (
    PLACES_MIME,
    accepts,
    drag_pixmap,
    drop_hint,
    file_paths,
    layer_ids,
    places_mime,
)
from geoduck.ui.pro.places import Place, Places, icon_name, missing_reason, place_of
from geoduck.ui.pro.style import ui_font
from geoduck.ui.pro.tokens import METRICS, Colors
from geoduck.ui.pro.widgets import (
    LOGO,
    ElidedLabel,
    SearchField,
    StatusDot,
    icon_button,
    label,
    reduced_motion,
)

#: Qué es cada fila del árbol (rol `ROLE`): una sección, una base, un esquema, un grupo o un lugar.
ROLE = Qt.ItemDataRole.UserRole
#: Texto secundario de una fila, en gris a la derecha («db», «solo lectura»).
META = Qt.ItemDataRole.UserRole + 1
#: (base, esquema) donde se envían las capas soltadas sobre esta fila (solo bases y esquemas escribibles).
TARGET = Qt.ItemDataRole.UserRole + 2
#: El texto secundario en turquesa (la geometría) en vez de gris.
ACCENT_META = Qt.ItemDataRole.UserRole + 3
#: La base activa (#168): franja y nombre turquesa, con la etiqueta «activa».
ACTIVE = Qt.ItemDataRole.UserRole + 4
SECTION, DATABASE, SCHEMA, GROUP, PLACE = "section", "database", "schema", "group", "place"
#: Una columna de una tabla o vista (#147): (fuente, ColumnInfo).
COLUMN = "column"
#: Una fila de espera mientras se leen las columnas.
LOADING = "loading"
#: Tablas como mucho de las que se piden las columnas al buscar (la búsqueda también encuentra columnas).
SEARCH_COLUMNS_LIMIT = 200
#: Cuánto dura el resaltado de una tabla nueva (#147: «nuevo», que se desvanece).
NEW_SECONDS = 2.0
#: El lago: ondas en bucle (1,2 s) y la salpicadura al soltar (0,4 s).
WAVE_MS = 1200
SPLASH_MS = 400


def column_icon(column: ColumnInfo) -> str:  # noqa: PLR0911 - un icono por familia de tipos
    """El icono de una columna por su tipo (#147): llave, geometría, texto, número, fecha, sí/no u otro."""
    if column.primary_key:
        return "key"
    if column.is_geometry:
        return "geometry"
    kind = column.data_type.upper()
    if kind.startswith(("VARCHAR", "CHAR", "TEXT", "STRING", "UUID", "ENUM")):
        return "type-text"
    if kind.startswith(
        ("INT", "BIGINT", "SMALLINT", "TINYINT", "HUGEINT", "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT",
         "UHUGEINT", "DOUBLE", "FLOAT", "REAL", "DECIMAL", "NUMERIC")
    ):  # fmt: skip
        return "type-number"
    if kind.startswith(("DATE", "TIME", "TIMESTAMP", "INTERVAL")):
        return "type-date"
    if kind.startswith("BOOL"):
        return "type-bool"
    return "type-other"


def column_type_text(column: ColumnInfo) -> str:
    """El tipo a la derecha, corto: «VARCHAR», «DECIMAL(10,2)», «GEOMETRY»."""
    text = column.data_type.strip()
    return text if len(text) <= 18 else text.split("(", 1)[0]


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
        tree = option.widget  # type: ignore[attr-defined]
        target = getattr(tree, "drop_item", None)
        item = tree.itemFromIndex(index) if tree is not None else None
        splash = getattr(tree, "splash_item", None)
        lake = item is not None and (item is target or item is splash)  # la base donde se soltarán
        box = QRectF(option.rect).adjusted(1, 1, -1, -1)  # type: ignore[attr-defined]
        fresh = tree.fresh(item) if item is not None and hasattr(tree, "fresh") else 0.0
        if fresh > 0:  # una tabla nueva (#147): turquesa con una barra a la izquierda, que se desvanece
            painter.save()
            soft = QColor(self.colors.accent_soft)
            soft.setAlphaF(fresh)
            painter.fillRect(option.rect, soft)  # type: ignore[attr-defined]
            bar = QColor(self.colors.accent)
            bar.setAlphaF(fresh)
            rect = option.rect  # type: ignore[attr-defined]
            painter.fillRect(QRect(0, rect.y(), 3, rect.height()), bar)
            painter.restore()
        if index.data(ACTIVE) and not lake:  # la base activa (#168): turquesa claro con su franja
            painter.save()
            rect = option.rect  # type: ignore[attr-defined]
            painter.fillRect(
                QRect(0, rect.y(), rect.right() + 1, rect.height()), QColor(self.colors.accent_soft)
            )
            painter.fillRect(QRect(0, rect.y(), 3, rect.height()), QColor(self.colors.accent))
            painter.restore()
        if lake:  # «el lago» (marca): la base se pinta de turquesa claro, con el pato a la derecha
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self.colors.accent_soft))
            painter.drawRoundedRect(box, 5, 5)
            painter.restore()
        self._lake = lake  # en el lago, el pato ocupa el sitio del texto de la derecha
        self._fresh = fresh > 0
        self._paint(painter, option, index)
        self._lake = False
        self._fresh = False
        if lake and item is not None:
            self._paint_lake(painter, option, item, box, tree)

    def _paint_lake(
        self, painter: QPainter, option: QStyleOptionViewItem, item: Any, box: QRectF, tree: Any
    ) -> None:
        """El lago (#147, maqueta `explorador-lago`): borde turquesa, «Soltar aquí · esquema», el pato con
        ondas que se expanden en bucle y, al soltar, un anillo que cruza la fila y un pequeño salto."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(self.colors.accent)
        pen = QPen(accent)
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 5, 5)
        target = item.data(0, TARGET)
        if target:
            name_width = QFontMetrics(item.font(0)).horizontalAdvance(item.text(0))
            rect = option.rect  # type: ignore[attr-defined]
            left = rect.x() + 26 + name_width + 10
            painter.setFont(self.small)
            painter.setPen(accent)
            painter.drawText(
                QRect(left, rect.y(), max(0, int(box.right()) - 40 - left), rect.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                QFontMetrics(self.small).elidedText(
                    tr("Drop here · {}").format(target[1]),
                    Qt.TextElideMode.ElideRight,
                    max(0, int(box.right()) - 40 - left),
                ),
            )
        side = 16
        splash = getattr(tree, "splash", 0.0) if item is getattr(tree, "splash_item", None) else 0.0
        x = int(box.right()) - side - 6
        hop = round(4 * math.sin(math.pi * splash)) if splash else 0
        y = int(box.center().y()) - side // 2 - 1 - hop
        phase = getattr(tree, "phase", 0.0)
        ripple = QColor(accent)
        for k in range(2):  # las ondas bajo el pato, que se expanden y se apagan en bucle
            t = (phase + k / 2) % 1.0
            ripple.setAlphaF(max(0.0, 0.65 * (1 - t)))
            wave = QPen(ripple)
            wave.setWidthF(1.2)
            painter.setPen(wave)
            grow = 3 + 9 * t
            painter.drawArc(QRectF(x - grow, y + hop + side - 3, side + 2 * grow, 6), 200 * 16, 140 * 16)
        if splash:  # el anillo grande que sale del pato y cruza la fila
            ring = QColor(accent)
            ring.setAlphaF(max(0.0, 0.7 * (1 - splash)))
            wave = QPen(ring)
            wave.setWidthF(1.5)
            painter.setPen(wave)
            radius = 8 + splash * box.width()
            center = box.right() - side / 2 - 6
            painter.setClipRect(box)
            painter.drawEllipse(
                QRectF(center - radius, box.center().y() - radius * 0.35, 2 * radius, radius * 0.7)
            )
            painter.setClipping(False)
        painter.drawPixmap(x, y, QIcon(LOGO).pixmap(side, side))
        painter.restore()

    def _paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        meta = index.data(META) or (tr("new") if getattr(self, "_fresh", False) else None)
        if not meta:
            super().paint(painter, option, index)
            return
        rect = option.rect  # type: ignore[attr-defined]
        width = QFontMetrics(self.small).horizontalAdvance(meta) + (20 if index.data(ACTIVE) else 10)
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
        if getattr(self, "_lake", False):
            return
        if index.data(ACTIVE):  # «activa»: una pastilla turquesa (maqueta `bases`)
            self._paint_pill(painter, QRect(rect.right() - width, rect.y(), width - 4, rect.height()), meta)
            return
        painter.save()
        painter.setFont(self.small)
        tone = (
            self.colors.accent
            if index.data(ACCENT_META) or getattr(self, "_fresh", False)
            else self.colors.faint
        )
        painter.setPen(QColor(tone))
        painter.drawText(
            QRect(rect.right() - width, rect.y(), width - 4, rect.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
            meta,
        )
        painter.restore()

    def _paint_pill(self, painter: QPainter, area: QRect, text: str) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bold = QFont(self.small)
        bold.setBold(True)
        painter.setFont(bold)
        width = QFontMetrics(bold).horizontalAdvance(text) + 12
        pill = QRectF(area.right() - width, area.center().y() - 8, width, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.colors.accent))
        painter.drawRoundedRect(pill, 8, 8)
        painter.setPen(QColor(self.colors.on_accent))
        painter.drawText(pill, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(hint.height(), 28))


class NavTree(QTreeWidget):
    """El árbol de la barra lateral, con arrastre en los dos sentidos (E5, workspace-pro-spec §9):
    capas de QGIS soltadas sobre una base (resaltada con un borde) y tablas arrastradas hacia QGIS."""

    #: (ids de capas, (base, esquema) o None = la base actual)
    layers_dropped = pyqtSignal(list, object)
    #: Archivos soltados (qgis-import-spec §10): rutas y la base donde se soltaron.
    files_dropped = pyqtSignal(list, object)
    #: Texto para el pie mientras se arrastra («Suelta para enviar 3 capas a «db»»); "" al salir.
    drop_hint = pyqtSignal(str)
    #: Algo que se puede soltar entra (True) o sale o se suelta (False): la guía «Suelta sobre una base…».
    drag_active = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.drop_item: QTreeWidgetItem | None = None
        self.current_target: Callable[[], tuple[str, str] | None] = lambda: None
        #: El lago (#147): la fase de las ondas (0–1, en bucle) y la salpicadura al soltar.
        self.phase = 0.0
        self.splash = 0.0
        self.splash_item: QTreeWidgetItem | None = None
        #: (base, esquema, nombre) → cuándo empezó su resaltado de tabla nueva.
        self.new_since: dict[tuple[str, str, str], float] = {}
        self._wave = QVariantAnimation(self)
        self._wave.setStartValue(0.0)
        self._wave.setEndValue(1.0)
        self._wave.setDuration(WAVE_MS)
        self._wave.setLoopCount(-1)
        self._wave.valueChanged.connect(self._waved)
        self._splash = QVariantAnimation(self)
        self._splash.setStartValue(0.0)
        self._splash.setEndValue(1.0)
        self._splash.setDuration(SPLASH_MS)
        self._splash.valueChanged.connect(self._splashed)
        self._splash.finished.connect(self._splash_done)
        self._fade = QTimer(self)
        self._fade.setInterval(50)
        self._fade.timeout.connect(self._faded)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    # -- el lago y lo nuevo (#147) ----------------------------------------------------------------------

    def _waved(self, value: Any) -> None:
        self.phase = float(value)
        self.viewport().update()

    def _splashed(self, value: Any) -> None:
        self.splash = float(value)
        self.viewport().update()

    def _splash_done(self) -> None:
        self.splash = 0.0
        self.splash_item = None
        self.viewport().update()

    def start_splash(self, item: QTreeWidgetItem | None) -> None:
        """Al soltar: el anillo y el salto del pato; sin animaciones, nada se mueve."""
        if item is None or reduced_motion(self):
            return
        self.splash_item = item
        self._splash.stop()
        self._splash.start()

    def fresh(self, item: QTreeWidgetItem) -> float:
        """Cuánto resalta una tabla nueva (1 → 0 en `NEW_SECONDS`); con menos animaciones, fijo y luego
        nada."""
        data = item.data(0, ROLE)
        if not self.new_since or not data or data[0] != PLACE:
            return 0.0
        place = data[1]
        since = self.new_since.get((place.database, place.schema, place.name))
        if since is None:
            return 0.0
        elapsed = time.monotonic() - since
        if elapsed >= NEW_SECONDS:
            return 0.0
        return 1.0 if reduced_motion(self) else 1.0 - elapsed / NEW_SECONDS

    def start_fade(self) -> None:
        if not self._fade.isActive():
            self._fade.start()

    def _faded(self) -> None:
        now = time.monotonic()
        self.new_since = {k: v for k, v in self.new_since.items() if now - v < NEW_SECONDS}
        if not self.new_since:
            self._fade.stop()
        self.viewport().update()

    # -- hacia QGIS -----------------------------------------------------------------------------------

    def mimeTypes(self) -> list[str]:  # noqa: N802 - API de Qt
        return [PLACES_MIME, "text/plain"]

    def mimeData(self, items: Any) -> QMimeData:  # noqa: N802 - API de Qt
        places = []
        for item in items:
            data = item.data(0, ROLE)
            if data and data[0] == PLACE and not data[1].is_query:
                places.append(data[1])
        return places_mime(places)

    #: Las columnas elegidas como texto para el editor (las pone la barra lateral, citadas si hace falta).
    column_text: Callable[[list[QTreeWidgetItem]], str] = staticmethod(  # type: ignore[assignment]
        lambda _items: ""
    )

    def startDrag(self, actions: Any) -> None:  # noqa: N802 - API de Qt
        """Arrastrar tablas al mapa: se arrastra el pato de GeoDuck (con cuántas lleva) hacia QGIS. Arrastrar
        columnas (#147): su nombre, como texto, se escribe donde se suelte en el editor."""
        items = self.selectedItems()
        columns = [i for i in items if (d := i.data(0, ROLE)) and d[0] == COLUMN]
        if columns:
            data = QMimeData()
            data.setText(self.column_text(columns))
            drag = QDrag(self)
            drag.setMimeData(data)
            drag.exec(Qt.DropAction.CopyAction)
            return
        count = sum(1 for i in items if (d := i.data(0, ROLE)) and d[0] == PLACE and not d[1].is_query)
        if not count:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.setPixmap(drag_pixmap(count))
        drag.setHotSpot(QPoint(14, 34))
        drag.exec(Qt.DropAction.CopyAction)

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
            if item is not None and not reduced_motion(self):
                if self._wave.state() != QVariantAnimation.State.Running:
                    self._wave.start()
            else:
                self._wave.stop()
                self.phase = 0.0
            self.viewport().update()

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if accepts(event.mimeData()) and self.isEnabled():
            event.acceptProposedAction()
            self.drag_active.emit(True)
            self.dragMoveEvent(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        if not accepts(event.mimeData()):
            event.ignore()
            return
        item, target = self._target(_pos(event))
        self._set_drop(item)
        where = target[0] if target else tr("the current database")
        self.drop_hint.emit(drop_hint(event.mimeData(), where))
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def dragLeaveEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        self._set_drop(None)
        self.drop_hint.emit("")
        self.drag_active.emit(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        ids = layer_ids(event.mimeData())
        files = file_paths(event.mimeData())
        item, target = self._target(_pos(event))
        self._set_drop(None)
        self.drop_hint.emit("")
        self.drag_active.emit(False)
        if ids or files:
            self.start_splash(item)
        if not ids and not files:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if files:
            self.files_dropped.emit(files, target)
        else:
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
    #: «Nueva base en memoria…» (#168).
    memory_database_requested = pyqtSignal()
    #: «Usar como base activa» (#168): el nombre de la base.
    activate_requested = pyqtSignal(str)
    send_layers_requested = pyqtSignal()
    #: «Importar archivos…» (qgis-import-spec §10): (base, esquema) donde, o None = la base actual.
    import_files_requested = pyqtSignal(object)
    diagnostics_requested = pyqtSignal()
    about_requested = pyqtSignal()
    start_requested = pyqtSignal()
    #: El 📌 del panel acoplado (#147): fijar al lado (True) o flotar encima (False).
    pin_toggled = pyqtSignal(bool)
    #: Hacen falta las columnas de (base, esquema, objeto): las pide el workspace (#147).
    columns_wanted = pyqtSignal(tuple)
    #: Doble clic en columnas (#147): sus nombres, ya citados si hace falta, para el editor.
    columns_requested = pyqtSignal(str)

    def __init__(self, colors: Colors, places: Places) -> None:
        super().__init__()
        self.colors = colors
        self.places = places
        self.catalog: CatalogSnapshot | None = None
        #: Por qué no se puede cerrar una base (#168), o None; lo pone el workspace (`close_reason`).
        self.close_reason: Callable[[str], str | None] | None = None
        #: Columnas conocidas por objeto (del catálogo que se muestra) y los objetos abiertos en el árbol.
        self.columns: dict[tuple[str, str, str], tuple[ColumnInfo, ...]] = {}
        self._tables_open: set[tuple[str, str, str]] = set()
        self._asked: set[tuple[str, str, str]] = set()
        #: Palabras que obligan a citar un nombre (las pone el workspace cuando DuckDB las da).
        self.reserved: frozenset[str] | None = None
        #: Tablas nuevas que aún no están en el árbol (se resaltan al aparecer).
        self._pending_new: set[tuple[str, str, str]] = set()
        self._collapsed: set[tuple[str, ...]] = set()
        self._opened: set[tuple[str, ...]] = set()
        self._quiet = False
        self.setProperty("pro", "side")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(METRICS.sidebar)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        #: La sesión arriba («GeoDuck», «Activo», «⋯»); en el panel la lleva su cabecera.
        self.session_head = self._build_header()
        box.addWidget(self.session_head)
        self.dock_head = self._build_dock_head()
        box.addWidget(self.dock_head)
        box.addLayout(self._build_filter())
        self.tree = self._build_tree()
        trees = QVBoxLayout()
        trees.setContentsMargins(8, 2, 8, 4)
        trees.setSpacing(6)
        box.addLayout(trees, 1)  # antes de sus widgets: sin padre, uno visible sería una ventana suelta
        # la guía mientras se arrastra (#147): dónde soltar
        self.drop_guide = label(tr("Drop on a database to bring it to GeoDuck"), "drop-guide")
        self.drop_guide.setWordWrap(True)
        self.drop_guide.hide()
        trees.addWidget(self.drop_guide)
        trees.addWidget(self.tree)
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
        self.title = label("GeoDuck")
        self.title.setFont(ui_font(bold=True))
        self.status = ElidedLabel(tr("Stopped"), "muted")
        self.status.setFont(ui_font(METRICS.font_small))
        titles.addWidget(self.title)
        titles.addWidget(self.status)
        row.addLayout(titles, 1)
        self.session_button = icon_button("more", tr("Session"), self.colors)
        # El menú de la sesión: solo lo que aplica: sin sesión, «Iniciar GeoDuck»;
        # con sesión, «Cerrar sesión»; nunca un «Iniciar» en gris.
        self.session_menu = QMenu(self)
        self.start_action = self.session_menu.addAction(tr("Start GeoDuck"))
        self.start_action.triggered.connect(self.start_requested.emit)
        self.session_open_db = self.session_menu.addAction(tr("Open database…"))
        self.session_open_db.triggered.connect(self.open_database_requested.emit)
        self.session_create_db = self.session_menu.addAction(tr("Create database…"))
        self.session_create_db.triggered.connect(self.create_database_requested.emit)
        self.session_memory_db = self.session_menu.addAction(tr("New database in memory…"))
        self.session_memory_db.triggered.connect(self.memory_database_requested.emit)
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

    def _build_dock_head(self) -> QWidget:
        """En el panel acoplado (#147, maqueta `explorador-lago`): «Explorador» y el 📌 para fijarlo al lado o
        dejarlo flotar encima."""
        head = QFrame()
        row = QHBoxLayout(head)
        row.setContentsMargins(14, 10, 8, 0)
        row.setSpacing(6)
        title = label(tr("Explorer"))
        title.setFont(ui_font(bold=True))
        row.addWidget(title, 1)
        self.pin_button = icon_button("pin", "", self.colors, size=14)
        self.pin_button.setIcon(icons.toggle("pin", self.colors.muted, self.colors.accent, 14))
        self.pin_button.setCheckable(True)
        self.pin_button.toggled.connect(self._pin_changed)
        self._pin_changed(False, emit=False)
        row.addWidget(self.pin_button)
        head.hide()
        return head

    def _pin_changed(self, pinned: bool, *, emit: bool = True) -> None:
        tip = (
            tr("Pinned: stays beside the editor. Click to let it float")
            if pinned
            else tr("Floating: closes with a click outside or Esc. Click to pin it beside the editor")
        )
        self.pin_button.setToolTip(tip)
        self.pin_button.setAccessibleName(tr("Pin the explorer"))
        if emit:
            self.pin_toggled.emit(pinned)

    def set_docked(self, docked: bool, *, pinned: bool) -> None:
        """Panel acoplado: la cabecera «Explorador 📌»; en la ventana, la de la sesión."""
        self.session_head.setVisible(not docked)
        self.dock_head.setVisible(docked)
        self.pin_button.blockSignals(True)
        self.pin_button.setChecked(pinned)
        self.pin_button.blockSignals(False)
        self._pin_changed(pinned, emit=False)

    def show_drop_guide(self, on: bool) -> None:
        self.drop_guide.setVisible(on and self.catalog is not None)

    def _build_filter(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(12, 10, 8, 6)
        row.setSpacing(4)
        self.search = SearchField(
            tr("Search tables and columns…"), self.colors, accessible_name=tr("Search tables and columns")
        )
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
        self.memory_db_action = self.add_menu.addAction(tr("New database in memory…"))
        self.memory_db_action.triggered.connect(self.memory_database_requested.emit)
        self.add_menu.addSeparator()
        self.import_action = self.add_menu.addAction(tr("Import files…"))
        self.import_action.triggered.connect(lambda: self.import_files_requested.emit(None))
        self.send_action = self.add_menu.addAction(tr("Add QGIS layers to GeoDuck…"))
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
        # varias tablas a la vez (Ctrl o Mayús) para cargarlas juntas en QGIS
        tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tree.setAccessibleName(tr("Databases and favorites"))
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._context_menu)
        tree.itemActivated.connect(self._activated)
        tree.itemExpanded.connect(lambda item: self._remember_expanded(item, True))
        tree.itemCollapsed.connect(lambda item: self._remember_expanded(item, False))
        tree.drag_active.connect(self.show_drop_guide)
        tree.column_text = self.column_text
        return tree

    def _build_footer(self) -> QWidget:
        foot = QFrame()
        foot.setProperty("pro", "rule-top")
        row = QHBoxLayout(foot)
        row.setContentsMargins(8, 6, 14, 6)
        row.setSpacing(0)
        self.diagnostics_button = self._link(
            tr("Diagnostics"), tr("Checks that GeoDuck has everything it needs")
        )
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
        """Punto de estado, motor («GeoDuck») y estado («Activo»)."""
        self.dot.set_state(dot)
        self.title.setText(engine)
        self.status.setText(text)
        self.refresh_action.setEnabled(ready)
        self.refresh_action.setVisible(dot != "off")
        self.close_action.setVisible(dot != "off")
        self.start_action.setVisible(dot == "off")
        for action in (self.session_open_db, self.session_create_db, self.session_memory_db):
            action.setEnabled(ready or dot == "off")
        for action in (self.open_db_action, self.create_db_action, self.memory_db_action):
            action.setEnabled(ready or dot == "off")
        self.send_action.setEnabled(ready)
        # Sin DuckDB, todo en gris salvo iniciar, abrir o crear una base, Diagnóstico y Acerca de
        started = dot != "off"
        for widget in (self.search, self.tree):
            widget.setEnabled(started)

    def current_target(self) -> tuple[str, str] | None:
        """El destino de lo nuevo sin una base elegida a mano (#168: una sola verdad): la base activa, en
        `main` o su único esquema, si es escribible. Soltar sobre una base sigue eligiendo esa."""
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.data(0, ACTIVE):
                target = item.data(0, TARGET)
                return tuple(target) if target else None
        return None

    def render(self, catalog: CatalogSnapshot | None) -> None:
        """Rehace el árbol (favoritos y bases; sin «Recientes», 2026-11-06), con lo plegado y el filtro. Un
        catálogo nuevo puede traer columnas cambiadas (ALTER, CREATE OR REPLACE, #147): las de los objetos
        abiertos se vuelven a pedir."""
        if catalog is not self.catalog:
            self.columns = {}
            self._asked = set()
        self.catalog = catalog
        tree = self.tree
        tree.setUpdatesEnabled(False)
        tree.clear()
        self._add_places("★ " + tr("Favorites"), "favorites", self.places.favorites)
        self._section(tr("Databases"), "databases")
        if catalog is None:
            hint = QTreeWidgetItem([tr("Start GeoDuck to see your databases")])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setForeground(0, QColor(self.colors.faint))
            tree.addTopLevelItem(hint)
        else:
            for db in catalog.databases:
                writable = db.in_memory or db.access is not AccessMode.READ_ONLY
                self._add_database(catalog, db.name, _access_text(db.access, db.in_memory), writable)
                if catalog_key(db.name) == catalog_key(catalog.default):
                    self._mark_active(tree.topLevelItem(tree.topLevelItemCount() - 1), db.name)
            if catalog.temporaries:
                temp = self._node(None, tr("Temporary"), (GROUP, "temp"), GROUP, bold=True)
                for obj in sorted(catalog.temporaries, key=lambda o: o.name.casefold()):
                    self._add_object(temp, place_of(obj.database, obj.schema, obj.name, obj.kind))
        self._apply_filter(self.search.edit.text())
        tree.setUpdatesEnabled(True)
        if self._pending_new:
            self._show_new()

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

    def _mark_active(self, item: QTreeWidgetItem, name: str) -> None:
        """La base activa (#168): una sola en la sesión; el editor muestra la misma."""
        access = item.data(0, META)
        item.setData(0, ACTIVE, True)
        item.setData(0, META, tr("active"))
        item.setForeground(0, QColor(self.colors.accent))
        item.setIcon(0, icons.icon("database", self.colors.accent, 14))
        item.setToolTip(0, f"{name} · {access}\n" + tr("Active database: «Run» and everything new go here"))

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
        # sus columnas, al expandir (#147): del catálogo de DuckDB, sin leer datos
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        source = (place.database, place.schema, place.name)
        if source in self._tables_open:
            self._fill_columns(item, source)
            self._quiet = True
            item.setExpanded(True)
            self._quiet = False

    # -- columnas (#147, maqueta `explorador-columnas`) ---------------------------------------------------

    def _fill_columns(self, item: QTreeWidgetItem, source: tuple[str, str, str]) -> None:
        """Las columnas bajo su tabla, o «Cargando…» mientras DuckDB las lee."""
        item.takeChildren()
        known = self.columns.get(source)
        if known is None:
            wait = QTreeWidgetItem([tr("Loading…")])
            wait.setData(0, ROLE, (LOADING, source))
            wait.setFlags(Qt.ItemFlag.NoItemFlags)
            wait.setForeground(0, QColor(self.colors.faint))
            item.addChild(wait)
            self._want(source)
            return
        for column in known:
            child = QTreeWidgetItem([column.name])
            child.setData(0, ROLE, (COLUMN, (source, column)))
            child.setData(0, META, column_type_text(column))
            child.setData(0, ACCENT_META, column.is_geometry)
            tone = self.colors.accent if column.is_geometry else self.colors.faint
            child.setIcon(0, icons.icon(column_icon(column), tone, 13))
            child.setToolTip(
                0,
                f"{column.name} · {column.data_type}"
                + (" · " + tr("primary key") if column.primary_key else "")
                + "\n"
                + tr("Double-click or drag it to the editor"),
            )
            child.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled
            )
            item.addChild(child)

    def _want(self, source: tuple[str, str, str]) -> None:
        if source not in self._asked:
            self._asked.add(source)
            self.columns_wanted.emit(source)

    def set_columns(self, source: tuple[str, str, str], columns: tuple[ColumnInfo, ...] | None) -> None:
        """Llegaron las columnas de `source` (o `None`: no se pudieron leer)."""
        if columns is None:
            self.columns.pop(source, None)
        else:
            self.columns[source] = columns
        for item in self._items_of(source):
            if item.isExpanded() or source in self._tables_open:
                if columns is None:
                    item.takeChildren()
                else:
                    self._fill_columns(item, source)
        if self.search.edit.text().strip():
            self._apply_filter(self.search.edit.text())

    def _items_of(self, source: tuple[str, str, str]) -> list[QTreeWidgetItem]:
        found: list[QTreeWidgetItem] = []

        def visit(item: QTreeWidgetItem) -> None:
            data = item.data(0, ROLE)
            if data and data[0] == PLACE and _source(data[1]) == source:
                found.append(item)
                return
            for index in range(item.childCount()):
                visit(item.child(index))

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))
        return found

    def column_text(self, items: list[QTreeWidgetItem]) -> str:
        """Los nombres de las columnas para el editor: citados si hace falta, separados por «, »."""
        names = []
        for item in items:
            data = item.data(0, ROLE)
            if data and data[0] == COLUMN:
                names.append(sql_name(data[1][1].name, self.reserved))
        return ", ".join(names)

    # -- lo nuevo (#147) ----------------------------------------------------------------------------------

    def mark_new(self, sources: list[tuple[str, str, str]]) -> None:
        """Tablas recién llevadas a DuckDB: resaltadas en turquesa con «nuevo», que se desvanece en 2 s, y el
        árbol abierto hasta ellas. Si aún no están en el árbol, al llegar el catálogo."""
        self._pending_new.update(s for s in sources if all(s))
        self._show_new()

    def _show_new(self) -> None:
        shown = set()
        last = None
        for source in self._pending_new:
            for item in self._items_of(source):
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.new_since[source] = time.monotonic()
                shown.add(source)
                last = item
        self._pending_new -= shown
        if last is not None:
            self.tree.scrollToItem(last)
            self.tree.start_fade()
            self.tree.viewport().update()

    def _is_open(self, key: tuple[str, ...]) -> bool:
        """Las bases y esquemas, abiertos salvo que el usuario los pliegue; los grupos de vistas, al revés."""
        if key[:2] == (GROUP, "views"):
            return key in self._opened
        return key not in self._collapsed

    def _remember_expanded(self, item: QTreeWidgetItem, expanded: bool) -> None:
        data = item.data(0, ROLE)
        if data and data[0] == PLACE and not data[1].is_query and item.parent() is not None:
            source = _source(data[1])
            if expanded:
                if not self._quiet:
                    self._tables_open.add(source)
                if item.childCount() == 0 or item.child(0).data(0, ROLE)[0] == LOADING:
                    self._fill_columns(item, source)
            elif not self._quiet:
                self._tables_open.discard(source)
            return
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
        if query:
            self._want_all_columns()
        self._quiet = True

        def matches(name: str) -> bool:
            return not query or fuzzy.score(query, fuzzy.fold(name)) is not None

        def visit(item: QTreeWidgetItem) -> bool:
            data = item.data(0, ROLE)
            if not data:
                return True
            if data[0] == PLACE:
                return show_place(item, data[1])
            if data[0] in (COLUMN, LOADING):
                return True
            any_child = False
            for index in range(item.childCount()):
                any_child = visit(item.child(index)) or any_child
            item.setHidden(bool(query) and not any_child)
            item.setExpanded(any_child if query else self._is_open(data[1]))
            return any_child

        def show_place(item: QTreeWidgetItem, place: Place) -> bool:
            """La tabla, si coincide su nombre o alguna de sus columnas (la búsqueda encuentra columnas)."""
            source = _source(place)
            if query and item.parent() is not None and source in self.columns:
                hits = {c.name for c in self.columns[source] if matches(c.name)}
                if hits:
                    if item.childCount() == 0 or item.child(0).data(0, ROLE)[0] != COLUMN:
                        self._fill_columns(item, source)
                    for index in range(item.childCount()):
                        child = item.child(index)
                        child.setHidden(child.text(0) not in hits)
                    item.setHidden(False)
                    item.setExpanded(True)
                    return True
            for index in range(item.childCount()):
                item.child(index).setHidden(False)
            if not query and item.parent() is not None:
                item.setExpanded(source in self._tables_open)
            visible = matches(item.text(0))
            item.setHidden(not visible)
            if query and visible:
                item.setExpanded(False)
            return visible

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

    def _want_all_columns(self) -> None:
        """Al buscar, las columnas de las tablas y vistas que aún no se conocen (como mucho
        `SEARCH_COLUMNS_LIMIT`), para que la búsqueda también las encuentre."""
        if self.catalog is None:
            return
        wanted = [
            (o.database, o.schema, o.name)
            for o in self.catalog.objects
            if (o.database, o.schema, o.name) not in self.columns
        ]
        for source in wanted[:SEARCH_COLUMNS_LIMIT]:
            self._want(source)

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

    def reveal(self, database: str, schema: str, name: str) -> bool:
        """Ctrl+clic en una tabla del SQL (#146): el filtro se limpia, sus carpetas se abren y queda elegida
        y a la vista. Devuelve si estaba en el árbol."""
        if self.search.edit.text():
            self.search.edit.clear()

        def visit(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            data = item.data(0, ROLE)
            if data and data[0] == PLACE:
                place = data[1]
                if (
                    not place.is_query
                    and catalog_key(place.database) == catalog_key(database)
                    and place.schema.casefold() == schema.casefold()
                    and place.name.casefold() == name.casefold()
                ):
                    return item
            for index in range(item.childCount()):
                found = visit(item.child(index))
                if found is not None:
                    return found
            return None

        for index in range(self.tree.topLevelItemCount()):
            found = visit(self.tree.topLevelItem(index))
            if found is not None:
                parent = found.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.setCurrentItem(found)
                self.tree.scrollToItem(found)
                return True
        return False

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
        if data[0] == COLUMN:  # doble clic: su nombre (o los de las elegidas) donde está el cursor
            chosen = [i for i in self.tree.selectedItems() if (d := i.data(0, ROLE)) and d[0] == COLUMN]
            self.columns_requested.emit(self.column_text(chosen if item in chosen else [item]))
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
        target = item.data(0, TARGET) if item is not None else None
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
        elif data[0] in (DATABASE, SCHEMA) and self.catalog is not None:
            db = self.catalog.get(item.text(0)) if data[0] == DATABASE else None
            if db is not None and catalog_key(db.name) != catalog_key(self.catalog.default):
                # #168: una sola base activa; también desde el desplegable del editor y Ctrl+K
                menu.addAction(tr("Use as active database"), lambda: self.activate_requested.emit(db.name))
            if target:  # una base o un esquema en escritura (qgis-import-spec §10)
                where = tuple(target)
                menu.addAction(tr("Import files here…"), lambda: self.import_files_requested.emit(where))
            if db is not None:
                menu.addSeparator()
                close = menu.addAction(tr("Close database"), lambda: self.detach_requested.emit(db.name))
                reason = self.close_reason(db.name) if self.close_reason is not None else None
                if reason:  # en gris, con el motivo (la activa, la última, una base en uso)
                    close.setEnabled(False)
                    close.setToolTip(tr("Cannot be closed. {0}").format(reason))
                    menu.setToolTipsVisible(True)
            if menu.isEmpty():
                return
        else:
            return
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(self.tree.viewport().mapToGlobal(pos))


def _source(place: Place) -> tuple[str, str, str]:
    return (place.database, place.schema, place.name)
