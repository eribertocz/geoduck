# SPDX-License-Identifier: GPL-2.0-or-later
"""Maqueta de E5 (G9) para aprobar antes de construir: «Enviar a DuckDB» con el sistema de diseño, soltar
capas de QGIS sobre una base, y el mini menú al soltar tablas de DuckDB en el mapa.

    QT_QPA_PLATFORM=offscreen python docs/evidence/g9/enviar/maqueta.py <carpeta>

Usa las piezas reales (el diálogo de G8 con el estilo nuevo, la barra lateral, el menú de «Cargar en QGIS»)
con datos de ejemplo. No es código del complemento.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsSettings, QgsVectorLayer
from qgis.PyQt.QtCore import QT_VERSION_STR

from tools.pro_shots import Store, settle, shoot, theme, wait


def layer(name: str, kind: str, wkt: str, count: int) -> QgsVectorLayer:
    item = QgsVectorLayer(f"{kind}?crs=EPSG:4326&field=id:integer&field=nombre:string", name, "memory")
    feats = []
    for i in range(count):
        feature = QgsFeature(item.fields())
        feature.setAttributes([i, f"{name} {i}"])
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        feats.append(feature)
    item.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(item)
    return item


def main() -> None:  # noqa: PLR0915 - todas las capturas, en orden
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "screenshots")
    out.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    settings = QgsSettings()
    settings.setValue("locale/overrideFlag", True)
    settings.setValue("locale/userLocale", "es_ES")
    from geoduck.ui import i18n

    i18n.install()
    from geoduck.app.coordinator import SessionCoordinator
    from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
    from geoduck.domain.session import SessionState
    from geoduck.plugin import make_memory_engine
    from geoduck.qgis_bridge.importer import LayerSender
    from geoduck.ui.dispatcher import QtDispatcher
    from geoduck.ui.pro.load import load_menu
    from geoduck.ui.pro.sidebar import DATABASE, ROLE
    from geoduck.ui.pro.workspace import ProWorkspace
    from geoduck.ui.send_dialog import SendDialog

    qt = "qt" + QT_VERSION_STR[0]
    theme(False)
    import tempfile

    tmp = tempfile.mkdtemp()
    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher(), None, LayerSender())
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    coordinator.attach_database(AttachRequest(f"{tmp}/db.duckdb", AccessMode.READ_WRITE, OpenAction.CREATE_NEW, "db"))
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("db") is not None)
    points = layer("medidores", "Point", "POINT (-68.13 -16.5)", 1200)
    points.selectByIds([1, 2, 3])
    layer("redes_bt", "LineString", "LINESTRING (-68.1 -16.5, -68.2 -16.6)", 340)
    layer("zonas", "Polygon", "POLYGON ((-68.1 -16.5, -68.2 -16.5, -68.2 -16.6, -68.1 -16.5))", 48)
    ids = [x.id() for x in QgsProject.instance().mapLayers().values()]

    # 1. «Enviar a DuckDB» con el estilo nuevo, con la base donde se soltaron las capas ya elegida
    dialog = SendDialog(
        coordinator.send_candidates(ids),
        coordinator.catalog,
        coordinator.read_import_target,
        checked=set(ids),
        destination=("db", "main"),
        pro=True,
    )
    dialog.show()
    settle(0.8)
    shoot(dialog, out / f"enviar-dialogo-{qt}.png")
    dialog.close()

    # 2. Capas de QGIS arrastradas sobre una base de la barra lateral: la base se resalta
    ws = ProWorkspace(coordinator, lambda: None, Store())
    ws.resize(1440, 900)
    ws.show()
    settle()
    tree = ws.sidebar.tree
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        data = item.data(0, ROLE)
        if data and data[0] == DATABASE and item.text(0) == "db":
            tree.setCurrentItem(item)
    ws.notify("Suelta las 3 capas para enviarlas a «db»")
    shoot(ws, out / f"enviar-soltar-en-base-{qt}.png")

    # 3. Tablas de DuckDB soltadas en el mapa: el mini menú
    menu = load_menu(ws, ws.colors, lambda _k: None, title="3 tablas · ¿cómo cargarlas?")
    menu.popup(ws.mapToGlobal(ws.rect().center()))
    settle()
    shoot(menu, out / f"enviar-soltar-en-mapa-{qt}.png")
    menu.close()
    ws.detach_coordinator()
    coordinator.shutdown(10)
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    app.exitQgis()


if __name__ == "__main__":
    main()
