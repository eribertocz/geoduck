# SPDX-License-Identifier: GPL-2.0-or-later
"""Idioma de la interfaz con el catálogo real de Qt (G6 · E4, GD-I18N-001, AT-I18N-001; ui-ux-spec §5).

Cada caso arranca QGIS en un proceso aparte: los textos de los módulos se traducen al importarse, y el idioma
se elige una vez, al cargar el complemento (como en QGIS real)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from qgis.PyQt.QtCore import QCoreApplication

from tests.conftest import spanish_catalog

pytestmark = pytest.mark.qgis

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from qgis.core import QgsApplication, QgsSettings
from qgis.PyQt.QtCore import QLocale
app = QgsApplication([], True); app.initQgis()
s = QgsSettings()
if sys.argv[2] == "system":
    s.remove("locale/overrideFlag"); s.remove("locale/userLocale")
else:
    s.setValue("locale/overrideFlag", True); s.setValue("locale/userLocale", sys.argv[2])
before = (QgsApplication.locale(), QLocale().name())
from tests.qgis.conftest import FakeIface
import geoduck
iface = FakeIface()
plugin = geoduck.classFactory(iface); plugin.initGui()
panel = plugin.content.sql_panel
out = {
    "run": panel.run_all_button.accessibleName(),
    "load": plugin.content.sql_panel.load_button.accessibleName(),
    "state": plugin.content.state_label.text(),
    "tab": panel.editor_tabs.tabText(0),
    "notebook": [
        panel.notebook_list.names()[0], panel.cell.run_button.toolTip(), panel.notebook_view.add_button.text()
    ],
    "after": [QgsApplication.locale(), QLocale().name()],
    "before": list(before),
}
from geoduck.domain.sql_text import quote_identifier
try:
    quote_identifier("")
except Exception as exc:
    out["error"] = str(exc)
plugin.unload()
print("JSON" + json.dumps(out, ensure_ascii=False))
"""


def run_qgis(locale: str, tmp_path: Path) -> dict:
    # configuración propia (HOME/XDG): no toca la de las demás pruebas, que ven QGIS en español
    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(ROOT), locale],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )
    line = next((x for x in result.stdout.splitlines() if x.startswith("JSON")), None)
    assert line is not None, result.stdout[-2000:] + result.stderr[-2000:]
    return json.loads(line[4:])


def test_qgis_in_english_shows_geoduck_in_english(tmp_path):
    out = run_qgis("en_US", tmp_path)
    assert (out["run"], out["tab"], out["state"]) == ("Run all", "Query 1", "No session")
    assert out["notebook"] == ["Query 1", "Run the cell (Ctrl+Enter)", "＋ Add cell"]  # G7
    assert "Load into QGIS" in out["load"]
    assert "cannot be empty" in out["error"]  # también los mensajes del motor
    assert out["after"] == out["before"]  # el idioma de QGIS no cambia


def test_qgis_in_spanish_shows_geoduck_in_spanish(tmp_path):
    out = run_qgis("es_ES", tmp_path)
    assert (out["run"], out["tab"], out["state"]) == ("Ejecutar todo", "Consulta 1", "Sin sesión")
    assert out["notebook"] == ["Consulta 1", "Ejecutar la celda (Ctrl+Intro)", "＋ Añadir celda"]  # G7
    assert "Cargar en QGIS" in out["load"]
    assert "no puede estar vacío" in out["error"]
    assert out["after"] == out["before"]


def test_another_language_falls_back_to_english(tmp_path):
    out = run_qgis("de_DE", tmp_path)
    assert out["run"] == "Run all" and out["after"] == out["before"]


def test_translating_never_calls_qt_so_the_engine_thread_can_do_it(qgis_app, monkeypatch):
    """F-107: el hilo del motor traduce mensajes; GeoDuck no llama a Qt para traducir."""
    from geoduck.domain import i18n
    from geoduck.ui import i18n as ui_i18n

    def forbidden(*_args, **_kwargs):
        raise AssertionError("QCoreApplication.translate no debe usarse")

    monkeypatch.setattr(QCoreApplication, "translate", forbidden)
    assert ui_i18n.install() == "es"
    try:
        results = []
        worker = threading.Thread(target=lambda: results.append(i18n.tr("Operation cancelled")))
        worker.start()
        worker.join(5)
        assert results == [spanish_catalog()["Operation cancelled"]]
        assert i18n.tr("Run all") == "Ejecutar todo"
    finally:
        ui_i18n.uninstall()
