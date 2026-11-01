# SPDX-License-Identifier: GPL-2.0-or-later
"""Genera capturas del panel en sus estados de G0 (evidencia de UI para PR/gates).

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
from geoduck.ui.dock import GeoDuckDock


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
    dock = GeoDuckDock(coordinator, run_diagnostics, window)
    dock.setFloating(True)
    dock.resize(380, 420)
    dock.show()
    pump(lambda: False, 0.3)
    dock.grab().save(str(out / f"dock_{tag}_sin_sesion.png"))
    dock.start_button.click()
    pump(lambda: coordinator.state is SessionState.READY)
    pump(lambda: False, 0.2)
    dock.grab().save(str(out / f"dock_{tag}_lista.png"))
    coordinator.shutdown(10)
    print("capturas en", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dist/screenshots")
