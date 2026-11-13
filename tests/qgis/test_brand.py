# SPDX-License-Identifier: GPL-2.0-or-later
"""Identidad visual de GeoDuck (#142; workspace-pro-spec §10): logo turquesa, logo en los submenús «GeoDuck»,
«Enviar a GeoDuck…» y la marca DuckDB solo como información técnica."""

from __future__ import annotations

from pathlib import Path

import pytest
from qgis.PyQt.QtWidgets import QMenu

import geoduck
from geoduck.domain.i18n import tr
from geoduck.plugin import brand_submenu
from geoduck.ui.about_dialog import AboutDialog

pytestmark = pytest.mark.qgis

LOGO = Path(geoduck.__file__).resolve().parent / "resources" / "icon.svg"


def test_the_logo_is_lake_turquoise_with_an_amber_beak():
    svg = LOGO.read_text(encoding="utf-8")
    assert 'fill="#0E8A87"' in svg and 'fill="#F2A33A"' in svg and 'fill="#0A5E5C"' in svg
    assert "#2F5FD0" not in svg.split("-->", 1)[1]  # nada del azul anterior


def test_only_the_geoduck_submenu_gets_the_logo(qgis_app):
    menu = QMenu()
    ours = menu.addMenu("&GeoDuck")
    other = menu.addMenu("&Otro complemento")
    plain = menu.addAction("GeoDuck")  # una acción suelta con ese nombre no es el submenú
    assert brand_submenu(menu)
    assert not ours.menuAction().icon().isNull()
    assert other.menuAction().icon().isNull() and plain.icon().isNull()  # lo ajeno no se toca (ADR-0011)
    assert not brand_submenu(QMenu())


def test_the_layer_menu_says_send_to_geoduck(iface):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    try:
        [action] = [a for a in iface.layer_actions if a.objectName() == "geoduckSendToDuckDB"]
        assert action.text() == tr("Send to GeoDuck…")
        assert "DuckDB" not in action.text() and "DuckDB" not in action.toolTip()
    finally:
        plugin.unload()


def test_about_names_duckdb_only_as_the_engine(qgis_app):
    dialog = AboutDialog(None, None)
    assert dialog.trademark.text() == tr("DuckDB is a trademark of the DuckDB Foundation.")
    dialog.deleteLater()
