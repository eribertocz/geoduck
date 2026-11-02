# SPDX-License-Identifier: GPL-2.0-or-later
"""G4/E4: diagnóstico y reparación de geometrías (AT-SPA-004; spatial-spec §9; F-98).

Estados distintos (NULL, vacía, ilegible, inválida, válida); diagnosticar no cambia nada; reparar crea una
copia nueva con los cambios informados; cancelar no publica nada. Sin la extensión `spatial`.
"""

from __future__ import annotations

import pytest
from qgis.core import QgsProject, QgsWkbTypes
from qgis.PyQt.QtWidgets import QDialog

import geoduck
from geoduck.app.events import LoadFinished
from geoduck.domain.load import LoadMode
from geoduck.domain.validity import GeometryDiagnosis, RepairReport
from geoduck.qgis_bridge.validity import CancelledError, DiagnoseTask, RepairTask
from geoduck.ui.validity_dialog import ValidityDialog
from tests.qgis.conftest import wait_for
from tests.qgis.test_multi_geometry import TIMEOUT, Session

pytestmark = pytest.mark.qgis

#: 1 válida, 2 inválidas (pajarita; anillo degenerado), 1 vacía, 1 NULL.
GEOMS = (
    "CREATE TABLE geoms (id INTEGER PRIMARY KEY, g GEOMETRY, w BLOB); INSERT INTO geoms VALUES "
    "(1, 'POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))', NULL), "
    "(2, 'POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))', NULL), "
    "(3, 'POLYGON((0 0, 1 0, 0 0))', NULL), "
    "(4, 'POLYGON EMPTY', NULL), "
    "(5, NULL, NULL)"
)


@pytest.fixture
def session(qgis_app):
    s = Session()
    s.sql(GEOMS)
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def load(session, mode=LoadMode.MEMORY, **kw):
    kw.setdefault("crs_override", "")
    ev = session.load(mode, 'SELECT id, g FROM "memory"."main"."geoms"', "geoms", **kw)
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    return QgsProject.instance().mapLayer(ev.report.layer_id)


def run_task(task):
    """Ejecuta una QgsTask en este hilo y devuelve lo que entrega a `on_done`."""
    out = []
    task._on_done = out.append
    ok = task.run()
    task.finished(ok)
    return out[0]


def snapshot_of(layer):
    return {f["id"]: f.geometry().asWkt() for f in layer.getFeatures()}


@pytest.mark.parametrize("mode", list(LoadMode))
def test_diagnosis_counts_each_state_and_changes_nothing(session, mode):
    kw = {"source": ("memory", "main", "geoms"), "source_kind": "table"} if mode is LoadMode.CONNECTED else {}
    layer = load(session, mode, **kw)
    before = snapshot_of(layer)
    source_before = session.rows("SELECT hash(g) FROM geoms ORDER BY id")
    diag = run_task(DiagnoseTask(layer, None))
    assert isinstance(diag, GeometryDiagnosis)
    assert (diag.examined, diag.valid, diag.invalid, diag.empty, diag.null, diag.unreadable) == (
        5,
        1,
        2,
        1,
        1,
        0,
    )
    by_id = {f.id(): f["id"] for f in layer.getFeatures()}
    assert sorted(by_id[f] for f in diag.invalid_fids) == [2, 3]
    reasons = dict(diag.reasons)
    assert "Self-intersection" in reasons[diag.invalid_fids[0]] or "intersec" in str(diag.reasons).lower()
    assert snapshot_of(layer) == before  # la capa no cambia
    assert session.rows("SELECT hash(g) FROM geoms ORDER BY id") == source_before  # ni el origen
    assert "Inválidas: 2" in "\n".join(diag.lines())


def test_connected_marked_wkb_counts_unreadable_apart_from_null(session):
    session.sql(
        "UPDATE geoms SET w = CASE id WHEN 1 THEN ST_AsWKB(g) WHEN 2 THEN from_hex('0101') ELSE NULL END"
    )
    ev = session.load(
        LoadMode.CONNECTED,
        'SELECT id, w FROM "memory"."main"."geoms"',
        "w",
        geometry="w",
        formats=(("w", "wkb"),),
        crs_override="",
        source=("memory", "main", "geoms"),
        source_kind="table",
    )
    assert isinstance(ev, LoadFinished), getattr(ev, "message", ev)
    layer = QgsProject.instance().mapLayer(ev.report.layer_id)
    diag = run_task(DiagnoseTask(layer, None))
    assert (diag.valid, diag.unreadable, diag.null) == (1, 1, 3)
    assert [f["id"] for f in layer.getFeatures() if f.id() in diag.unreadable_fids] == [2]


def test_repair_makes_a_new_copy_and_reports_every_change(session):
    layer = load(session)
    before = snapshot_of(layer)
    diag = run_task(DiagnoseTask(layer, None))
    report = run_task(RepairTask(layer, diag.invalid_fids, None))
    assert isinstance(report, RepairReport)
    assert report.repaired == 2 and report.failed_fids == ()
    assert report.changed_type == 2  # pajarita → MultiPolygon; anillo degenerado → LineString (F-98)
    assert report.changed_parts >= 1
    names = set(report.layers)
    assert names == {
        "geoms (reparada) — Polygon",
        "geoms (reparada) — LineString",
        "geoms (reparada) — sin geometría",
    }
    copies = {lyr.name(): lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() in names}
    assert sum(lyr.featureCount() for lyr in copies.values()) == 5
    polys = copies["geoms (reparada) — Polygon"]
    assert all(f.geometry().isGeosValid() or f.geometry().isEmpty() for f in polys.getFeatures())
    assert QgsWkbTypes.isMultiType(polys.wkbType())
    assert snapshot_of(layer) == before  # la original no cambia
    text = report.message()
    assert "2 geometrías reparadas" in text and "2 cambiaron de tipo" in text and "no cambia" in text


def test_cancel_publishes_nothing(session):
    layer = load(session)
    count = len(QgsProject.instance().mapLayers())
    diag = run_task(DiagnoseTask(layer, None))
    task = RepairTask(layer, diag.invalid_fids, None)
    task.cancel()
    result = run_task(task)
    assert isinstance(result, CancelledError)
    assert len(QgsProject.instance().mapLayers()) == count
    cancelled = DiagnoseTask(layer, None)
    cancelled.cancel()
    assert isinstance(run_task(cancelled), CancelledError)


def test_dialog_asks_before_repairing():
    diag = GeometryDiagnosis("id", "capa", 3, 1, 2, 0, 0, 0, (1, 2), (), ((1, "Self-intersection"),))
    calls = []
    answers = [False, True]
    dialog = ValidityDialog(diag, on_repair=lambda: calls.append(1), confirm=lambda *_: answers.pop(0))
    assert dialog.repair_button.isEnabled()
    assert (
        "Inválidas: 2" in dialog.summary_label.text() and "Self-intersection" in dialog.summary_label.text()
    )
    dialog.repair_button.click()
    assert calls == []
    dialog.repair_button.click()
    assert calls == [1]
    valid = GeometryDiagnosis("id", "capa", 1, 1)
    assert not ValidityDialog(valid, on_repair=lambda: None).repair_button.isEnabled()


def test_layer_menu_action_diagnoses_and_selects(iface, session):
    plugin = geoduck.classFactory(iface)
    plugin.initGui()
    try:
        assert plugin.validity.action in iface.layer_actions
        shown = []

        class Auto(ValidityDialog):
            def exec(self):
                shown.append(self)
                return QDialog.DialogCode.Rejected

        plugin.validity.dialog_factory = Auto
        layer = load(session)
        plugin.validity.register([layer.id()])
        assert layer.id() in iface.layer_actions[plugin.validity.action]
        iface.active_layer = layer
        plugin.validity.action.trigger()
        assert wait_for(lambda: bool(shown), TIMEOUT)
        assert sorted(f["id"] for f in layer.selectedFeatures()) == [2, 3]
        assert "2 inválidas" in plugin.content.message_label.text()
    finally:
        plugin.unload()
    assert not iface.layer_actions
