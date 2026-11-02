# SPDX-License-Identifier: GPL-2.0-or-later
"""Genera capturas de GeoDuck en ventana propia y en panel, sin sesión y con sesión (evidencia de UI).

Uso (dentro del Python de QGIS):  python tools/screenshot_dock.py <carpeta_salida>
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.core import Qgis, QgsApplication
from qgis.PyQt.QtCore import QT_VERSION_STR, QCoreApplication
from qgis.PyQt.QtWidgets import QMainWindow

from geoduck.app.coordinator import SessionCoordinator
from geoduck.domain.session import SessionState
from geoduck.plugin import make_memory_engine, run_diagnostics
from geoduck.ui.dispatcher import QtDispatcher
from geoduck.ui.shells import DockShell, WindowShell
from geoduck.ui.workspace import WorkspaceContent


def pump(predicate, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end and not predicate():
        QCoreApplication.processEvents()
        time.sleep(0.01)


def main(out_dir: str) -> None:
    app = QgsApplication([], True)
    app.initQgis()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"qgis{Qgis.version().split('-')[0]}_qt{QT_VERSION_STR}"
    window = QMainWindow()
    dispatcher = QtDispatcher()
    coordinator = SessionCoordinator(make_memory_engine, dispatcher)
    content = WorkspaceContent(coordinator, run_diagnostics)
    shell = WindowShell(window)
    shell.slot.put(content)
    content.set_presentation(wide=True)
    dock = DockShell(window)
    dock.setFloating(True)
    dock.resize(380, 620)

    def grab_both(state: str) -> None:
        shell.show()
        pump(lambda: False, 0.3)
        shell.grab().save(str(out / f"ventana_{tag}_{state}.png"))
        shell.slot.take(content)  # el mismo contenido, trasladado al panel (ADR-0013)
        dock.slot.put(content)
        content.set_presentation(wide=False)
        shell.hide()
        dock.show()
        pump(lambda: False, 0.3)
        dock.grab().save(str(out / f"dock_{tag}_{state}.png"))
        dock.slot.take(content)
        shell.slot.put(content)
        content.set_presentation(wide=True)
        dock.hide()

    grab_both("sin_sesion")
    content.start_button.click()
    pump(lambda: coordinator.state is SessionState.READY)
    content.sql_panel.editor.setText(
        "CREATE TEMP TABLE puntos AS SELECT 1 AS id;\nSELECT 42 AS n, 'texto' AS t, NULL AS nulo;"
    )
    content.sql_panel.run_all_button.click()
    pump(lambda: coordinator.state is SessionState.READY and content.sql_panel.results.count() == 1)
    grab_both("lista")
    coordinator.shutdown(10)
    print("capturas en", out)
    # Cierre ordenado, como QGIS al salir: sin él, QGIS 3.34–3.40 fallan al terminar el proceso (señal 11).
    content.detach()
    shell.close()
    dock.close()
    window.close()
    content = shell = dock = window = None  # sin referencias vivas antes de exitQgis()
    QCoreApplication.processEvents()
    app.exitQgis()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dist/screenshots")
