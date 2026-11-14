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
from geoduck.qgis_bridge.provider import decode_uri
from tests.qgis.conftest import wait_for
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
    view = load(session, "v")  # DuckDB no escribe en vistas
    assert not view.dataProvider().editable
    assert not view.startEditing()
    _, query = session.load("SELECT * FROM t", name="consulta")
    assert not query.dataProvider().editable
    keyless = load(session, "sin")  # sin clave: rowid, como ctid en PostGIS (2026-11-02)
    assert keyless.dataProvider().editable and keyless.startEditing()
    keyless.rollBack()


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
    assert layer.isEditable() and layer.editBuffer().isModified()  # los cambios pendientes se conservan
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


# -- tablas sin clave (rowid) y claves de cualquier tipo (como QGIS con PostGIS, 2026-11-02) ------------


def test_table_without_key_is_editable_through_rowid(session):
    session.sql(
        "CREATE TABLE libre AS SELECT range::INTEGER AS n, 'v' || range AS nombre, "
        "('POINT(' || range || ' 0)')::GEOMETRY AS g FROM range(10); "
        "INSERT INTO libre SELECT 99, 'copia', 'POINT(99 0)'::GEOMETRY FROM range(3)"  # 3 filas idénticas
    )
    layer = load(session, "libre")
    assert decode_uri(layer.source())["fid"] == "rowid"
    feats = {f["n"]: f.id() for f in layer.getFeatures() if f["n"] != 99}
    copies = [f.id() for f in layer.getFeatures() if f["n"] == 99]
    assert len(copies) == 3
    assert layer.startEditing()
    layer.changeAttributeValue(feats[2], layer.fields().indexOf("nombre"), "cambiada")
    layer.changeGeometry(feats[3], QgsGeometry.fromWkt("POINT(30 30)"))
    layer.deleteFeature(feats[4])
    layer.deleteFeature(copies[0])  # una sola de las tres copias idénticas
    new = QgsFeature(layer.fields())
    new["n"], new["nombre"] = 50, "nueva"
    new.setGeometry(QgsGeometry.fromWkt("POINT(50 0)"))
    layer.addFeature(new)
    assert layer.commitChanges(), layer.commitErrors()
    assert rows(session, "SELECT nombre FROM libre WHERE n = 2")[0][0] == "cambiada"
    assert rows(session, "SELECT st_astext(g) FROM libre WHERE n = 3")[0][0] == "POINT (30 30)"
    assert rows(session, "SELECT count(*) FROM libre WHERE n = 4")[0][0] == 0
    assert rows(session, "SELECT count(*) FROM libre WHERE n = 99")[0][0] == 2
    assert rows(session, "SELECT nombre FROM libre WHERE n = 50")[0][0] == "nueva"
    assert sorted(f["n"] for f in layer.getFeatures()) == sorted([0, 1, 2, 3, 5, 6, 7, 8, 9, 50, 99, 99])


def test_moved_rowids_are_detected_and_never_overwrite_another_row(session, tmp_path):
    """Si DuckDB compacta la tabla y los rowid se mueven, el guardado lo detecta por la huella."""
    from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction

    session.coordinator.attach_database(
        AttachRequest(str(tmp_path / "c.duckdb"), AccessMode.READ_WRITE, OpenAction.CREATE_NEW, alias="c")
    )
    assert wait_for(
        lambda: (
            session.coordinator.catalog is not None
            and any(d.name == "c" for d in session.coordinator.catalog.databases)
        ),
        TIMEOUT,
    )
    session.sql("CREATE TABLE c.big AS SELECT range AS n, 'v' AS s FROM range(300000); CHECKPOINT c")
    _, layer = session.load('SELECT * FROM "c"."main"."big"', name="big", source=("c", "main", "big"))
    assert decode_uri(layer.source())["fid"] == "rowid"
    target = next(layer.getFeatures(QgsFeatureRequest().setFilterExpression("n = 250000")))
    assert layer.startEditing()
    layer.changeAttributeValue(target.id(), layer.fields().indexOf("s"), "mía")
    session.sql("DELETE FROM c.big WHERE n < 200000; CHECKPOINT c")  # compacta: los rowid se mueven
    assert rows(session, "SELECT rowid FROM c.big WHERE n = 250000")[0][0] != target.id()
    before = rows(session, "SELECT count(*), sum(hash(n, s)) FROM c.big")
    assert not layer.commitChanges()
    assert any("Conflicto" in e for e in layer.commitErrors())
    assert rows(session, "SELECT count(*), sum(hash(n, s)) FROM c.big") == before  # nada escrito
    layer.rollBack()
    layer.reload()
    target = next(layer.getFeatures(QgsFeatureRequest().setFilterExpression("n = 250000")))
    assert layer.startEditing()
    layer.changeAttributeValue(target.id(), layer.fields().indexOf("s"), "mía")
    assert layer.commitChanges(), layer.commitErrors()
    assert rows(session, "SELECT n FROM c.big WHERE s = 'mía'") == ((250000,),)


def test_text_and_composite_keys_are_editable(session):
    session.sql(
        "CREATE TABLE tk (codigo VARCHAR PRIMARY KEY, nombre VARCHAR, g GEOMETRY); "
        "INSERT INTO tk SELECT 'c' || range, 'n' || range, ('POINT(' || range || ' 0)')::GEOMETRY "
        "FROM range(5); "
        "CREATE TABLE ck (a VARCHAR, b DATE, v INTEGER, PRIMARY KEY (a, b)); "
        "INSERT INTO ck VALUES ('x', DATE '2026-01-01', 1), ('x', DATE '2026-01-02', 2)"
    )
    tk = load(session, "tk")
    assert decode_uri(tk.source())["fid"] == "map"
    by_code = {f["codigo"]: f.id() for f in tk.getFeatures()}
    assert tk.startEditing()
    tk.changeAttributeValue(by_code["c1"], tk.fields().indexOf("nombre"), "uno")
    tk.deleteFeature(by_code["c2"])
    new = QgsFeature(tk.fields())
    new["codigo"], new["nombre"] = "c9", "nueve"
    tk.addFeature(new)
    assert tk.commitChanges(), tk.commitErrors()
    assert rows(session, "SELECT codigo, nombre FROM tk ORDER BY codigo") == (
        ("c0", "n0"),
        ("c1", "uno"),
        ("c3", "n3"),
        ("c4", "n4"),
        ("c9", "nueve"),
    )
    assert tk.startEditing()  # la clave identifica la entidad: no se cambia
    tk.changeAttributeValue(by_code["c0"], tk.fields().indexOf("codigo"), "otro")
    assert not tk.commitChanges()
    assert any("identifica la entidad" in e for e in tk.commitErrors())
    tk.rollBack()
    ck = load(session, "ck")
    first = next(ck.getFeatures(QgsFeatureRequest().setFilterExpression("v = 2")))
    assert ck.startEditing()
    ck.changeAttributeValue(first.id(), ck.fields().indexOf("v"), 20)
    assert ck.commitChanges(), ck.commitErrors()
    assert rows(session, "SELECT v FROM ck ORDER BY b") == ((1,), (20,))


def test_key_with_default_is_filled_by_duckdb(session):
    session.sql("CREATE TABLE ud (id UUID PRIMARY KEY DEFAULT uuid(), nombre VARCHAR)")
    layer = load(session, "ud")
    assert layer.startEditing()
    for name in ("a", "b"):
        f = QgsFeature(layer.fields())
        f["nombre"] = name
        layer.addFeature(f)
    assert layer.commitChanges(), layer.commitErrors()
    assert rows(session, "SELECT count(DISTINCT id), count(*) FROM ud") == ((2, 2),)
    assert sorted(f["nombre"] for f in layer.getFeatures()) == ["a", "b"]


def test_a_time_column_is_edited_as_a_time(session):
    """#141: una columna TIME llega a QGIS como hora (QTime) y se escribe de vuelta como TIME."""
    from qgis.PyQt.QtCore import QTime

    session.sql(
        "CREATE TABLE turnos (id INTEGER PRIMARY KEY, entrada TIME); "
        "INSERT INTO turnos VALUES (1, '08:30:15.250')"
    )
    layer = load(session, "turnos")
    index = layer.fields().indexOf("entrada")
    [feature] = layer.getFeatures()
    assert feature["entrada"] == QTime(8, 30, 15, 250)
    assert layer.startEditing()
    assert layer.changeAttributeValue(feature.id(), index, QTime(17, 45, 0, 500))
    assert layer.commitChanges(), layer.commitErrors()
    assert str(rows(session, "SELECT entrada FROM turnos WHERE id = 1")[0][0]) == "17:45:00.500000"


def test_an_interrupt_on_begin_or_rollback_never_leaves_a_transaction(session, monkeypatch):
    """#157: «Cancelar» justo sobre el BEGIN del guardado abría la transacción y nadie la revertía; y un solo
    ROLLBACK interrumpido la dejaba abortada. Ahora se revierte siempre, sin depender de los tiempos."""
    import duckdb

    from geoduck.engine import worker as worker_module

    layer = load(session)
    before = checksum(session)
    assert layer.startEditing()
    read_all(layer, [60])
    layer.changeAttributeValue(60, layer.fields().indexOf("nombre"), "interrumpido")
    original = worker_module.ConnectionHandle.execute
    calls = {"rollback": 0}

    def execute(self, text, *args, **kwargs):
        if text == "ROLLBACK":
            calls["rollback"] += 1
            if calls["rollback"] == 1:  # el primer ROLLBACK también cae bajo la interrupción
                raise duckdb.InterruptException("INTERRUPT Error: Interrupted!")
        result = original(self, text, *args, **kwargs)
        if text == "BEGIN":
            raise duckdb.InterruptException("INTERRUPT Error: Interrupted!")  # después de abrirla
        return result

    monkeypatch.setattr(worker_module.ConnectionHandle, "execute", execute)
    assert not layer.commitChanges()
    monkeypatch.undo()
    assert calls["rollback"] >= 2
    assert not session.engine.transaction_state().result(TIMEOUT).is_open
    assert checksum(session) == before
    layer.rollBack()
