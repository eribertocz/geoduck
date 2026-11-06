# SPDX-License-Identifier: GPL-2.0-or-later
"""Capturas de «Cargar en QGIS» de Workspace Pro (G9 · E4b) para revisarlas con el propietario.

    QT_QPA_PLATFORM=offscreen python tools/pro_load_shots.py <carpeta>

En QGIS en español: la pestaña de tabla con «Exportar» y «Cargar en QGIS», su menú (Copia / Conectada), la
ventana de SRC (solo si falta) y el aviso al guardar el proyecto con copias.
Escribe `cargar-<pantalla>-<qt>.png`.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.core import QgsApplication, QgsSettings, QgsVectorLayer
from qgis.PyQt.QtCore import QT_VERSION_STR

from tools.pro_shots import Store, settle, shoot, theme, wait


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
    from geoduck.domain.session import SessionState
    from geoduck.domain.sql import RunScope
    from geoduck.plugin import make_memory_engine
    from geoduck.ui.dispatcher import QtDispatcher
    from geoduck.ui.pro.load import CrsDialog
    from geoduck.ui.pro.places import Place
    from geoduck.ui.pro.project_copies import SaveCopiesDialog
    from geoduck.ui.pro.table_page import GRID
    from geoduck.ui.pro.workspace import ProWorkspace

    qt = "qt" + QT_VERSION_STR[0]
    theme(False)
    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher())
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    coordinator.execute_sql(
        "CREATE TABLE consumidores AS SELECT 100000 + range AS consumidor,"
        " 'CLIENTE ' || range AS razon_social,"
        " round(20 + range * 1.7, 1) AS consumo_kwh,"
        " ('POINT (' || (-68.2 + range / 1000) || ' -16.5)')::GEOMETRY('OGC:CRS84') AS geom FROM range(500);",
        RunScope.ALL,
    )
    wait(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    wait(lambda: any(o.name == "consumidores" for o in coordinator.catalog.objects))
    ws = ProWorkspace(coordinator, lambda: None, Store())
    ws.resize(1440, 900)
    ws.show()
    ws.open_place(Place("table", "consumidores", "memory", "main"))
    page = ws.tabs.page(0)
    wait(lambda: page.body.currentIndex() == GRID and page.model.rowCount() > 0)
    page.set_detail_open(False)
    page.detail_button.setChecked(False)
    shoot(ws, out / f"cargar-tabla-{qt}.png")
    menu = page.load_menu
    menu.popup(page.load_button.mapToGlobal(page.load_button.rect().bottomLeft()))
    settle()
    shoot(menu, out / f"cargar-menu-{qt}.png")
    menu.close()
    crs = CrsDialog(["geom", "geom_centro"], ws)
    crs.show()
    shoot(crs, out / f"cargar-src-{qt}.png")
    crs.close()
    layers = [
        QgsVectorLayer("Point?crs=EPSG:4326", name, "memory") for name in ("consumidores", "Consulta 1")
    ]
    save = SaveCopiesDialog(layers, Path("/proyectos/consumo_geoduck.gpkg"), ws)
    save.show()
    shoot(save, out / f"cargar-guardar-copias-{qt}.png")
    save.close()
    ws.detach_coordinator()
    coordinator.shutdown(10)
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    app.exitQgis()


if __name__ == "__main__":
    main()
