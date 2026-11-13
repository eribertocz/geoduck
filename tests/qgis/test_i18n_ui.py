# SPDX-License-Identifier: GPL-2.0-or-later
"""Idioma de la interfaz con el catálogo real de Qt (G6 · E4, GD-I18N-001, AT-I18N-001; AT-WSP-010).

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
ws = plugin.content
out = {
    "start": ws.start_button.text(),
    "state": ws.state_title.text(),
    "status": ws.sidebar.status.text(),
    "dock": ws.dock_button.text(),
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
    assert (out["start"], out["state"], out["status"]) == (
        "Start GeoDuck",
        "GeoDuck is not started",
        "Not started",
    )
    assert out["dock"] == "Dock to QGIS"
    assert "cannot be empty" in out["error"]  # también los mensajes del motor
    assert out["after"] == out["before"]  # el idioma de QGIS no cambia


def test_qgis_in_spanish_shows_geoduck_in_spanish(tmp_path):
    out = run_qgis("es_ES", tmp_path)
    assert (out["start"], out["state"], out["status"]) == (
        "Iniciar GeoDuck",
        "GeoDuck no está iniciado",
        "No iniciado",
    )
    assert out["dock"] == "Acoplar a QGIS"
    assert "no puede estar vacío" in out["error"]
    assert out["after"] == out["before"]


def test_another_language_falls_back_to_english(tmp_path):
    out = run_qgis("de_DE", tmp_path)
    assert out["start"] == "Start GeoDuck" and out["after"] == out["before"]


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
        assert i18n.tr("Start GeoDuck") == "Iniciar GeoDuck"
    finally:
        ui_i18n.uninstall()
