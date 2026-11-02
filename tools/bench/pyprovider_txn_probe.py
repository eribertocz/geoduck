# SPDX-License-Identifier: GPL-2.0-or-later
# ruff: noqa: N802, N803, N806, B008, E501, PLR0917 - firmas de la API de QGIS y SQL de prueba en una línea
"""Spike G3-D: guardado atómico y detección de conflictos en la edición conectada (no es código del complemento).

Problema medido en G3-C: QGIS guarda llamando a varios métodos del proveedor uno tras otro y quita de su
búfer lo que cada uno confirma; un proveedor Python no puede deshacer lo ya aceptado (pérdida silenciosa
con una transacción por guardado, o guardado parcial con una por método).

Prototipo «guardado previo»: GeoDuck escucha `QgsVectorLayer.beforeCommitChanges`, lee el búfer de
edición completo y lo aplica en **una** transacción del `SessionWorker`:

  1. conflictos: compara `hash(fila)` actual con la huella guardada cuando QGIS leyó esa fila (control
     optimista); si alguna cambió o desapareció, ROLLBACK y nada se escribe;
  2. validación: tipos de geometría compatibles con la capa (la misma comprobación que hace QGIS);
  3. escrituras por lotes (`row`, `many` o `arrow`), con ids de altas pedidos antes a la secuencia;
  4. COMMIT. Cualquier error o cancelación → ROLLBACK.

Después QGIS llama a los métodos del proveedor: si el guardado previo confirmó, devuelven éxito (y los ids
nuevos); si no, devuelven error y QGIS conserva el búfer entero. Así QGIS informa éxito solo si DuckDB
confirmó.

Uso: python pyprovider_txn_probe.py --sizes 100 1000 10000 --out resultado.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyprovider_edit_probe as edit
import pyprovider_probe as base


def plain(v):
    """NULL de QGIS (QVariant nulo en PyQt5, None en PyQt6) → None."""
    if v is None or (hasattr(v, "isNull") and v.isNull()):
        return None
    return v


def build_txn(Editable):  # noqa: PLR0915 - prototipo completo
    from qgis.core import Qgis, QgsDataProvider, QgsWkbTypes

    class Txn(Editable):
        @classmethod
        def providerKey(cls):
            return "geoduck_txn"

        @classmethod
        def createProvider(cls, uri, options, flags=Qgis.DataProviderReadFlags()):
            return Txn(uri, options, flags)

        def __init__(
            self, uri="", options=QgsDataProvider.ProviderOptions(), flags=Qgis.DataProviderReadFlags()
        ):
            super().__init__(uri, options, flags)
            parts = dict(x.split("=", 1) for x in uri.split("|") if "=" in x)
            self.batch = parts.get("batch", "arrow")
            self.check = parts.get("check", "hash") != "none"
            self.capture = False
            self.seen: dict[int, int] = {}
            self.result: dict | None = None
            if self._valid:
                names = [f.name() for f in self._fields] + [self.geom]
                self.hash_expr = "hash(" + ", ".join(base._q(n) for n in names) + ")"

        # Los métodos de edición solo informan lo que el guardado previo ya hizo (o no).
        def _verdict(self):
            r = self.result
            if r is None:
                self.pushError(
                    "Guardado sin pasar por GeoDuck: rechazado para no escribir fuera de una transacción"
                )
                return False
            if not r["ok"]:
                self.pushError(r["error"])
                return False
            return True

        def addFeatures(self, flist, flags=None):
            edit.CALLS.append(f"addFeatures({len(flist)})")
            if not self._verdict():
                return False, flist
            mapping = self.result["fid_map"]
            for f in flist:
                new = mapping.get(f.id())
                if new is None:
                    self.pushError(f"Alta sin id asignado por el guardado previo (fid {f.id()})")
                    return False, flist
                f.setId(new)
                f.setAttribute(self.key, new)
            self._count += len(flist)
            return True, flist

        def deleteFeatures(self, ids):
            edit.CALLS.append(f"deleteFeatures({len(ids)})")
            ok = self._verdict()
            if ok:
                self._count -= len(ids)
            return ok

        def changeAttributeValues(self, attr_map):
            edit.CALLS.append(f"changeAttributeValues({len(attr_map)})")
            return self._verdict()

        def changeGeometryValues(self, geometry_map):
            edit.CALLS.append(f"changeGeometryValues({len(geometry_map)})")
            return self._verdict()

        def leaveUpdateMode(self):
            edit.CALLS.append("leaveUpdateMode")
            return True

    def compatible(layer_type, geom) -> bool:
        if geom is None or geom.isNull() or layer_type in (Qgis.WkbType.Unknown, Qgis.WkbType.NoGeometry):
            return True
        return QgsWkbTypes.flatType(geom.wkbType()) == QgsWkbTypes.flatType(layer_type)

    def precommit(layer, provider, cancel_after: float | None = None):  # noqa: PLR0915 - un guardado entero
        """Aplica el búfer de edición entero en una transacción. Devuelve el veredicto."""
        eb = layer.editBuffer()
        added = dict(eb.addedFeatures())
        changed = {int(k): dict(v) for k, v in eb.changedAttributeValues().items() if int(k) >= 0}
        geoms = {int(k): v for k, v in eb.changedGeometries().items() if int(k) >= 0}
        deleted = [int(x) for x in eb.deletedFeatureIds() if int(x) >= 0]
        fields = provider.fields()
        table, key, gcol = provider.table, provider.key, provider.geom
        for fid, g in [*geoms.items(), *((k, f.geometry()) for k, f in added.items())]:
            if not compatible(provider.wkbType(), g):
                return {
                    "ok": False,
                    "error": f"Geometría incompatible con la capa en la entidad {fid}",
                    "fid_map": {},
                }
        for ch in changed.values():
            if any(fields.at(i).name() == key for i in ch):
                return {
                    "ok": False,
                    "error": "No se puede cambiar la clave primaria (es el FID de QGIS)",
                    "fid_map": {},
                }
        touched = sorted(set(changed) | set(geoms) | set(deleted))
        seen = {fid: provider.seen.get(fid) for fid in touched}
        cols = [f.name() for f in fields]
        rows_add = []
        for tmp, f in added.items():
            values = {c: plain(f.attribute(c)) for c in cols if c != key}
            g = f.geometry()
            rows_add.append((int(tmp), values, bytes(g.asWkb()) if not g.isNull() else None))
        upd = [(fid, {fields.at(i).name(): plain(v) for i, v in ch.items()}) for fid, ch in changed.items()]
        gup = [(fid, bytes(g.asWkb()) if not g.isNull() else None) for fid, g in geoms.items()]
        mode, check, hash_expr = provider.batch, provider.check, provider.hash_expr

        def op(handle, token):
            con = (
                handle._con
            )  # el prototipo usa la conexión dentro del hilo del worker (ver estudio: API necesaria)
            try:
                handle.execute("BEGIN")
            except Exception as exc:
                raise RuntimeError(
                    "La sesión tiene una transacción abierta: confírmela o reviértala antes de guardar"
                ) from exc
            try:
                if check and touched:
                    con.register("__gd_touched", _arrow({"fid": touched}))
                    now = dict(
                        con.execute(
                            f"SELECT {base._q(key)}, {hash_expr} FROM {table} WHERE {base._q(key)} IN (SELECT fid FROM __gd_touched)"
                        ).fetchall()
                    )
                    con.unregister("__gd_touched")
                    conflicts = [
                        fid for fid in touched if fid not in now or seen[fid] is None or now[fid] != seen[fid]
                    ]
                    if conflicts:
                        raise RuntimeError(
                            f"Conflicto: {len(conflicts)} entidad(es) cambiaron o desaparecieron en DuckDB desde que QGIS las leyó (p. ej. {conflicts[:5]})"
                        )
                seq = con.execute(
                    f"SELECT column_default FROM duckdb_columns() WHERE table_name = '{table.split('.')[-1]}' AND column_name = '{key}'"
                ).fetchone()
                fid_map = {}
                if rows_add:
                    if seq and seq[0] and "nextval" in seq[0]:
                        ids = [
                            r[0]
                            for r in con.execute(f"SELECT {seq[0]} FROM range({len(rows_add)})").fetchall()
                        ]
                    else:
                        raise RuntimeError("La clave no tiene secuencia: las altas necesitan id explícito")
                    fid_map = {tmp: int(i) for (tmp, _, _), i in zip(rows_add, ids, strict=True)}
                writers[mode](con, table, key, gcol, cols, upd, gup, deleted, rows_add, fid_map, token)
                if token.cancelled:
                    raise RuntimeError("Guardado cancelado")
                handle.execute("COMMIT")
                return fid_map
            except BaseException:
                with contextlib.suppress(Exception):  # el worker verificará la conexión después
                    handle.execute("ROLLBACK")
                raise

        worker = base.SESSIONS[provider.session]
        handle = worker.submit(op)
        if cancel_after is not None:
            threading.Timer(cancel_after, lambda: worker.cancel(handle.op_id)).start()
        try:
            fid_map = handle.future.result()
            return {"ok": True, "error": "", "fid_map": fid_map}
        except Exception as exc:
            msg = next((x.strip() for x in str(exc).splitlines() if x.strip()), repr(exc))
            return {"ok": False, "error": msg, "fid_map": {}}

    def attach(layer):
        """Lo que haría GeoDuck al publicar una capa editable: conectar el guardado previo."""
        provider = layer.dataProvider()

        def on_start():
            provider.capture = True

        def on_stop():
            provider.capture = False
            provider.seen.clear()

        def before(stop_editing):
            provider.result = precommit(layer, provider, getattr(layer, "_cancel_after", None))

        layer.editingStarted.connect(on_start)
        layer.editingStopped.connect(on_stop)
        layer.beforeCommitChanges.connect(before)
        layer._gd_slots = (on_start, on_stop, before)
        if layer.isEditable():
            on_start()

    return Txn, attach


def _arrow(d):
    import pyarrow as pa

    return pa.table(d)


def _w_row(con, table, key, gcol, cols, upd, gup, deleted, rows_add, fid_map, token):
    q = base._q
    for fid, values in upd:
        if token.cancelled:
            return
        con.execute(
            f"UPDATE {table} SET {', '.join(f'{q(n)} = ?' for n in values)} WHERE {q(key)} = ?",
            [*values.values(), fid],
        )
    for fid, wkb in gup:
        if token.cancelled:
            return
        con.execute(f"UPDATE {table} SET {q(gcol)} = ST_GeomFromWKB(?) WHERE {q(key)} = ?", [wkb, fid])
    if deleted:
        con.execute(f"DELETE FROM {table} WHERE {q(key)} IN ({', '.join(map(str, deleted))})")
    for tmp, values, wkb in rows_add:
        if token.cancelled:
            return
        names = [key, *values, gcol]
        con.execute(
            f"INSERT INTO {table} ({', '.join(map(q, names))}) VALUES ({', '.join(['?'] * (len(names) - 1))}, ST_GeomFromWKB(?))",
            [fid_map[tmp], *values.values(), wkb],
        )


def _w_many(con, table, key, gcol, cols, upd, gup, deleted, rows_add, fid_map, token):
    q = base._q
    by_cols: dict[tuple, list] = {}
    for fid, values in upd:
        by_cols.setdefault(tuple(values), []).append([*values.values(), fid])
    for names, params in by_cols.items():
        con.executemany(
            f"UPDATE {table} SET {', '.join(f'{q(n)} = ?' for n in names)} WHERE {q(key)} = ?", params
        )
    if gup:
        con.executemany(
            f"UPDATE {table} SET {q(gcol)} = ST_GeomFromWKB(?) WHERE {q(key)} = ?", [[w, f] for f, w in gup]
        )
    if deleted:
        con.execute(f"DELETE FROM {table} WHERE {q(key)} IN ({', '.join(map(str, deleted))})")
    if rows_add:
        names = [key, *rows_add[0][1], gcol]
        con.executemany(
            f"INSERT INTO {table} ({', '.join(map(q, names))}) VALUES ({', '.join(['?'] * (len(names) - 1))}, ST_GeomFromWKB(?))",
            [[fid_map[t], *v.values(), w] for t, v, w in rows_add],
        )


def _w_arrow(con, table, key, gcol, cols, upd, gup, deleted, rows_add, fid_map, token):
    q = base._q
    types = dict(
        con.execute(
            f"SELECT column_name, data_type FROM duckdb_columns() WHERE table_name = '{table.split('.')[-1]}'"
        ).fetchall()
    )
    by_cols: dict[tuple, list] = {}
    for fid, values in upd:
        by_cols.setdefault(tuple(values), []).append((fid, values))
    for names, items in by_cols.items():
        data = {"__fid": [f for f, _ in items]}
        for n in names:
            data[n] = [v[n] for _, v in items]
        con.register("__gd_upd", _arrow(data))
        sets = ", ".join(f"{q(n)} = CAST(u.{q(n)} AS {types[n]})" for n in names)
        con.execute(f"UPDATE {table} SET {sets} FROM __gd_upd u WHERE {table}.{q(key)} = u.__fid")
        con.unregister("__gd_upd")
    if gup:
        con.register("__gd_geo", _arrow({"__fid": [f for f, _ in gup], "wkb": [w for _, w in gup]}))
        con.execute(
            f"UPDATE {table} SET {q(gcol)} = ST_GeomFromWKB(u.wkb) FROM __gd_geo u WHERE {table}.{q(key)} = u.__fid"
        )
        con.unregister("__gd_geo")
    if deleted:
        con.register("__gd_del", _arrow({"__fid": deleted}))
        con.execute(f"DELETE FROM {table} WHERE {q(key)} IN (SELECT __fid FROM __gd_del)")
        con.unregister("__gd_del")
    if rows_add:
        names = list(rows_add[0][1])
        data = {"__fid": [fid_map[t] for t, _, _ in rows_add], "wkb": [w for _, _, w in rows_add]}
        for n in names:
            data[n] = [v[n] for _, v, _ in rows_add]
        con.register("__gd_add", _arrow(data))
        sel = ", ".join(["__fid", *(f"CAST({q(n)} AS {types[n]})" for n in names), "ST_GeomFromWKB(wkb)"])
        con.execute(
            f"INSERT INTO {table} ({', '.join(map(q, [key, *names, gcol]))}) SELECT {sel} FROM __gd_add"
        )
        con.unregister("__gd_add")


writers = {"row": _w_row, "many": _w_many, "arrow": _w_arrow}


def main() -> None:  # noqa: PLR0915 - secuencia de experimentos
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import (
        Qgis,
        QgsApplication,
        QgsFeature,
        QgsFeatureRequest,
        QgsGeometry,
        QgsPointXY,
        QgsProviderMetadata,
        QgsProviderRegistry,
        QgsVectorLayer,
    )

    app = QgsApplication([], False)
    app.initQgis()
    Txn, attach = build_txn(edit.build_editable(base.build_provider()))
    QgsProviderRegistry.instance().registerProvider(
        QgsProviderMetadata(Txn.providerKey(), "GeoDuck txn", Txn.createProvider)
    )
    Edit = edit.build_editable(base.build_provider())
    QgsProviderRegistry.instance().registerProvider(
        QgsProviderMetadata(Edit.providerKey(), "GeoDuck edit", Edit.createProvider)
    )
    from geoduck.engine.worker import SessionWorker

    worker = SessionWorker(":memory:")
    worker.start().result()
    base.SESSIONS["s1"] = worker
    work = tempfile.mkdtemp(prefix="geoduck-txn-")

    def run(sql, params=None, rows=50):
        return worker.submit(lambda h, t: h.execute(sql, params, max_rows=rows)).future.result()

    def snapshot():
        def op(h, t):
            return {
                r[0]: (r[1], r[2], r[3])
                for r in h._con.execute("SELECT id, nombre, valor, ST_AsText(geom) FROM e.t").fetchall()
            }

        return worker.submit(op).future.result()

    TOTAL = 60_000
    run("LOAD spatial")
    run(f"ATTACH '{work}/e.duckdb' AS e")

    def reset():
        run("DROP TABLE IF EXISTS e.t")
        run("DROP SEQUENCE IF EXISTS e.s")
        run("CREATE SEQUENCE e.s START 10000000")
        run(
            "CREATE TABLE e.t (id BIGINT PRIMARY KEY DEFAULT nextval('e.s'), nombre VARCHAR NOT NULL, valor DOUBLE, geom GEOMETRY('OGC:CRS84'))"
        )
        run(
            f"INSERT INTO e.t SELECT range, 'n' || range, range * 0.5, ST_Point(range % 1000, range // 1000)::GEOMETRY('OGC:CRS84') FROM range({TOTAL})"
        )
        run("CREATE INDEX rt ON e.t USING RTREE (geom)")

    def layer(provider="geoduck_txn", batch="arrow", check="hash"):
        uri = f"session=s1|table=e.t|geom=geom|key=id|fetch=table|pushdown=spatial|batch={batch}|check={check}|type=Point"
        lyr = QgsVectorLayer(uri, "t", provider)
        if provider == "geoduck_txn":
            attach(lyr)
        return lyr

    def edits(lyr, n, tag):
        """n cambios de atributo, n/2 de geometría, n/4 bajas y n altas; QGIS lee antes lo que edita."""
        ia, iv = lyr.fields().indexOf("nombre"), lyr.fields().indexOf("valor")
        t0 = time.perf_counter()
        attr_ids = list(range(0, n))
        geom_ids = list(range(2 * n, 2 * n + n // 2))
        del_ids = list(range(4 * n, 4 * n + n // 4))
        olds = {
            f.id(): f
            for f in lyr.getFeatures(QgsFeatureRequest().setFilterFids(attr_ids + geom_ids + del_ids))
        }
        for fid in attr_ids:
            lyr.changeAttributeValue(fid, ia, f"{tag}-{fid}", olds[fid]["nombre"])
            lyr.changeAttributeValue(fid, iv, -1.0, olds[fid]["valor"])
        for fid in geom_ids:
            lyr.changeGeometry(fid, QgsGeometry.fromPointXY(QgsPointXY(5000 + fid, 5000)))
        lyr.deleteFeatures(del_ids)
        for i in range(n):
            f = QgsFeature(lyr.fields())
            f.setAttribute("nombre", f"{tag}-alta-{i}")
            f.setAttribute("valor", float(i))
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(9000 + i % 100, 9000 + i // 100)))
            lyr.addFeature(f)
        expected = {"attr": attr_ids, "geom": geom_ids, "deleted": del_ids, "added": n, "tag": tag}
        return expected, round(time.perf_counter() - t0, 3)

    def verify(before, after, exp, applied: bool) -> bool:
        """Integridad: o todo aplicado (y lo no tocado intacto) o nada aplicado."""
        if not applied:
            return after == before
        touched = set(exp["attr"]) | set(exp["geom"]) | set(exp["deleted"])
        for fid, row in before.items():
            if fid in touched:
                continue
            if after.get(fid) != row:
                return False
        ok = all(after[f][0] == f"{exp['tag']}-{f}" and after[f][1] == -1.0 for f in exp["attr"])
        ok &= all(after[f][2] == f"POINT ({5000 + f} 5000)" for f in exp["geom"])
        ok &= all(f not in after for f in exp["deleted"])
        ok &= sum(1 for r in after.values() if str(r[0]).startswith(f"{exp['tag']}-alta-")) == exp["added"]
        return ok

    res: dict = {"qgis": Qgis.version(), "sizes": args.sizes, "runs": []}

    def record(name, n, **kw):
        e = {"case": name, "n": n, **kw}
        res["runs"].append(e)
        print(json.dumps(e, ensure_ascii=False), flush=True)

    for n in args.sizes:
        # E1: guardado correcto con cada estrategia de escritura
        for batch in ("row", "many", "arrow"):
            reset()
            lyr = layer(batch=batch)
            lyr.startEditing()
            exp, edit_s = edits(lyr, n, f"ok{batch}")
            before = snapshot()
            t0 = time.perf_counter()
            ok = lyr.commitChanges()
            commit_s = round(time.perf_counter() - t0, 3)
            after = snapshot()
            new_fids = (
                sorted(
                    f.id()
                    for f in lyr.getFeatures(
                        QgsFeatureRequest().setFilterExpression(f"\"nombre\" LIKE 'ok{batch}-alta-%'")
                    )
                )
                if n <= 1000
                else None
            )
            record(
                "commit_ok",
                n,
                batch=batch,
                qgis_ok=ok,
                edit_buffer_s=edit_s,
                commit_s=commit_s,
                integrity=verify(before, after, exp, applied=ok),
                db_applied=after != before,
                fids_from_sequence=None
                if new_fids is None
                else (new_fids[0] >= 10_000_000 and len(new_fids) == n),
            )

        # E2: conflicto — el panel SQL cambia una fila que QGIS está editando
        reset()
        lyr = layer()
        lyr.startEditing()
        exp, _ = edits(lyr, n, "conf")
        run("UPDATE e.t SET nombre = 'desde-sql' WHERE id = 1")
        before = snapshot()
        ok = lyr.commitChanges()
        after = snapshot()
        record(
            "conflict_on_edited_row",
            n,
            qgis_ok=ok,
            db_unchanged=after == before,
            sql_change_kept=after[1][0] == "desde-sql",
            buffer_kept=lyr.isEditable()
            and len(lyr.editBuffer().addedFeatures()) == n
            and 0 in lyr.editBuffer().changedAttributeValues(),
            errors=[e for e in lyr.commitErrors() if "Conflicto" in e][:1],
        )
        # Recuperación: el usuario decide sobrescribir → se vuelve a leer la fila (nueva huella) y se reintenta
        _ = next(lyr.dataProvider().getFeatures(QgsFeatureRequest(1)))
        before = snapshot()
        ok = lyr.commitChanges()
        after = snapshot()
        record("conflict_retry_after_reread", n, qgis_ok=ok, integrity=verify(before, after, exp, applied=ok))

        # E2b: el mismo caso con el proveedor sin guardado previo (G3-C): ¿se pierde el cambio de SQL?
        reset()
        lyr = layer(provider="geoduck_edit")
        lyr.startEditing()
        old = next(lyr.getFeatures(QgsFeatureRequest(1)))
        lyr.changeAttributeValue(1, lyr.fields().indexOf("nombre"), "desde-qgis", old["nombre"])
        run("UPDATE e.t SET nombre = 'desde-sql', valor = 123 WHERE id = 1")
        ok = lyr.commitChanges()
        row = snapshot()[1]
        record(
            "naive_provider_concurrent",
            n,
            qgis_ok=ok,
            final_nombre=row[0],
            final_valor=row[1],
            silent_overwrite=ok and row[0] == "desde-qgis",
        )

        # E3: el panel SQL cambia una fila que QGIS no toca: no hay conflicto y se conservan ambos cambios
        reset()
        lyr = layer()
        lyr.startEditing()
        exp, _ = edits(lyr, n, "libre")
        run(f"UPDATE e.t SET nombre = 'sql-ajeno' WHERE id = {TOTAL - 1}")
        before = snapshot()
        ok = lyr.commitChanges()
        after = snapshot()
        record(
            "sql_change_on_other_row",
            n,
            qgis_ok=ok,
            integrity=verify(before, after, exp, applied=ok),
            sql_change_kept=after[TOTAL - 1][0] == "sql-ajeno",
        )

        # E4: error de DuckDB a mitad (NOT NULL en la última alta): nada se escribe y QGIS no informa éxito
        reset()
        lyr = layer()
        lyr.startEditing()
        exp, _ = edits(lyr, n, "err")
        last = list(lyr.editBuffer().addedFeatures())[-1]
        lyr.changeAttributeValue(last, lyr.fields().indexOf("nombre"), None)
        before = snapshot()
        ok = lyr.commitChanges()
        after = snapshot()
        record(
            "error_mid_batch",
            n,
            qgis_ok=ok,
            db_unchanged=after == before,
            buffer_kept=lyr.isEditable() and len(lyr.editBuffer().addedFeatures()) == n,
            errors=[e for e in lyr.commitErrors() if "NOT NULL" in e][:1],
        )
        lyr.changeAttributeValue(last, lyr.fields().indexOf("nombre"), "corregido")
        before = snapshot()
        ok = lyr.commitChanges()
        after = snapshot()
        record("error_fixed_retry", n, qgis_ok=ok, db_applied=after != before)

        # E5: cancelación durante el guardado (interrupt del worker): ROLLBACK y búfer intacto
        reset()
        lyr = layer(batch="row")
        lyr.startEditing()
        exp, _ = edits(lyr, n, "can")
        lyr._cancel_after = 0.05
        before = snapshot()
        t0 = time.perf_counter()
        ok = lyr.commitChanges()
        after = snapshot()
        lyr._cancel_after = None
        record(
            "cancel_during_commit",
            n,
            qgis_ok=ok,
            s=round(time.perf_counter() - t0, 3),
            db_unchanged=after == before,
            buffer_kept=lyr.isEditable() and len(lyr.editBuffer().addedFeatures()) == n,
            errors=lyr.commitErrors()[-1:],
        )
        before = snapshot()
        ok = lyr.commitChanges()
        after = snapshot()
        record(
            "cancel_retry",
            n,
            qgis_ok=ok,
            integrity=verify(before, after, exp, applied=ok) if ok else after == before,
        )

        # E6: geometría incompatible (polígono en capa de puntos): la validación previa evita escribir
        reset()
        lyr = layer()
        lyr.startEditing()
        exp, _ = edits(lyr, n, "geo")
        lyr.changeGeometry(2 * n, QgsGeometry.fromWkt("POLYGON((0 0, 1 0, 1 1, 0 0))"))
        before = snapshot()
        ok = lyr.commitChanges()
        after = snapshot()
        record(
            "incompatible_geometry",
            n,
            qgis_ok=ok,
            db_unchanged=after == before,
            errors=[e for e in lyr.commitErrors() if "incompatible" in e.lower()][:1],
        )
        lyr.rollBack()

        # E7: transacción del usuario abierta
        reset()
        lyr = layer()
        lyr.startEditing()
        exp, _ = edits(lyr, n, "utx")
        run("BEGIN")
        run("UPDATE e.t SET valor = 999 WHERE id = 59000")
        ok = lyr.commitChanges()
        run("ROLLBACK")
        before = snapshot()
        record(
            "user_transaction_open",
            n,
            qgis_ok=ok,
            buffer_kept=lyr.isEditable() and len(lyr.editBuffer().addedFeatures()) == n,
        )
        ok = lyr.commitChanges()
        after = snapshot()
        record("user_transaction_retry", n, qgis_ok=ok, integrity=verify(before, after, exp, applied=ok))

        # E8: DETACH entre la edición y el guardado
        reset()
        lyr = layer()
        lyr.startEditing()
        exp, _ = edits(lyr, n, "det")
        run("DETACH e")
        ok = lyr.commitChanges()
        run(f"ATTACH '{work}/e.duckdb' AS e")
        record(
            "detach_before_commit",
            n,
            qgis_ok=ok,
            buffer_kept=lyr.isEditable() and len(lyr.editBuffer().addedFeatures()) == n,
            errors=lyr.commitErrors()[-1:],
        )
        lyr.rollBack()

    worker.close().result()
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    app.exitQgis()


if __name__ == "__main__":
    main()
