# SPDX-License-Identifier: GPL-2.0-or-later
"""GeoDuck → QGIS en el diálogo único y la línea de tiempo (#148, puntos 15, 19 y 25; maquetas
`cargar-qgis`, `dialogo-unico`, `progreso-traza` y `flujo-completo`): PyQGIS real con una sesión real."""

from __future__ import annotations

import pytest
from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QPoint, QPointF, Qt
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from geoduck.domain.i18n import tr
from geoduck.domain.session import SessionState
from geoduck.domain.sql import RunScope
from geoduck.ui.pro.load import COPY
from geoduck.ui.pro.places import TABLE, Place
from geoduck.ui.pro.timeline import DONE, FAILED, RUNNING, WAITING, Step, TimelineView
from geoduck.ui.pro.transfer import INFO, NameList, NameRow
from tests.qgis import test_pro_load as base
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_load import layers_named, open_table, options_workspace, workspace

pytestmark = pytest.mark.qgis

#: Las fixtures de la carga: el complemento con su sesión y tres tablas (`puntos`, `sin_src`, `dos`).
coordinator = base.coordinator
clean = base.clean


def test_the_load_menu_has_the_layer_name_on_top_and_enter_is_copy(coordinator):
    """#148, punto 15: el nombre ya viene puesto (el de la tabla); se edita y Enter = Copia."""
    ws = workspace(coordinator)
    page = open_table(ws, "puntos")
    menu = page.load_menu
    menu.popup(QPoint(100, 100))
    QApplication.processEvents()
    edit = menu.name_edit
    assert edit.text() == "puntos"
    edit.setText("Mis puntos")
    edit.returnPressed.emit()  # Enter
    assert wait_for(lambda: layers_named("Mis puntos") and coordinator.state is SessionState.READY, 30)
    assert ws.loader.last_report.layer_name == "Mis puntos"


def test_several_tables_change_names_in_the_dialog_and_follow_the_timeline(coordinator):
    """«Cargar en QGIS ▸ Cambiar nombres…»: el diálogo único hacia QGIS, con «Copia o Conectada», un nombre
    por tabla y, al cargar, la línea de tiempo con cada capa."""
    QgsProject.instance().addMapLayer(QgsVectorLayer("Point", "dos", "memory"))  # ya hay una «dos»
    ws = workspace(coordinator)
    menu = ws._load_menu_for(
        ws, [Place(TABLE, "puntos", "memory", "main"), Place(TABLE, "dos", "memory", "main")]
    )
    texts = [w.text() for w in menu.findChildren(type(ws.dock_button)) if w.text()]
    assert tr("Change names…") in texts
    [change] = [w for w in menu.findChildren(type(ws.dock_button)) if w.text() == tr("Change names…")]
    change.click()
    window = ws.to_qgis.window
    assert window.title.text() == tr("Load in QGIS")
    assert window.source_chip.text.text() == tr("{0} GeoDuck tables").format(2)
    first, second = window.names.rows
    assert first.origin.text() == tr("from: {0}").format("memory.main.puntos")
    assert second.note.isVisibleTo(second) and second.note.property("tone") == INFO  # solo avisa
    first.start_edit()
    QTest.keyClicks(first.edit, "Puntos 2025")
    QTest.keyClick(first.edit, Qt.Key.Key_Return)
    assert first.name == "Puntos 2025" and second.editing  # Enter pasa al siguiente
    QTest.keyClick(second.edit, Qt.Key.Key_Escape)
    assert ws.to_qgis.load_button.text() == tr("Load {0} layers").format(2)
    ws.to_qgis.load_button.click()
    assert window.stack.currentIndex() == 1  # el mismo diálogo, ahora la línea de tiempo
    assert wait_for(lambda: not ws.to_qgis.running and coordinator.state is SessionState.READY, 60)
    view = window.timeline
    assert view.title.text() == tr("Done: {0} layers in QGIS").format(2)
    assert [row.name.text() for row in view.rows] == ["Puntos 2025", "dos"]
    assert all(row.status.text().startswith("✓ ") for row in view.rows)
    assert all(v.node.state == DONE for v in view.rows[0].views)
    assert layers_named("Puntos 2025")
    QApplication.processEvents()  # los botones nuevos del pie se muestran en el siguiente ciclo
    footer = [w.text() for w in window.findChildren(type(ws.dock_button)) if w.isVisibleTo(window)]
    assert tr("View on map") in footer and tr("Close") in footer


def _jobs(ws):
    from geoduck.ui.pro.drag import place_job

    return [place_job(Place(TABLE, n, "memory", "main")) for n in ("puntos", "dos")]


def test_more_options_has_the_name_and_a_searchable_list_that_never_grows(coordinator):
    """#148, punto 25: lista de alto fijo con desplazamiento; con más de 8 columnas, «Buscar columna…» y
    «Todas · Ninguna»; el nombre de la capa, ya relleno."""
    from geoduck.ui.pro.load import OPTIONS
    from geoduck.ui.pro.load_options import ROW_HEIGHT, VISIBLE_ROWS

    columns = ", ".join(f"'POINT ({i} {i})' AS wkt_{i}" for i in range(10))
    coordinator.execute_sql(f"CREATE TABLE muchas AS SELECT 1 AS id, {columns};", RunScope.ALL)
    assert wait_for(lambda: coordinator.state is SessionState.READY)
    coordinator.refresh_catalog()
    assert wait_for(lambda: any(o.name == "muchas" for o in coordinator.catalog.objects))
    ws = options_workspace(coordinator, lambda _d: None)
    open_table(ws, "muchas").load_in_qgis(OPTIONS)
    assert wait_for(lambda: ws.seen)
    dialog = ws.seen[0]
    assert dialog.name_edit.text() == "muchas"
    assert len(dialog.checks) == 10 and dialog.search is not None
    assert dialog.list.height() == VISIBLE_ROWS * ROW_HEIGHT + 10
    dialog.search.setText("wkt_3")
    assert [c for c in dialog.checks if not c.isHidden()] == [dialog.candidate_checks["wkt_3"][0]]
    dialog._check_all(True)  # «Todas»: solo las que se ven
    assert dialog.chosen_geometries() == ["wkt_3"]
    assert dialog.count.text().startswith(tr("{0} of {1} chosen").format(1, 10))
    dialog.name_edit.setText("Consumo")
    assert dialog.choice()["name"] == "Consumo"


def test_the_timeline_draws_steps_and_rows_fold(qgis_app):
    holder = TimelineView(_colors())
    holder.resize(520, 400)
    holder.show()
    first = holder.add_row("predios")
    second = holder.add_row("redes")
    first.set_steps(
        [
            Step("file", "Origen · GPKG", "C:/datos/catastro.gpkg", DONE),
            Step("bolt", "Lectura directa con DuckDB", "", DONE, 0.1),
            Step("database", "Copiando a DuckDB", "182 000 de 300 000 filas", RUNNING, 1.2, 0.6),
            Step("table", "Destino", "memory.main.predios", WAITING),
        ]
    )
    second.set_steps([Step("file", "Origen", "", FAILED)])
    holder.follow(first)
    assert first.open and not second.open  # la que avanza, abierta; las demás, plegadas
    view = first.views[2]
    assert view.bar.isVisibleTo(view) and view.bar.value() == 600 and view.time.text() == "1,2 s"
    assert view.node.state == RUNNING and first.views[3].node.state == WAITING
    click = QPointF(10, 10)
    QTest.mouseClick(second, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click.toPoint())
    assert second.open and second.user_set
    holder.follow(first)
    assert second.open  # el usuario la abrió: no se pliega sola
    holder.set_header("Listo", "memory · main", 2.0, pill="⚡ 1 directo")
    assert holder.pill.isVisibleTo(holder) and not holder.time.isVisibleTo(holder)
    holder.close()


def test_names_edit_with_double_click_or_f2_and_escape_keeps_them(qgis_app):
    names = NameList()
    names.resize(400, 300)
    names.show()
    a = names.add(NameRow(_colors(), "lecturas", "memory.main.lecturas"))
    b = names.add(NameRow(_colors(), "clientes", "memory.main.clientes"))
    QTest.mouseDClick(a.shown, Qt.MouseButton.LeftButton)
    assert a.editing
    QTest.keyClicks(a.edit, "x")
    QTest.keyClick(a.edit, Qt.Key.Key_Escape)
    assert a.name == "lecturas" and not a.editing
    b.setFocus()
    QTest.keyClick(b, Qt.Key.Key_F2)
    assert b.editing
    names.close()


def _colors():
    from geoduck.ui.pro.tokens import LIGHT

    return LIGHT


def test_copy_is_still_one_click(coordinator):
    """Los atajos siguen: «Copia» del menú carga con el nombre propuesto; si termina antes de 2 s, sin
    abrir el diálogo (basta el aviso)."""
    ws = workspace(coordinator)
    page = open_table(ws, "puntos")
    page.load_in_qgis(COPY)
    assert wait_for(lambda: layers_named("puntos") and coordinator.state is SessionState.READY, 30)
    assert ws.to_qgis.window is None


def test_a_slow_one_click_load_opens_the_timeline(coordinator, monkeypatch):
    """La opción intermedia: si el atajo sigue cargando a los 2 s, se abre la línea
    de tiempo con lo que va y sin aviso aparte; si termina antes, solo el aviso (prueba de arriba)."""
    from geoduck.ui.pro import load_window
    from geoduck.ui.pro.load import CONNECTED

    assert load_window.REVEAL_MS == 2000
    started = load_window.LoadWindow.job_started

    def slow(self, index, request):  # «pasaron los 2 s» justo al empezar: sin esperar de verdad
        started(self, index, request)
        self._reveal()

    monkeypatch.setattr(load_window.LoadWindow, "job_started", slow)
    ws = workspace(coordinator)
    page = open_table(ws, "puntos")
    page.load_in_qgis(CONNECTED)
    assert wait_for(lambda: ws.to_qgis.window is not None)
    window = ws.to_qgis.window
    assert window.stack.currentIndex() == 1  # directo a la línea de tiempo, sin el formulario
    assert wait_for(lambda: not ws.to_qgis.running and coordinator.state is SessionState.READY, 30)
    assert window.timeline.title.text() == tr("Done: 1 layer in QGIS")
    assert layers_named("puntos")
    assert ws.to_qgis.showing() and ws._loaded(ws.loader.last_report)  # la ventana ya lo dice: sin aviso
