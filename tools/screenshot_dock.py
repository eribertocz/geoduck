# SPDX-License-Identifier: GPL-2.0-or-later
# ruff: noqa: E402 - el entorno (QT_QPA_PLATFORM, sys.path) va antes de importar QGIS
"""Capturas de GeoDuck para comparar con la maqueta (docs/g5/maqueta/): ventana propia, panel acoplado,
menú «Cargar en QGIS ▾» y diálogos «Abrir/Crear base DuckDB». Usa el complemento real (controlador,
shells y hoja de estilo) con datos de ejemplo parecidos a los de la maqueta.

Uso (dentro del Python de QGIS):  python tools/screenshot_dock.py <carpeta_salida> [--oscuro]
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qgis.core import Qgis, QgsApplication, QgsProject, QgsSettings
from qgis.PyQt.QtCore import QT_VERSION_STR, QCoreApplication, Qt
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QDialog

import geoduck
from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.load import LoadMode
from geoduck.domain.session import SessionState
from geoduck.ui.attach_dialog import AttachDialog
from geoduck.ui.load_dialog import LoadDialog
from tests.qgis.conftest import FakeIface

DATOS = """
CREATE TABLE consumidores AS SELECT 838835 + i * 7919 % 99991 AS Consumidor,
  ['QUEA CONDORI RENE', 'SUAZNABAR VENEGAS SERGIO', 'SUPO HUAQUI FRANCISCA', 'KULJIS MERUVIA IVANKO',
   'VASQUEZ CORRO PATRICIA', 'MAMANI QUISPE JUAN', 'FLORES ROJAS ANA', 'CHOQUE LIMACHI LUIS'][i % 8 + 1]
   AS RazonSocial,
  ['URB. 31 DE ENERO, AV. 23', 'V. EL CARMEN, LIBERTAD 58', 'SANTA ROSA DE KAATA', 'ACHUMANI, CLL. 8 #471',
   'AV. BUENOS AIRES 1203', 'CALLE COMERCIO 455', 'VILLA FATIMA, CALLE 3',
   'SOPOCACHI, ECUADOR 2210'][i % 8 + 1]
   AS Direccion,
  CASE WHEN i % 3 = 0 THEN '0201' ELSE '0202' END AS CodigoMunicipio,
  ('POINT(' || (-68.15 + i * 0.0001) || ' ' || (-16.5 + i * 0.0001) || ')')::GEOMETRY('OGC:CRS84') AS geometry
FROM range(3000) t(i);
CREATE TABLE medidores AS SELECT range AS id FROM range(10);
CREATE TABLE zonas AS SELECT range AS id FROM range(4);
CREATE VIEW v_activos AS SELECT * FROM consumidores
"""
EDITOR = (
    "SELECT Consumidor, RazonSocial, Direccion, geometry\n"
    "FROM db.consumidores\n"
    "WHERE CodigoMunicipio = '0201';\n"
    "-- Total por zona\n"
    "SELECT CodigoMunicipio, count(*) AS n FROM db.consumidores GROUP BY 1;\n"
    "SELECT * FROM inexistente;"
)


class AutoDialog(LoadDialog):
    def exec(self):
        self.mode_buttons[LoadMode.CONNECTED].setChecked(True)
        return QDialog.DialogCode.Accepted


def pump(predicate=lambda: False, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not predicate():
        QCoreApplication.processEvents()
        time.sleep(0.01)


def dark_palette() -> QPalette:
    palette = QPalette()
    for role, value in (
        (QPalette.ColorRole.Window, "#1e1f22"),
        (QPalette.ColorRole.WindowText, "#e6edf3"),
        (QPalette.ColorRole.Base, "#161b22"),
        (QPalette.ColorRole.Text, "#e6edf3"),
        (QPalette.ColorRole.Button, "#2b2d31"),
        (QPalette.ColorRole.ButtonText, "#e6edf3"),
    ):
        palette.setColor(role, QColor(value))
    return palette


def main(out_dir: str, dark: bool) -> None:  # noqa: PLR0915 - un recorrido lineal de capturas
    app = QgsApplication([], True)
    app.initQgis()
    if dark:
        app.setPalette(dark_palette())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"qgis{Qgis.version().split('-')[0]}_qt{QT_VERSION_STR}" + ("_oscuro" if dark else "")
    folder = tempfile.mkdtemp()
    db = os.path.join(folder, "db.duckdb")
    import duckdb

    con = duckdb.connect(db)
    for statement in DATOS.split(";"):
        if statement.strip():
            con.execute(statement)
    con.close()

    QgsSettings().remove("geoduck/workspace")  # como una instalación limpia: ventana propia
    iface = FakeIface()
    iface.mainWindow().resize(1440, 900)
    iface.mainWindow().show()
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    content, ws, coordinator = plugin.content, plugin.workspace, plugin.coordinator
    content.load_flow._dialog_factory = AutoDialog
    plugin.action.trigger()
    ws.window.resize(1440, 900)
    pump(timeout=0.3)
    ws.window.grab().save(str(out / f"ventana_{tag}_sin_sesion.png"))

    content.start_button.click()
    pump(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    coordinator.attach_database(AttachRequest(db, AccessMode.READ_WRITE, OpenAction.OPEN_EXISTING, "db"))
    pump(lambda: coordinator.state is SessionState.READY and coordinator.catalog.get("db") is not None)
    panel = content.sql_panel
    panel.editor.setText("CREATE TEMP TABLE borrador AS SELECT 1 AS x;")
    panel.run_all_button.click()
    pump(lambda: coordinator.state is SessionState.READY and not panel._running)
    panel.editor.setText(EDITOR)
    panel.run_all_button.click()
    pump(lambda: coordinator.state is SessionState.READY and not panel._running)
    panel.results.setCurrentIndex(0)
    panel.load_button.click()
    pump(lambda: bool(QgsProject.instance().mapLayers()) and coordinator.state is SessionState.READY, 60)
    item = content.explorer.findItems("consumidores", Qt.MatchFlag.MatchRecursive)
    if item:
        content.explorer.setCurrentItem(item[0])
    pump(timeout=0.5)
    ws.window.grab().save(str(out / f"ventana_{tag}.png"))
    panel._fill_load_menu(panel.current_view())
    panel.load_menu.adjustSize()
    panel.load_menu.grab().save(str(out / f"menu_cargar_{tag}.png"))

    ws.window.toggle_button.click()  # al panel
    ws.dock.setFloating(True)
    ws.dock.resize(470, 900)
    content.tabs.setCurrentWidget(panel)
    pump(timeout=0.5)
    ws.dock.grab().save(str(out / f"panel_{tag}.png"))
    content.tabs.setCurrentIndex(0)
    pump(timeout=0.3)
    ws.dock.grab().save(str(out / f"panel_explorador_{tag}.png"))

    for action, name in ((OpenAction.OPEN_EXISTING, "abrir"), (OpenAction.CREATE_NEW, "crear")):
        dialog = AttachDialog(action, content)
        dialog.path_edit.setText(
            db if action is OpenAction.OPEN_EXISTING else os.path.join(folder, "ventas.duckdb")
        )
        dialog.show()
        pump(timeout=0.3)
        dialog.grab().save(str(out / f"dialogo_{name}_{tag}.png"))
        dialog.close()

    print("capturas en", out)
    QgsSettings().remove("geoduck/workspace")
    plugin.unload()  # cierre ordenado, como QGIS al salir (evita fallos al terminar en 3.34–3.40)
    iface.mainWindow().close()
    QgsProject.instance().removeAllMapLayers()
    QCoreApplication.processEvents()
    app.exitQgis()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else "dist/screenshots", "--oscuro" in sys.argv)
