# SPDX-License-Identifier: GPL-2.0-or-later
"""Capturas de la estructura de Workspace Pro (G9 · E2).

    QT_QPA_PLATFORM=offscreen python tools/pro_shots.py <carpeta>

Con una sesión real de DuckDB y datos de ejemplo, en QGIS en español: ventana (claro y oscuro), Ctrl+K,
panel acoplado y «sin sesión». Escribe `<pantalla>-<tema>-<qt>.png`. Las preferencias van a un diccionario,
nunca al perfil de QGIS.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.core import QgsApplication, QgsSettings
from qgis.PyQt.QtCore import QT_VERSION_STR, QCoreApplication
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QVBoxLayout, QWidget

SAMPLE = """
CREATE TABLE consumidores AS SELECT range AS id, 'Consumidor ' || range AS nombre FROM range(10);
CREATE TABLE lecturas (id INTEGER, kwh DOUBLE);
CREATE TABLE medidores (id INTEGER);
CREATE TABLE municipios (codigo VARCHAR, nombre VARCHAR);
CREATE TABLE zonas (id INTEGER);
CREATE VIEW consumo_por_municipio AS SELECT * FROM municipios;
CREATE VIEW lecturas_2025 AS SELECT * FROM lecturas;
CREATE SCHEMA ventas;
CREATE TABLE ventas.facturas (id INTEGER);
CREATE TABLE ventas.clientes (id INTEGER);
CREATE TEMP TABLE resultado_temporal AS SELECT 1 AS x;
"""


class Store(dict):
    def value(self, key, defaultValue=None):  # noqa: N803
        return self.get(key, defaultValue)

    def setValue(self, key, value):  # noqa: N802
        self[key] = value


def wait(predicate, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError


def settle(seconds: float = 0.3) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def theme(dark: bool) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#16181d" if dark else "#f0f0f0"))
    QApplication.setPalette(palette)


def session(folder: Path):
    from geoduck.app.coordinator import SessionCoordinator
    from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
    from geoduck.domain.session import SessionState
    from geoduck.domain.sql import RunScope
    from geoduck.plugin import make_memory_engine
    from geoduck.ui.dispatcher import QtDispatcher

    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher())
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    path = folder / "db.duckdb"
    coordinator.attach_database(AttachRequest(str(path), AccessMode.READ_WRITE, OpenAction.CREATE_NEW, "db"))
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("db") is not None)
    coordinator.execute_sql("USE db;\n" + SAMPLE + "USE memory;", RunScope.ALL)
    wait(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    wait(lambda: any(o.name == "zonas" for o in coordinator.catalog.objects))
    return coordinator


def shoot(widget: QWidget, path: Path) -> None:
    settle()
    widget.grab().save(str(path))
    print(path)


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
    from geoduck.ui.pro.places import Place
    from geoduck.ui.pro.shell import DockHeader
    from geoduck.ui.pro.workspace import ProWorkspace

    qt = "qt" + QT_VERSION_STR[0]
    with tempfile.TemporaryDirectory() as tmp:
        coordinator = session(Path(tmp))
        for dark in (False, True):
            name = "oscuro" if dark else "claro"
            theme(dark)
            store = Store()
            ws = ProWorkspace(coordinator, lambda: None, store)
            ws.resize(1440, 900)
            ws.show()
            ws.places.toggle_favorite(Place("table", "consumidores", "db", "main"))
            for table in ("lecturas", "consumidores"):
                ws.open_place(Place("table", table, "db", "main"))
            ws.new_query()
            ws.tabs.bar.setCurrentIndex(1)
            ws.notify("Base «db» abierta")
            shoot(ws, out / f"ventana-{name}-{qt}.png")
            ws.command_palette.open()
            ws.command_palette.edit.setText("lec")
            shoot(ws, out / f"ctrl-k-{name}-{qt}.png")
            ws.command_palette.close_palette()
            if not dark:
                for index in reversed(range(len(ws.tabs))):
                    ws.tabs.close_tab(index)
                shoot(ws, out / f"sin-pestanas-{name}-{qt}.png")
                ws.open_place(Place("table", "consumidores", "db", "main"))
                dock = QWidget()
                dock.setObjectName("dock")
                box = QVBoxLayout(dock)
                box.setContentsMargins(0, 0, 0, 0)
                box.setSpacing(0)
                header = DockHeader(ws)
                box.addWidget(header)
                box.addWidget(ws, 1)
                ws.set_presentation(wide=False)
                dock.show()
                settle()
                dock.resize(420, 900)  # tras mostrarlo: al mostrarse conserva el ancho que traía el workspace
                shoot(dock, out / f"panel-{name}-{qt}.png")
            ws.detach_coordinator()
            ws.deleteLater()
        coordinator.shutdown(10)
        theme(False)
        from geoduck.app.coordinator import SessionCoordinator
        from geoduck.plugin import make_memory_engine
        from geoduck.ui.dispatcher import QtDispatcher

        idle = SessionCoordinator(make_memory_engine, QtDispatcher())
        ws = ProWorkspace(idle, lambda: None, Store())
        ws.resize(1440, 900)
        ws.show()
        shoot(ws, out / f"sin-sesion-claro-{qt}.png")
        ws.detach_coordinator()
        ws.close()
        ws.deleteLater()
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    # los widgets se borran antes de cerrar QGIS: si no, Python los destruye al salir y Qt 5 se cae
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    import gc

    gc.collect()
    app.exitQgis()
    # Al volver de `main`, Python destruiría sus objetos de QGIS en mal orden y Qt 5 se cae (no afecta a
    # las capturas, ya escritas): se sale aquí, sin esa limpieza.
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
