# SPDX-License-Identifier: GPL-2.0-or-later
"""Capturas de lo nuevo de G9 · E6 para revisarlas con el propietario.

    QT_QPA_PLATFORM=offscreen python tools/pro_switch_shots.py <carpeta>

En QGIS en español: la pestaña «Historial» (clara y oscura), el aviso «La transacción falló · Revertir», el
aviso de carga con «Ver en el mapa» y la pantalla de inicio con el entorno incompleto.
Escribe `cambio-<pantalla>-<qt>.png`.
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
    from geoduck.infra.diagnostics import collect
    from geoduck.plugin import make_memory_engine
    from geoduck.qgis_bridge.loader import BridgeLoader
    from geoduck.ui.dispatcher import QtDispatcher
    from geoduck.ui.pro.load import COPY
    from geoduck.ui.pro.workspace import ProWorkspace

    qt = "qt" + QT_VERSION_STR[0]

    def run(coordinator: SessionCoordinator, sql: str) -> None:
        coordinator.execute_sql(sql, RunScope.ALL)
        wait(lambda: coordinator.state is not SessionState.BUSY)

    for dark in (False, True):
        theme(dark)
        coordinator = SessionCoordinator(make_memory_engine, QtDispatcher(), BridgeLoader())
        coordinator.start_memory_session()
        wait(lambda c=coordinator: c.state is SessionState.READY and c.catalog is not None)
        ws = ProWorkspace(coordinator, lambda: None, Store())
        ws.resize(1440, 900)
        ws.show()
        for sql in (
            "CREATE TABLE consumidores AS SELECT range AS id, 20 + range * 1.7 AS kwh FROM range(5000);",
            "SELECT count(*), avg(kwh) FROM consumidores WHERE kwh > 100;",
            "SELECT * FROM consumidor;",
            "UPDATE consumidores SET kwh = kwh * 1.1 WHERE id < 100;"
            " SELECT * FROM consumidores ORDER BY kwh DESC LIMIT 50;",
        ):
            run(coordinator, sql)
        ws.open_history()
        settle(0.4)
        shoot(ws, out / f"cambio-historial{'-oscuro' if dark else ''}-{qt}.png")
        if not dark:
            # «Ver en el mapa» en el aviso de la carga
            ws.on_view_map = lambda _ids: None
            run(
                coordinator,
                "CREATE TABLE pozos AS SELECT range AS id,"
                " ('POINT (' || (-68 - range) || ' -16)')::GEOMETRY('OGC:CRS84') AS geom FROM range(30);",
            )
            ws.loader.start('SELECT * FROM "pozos"', "pozos", COPY)
            wait(lambda w=ws: w.loader.last_report is not None and w.last_toast is not None, 60)
            settle(0.4)
            shoot(ws, out / f"cambio-ver-en-el-mapa-{qt}.png")
            ws.last_toast.dismiss()
            # la transacción abortada
            run(coordinator, "BEGIN; SELECT * FROM no_existe;")
            settle(0.4)
            shoot(ws, out / f"cambio-revertir-{qt}.png")
            ws.rollback()
            wait(lambda c=coordinator: c.state is SessionState.READY)
        ws.detach_coordinator()
        coordinator.shutdown(10)
        ws.close()

    # sin DuckDB: la pantalla de inicio lo explica
    theme(False)
    idle = SessionCoordinator(make_memory_engine, QtDispatcher())

    def missing(name: str) -> object:
        if name in ("duckdb", "pyarrow"):
            raise ImportError(f"No module named {name!r}")
        import importlib

        return importlib.import_module(name)

    ws = ProWorkspace(idle, lambda: collect(import_module=missing), Store())
    ws.resize(1440, 900)
    ws.show()
    settle(0.3)
    shoot(ws, out / f"cambio-sin-duckdb-{qt}.png")
    ws.detach_coordinator()
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    app.exitQgis()


if __name__ == "__main__":
    main()
