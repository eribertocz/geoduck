# SPDX-License-Identifier: GPL-2.0-or-later
"""Capturas de la pestaña de tabla de Workspace Pro (G9 · E3).

    QT_QPA_PLATFORM=offscreen python tools/pro_table_shots.py <carpeta>

Con una sesión real de DuckDB y una tabla de ejemplo de 50 000 filas, en QGIS en español: «Datos» con dos
filtros, orden y detalle de fila (claro y oscuro), el filtro nuevo y «Estructura». Escribe
`tabla-<pantalla>-<tema>-<qt>.png`. Las preferencias van a un diccionario, nunca al perfil de QGIS.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.core import QgsApplication, QgsSettings
from qgis.PyQt.QtCore import QT_VERSION_STR

from tools.pro_shots import Store, settle, shoot, theme, wait

SAMPLE = """
CREATE TABLE consumidores (
    consumidor BIGINT PRIMARY KEY,
    razon_social VARCHAR,
    direccion VARCHAR,
    codigo_municipio VARCHAR,
    consumo_kwh DOUBLE,
    geom GEOMETRY
);
INSERT INTO consumidores SELECT
    100000 + range,
    ['MAMANI QUISPE JUAN', 'FLORES ROJAS ANA', 'CHOQUE LIMACHI LUIS', 'QUEA CONDORI RENE'][range % 4 + 1],
    CASE WHEN range % 9 = 4 THEN NULL ELSE 'AV. ' || range || ', ZONA ' || (range % 30) END,
    lpad(((range % 12) + 195)::VARCHAR, 4, '0'),
    round(20 + (range * 37 % 400) / 1.7, 1),
    ('POINT (' || (-68.2 + (range % 100) / 1000.0) || ' ' || (-16.5 - (range % 77) / 1000.0) || ')')::GEOMETRY
FROM range(50000);
"""


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
    from geoduck.domain.browse import GT, Filter
    from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
    from geoduck.domain.session import SessionState
    from geoduck.domain.sql import RunScope
    from geoduck.plugin import make_memory_engine
    from geoduck.ui.dispatcher import QtDispatcher
    from geoduck.ui.pro.places import Place
    from geoduck.ui.pro.table_page import GRID
    from geoduck.ui.pro.workspace import ProWorkspace

    qt = "qt" + QT_VERSION_STR[0]
    with tempfile.TemporaryDirectory() as tmp:
        coordinator = SessionCoordinator(make_memory_engine, QtDispatcher())
        coordinator.start_memory_session()
        wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
        request = AttachRequest(
            str(Path(tmp) / "db.duckdb"), AccessMode.READ_WRITE, OpenAction.CREATE_NEW, "db"
        )
        coordinator.attach_database(request)
        wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("db") is not None)
        coordinator.execute_sql("USE db;\n" + SAMPLE + "USE memory;", RunScope.ALL)
        wait(lambda: coordinator.state is SessionState.READY)
        coordinator.refresh_catalog()
        wait(lambda: any(o.name == "consumidores" for o in coordinator.catalog.objects))
        for dark in (False, True):
            name = "oscuro" if dark else "claro"
            theme(dark)
            ws = ProWorkspace(coordinator, lambda: None, Store())
            ws.resize(1440, 900)
            ws.show()
            ws.open_place(Place("table", "consumidores", "db", "main"))
            page = ws.tabs.page(0)
            wait(lambda p=page: p.body.currentIndex() == GRID and p.model.rowCount() > 0)
            page.add_filter(Filter("codigo_municipio", "=", "0201"))
            page.add_filter(Filter("consumo_kwh", GT, "50"))
            wait(lambda p=page: p.total is not None and p.model.rowCount() > 0)
            page.grid.selectRow(2)
            wait(lambda p=page: p.detail.fields and p.detail.title.text().endswith("3"))
            settle(0.5)
            ws.notify("Tabla «consumidores» abierta")
            shoot(ws, out / f"tabla-datos-{name}-{qt}.png")
            if not dark:
                page.open_filter_popup()
                popup = page.popup
                popup.column.setCurrentText("razon_social")
                popup.operator.setCurrentIndex(6)  # contiene
                popup.value.setText("quispe")
                shoot(popup, out / f"tabla-filtro-{name}-{qt}.png")
                popup.close()
                page.mode.buttons[1].click()
                wait(lambda p=page: bool(p.structure.create.toPlainText()))
                shoot(ws, out / f"tabla-estructura-{name}-{qt}.png")
            ws.detach_coordinator()
            ws.deleteLater()
        coordinator.shutdown(10)
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    app.exitQgis()


if __name__ == "__main__":
    main()
