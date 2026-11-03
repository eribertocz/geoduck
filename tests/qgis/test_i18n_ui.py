# SPDX-License-Identifier: GPL-2.0-or-later
"""Idioma de la interfaz con el catálogo real de Qt (G6 · E4, GD-I18N-001, AT-I18N-001; ui-ux-spec §5).

Cada caso arranca QGIS en un proceso aparte: los textos de los módulos se traducen al importarse, y el idioma
se elige una vez, al cargar el complemento (como en QGIS real)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from qgis.PyQt.QtCore import QCoreApplication, QTranslator

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
    "load": plugin.content.sql_panel.load_button.text(),
    "state": plugin.content.state_label.text(),
    "tab": panel.editor_tabs.tabText(0),
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
    assert (out["run"], out["tab"], out["state"]) == ("Run", "Query 1", "No session")
    assert "Load into QGIS" in out["load"]
    assert "cannot be empty" in out["error"]  # también los mensajes del motor
    assert out["after"] == out["before"]  # el idioma de QGIS no cambia


def test_qgis_in_spanish_shows_geoduck_in_spanish(tmp_path):
    out = run_qgis("es_ES", tmp_path)
    assert (out["run"], out["tab"], out["state"]) == ("Ejecutar", "Consulta 1", "Sin sesión")
    assert "Cargar en QGIS" in out["load"]
    assert "no puede estar vacío" in out["error"]
    assert out["after"] == out["before"]


def test_another_language_falls_back_to_english(tmp_path):
    out = run_qgis("de_DE", tmp_path)
    assert out["run"] == "Run" and out["after"] == out["before"]


def test_the_compiled_qm_translates_every_text_like_the_ts(qgis_app):
    # QCoreApplication.translate, como GeoDuck (QTranslator.translate de PyQt6 solo admite ASCII)
    translator = QTranslator()
    assert translator.load(str(ROOT / "geoduck" / "i18n" / "geoduck_es.qm"))
    QCoreApplication.installTranslator(translator)
    try:
        for source, spanish in spanish_catalog().items():
            assert QCoreApplication.translate("GeoDuck", source) == spanish, source
    finally:
        QCoreApplication.removeTranslator(translator)
