# SPDX-License-Identifier: GPL-2.0-or-later
"""Modalidad Conectada, edición (G3/E6; AT-BRD-010; qgis-bridge-spec §5.4).

Guardado atómico desde `beforeCommitChanges`: conflictos por huella, escrituras por lotes, validación
previa, transacción del usuario, y nunca éxito en QGIS sin COMMIT en DuckDB.
"""

from __future__ import annotations

import time

import pytest
from qgis.core import QgsFeature, QgsFeatureRequest, QgsGeometry, QgsProject

from geoduck.app.events import PreviewsInvalidated
from tests.qgis.test_load_connected import Session

pytestmark = pytest.mark.qgis

TIMEOUT = 60
N = 20_000

TABLE = (
    "CREATE SEQUENCE s START 100000; "
    "CREATE TABLE t (id BIGINT PRIMARY KEY DEFAULT nextval('s'), nombre VARCHAR NOT NULL, valor DOUBLE, "
    "dia DATE, grande HUGEINT, geom GEOMETRY('OGC:CRS84')); "
    "INSERT INTO t SELECT range, 'n' || range, range * 0.5, DATE '2026-01-01' + range::INTEGER % 300, range, "
    f"('POINT(' || (range % 200) || ' ' || (range // 200) || ')')::GEOMETRY('OGC:CRS84') FROM range({N})"
)


@pytest.fixture
def session(qgis_app):
    s = Session()
    s.loader.on_data_changed = s.coordinator.mark_data_changed
    s.sql(TABLE)
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def load(session, table="t"):
    _, layer = session.load(
        f'SELECT * FROM "memory"."main"."{table}"', name=table, source=("memory", "main", table)
    )
    return layer


def rows(session, sql):
    return session.engine.query(sql, max_rows=100_000, priority=False).future.result(TIMEOUT).rows


def checksum(session):
    return rows(session, "SELECT count(*), sum(hash(id, nombre, valor, dia, grande, geom)) FROM t")[0]


def read_all(layer, fids):
    return {f.id(): f for f in layer.getFeatures(QgsFeatureRequest().setFilterFids(fids))}


def test_editability(session):
    layer = load(session)
    assert layer.dataProvider().editable
    assert layer.startEditing()
    layer.rollBack()
    session.sql("CREATE VIEW v AS SELECT * FROM t; CREATE TABLE sin AS SELECT * FROM t LIMIT 3")
    for name in ("v", "sin"):
        other = load(session, name)
        assert not other.dataProvider().editable
        assert not other.startEditing()


def test_update_delete_insert_in_one_transaction(session):
    layer = load(session)
    epoch = session.coordinator.data_epoch
    assert layer.startEditing()
    feats = read_all(layer, [1, 2, 3])
    idx = layer.fields().indexOf("nombre")
    assert layer.changeAttributeValue(1, idx, "cambiado")
    assert layer.changeAttributeValue(2, layer.fields().indexOf("dia"), feats[2]["dia"].addDays(1))
    assert layer.changeGeometry(3, QgsGeometry.fromWkt("POINT(500 500)"))
    assert layer.deleteFeature(4)
    new = QgsFeature(layer.fields())
    new["nombre"] = "nueva"
    new["valor"] = 1.25
    new.setGeometry(QgsGeometry.fromWkt("POINT(7 8)"))
    assert layer.addFeature(new)
    assert layer.commitChanges(), layer.commitErrors()
    assert rows(session, "SELECT nombre FROM t WHERE id = 1")[0][0] == "cambiado"
    assert str(rows(session, "SELECT dia FROM t WHERE id = 2")[0][0]) == "2026-01-04"
    assert rows(session, "SELECT st_astext(geom), st_crs(geom) FROM t WHERE id = 3")[0] == (
        "POINT (500 500)",
        "OGC:CRS84",
    )
    assert rows(session, "SELECT count(*) FROM t WHERE id = 4")[0][0] == 0
    added = rows(session, "SELECT id, valor, st_astext(geom) FROM t WHERE nombre = 'nueva'")
    assert added == ((100000, 1.25, "POINT (7 8)"),)
    assert layer.featureCount() == N
    assert [
        f.id() for f in layer.getFeatures(QgsFeatureRequest().setFilterExpression("nombre = 'nueva'"))
    ] == [100000]
    assert session.coordinator.data_epoch > epoch  # vistas previas marcadas como posiblemente obsoletas
    assert any(isinstance(e, PreviewsInvalidated) for e in session.events)


def test_conflict_keeps_buffer_and_changes_nothing_then_retry_overwrites(session):
    layer = load(session)
    assert layer.startEditing()
    read_all(layer, [10, 11])
    session.sql("UPDATE t SET valor = -1 WHERE id = 10")  # cambio en DuckDB después de leer
    before = checksum(session)
    layer.changeAttributeValue(10, layer.fields().indexOf("nombre"), "mío")
    layer.changeAttributeValue(11, layer.fields().indexOf("nombre"), "mío también")
    assert not layer.commitChanges()
    assert any("Conflicto" in e for e in layer.commitErrors())
    assert checksum(session) == before  # ROLLBACK: ni siquiera la fila 11
    assert layer.isEditable() and len(layer.editBuffer().changedAttributeValues()) == 2  # búfer intacto
    assert layer.commitChanges(), layer.commitErrors()  # reintento: sobrescribe a sabiendas
    assert rows(session, "SELECT id, nombre, valor FROM t WHERE id IN (10, 11) ORDER BY id") == (
        (10, "mío", -1.0),
        (11, "mío también", 5.5),
    )


def test_deleted_elsewhere_is_a_conflict(session):
    layer = load(session)
    assert layer.startEditing()
    read_all(layer, [20])
    session.sql("DELETE FROM t WHERE id = 20")
    layer.changeAttributeValue(20, layer.fields().indexOf("nombre"), "x")
    assert not layer.commitChanges()
    assert any("Conflicto" in e for e in layer.commitErrors())
    layer.rollBack()


def test_edit_without_prior_read_records_the_fingerprint_on_edit(session):
    layer = load(session)
    assert layer.startEditing()
    layer.changeAttributeValue(30, layer.fields().indexOf("valor"), 3.0)  # sin leerla en esta edición
    assert layer.commitChanges(), layer.commitErrors()
    assert rows(session, "SELECT valor FROM t WHERE id = 30")[0][0] == 3.0


def test_failed_write_rolls_back_everything(session):
    layer = load(session)
    before = checksum(session)
    assert layer.startEditing()
    read_all(layer, [40])
    layer.changeAttributeValue(40, layer.fields().indexOf("nombre"), "ok")
    bad = QgsFeature(layer.fields())  # nombre NOT NULL: el INSERT falla después del UPDATE
    bad.setGeometry(QgsGeometry.fromWkt("POINT(1 1)"))
    layer.addFeature(bad)
    assert not layer.commitChanges()
    assert any("revirtió" in e for e in layer.commitErrors())
    assert checksum(session) == before
    assert layer.isEditable() and layer.editBuffer().isModified()
    layer.rollBack()


def test_validation_before_touching_duckdb(session):
    layer = load(session)
    fields = layer.fields()
    before = checksum(session)
    cases = [
        ("clave", lambda: layer.changeAttributeValue(1, fields.indexOf("id"), 999999)),
        ("solo lectura", lambda: layer.changeAttributeValue(1, fields.indexOf("grande"), "5")),
        ("incompatible", lambda: layer.changeGeometry(1, QgsGeometry.fromWkt("LINESTRING(0 0, 1 1)"))),
    ]
    for text, edit in cases:
        assert layer.startEditing()
        read_all(layer, [1])
        edit()
        assert not layer.commitChanges()
        assert any(text in e for e in layer.commitErrors()), (text, layer.commitErrors())
        layer.rollBack()
    assert checksum(session) == before


def test_open_user_transaction_rejects_the_save(session):
    layer = load(session)
    assert layer.startEditing()
    read_all(layer, [50])
    layer.changeAttributeValue(50, layer.fields().indexOf("nombre"), "x")
    session.sql("BEGIN")
    assert not layer.commitChanges()
    assert any("transacción abierta" in e for e in layer.commitErrors())
    session.sql("ROLLBACK")
    assert layer.commitChanges(), layer.commitErrors()


def test_explicit_id_without_sequence(session):
    session.sql("CREATE TABLE k (id INTEGER PRIMARY KEY, nombre VARCHAR)")
    layer = load(session, "k")
    assert layer.dataProvider().editable
    assert layer.startEditing()
    f = QgsFeature(layer.fields())
    f["nombre"] = "sin id"
    layer.addFeature(f)
    assert not layer.commitChanges()
    assert any("no tiene secuencia" in e for e in layer.commitErrors())
    layer.rollBack()
    assert layer.startEditing()
    f = QgsFeature(layer.fields())
    f["id"], f["nombre"] = 7, "con id"
    layer.addFeature(f)
    assert layer.commitChanges(), layer.commitErrors()
    assert rows(session, "SELECT * FROM k") == ((7, "con id"),)


@pytest.mark.parametrize("n", [100, 1_000, 10_000])
def test_batches(session, n):
    layer = load(session)
    assert layer.startEditing()
    idx = layer.fields().indexOf("valor")
    t0 = time.perf_counter()
    layer.beginEditCommand("lote")
    for fid in range(n):
        layer.changeAttributeValue(fid, idx, -fid)
    layer.endEditCommand()
    for fid in range(n, n + n // 10):
        layer.deleteFeature(fid)
    ok = layer.commitChanges()
    elapsed = time.perf_counter() - t0
    assert ok, layer.commitErrors()
    assert rows(session, f"SELECT count(*), sum(valor) FROM t WHERE id < {n}")[0] == (n, -sum(range(n)))
    assert rows(session, "SELECT count(*) FROM t")[0][0] == N - n // 10
    assert elapsed < 60
