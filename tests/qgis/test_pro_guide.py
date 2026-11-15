# SPDX-License-Identifier: GPL-2.0-or-later
"""Accesos a la guía de uso desde GeoDuck (#150; maqueta `150`)."""

from __future__ import annotations

import pytest
from qgis.PyQt.QtGui import QGuiApplication

from geoduck.domain.i18n import tr
from geoduck.domain.sql_errors import explain
from geoduck.ui import guide
from geoduck.ui.pro.error_card import ErrorCardView, guide_section
from geoduck.ui.pro.places import Place
from geoduck.ui.pro.tokens import LIGHT
from tests.qgis import test_pro_workspace as base
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_switch import plugin  # noqa: F401 - fixture
from tests.qgis.test_pro_workspace import _CREATED, Store, has, run, start, workspace

pytestmark = pytest.mark.qgis

coordinator = base.coordinator
delete_widgets_in_the_main_thread = base.delete_widgets_in_the_main_thread


@pytest.fixture
def opened(monkeypatch):
    """Las páginas que se abrirían en el navegador, sin abrirlo; la guía, como si estuviera instalada."""
    pages: list[tuple[str, str]] = []
    monkeypatch.setattr(guide, "available", lambda: True)
    monkeypatch.setattr(
        guide, "open_page", lambda page=guide.START, section="": pages.append((page, section)) or True
    )
    return pages


def test_the_help_menu_lists_the_guide_and_the_rest(coordinator, opened):
    ws = workspace(coordinator)
    labels = [item[0] if item else None for item in ws.help_actions()]
    assert labels == [
        tr("User guide") + "\tF1",
        tr("Start here (5 min)"),
        tr("Keyboard shortcuts"),
        tr("What's new"),
        None,
        tr("Report a problem…"),
        tr("Environment diagnostics"),
        tr("About GeoDuck"),
    ]
    ws._open_page = guide.open_page
    for item in ws.help_actions()[1:4]:
        item[1]()
    assert opened == [(guide.START, ""), (guide.SHORTCUTS, ""), (guide.WHATS_NEW, "")]
    assert ws.help_button.accessibleName()


def test_f1_opens_the_page_of_what_is_on_screen(coordinator, opened):
    start(coordinator)
    run(coordinator, "CREATE TABLE t AS SELECT 1 AS id", expect=has("t"))
    ws = workspace(coordinator)
    ws._open_page = guide.open_page
    ws.open_contextual_guide()
    ws.open_place(Place("table", "t", "memory", "main"))
    ws.open_contextual_guide()
    ws.new_query()
    ws.open_contextual_guide()
    assert [page for page, _ in opened] == [guide.START, guide.EXPLORE_TABLE, guide.SQL_EDITOR]


def test_without_the_guide_the_footer_says_so(coordinator):
    ws = workspace(coordinator)
    ws._open_page = lambda page, section="": False
    ws.open_guide(guide.START)
    assert ws.notice.text() == tr("The user guide is not included in this installation.")


def test_report_a_problem_copies_the_diagnostics_and_opens_its_page(coordinator, opened):
    from geoduck.infra.diagnostics import collect
    from geoduck.ui.pro.workspace import ProWorkspace

    ws = ProWorkspace(coordinator, collect, Store())
    _CREATED.append(ws)
    ws._open_page = guide.open_page
    QGuiApplication.clipboard().setText("")
    ws.report_problem()
    assert opened == [(guide.REPORT, "")]
    assert "GeoDuck" in QGuiApplication.clipboard().text()


def test_error_cards_link_to_their_section_only_when_the_guide_explains_them(opened):
    known = explain(
        "CatalogException", "Catalog Error: Table with name predio does not exist!", "FROM predio", 5
    )
    raw = explain("", "Something the guide does not know about", "SELECT 1", None)
    assert guide_section(known) == "not-found" and guide_section(raw) == ""
    view = ErrorCardView(known, LIGHT)
    assert view.more_button is not None and view.more_button.text() == tr("More information")
    view.more_button.click()
    assert opened == [(guide.ERRORS, "not-found")]
    assert ErrorCardView(raw, LIGHT).more_button is None


def test_the_qgis_database_menu_has_the_user_guide(plugin, iface):  # noqa: F811
    item = plugin()
    names = [action.text() for _, action in iface.menu]
    assert tr("User guide") in names
    item.unload()
    assert not [a for _, a in iface.menu if a.text() == tr("User guide")]
    assert wait_for(lambda: True)
