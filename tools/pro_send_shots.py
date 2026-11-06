# SPDX-License-Identifier: GPL-2.0-or-later
"""Capturas de «Enviar a DuckDB» y del arrastre de Workspace Pro (G9 · E5) para revisarlas con el propietario.

    QT_QPA_PLATFORM=offscreen python tools/pro_send_shots.py <carpeta>

En QGIS en español: el diálogo limpio (todo nuevo) y con una tabla que ya existe, la base resaltada al
soltar, el progreso en el pie, el aviso final y el mini menú al soltar tablas en el mapa.
Escribe `enviar-<pantalla>-<qt>.png`.
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
    from geoduck.ui.pro.workspace import ProWorkspace
    from geoduck.ui.send_dialog import SendDialog

    qt = "qt" + QT_VERSION_STR[0]
    theme(False)
    tmp = tempfile.mkdtemp()
    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher(), None, LayerSender())
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    coordinator.attach_database(
        AttachRequest(f"{tmp}/db.duckdb", AccessMode.READ_WRITE, OpenAction.CREATE_NEW, "db")
    )
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("db") is not None)
    medidores = layer("medidores", "Point", "POINT (-68.13 -16.5)", 1200)
    redes = layer("redes_bt", "LineString", "LINESTRING (-68.1 -16.5, -68.2 -16.6)", 340)
    zonas = layer("zonas", "Polygon", "POLYGON ((-68.1 -16.5, -68.2 -16.5, -68.2 -16.6, -68.1 -16.5))", 48)
    ids = [medidores.id(), redes.id(), zonas.id()]

    def dialog(name: str) -> None:
        shown = SendDialog(
            coordinator.send_candidates(ids),
            coordinator.catalog,
            coordinator.read_import_target,
            checked=set(ids),
            destination=("db", "main"),
            pro=True,
        )
        shown.show()
        wait(lambda: shown.target_ready)
        settle(0.3)
        shoot(shown, out / f"enviar-{name}-{qt}.png")
        shown.close()
        shown.deleteLater()

    # 1. El diálogo cuando todo es nuevo (solo se abre desde Ctrl+K o «+»: al soltar, ni aparece)
    dialog("dialogo-limpio")

    ws = ProWorkspace(coordinator, lambda: None, Store())
    ws.resize(1440, 900)
    ws.show()
    settle()
    tree = ws.sidebar.tree
    items = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    base = next(i for i in items if (i.data(0, ROLE) or ("",))[0] == DATABASE and i.text(0) == "db")
    # 2. Capas arrastradas sobre «db»: borde de acento y el pie dice dónde irán
    tree.drop_item = base
    tree.viewport().update()
    ws.notify(tr("Drop to send {0} layer(s) to «{1}»").format(3, "db"))
    settle()
    shoot(ws, out / f"enviar-soltar-en-base-{qt}.png")
    tree.drop_item = None
    # 3. Enviando: barra fina y «Cancelar» en el pie
    ws.show_progress(tr("Sending {0} layer(s) to DuckDB…").format(3), 1588)
    ws.set_progress(900)
    settle()
    shoot(ws, out / f"enviar-progreso-{qt}.png")
    ws.hide_progress()
    # 4. Sin diálogo (todo nuevo): el aviso final
    ws.send_layers(ids, ("db", "main"))
    wait(lambda: ws.quick_send.last_report is not None and coordinator.state is SessionState.READY, 60)
    settle(0.4)
    shoot(ws, out / f"enviar-aviso-{qt}.png")
    # 5. Las mismas capas otra vez: ya existen, así que sí se abre el diálogo (con «Qué pasará»)
    coordinator.refresh_catalog()
    wait(lambda: coordinator.state is SessionState.READY)
    dialog("dialogo-ya-existe")
    # 6. Tablas soltadas en el mapa: el mini menú
    handler = PlacesDropHandler(lambda: ws)
    places = [Place(TABLE, name, "db", "main") for name in ("medidores", "redes_bt", "zonas")]
    handler.show_menu(ws, places, ws.mapToGlobal(ws.rect().center()))
    settle()
    shoot(handler.menu, out / f"enviar-soltar-en-mapa-{qt}.png")
    handler.menu.close()
    ws.detach_coordinator()
    coordinator.shutdown(10)
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    app.exitQgis()


if __name__ == "__main__":
    main()
