# SPDX-License-Identifier: GPL-2.0-or-later
"""Archivos → DuckDB (qgis-import-spec §10; decisión del propietario, 2026-11-07), con QGIS, coordinador y
worker DuckDB reales. Todo lo lee y lo copia DuckDB, nunca QGIS:

- «Importar archivos…» con el selector → los tres pasos con «Archivos → DuckDB»;
- archivos soltados en una base de la barra lateral (el lago) o en cualquier parte;
- soltados en el editor: su lectura en el cursor, sin ejecutarla;
- un formato que no está en la lista, en gris con «ábrelo primero en QGIS»;
- un archivo de GDAL sin `spatial`: la nota pide permiso y GeoDuck no la carga sin ese clic.
"""

from __future__ import annotations

import duckdb
import pyarrow as pa
import pytest
from pyarrow import feather
from qgis.PyQt.QtCore import QCoreApplication, QMimeData, QPoint, QPointF, Qt, QUrl
from qgis.PyQt.QtGui import QDragEnterEvent, QDropEvent

from geoduck.domain.files import file_filters, unsupported_lines
from geoduck.domain.i18n import tr
from geoduck.ui.pro.add_layers import NEEDS_SPATIAL
from geoduck.ui.pro.drag import accepts, file_paths
from geoduck.ui.pro.widgets import lines_html
from geoduck.ui.pro.workspace import ProWorkspace
from tests.qgis import test_pro_send as send
from tests.qgis.conftest import wait_for
from tests.qgis.test_pro_send import (
    _CREATED,
    DB,
    Store,
    add_all,
    database_item,
    drop,
    has_tables,
    to_step_two,
)

pytestmark = pytest.mark.qgis

#: Las fixtures de «Capas de QGIS → DuckDB»: el complemento con una sesión lista y la limpieza.
coordinator = send.coordinator
clean = send.clean

TIMEOUT = 60


def _spatial_available() -> bool:
    try:
        con = duckdb.connect()
        con.execute("LOAD spatial")
        con.close()
    except duckdb.Error:
        return False
    return True


def workspace(coordinator, files=()):
    asked: list = []

    def ask_files(title, filters):
        asked.append((title, filters))
        return list(files)

    ws = ProWorkspace(coordinator, lambda: None, Store(), ask_files=ask_files)
    ws.asked = asked
    _CREATED.append(ws)
    ws.resize(1300, 800)
    ws.show()
    return ws


@pytest.fixture
def data(tmp_path):
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT i AS id, 'n' || i AS nombre FROM range(9) r(i)")
    con.execute(f"COPY t TO '{tmp_path / 'lecturas.parquet'}' (FORMAT parquet)")
    con.execute(f"COPY t TO '{tmp_path / 'clientes.csv'}' (FORMAT csv, HEADER)")
    con.close()
    feather.write_feather(pa.table({"id": [1, 2, 3]}), str(tmp_path / "medidas.arrow"))
    (tmp_path / "vieja.sqlite").write_bytes(b"SQLite format 3\x00")
    (tmp_path / "capa.gpkg").write_bytes(b"")
    return tmp_path


def urls_mime(paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def wait_scanned(ws):
    return wait_for(lambda: not ws.to_duckdb._scanning and ws.to_duckdb._candidates, TIMEOUT)


def test_import_files_lists_them_and_duckdb_copies_them(coordinator, data):
    paths = [data / "lecturas.parquet", data / "clientes.csv", data / "medidas.arrow"]
    ws = workspace(coordinator, [str(p) for p in paths])
    ws.import_files()
    _title, filters = ws.asked[0]
    assert filters == file_filters() and "*.parquet" in filters[0] and "*.sqlite" not in filters[0]
    flow = ws.to_duckdb
    window = flow.window
    assert wait_scanned(ws)
    assert window.title.text().startswith(tr("Files → DuckDB"))
    assert len(window.chosen()) == 3 and not window.note.isVisible()
    detail = window.rows["file:0"].text(1)
    assert "Parquet" in detail and tr("{0} rows").format(9) in detail
    dialog = to_step_two(ws)
    assert not dialog.reproject_row.isVisible()  # DuckDB lo copia tal cual
    add_all(ws, coordinator)
    assert [s["state"] for s in flow.states] == ["done"] * 3
    assert has_tables(coordinator, {"lecturas", "clientes", "medidas"})
    assert tr("{0} tables added to DuckDB from files").format(3) in flow.done_text()


def test_files_dropped_on_a_database_go_there_and_light_up_the_lake(coordinator, data):
    ws = workspace(coordinator)
    item = database_item(ws, DB)
    tree = ws.sidebar.tree
    mime = urls_mime([data / "lecturas.parquet"])
    assert accepts(mime) and file_paths(mime) == [str(data / "lecturas.parquet")]
    pos = tree.visualItemRect(item).center()
    enter = QDragEnterEvent(
        pos, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    tree.dragEnterEvent(enter)
    assert enter.isAccepted() and tree.drop_item is item  # el pato al lago
    dropped = []
    tree.files_dropped.connect(lambda paths, target: dropped.append((paths, target)))
    event = drop(tree, mime, pos)
    assert event.dropAction() == Qt.DropAction.CopyAction
    assert dropped == [([str(data / "lecturas.parquet")], (DB, "main"))]
    assert wait_scanned(ws) and ws.to_duckdb._destination == (DB, "main")


def test_unsupported_files_get_a_clear_notice_and_the_others_go_on(coordinator, data):
    """Decisión del propietario (2026-11-07): un archivo fuera de la lista no entra al diálogo; el aviso
    dice cuáles, qué hacer y que los demás siguen, con «Abrir en QGIS»."""
    ws = workspace(coordinator)
    other = data / "plano.dwg"
    other.write_bytes(b"x")
    ws.import_files(paths=[str(data / "vieja.sqlite"), str(other), str(data / "lecturas.parquet")])
    text = ws.last_toast.text.text()
    lines = unsupported_lines([str(data / "vieja.sqlite"), str(other)], 1)
    assert lines == [
        tr("«{0}» is not in GeoDuck's list").format("vieja.sqlite"),
        tr("Read it with SQL in the editor, or open it in QGIS and then add the layer"),
        tr("GeoDuck cannot read: {0}").format("plano.dwg"),
        tr("The other file goes on to «Files → DuckDB»"),
    ]
    assert text == lines_html(lines)
    assert wait_scanned(ws)
    assert list(ws.to_duckdb.window.rows) == ["file:0"]  # solo el compatible
    assert ws.to_duckdb._candidates[0].name == "lecturas"


def test_only_unsupported_files_open_no_dialog_and_qgis_can_open_them(coordinator, tmp_path):
    import sqlite3

    from qgis.core import QgsProject

    path = tmp_path / "vieja.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE clientes (id INTEGER PRIMARY KEY, nombre TEXT)")
    con.execute("INSERT INTO clientes VALUES (1, 'a')")
    con.commit()
    con.close()
    ws = workspace(coordinator)
    ws.import_files(paths=[str(path)])
    assert ws.to_duckdb.window is None and ws.last_toast is not None
    before = len(QgsProject.instance().mapLayers())
    ws.open_in_qgis([str(path)])  # «Abrir en QGIS»
    assert len(QgsProject.instance().mapLayers()) == before + 1


@pytest.mark.skipif(_spatial_available(), reason="aquí `spatial` ya se puede cargar sin instalar")
def test_a_gdal_file_without_spatial_asks_before_installing(coordinator, data):
    ws = workspace(coordinator)
    ws.import_files(paths=[str(data / "capa.gpkg")])
    assert wait_scanned(ws)
    window = ws.to_duckdb.window
    assert ws.to_duckdb._candidates[0].problem == NEEDS_SPATIAL
    assert window.note.isVisible() and "GeoPackage" in window.note_text.text()
    assert window.spatial_button.text() == tr("Install and continue")


def test_without_the_click_geoduck_does_not_load_spatial(coordinator, data):
    ws = workspace(coordinator)
    ws.import_files(paths=[str(data / "capa.gpkg")])
    assert wait_scanned(ws)
    assert ws.to_duckdb.window.note.isVisible()
    rows = []
    coordinator.read_rows(
        "SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'", 1, rows.append
    )
    assert wait_for(lambda: rows, TIMEOUT)
    assert not rows[0].rows or not rows[0].rows[0][0]


def drop_on_editor(page, mime):
    viewport = page.editor.viewport()
    pos = QPoint(20, 10)
    buttons, keys = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    enter = QDragEnterEvent(pos, Qt.DropAction.CopyAction, mime, buttons, keys)
    QCoreApplication.sendEvent(viewport, enter)
    event = QDropEvent(QPointF(pos), Qt.DropAction.CopyAction, mime, buttons, keys)
    QCoreApplication.sendEvent(viewport, event)
    return enter, event


def test_files_dropped_on_the_editor_write_create_table_without_running(coordinator, data):
    """Decisión del propietario (2026-11-07): soltar archivos en el editor es llevarlos a DuckDB: un
    `CREATE TABLE … AS SELECT *` por archivo, en la misma pestaña, sin ejecutar; los nombres no chocan."""
    ws = workspace(coordinator)
    ws.new_query()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    page.editor.setText("SELECT 1;")
    page.editor.setCursorPosition(0, 3)
    assert wait_for(lambda: coordinator.vocabulary() is not None, TIMEOUT)  # para no citar de más
    paths = [data / "lecturas.parquet", data / "clientes.csv"]
    enter, event = drop_on_editor(page, urls_mime(paths))
    assert enter.isAccepted() and event.isAccepted()
    database, schema = page.drop_target()
    text = page.editor.text()
    assert text.startswith("SELECT 1;\n\n")
    assert f"CREATE TABLE {database}.{schema}.lecturas AS\nSELECT * FROM read_parquet('{paths[0]}');" in text
    assert f"CREATE TABLE {database}.{schema}.clientes AS\nSELECT * FROM read_csv('{paths[1]}');" in text
    assert page.editor.getCursorPosition() == (2, 0)  # en la primera sentencia escrita
    assert ws.to_duckdb.window is None and not page.results  # nada se ejecutó ni se abrió


def test_layers_dropped_on_the_editor_open_the_dialog(coordinator):
    from tests.qgis.test_pro_send import layers_mime, points

    ws = workspace(coordinator)
    ws.new_query()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    page.editor.setText("")
    _model, mime = layers_mime([points("capa", 3)])
    drop_on_editor(page, mime)
    assert page.editor.text() == ""
    assert ws.to_duckdb.window is not None and ws.to_duckdb.window.isVisible()


def test_an_arrow_file_dropped_on_the_editor_goes_to_the_import(coordinator, data):
    ws = workspace(coordinator)
    ws.new_query()
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    page.editor.setText("")
    drop_on_editor(page, urls_mime([data / "medidas.arrow"]))
    assert page.editor.text() == ""
    assert wait_scanned(ws) and ws.to_duckdb.window.isVisible()


@pytest.mark.skipif(not _spatial_available(), reason="extensión spatial no instalada aquí")
def test_with_the_click_spatial_loads_and_the_layers_appear(coordinator, tmp_path):
    con = duckdb.connect()
    con.execute("LOAD spatial")
    con.execute("CREATE TABLE p AS SELECT i AS id, ST_Point(i, i) AS geom FROM range(3) r(i)")
    path = tmp_path / "pozos.gpkg"
    con.execute(f"COPY p TO '{path}' (FORMAT gdal, DRIVER 'GPKG')")
    con.close()
    ws = workspace(coordinator)
    ws.import_files(paths=[str(path)])
    assert wait_scanned(ws)
    window = ws.to_duckdb.window
    assert window.note.isVisible()
    assert wait_for(lambda: window.spatial_button.text() == tr("Load and continue"), TIMEOUT)
    window.spatial_button.click()  # el permiso del usuario
    assert wait_for(lambda: not window.note.isVisible() and "file:0" in window.rows, TIMEOUT)
    assert wait_for(lambda: ws.to_duckdb._candidates[0].problem is None, TIMEOUT)
    assert window.rows["file:0"].text(0) == "pozos"
    to_step_two(ws)
    add_all(ws, coordinator)
    assert has_tables(coordinator, {"pozos"})


def test_write_query_reads_a_file_outside_the_list_with_sql(coordinator, data):
    """«Escribir consulta»: el GDAL de DuckDB lo lee; una pestaña con su CREATE TABLE, sin ejecutar."""
    ws = workspace(coordinator)
    path = str(data / "vieja.sqlite")
    ws.write_query([path])
    page = ws.tabs.page(ws.tabs.bar.currentIndex())
    assert wait_for(lambda: "ST_Read" in page.editor.text(), TIMEOUT)
    text = page.editor.text()
    assert "spatial;" in text.splitlines()[0]  # visible: lo decide el usuario al ejecutar
    assert f"SELECT * FROM ST_Read('{path}');" in text and "CREATE TABLE" in text
    assert not page.results
