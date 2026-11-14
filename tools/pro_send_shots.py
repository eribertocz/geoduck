# SPDX-License-Identifier: GPL-2.0-or-later
"""Capturas de «Capas de QGIS → DuckDB» (F-131) y del arrastre de Workspace Pro.

    QT_QPA_PLATFORM=offscreen python tools/pro_send_shots.py <carpeta>

En QGIS en español: la base resaltada al soltar, los tres pasos (capas, dónde, progreso y resumen), la línea
del pie, el aviso final con «×» y el mini menú al soltar tablas en el mapa (el otro sentido).
Escribe `anadir-<pantalla>-<qt>.png` y `enviar-soltar-en-mapa-<qt>.png`.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    os.environ.setdefault("GEODUCK_RECOVERY_DIR", tempfile.mkdtemp())
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
    from geoduck.ui.i18n import tr
    from geoduck.ui.pro.drag import PlacesDropHandler
    from geoduck.ui.pro.places import TABLE, Place
    from geoduck.ui.pro.sidebar import DATABASE, ROLE
    from geoduck.ui.pro.widgets import lines_html
    from geoduck.ui.pro.workspace import ProWorkspace

    qt = "qt" + QT_VERSION_STR[0]
    theme(False)
    tmp = tempfile.mkdtemp()
    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher(), None, LayerSender())
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    request = AttachRequest(f"{tmp}/prueba.duckdb", AccessMode.READ_WRITE, OpenAction.CREATE_NEW, "prueba")
    coordinator.attach_database(request)
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("prueba") is not None)
    medidores = layer("medidores", "Point", "POINT (-68.13 -16.5)", 200000)
    redes = layer("redes_bt", "LineString", "LINESTRING (-68.1 -16.5, -68.2 -16.6)", 340)
    zonas = layer("zonas", "Polygon", "POLYGON ((-68.1 -16.5, -68.2 -16.5, -68.2 -16.6, -68.1 -16.5))", 48)
    clientes = QgsVectorLayer("None?field=id:integer", "clientes", "memory")
    QgsProject.instance().addMapLayer(clientes)

    ws = ProWorkspace(coordinator, lambda: None, Store())
    ws.resize(1440, 900)
    ws.show()
    settle()
    tree = ws.sidebar.tree
    items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    base = next(i for i in items if (i.data(0, ROLE) or ("",))[0] == DATABASE and i.text(0) == "prueba")
    # Capas arrastradas sobre «prueba»: borde de acento y el pie dice dónde irán
    tree.drop_item = base
    tree.viewport().update()
    ws.notify(tr("Drop to send {0} layer(s) to «{1}»").format(3, "prueba"))
    settle()
    shoot(ws, out / f"anadir-soltar-en-base-{qt}.png")
    tree.drop_item = None
    # 1. «Añadir capas de QGIS a DuckDB…»: todas las capas, agrupadas; las seleccionadas en QGIS, marcadas
    ws.add_layers([medidores.id(), redes.id(), zonas.id()])
    flow = ws.to_duckdb
    window = flow.window
    settle(0.3)
    shoot(window, out / f"anadir-paso1-{qt}.png")
    # 2. Dónde: la base, el esquema y qué pasará
    flow.next_button.click()
    wait(lambda: window.send_dialog is not None and window.send_dialog.target_ready)
    dialog = window.send_dialog
    dialog.destination.setCurrentIndex([d for d, _s in dialog.destinations].index("prueba"))
    wait(lambda: dialog.target_ready)
    flow._sync_add()
    settle(0.3)
    shoot(window, out / f"anadir-paso2-{qt}.png")
    # 3. Progreso capa por capa
    flow.add_button.click()
    big = next(i for i, state in enumerate(flow.states) if state["name"] == "medidores")
    wait(lambda: flow.states[big]["state"] == "running" and flow.states[big]["rows"] > 0, 60)
    waiting = [i for i, state in enumerate(flow.states) if state["state"] == "waiting"]
    if waiting:
        flow.remove(waiting[-1])  # una capa quitada mientras espera
    settle(0.2)
    shoot(window, out / f"anadir-paso3-{qt}.png")
    shoot(ws, out / f"anadir-pie-{qt}.png")
    wait(lambda: not flow.running, 120)
    settle(0.3)
    shoot(window, out / f"anadir-paso3-listo-{qt}.png")
    window.hide()
    ws.toast(lines_html(flow.done_lines()), [(tr("Open"), lambda: None), (tr("Undo"), lambda: None)], 0)
    settle(0.4)
    shoot(ws, out / f"anadir-aviso-{qt}.png")
    # Tablas de DuckDB soltadas en el mapa: el mini menú (el otro sentido)
    handler = PlacesDropHandler(lambda: ws)
    places = [Place(TABLE, name, "prueba", "main") for name in ("medidores", "redes_bt")]
    handler.show_menu(ws, places, ws.mapToGlobal(ws.rect().center()))
    settle()
    shoot(handler.menu, out / f"enviar-soltar-en-mapa-{qt}.png")
    handler.menu.close()
    ws.detach_coordinator()
    coordinator.shutdown(10)
    sys.stdout.flush()
    os._exit(0)  # como pro_shots: sin la limpieza de PyQt5 al salir


if __name__ == "__main__":
    main()
