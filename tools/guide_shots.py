# SPDX-License-Identifier: GPL-2.0-or-later
"""Capturas de la guía de uso (#150), con GeoDuck real y una sesión de ejemplo.

    QT_QPA_PLATFORM=offscreen python tools/guide_shots.py es|en

Escribe `docs/guide/<idioma>/img/*.png` con QGIS en ese idioma: sin pestañas, una tabla, una consulta con su
resultado y el aviso antes de crear un índice espacial. Las preferencias van a un diccionario, nunca al perfil
de QGIS. Se vuelven a generar cuando cambia la interfaz.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("GEODUCK_SPATIAL", "0")
# sin las copias de recuperación del equipo (el aviso «N consultas no se guardaron…» taparía la captura)
os.environ["GEODUCK_RECOVERY_DIR"] = tempfile.mkdtemp(prefix="geoduck-guide-")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from qgis.core import QgsApplication, QgsSettings  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication, QTimer  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

SAMPLE = """
CREATE TABLE lecturas AS SELECT range AS id,
    CASE range % 3 WHEN 0 THEN 'Sur' WHEN 1 THEN 'Norte' ELSE 'Centro' END AS zona,
    round(120 + (range % 3) * 35 + (range * 7919) % 500 / 10.0, 1) AS kwh,
    DATE '2025-01-01' + (range % 365)::INTEGER AS fecha
    FROM range(1000000);
CREATE TABLE predios AS SELECT range AS id, 'Predio ' || range AS nombre FROM range(5000);
CREATE VIEW consumo_por_zona AS
    SELECT zona, count(*) AS lecturas, avg(kwh) AS promedio FROM lecturas GROUP BY zona;
"""
QUERY = """SELECT zona, count(*) AS lecturas, round(avg(kwh), 1) AS promedio
FROM lecturas
GROUP BY zona
ORDER BY promedio DESC;"""
SIZE = (1100, 600)


class Store(dict):
    def value(self, key, defaultValue=None):  # noqa: N803
        return self.get(key, defaultValue)

    def setValue(self, key, value):  # noqa: N802
        self[key] = value


def wait(predicate, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise TimeoutError


def settle(seconds: float = 0.5) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def shoot(widget: QWidget, path: Path) -> None:
    settle()
    widget.grab().save(str(path))
    print(path)


def main() -> None:  # noqa: PLR0915 - las capturas, en orden
    lang = sys.argv[1] if len(sys.argv) > 1 else "es"
    out = ROOT / "docs" / "guide" / lang / "img"
    out.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    settings = QgsSettings()
    settings.setValue("locale/overrideFlag", True)
    settings.setValue("locale/userLocale", "es_ES" if lang == "es" else "en_US")
    from geoduck.ui import i18n

    i18n.install()
    from geoduck.app.coordinator import SessionCoordinator
    from geoduck.domain.session import SessionState
    from geoduck.domain.sql import RunScope
    from geoduck.plugin import make_memory_engine
    from geoduck.ui.dispatcher import QtDispatcher
    from geoduck.ui.pro.places import Place
    from geoduck.ui.pro.query_page import QueryPage
    from geoduck.ui.pro.workspace import ProWorkspace

    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher())
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    coordinator.execute_sql(SAMPLE, RunScope.ALL)
    wait(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    wait(lambda: any(o.name == "consumo_por_zona" for o in coordinator.catalog.objects))

    ws = ProWorkspace(coordinator, lambda: None, Store())
    ws.set_presentation(wide=True)
    ws.resize(*SIZE)
    ws.show()
    shoot(ws, out / "welcome.png")

    ws.open_place(Place("table", "lecturas", "memory", "main"))
    settle(1.5)
    shoot(ws, out / "table.png")

    ws.new_query()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert isinstance(page, QueryPage)
    page.editor.setText(QUERY)
    page.execute(RunScope.ALL)
    wait(lambda: coordinator.state is SessionState.READY)
    settle(1.5)
    shoot(ws, out / "query.png")

    def grab_dialog() -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                widget.grab().save(str(out / "spatial-index.png"))
                print(out / "spatial-index.png")
                widget.reject()

    QTimer.singleShot(600, grab_dialog)
    ws._spatial_index_dialog("predios", "memory", True)

    ws.detach_coordinator()
    ws.deleteLater()
    coordinator.shutdown(10)
    settings.remove("locale/overrideFlag")
    settings.remove("locale/userLocale")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
