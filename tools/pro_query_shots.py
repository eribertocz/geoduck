# SPDX-License-Identifier: GPL-2.0-or-later
"""Capturas de la pestaña de consulta de Workspace Pro (G9 · E4a).

    QT_QPA_PLATFORM=offscreen python tools/pro_query_shots.py <carpeta>

Con una sesión real de DuckDB y SQL de ejemplo, en QGIS en español: resultado (claro y oscuro), mensajes con
un error y GeoDuck sin DuckDB iniciado. Escribe `consulta-<pantalla>-<tema>-<qt>.png`. Las preferencias van a
un diccionario y la copia de recuperación a una carpeta temporal, nunca al perfil de QGIS.
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

from tools.pro_shots import Store, shoot, theme, wait

SETUP = """
CREATE TABLE municipios AS SELECT * FROM (VALUES
  ('0201', 'El Alto'), ('0202', 'La Paz'), ('0203', 'Viacha'), ('0204', 'Achocalla'), ('0205', 'Mecapaca'),
  ('0206', 'Palca'), ('0207', 'Laja'), ('0208', 'Pucarani')) t(codigo, nombre);
CREATE TABLE lecturas AS SELECT
  lpad(((range % 8) + 201)::VARCHAR, 4, '0') AS codigo, DATE '2025-11-01' AS mes,
  round(80 + (range * 37 % 200) / 1.3, 1) AS kwh FROM range(20000);
"""

SQL = """-- Consumo medio por municipio, noviembre
SELECT m.nombre,
       count(*)    AS suministros,
       avg(l.kwh)  AS kwh_medio
FROM lecturas l
JOIN municipios m USING (codigo)
WHERE l.mes >= '2025-11-01'
GROUP BY ALL
ORDER BY kwh_medio DESC;
"""

ERRORS = """CREATE TABLE zonas_borrador AS SELECT 1 AS id;
SELECT kwh_mes FROM lecturas;
SELECT 3;
"""


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
    from geoduck.ui.pro.query_page import MESSAGES
    from geoduck.ui.pro.workspace import ProWorkspace

    qt = "qt" + QT_VERSION_STR[0]
    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher())
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    coordinator.execute_sql(SETUP, RunScope.ALL)
    wait(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    wait(lambda: any(o.name == "lecturas" for o in coordinator.catalog.objects))
    for dark in (False, True):
        name = "oscuro" if dark else "claro"
        theme(dark)
        ws = ProWorkspace(coordinator, lambda: None, Store())
        ws.resize(1440, 900)
        ws.show()
        ws.new_query()
        page = ws.tabs.page(0)
        page.editor.setText(SQL)
        page.execute(RunScope.ALL)
        wait(lambda p=page: p.run is None and coordinator.state is SessionState.READY and p.results)
        shoot(ws, out / f"consulta-resultado-{name}-{qt}.png")
        if not dark:
            page.editor.setText(ERRORS)
            page.execute(RunScope.ALL)
            wait(lambda p=page: p.run is None and coordinator.state is SessionState.READY)
            page.view.set_current(MESSAGES)
            page._show_view(MESSAGES)
            shoot(ws, out / f"consulta-mensajes-{name}-{qt}.png")
        ws.detach_coordinator()
        ws.deleteLater()
    coordinator.shutdown(10)
    theme(False)
    idle = SessionCoordinator(make_memory_engine, QtDispatcher())
    ws = ProWorkspace(idle, lambda: None, Store())
    ws.resize(1440, 900)
    ws.show()
    shoot(ws, out / f"consulta-sin-duckdb-claro-{qt}.png")
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    app.exitQgis()
    sys.stdout.flush()
    os._exit(0)  # como pro_shots: sin la limpieza de PyQt5 al salir (Qt 5 se cae)


if __name__ == "__main__":
    main()
