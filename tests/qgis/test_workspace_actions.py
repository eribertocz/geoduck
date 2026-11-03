# SPDX-License-Identifier: GPL-2.0-or-later
"""G5/E4: «Cargar en QGIS ▾», registro con filtros, «Ver en el mapa» y ubicación de las acciones
(AT-UX-008, AT-UX-009; ui-ux-spec §8)."""

from __future__ import annotations

from typing import ClassVar

import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog

import geoduck
from geoduck.domain.load import LoadMode
from geoduck.domain.session import SessionState
from geoduck.ui.load_dialog import LoadDialog
from geoduck.ui.map_view import NO_EXTENT
from geoduck.ui.sql_panel import LOG_MESSAGE
from tests.qgis.conftest import FakeIface, wait_for
from tests.qgis.test_sql_panel import run
from tests.qgis.test_workspace import WorkspaceMode, plugin, qgis_window, start, toggle  # noqa: F401

pytestmark = pytest.mark.qgis

POINTS = "SELECT range AS id, ('POINT(' || range || ' 1)')::GEOMETRY('OGC:CRS84') AS g FROM range(300)"


class KeepModeDialog(LoadDialog):
    """El diálogo real de G4, aceptado sin tocar nada: se carga con la modalidad que venía marcada."""

    seen: ClassVar[list[LoadMode | None]] = []

    def exec(self):
        checked = [m for m, b in self.mode_buttons.items() if b.isChecked()]
        KeepModeDialog.seen.append(checked[0] if checked else None)
        return QDialog.DialogCode.Accepted


def layers():
    return list(QgsProject.instance().mapLayers().values())


def menu_actions(view):
    view.load_menu.aboutToShow.emit()  # se rellena al abrirse, con la disponibilidad del momento
    return {a.objectName().removeprefix("geoduckLoad_"): a for a in view.load_menu.actions()}


def presentation(plugin, where):  # noqa: F811 - `plugin` es la fixture
    plugin.action.trigger()
    if where == "panel":
        toggle(plugin.workspace)
        plugin.content.tabs.setCurrentWidget(plugin.content.sql_panel)


# -- AT-UX-008: «Cargar en QGIS ▾» en ambos modos; «Ver en el mapa» --------------------------------------


@pytest.mark.parametrize("where", ["ventana", "panel"])
@pytest.mark.parametrize("mode", list(LoadMode))
def test_load_menu_opens_the_g4_dialog_with_that_mode_and_loads_one_layer(plugin, where, mode):  # noqa: F811
    coordinator = start(plugin)
    presentation(plugin, where)
    plugin.content.load_flow._dialog_factory = KeepModeDialog
    KeepModeDialog.seen.clear()
    panel = plugin.content.sql_panel
    run(panel, coordinator, POINTS)
    view = panel.result_views()[-1]
    actions = menu_actions(view)
    assert list(actions) == ["memory", "snapshot", "connected"]
    assert all(a.isEnabled() for a in actions.values())
    assert "—" in actions["memory"].text()  # nombre y descripción
    actions[mode.value].trigger()
    assert wait_for(lambda: len(layers()) == 1 and coordinator.state is SessionState.READY, 60)
    wait_for(lambda: False, 0.3)
    assert KeepModeDialog.seen == [mode]  # el diálogo de G4 se abrió con esa modalidad marcada
    assert len(layers()) == 1  # una capa por carga, sin duplicados
    layer = layers()[0]
    assert layer.featureCount() == 300
    assert layer.providerType() == {LoadMode.MEMORY: "memory", LoadMode.SNAPSHOT: "ogr"}.get(mode, "geoduck")


@pytest.mark.parametrize("mode", list(LoadMode))
def test_a_statement_ending_in_semicolon_and_comment_loads(plugin, mode):  # noqa: F811
    """Hallazgo de E4b: la sentencia del editor incluye su `;` y el comentario que la sigue; al cargarla,
    dentro de la subconsulta, daba «Parser Error» (desde G3). Ahora `load_sql` los quita del final."""
    coordinator = start(plugin)
    plugin.content.load_flow._dialog_factory = KeepModeDialog
    KeepModeDialog.seen.clear()
    panel = plugin.content.sql_panel
    run(panel, coordinator, POINTS + " WHERE id < 100;\n-- Total por zona\nSELECT 1 AS uno;")
    panel.results.setCurrentIndex(0)
    actions = menu_actions(panel.current_view())
    actions[mode.value].trigger()
    assert wait_for(lambda: len(layers()) == 1 and coordinator.state is SessionState.READY, 60)
    assert layers()[0].featureCount() == 100
    assert "No se puede cargar" not in plugin.content.message_label.text()


def test_unavailable_modes_are_disabled_with_their_reason(plugin, monkeypatch):  # noqa: F811
    coordinator = start(plugin)
    run(plugin.content.sql_panel, coordinator, POINTS)
    view = plugin.content.sql_panel.result_views()[-1]
    reasons = dict.fromkeys(LoadMode)
    reasons[LoadMode.SNAPSHOT] = "GDAL 3.8 o superior"
    monkeypatch.setattr(coordinator, "load_modes", lambda: dict(reasons))
    actions = menu_actions(view)
    assert not actions["snapshot"].isEnabled() and "GDAL 3.8 o superior" in actions["snapshot"].text()
    assert actions["memory"].isEnabled() and actions["connected"].isEnabled()


def test_view_on_map_selects_and_zooms_to_a_valid_extent(plugin, iface):  # noqa: F811
    coordinator = start(plugin)
    content = plugin.content
    QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert not content.map_button.isEnabled()
    content.load_flow._dialog_factory = KeepModeDialog
    run(content.sql_panel, coordinator, POINTS)
    content.sql_panel.result_views()[-1].load_button.click()
    assert wait_for(lambda: len(layers()) == 1 and content.map_button.isEnabled(), 60)
    layer = layers()[0]
    content.message_label.setText("")
    content.map_button.click()
    assert iface.active_layer is layer  # seleccionada en el panel de capas
    extent = iface.mapCanvas().extent()
    assert extent.contains(layer.extent().center())  # zoom a la capa
    assert NO_EXTENT not in content.message_label.text()
    QgsProject.instance().removeMapLayer(layer.id())
    assert not content.map_button.isEnabled()  # la capa ya no está: la acción se desactiva


@pytest.mark.parametrize(
    "sql",
    ["SELECT 1 AS id, 'x' AS t", "SELECT 1 AS id, NULL::GEOMETRY('OGC:CRS84') AS g"],
    ids=["tabla", "vacia"],
)
def test_view_on_map_without_a_valid_extent_selects_without_zoom(plugin, iface, sql):  # noqa: F811
    coordinator = start(plugin)
    content = plugin.content
    content.load_flow._dialog_factory = KeepModeDialog
    run(content.sql_panel, coordinator, sql)
    content.sql_panel.result_views()[-1].load_button.click()
    assert wait_for(lambda: len(layers()) == 1 and content.map_button.isEnabled(), 60)
    before = iface.mapCanvas().extent()
    content.map_button.click()
    assert iface.active_layer is layers()[0]
    assert content.message_label.text() == NO_EXTENT
    assert iface.mapCanvas().extent() == before  # sin zoom


def test_view_on_map_minimizes_the_window_and_the_toolbar_button_restores_it(plugin):  # noqa: F811
    coordinator = start(plugin)
    content, ws = plugin.content, plugin.workspace
    content.load_flow._dialog_factory = KeepModeDialog
    plugin.action.trigger()  # ventana propia visible
    run(content.sql_panel, coordinator, POINTS)
    content.sql_panel.result_views()[-1].load_button.click()
    assert wait_for(lambda: len(layers()) == 1 and content.map_button.isEnabled(), 60)
    content.map_button.click()
    assert wait_for(ws.window.isMinimized)  # deja ver el mapa (decisión del propietario)
    assert coordinator.state is SessionState.READY  # la sesión no cambia
    plugin.action.trigger()  # el botón de GeoDuck la restaura (no la oculta)
    assert wait_for(lambda: not ws.window.isMinimized() and ws.window.isVisible())
    assert plugin.action.isChecked()
    toggle(ws)  # en el panel acoplado no se minimiza nada
    content.map_button.click()
    wait_for(lambda: False, 0.3)
    assert ws.dock.isVisible() and not ws.window.isMinimized()


# -- AT-UX-009: registro Todo / OK / Error ------------------------------------------------------------------


def log_rows(panel):
    return [r for r in range(panel.log.rowCount()) if not panel.log.isRowHidden(r)]


def test_log_filters_hide_rows_without_deleting_and_keep_the_full_message(plugin):  # noqa: F811
    coordinator = start(plugin)
    panel = plugin.content.sql_panel
    run(panel, coordinator, "SELECT 1 AS uno;\nSELECT 2 AS dos;")
    run(panel, coordinator, "SELECT * FROM inexistente;")
    buttons = panel.log_filter_buttons
    assert [buttons[k].text() for k in ("all", "ok", "error")] == ["Todo (3)", "OK (2)", "Error (1)"]
    buttons["ok"].click()
    assert len(log_rows(panel)) == 2 and panel.log.rowCount() == 3  # oculta, no borra
    buttons["error"].click()
    rows = log_rows(panel)
    assert len(rows) == 1
    message = panel.log.item(rows[0], LOG_MESSAGE)
    assert "inexistente" in message.text()
    assert message.toolTip() == message.text()  # el mensaje completo, accesible
    assert message.data(Qt.ItemDataRole.AccessibleTextRole) == message.text()
    run(panel, coordinator, "SELECT 3 AS tres;")  # una fila OK nueva no aparece con el filtro «Error»
    assert len(log_rows(panel)) == 1 and buttons["all"].text() == "Todo (4)"
    buttons["all"].click()
    assert len(log_rows(panel)) == 4


def test_the_panel_log_tab_counts_errors_and_the_filter_is_remembered(iface):
    first = geoduck.classFactory(qgis_window(iface))
    first.initGui()
    coordinator = start(first)
    first.action.trigger()
    toggle(first.workspace)  # panel: pestañas Explorador / SQL / Registro
    content, panel = first.content, first.content.sql_panel
    assert [content.tabs.tabText(i) for i in range(content.tabs.count())] == ["Explorador", "SQL", "Registro"]
    content.tabs.setCurrentIndex(0)
    wait_for(lambda: False, 0.2)
    visible = [content.tabs.widget(i).isVisible() for i in range(content.tabs.count())]
    assert visible == [True, False, False]  # solo la pestaña activa se dibuja
    run(panel, coordinator, "SELECT * FROM inexistente;")
    assert content.tabs.tabText(2) == "Registro (1)"
    panel.log_filter_buttons["error"].click()
    toggle(first.workspace)  # ventana: el registro vuelve debajo del editor y los resultados
    assert panel.splitter.widget(2) is panel.log_section and content.tabs.count() == 0  # sin pestañas
    first.unload()
    iface.mainWindow().close()
    second_iface = qgis_window(FakeIface())
    second = geoduck.classFactory(second_iface)
    second.initGui()
    try:
        assert second.content.sql_panel.log_filter == "error"
        assert second.content.sql_panel.log_filter_buttons["error"].isChecked()
    finally:
        second.unload()
        second_iface.mainWindow().close()


# -- ubicación de las acciones existentes (ui-ux-spec §8) -----------------------------------------------


def test_existing_actions_are_where_section_8_puts_them(plugin):  # noqa: F811
    content = plugin.content
    card = content.databases_card
    # Sin sesión: «Iniciar sesión» al pie de «Bases de datos» (decisión del propietario, 2026-11-02)
    assert card.isAncestorOf(content.start_button) and content.start_button.isVisibleTo(content)
    assert not content.close_button.isVisibleTo(content)
    assert content.add_button.menu().actions() == [content.open_action, content.create_action]
    assert not hasattr(content, "spatial_action") and not hasattr(
        content, "more_button"
    )  # sin «Activar spatial…»
    coordinator = start(plugin)
    assert not content.start_button.isVisibleTo(content) and content.close_button.isVisibleTo(content)
    assert card.isAncestorOf(content.close_button) and content.close_button.text() == "Cerrar sesión"
    assert content.session_bar.isAncestorOf(content.rollback_button) and content.rollback_button.isHidden()
    assert content.refresh_button.isEnabled()
    item = content.explorer.findItems("main", Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)[0]
    assert item is not None
    explorer = content.explorer
    root = explorer.topLevelItem(0)
    menu = explorer.database_menu(root)
    assert menu.actions() == [content.detach_action]
    assert not content.detach_action.isEnabled()  # la raíz no se desadjunta (protección de G1/G3)
    assert explorer.database_menu(root.child(0)) is None  # un esquema no tiene ese menú
    events = []
    coordinator.subscribe(events.append)
    content.refresh_button.click()
    assert wait_for(lambda: coordinator.state is SessionState.READY and events)
