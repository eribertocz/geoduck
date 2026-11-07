# SPDX-License-Identifier: GPL-2.0-or-later
"""Arrastrar entre QGIS y GeoDuck, en los dos sentidos (G9 · E5; workspace-pro-spec §9).

- **QGIS → DuckDB:** capas del panel de capas soltadas sobre una base de la barra lateral (o en cualquier
  parte de GeoDuck: a la base actual). Las lee `layer_ids` del formato del panel de capas de QGIS.
- **DuckDB → QGIS:** tablas o vistas arrastradas desde la barra lateral (`places_mime`) y soltadas en el
  mapa o en el panel de capas. `PlacesDropHandler` (un `QgsCustomDropHandler` que registra el complemento)
  muestra el mini menú «N tablas · ¿cómo cargarlas?» (Copia / Conectada) donde se soltaron; Esc cancela.
  El SRC sale de cada columna; una sola ventana pequeña solo si a alguna le falta.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from qgis.gui import QgsCustomDropHandler
from qgis.PyQt.QtCore import QByteArray, QMimeData, QPoint, Qt
from qgis.PyQt.QtGui import QColor, QCursor, QIcon, QPainter, QPixmap

from geoduck.domain.sql_text import quote_identifier
from geoduck.ui.i18n import tr
from geoduck.ui.pro.load import load_menu
from geoduck.ui.pro.places import QUERY, VIEW, Place
from geoduck.ui.pro.widgets import LOGO

#: Formato del panel de capas de QGIS al arrastrar capas (`QgsLayerTreeModel::mimeData`).
LAYERS_MIME = "application/qgis.layertreemodeldata"
#: Tablas y vistas de GeoDuck arrastradas desde la barra lateral (JSON).
PLACES_MIME = "application/x-geoduck-places"


def layer_ids(data: QMimeData) -> list[str]:
    """Ids de las capas arrastradas desde el panel de capas, en orden (también las de dentro de un grupo)."""
    if not data.hasFormat(LAYERS_MIME):
        return []
    raw = bytes(data.data(LAYERS_MIME)).decode("utf-8", "replace")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    found: list[str] = []
    for node in root.iter("layer-tree-layer"):
        layer_id = node.get("id")
        if layer_id and layer_id not in found:
            found.append(layer_id)
    return found


def places_mime(places: list[Place]) -> QMimeData:
    data = QMimeData()
    payload = [[p.kind, p.name, p.database, p.schema] for p in places if p.kind != QUERY]
    data.setData(PLACES_MIME, QByteArray(json.dumps(payload).encode("utf-8")))
    data.setText("\n".join(p.name for p in places))
    return data


def places_from(data: QMimeData) -> list[Place]:
    if not data.hasFormat(PLACES_MIME):
        return []
    try:
        payload = json.loads(bytes(data.data(PLACES_MIME)).decode("utf-8"))
        return [Place(kind, name, database, schema) for kind, name, database, schema in payload]
    except (ValueError, TypeError):
        return []


def place_job(place: Place) -> dict[str, Any]:
    """La carga de una tabla o vista entera (como «Cargar en QGIS» sin filtros: una «Conectada» se edita)."""
    parts = (place.database, place.schema, place.name)
    return {
        "sql": "SELECT * FROM " + ".".join(quote_identifier(part) for part in parts),
        "name": place.name,
        "source": parts,
        "source_kind": "view" if place.kind == VIEW else "table",
    }


def menu_title(count: int) -> str:
    return (
        tr("1 table · how to load it?") if count == 1 else tr("{} tables · how to load them?").format(count)
    )


class PlacesDropHandler(QgsCustomDropHandler):
    """Tablas de GeoDuck soltadas en el mapa o en el panel de capas de QGIS. `workspace()` da el workspace
    abierto (o None): su `loader` carga y sus colores pintan el mini menú."""

    def __init__(self, workspace: Callable[[], Any]) -> None:
        super().__init__()
        self._workspace = workspace
        #: El último menú mostrado (para las pruebas) y dónde.
        self.menu: Any = None

    def canHandleMimeData(self, data: QMimeData) -> bool:  # noqa: N802 - API de QGIS
        return data.hasFormat(PLACES_MIME)

    def handleMimeDataV2(self, data: QMimeData) -> bool:  # noqa: N802 - API de QGIS
        places = places_from(data)
        workspace = self._workspace()
        if not places or workspace is None:
            return False
        self.show_menu(workspace, places, QCursor.pos())
        return True

    def show_menu(self, workspace: Any, places: list[Place], at: QPoint) -> None:
        jobs = [place_job(place) for place in places]
        self.menu = load_menu(
            workspace,
            workspace.colors,
            lambda kind: workspace.loader.start_many(jobs, kind),
            title=menu_title(len(places)),
        )
        self.menu.popup(at)  # Esc o un clic fuera cierran el menú sin cargar nada


def drag_pixmap(count: int) -> QPixmap:
    """Lo que se ve al arrastrar tablas hacia el mapa: el pato de GeoDuck, y cuántas lleva si son varias
    (propietario, 2026-11-07: «como arrastrar un pato al lago»)."""
    size = 40
    image = QPixmap(size + 22, size)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawPixmap(0, 0, QIcon(LOGO).pixmap(size, size))
    if count > 1:
        painter.setBrush(QColor("#F2A33A"))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawEllipse(size - 10, 0, 22, 18)
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#1F2430"))
        painter.drawText(size - 10, 0, 22, 18, int(Qt.AlignmentFlag.AlignCenter), str(count))
    painter.end()
    return image
