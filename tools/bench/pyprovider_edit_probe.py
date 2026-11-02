# SPDX-License-Identifier: GPL-2.0-or-later
# ruff: noqa: N802, N803, N806, B008, E501 - firmas de la API de QGIS y SQL de prueba en una línea
"""Spike G3-C: edición nativa desde QGIS con el proveedor «geoduck» prototipo (no es código del complemento).

Extiende el proveedor de `pyprovider_probe.py` con `addFeatures`, `changeAttributeValues`,
`changeGeometryValues` y `deleteFeatures`. Cada método es una operación del `SessionWorker` real; la
conexión no sale de su hilo. Dos políticas de transacción (`txn=` en la URI):

  per-call  cada método abre y cierra su propia transacción (BEGIN … COMMIT);
  group     el primer método de un guardado abre la transacción y `leaveUpdateMode()` la confirma;
            un fallo revierte todo el guardado.

En ambas, si la sesión del usuario ya tiene una transacción abierta, el guardado se rechaza (no se
mezclan los cambios de QGIS con una transacción ajena ni se anidan transacciones).

Una capa es editable solo si es una tabla base (no vista ni consulta), de una base no READ_ONLY, con clave
primaria de una sola columna entera que coincide con `key=` (el FID de QGIS).

Uso: python pyprovider_edit_probe.py --out resultado.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pyprovider_probe as base

CALLS: list[str] = []


def build_editable(Provider):
    from qgis.core import Qgis, QgsDataProvider, QgsGeometry

    caps_edit = (
        Qgis.VectorProviderCapability.AddFeatures
        | Qgis.VectorProviderCapability.DeleteFeatures
        | Qgis.VectorProviderCapability.ChangeAttributeValues
        | Qgis.VectorProviderCapability.ChangeGeometries
        | Qgis.VectorProviderCapability.SelectAtId
    )

    def plain(v):
        if v is None or (hasattr(v, "isNull") and v.isNull()):
            return None
        return v

    class Editable(Provider):
        @classmethod
        def providerKey(cls):
            return "geoduck_edit"

        @classmethod
        def createProvider(cls, uri, options, flags=Qgis.DataProviderReadFlags()):
            return Editable(uri, options, flags)

        def __init__(
            self, uri="", options=QgsDataProvider.ProviderOptions(), flags=Qgis.DataProviderReadFlags()
        ):
            super().__init__(uri, options, flags)
            parts = dict(x.split("=", 1) for x in uri.split("|") if "=" in x)
            self.txn = parts.get("txn", "per-call")
            if parts.get("type"):  # DuckDB no guarda el subtipo de GEOMETRY: hay que declararlo (tabla vacía)
                self._wkb = getattr(Qgis.WkbType, parts["type"])
            self.editable = False
            self.readonly_reason = ""
            self.group_open = False
            self.group_failed = False
            if not self._valid:
                return
            table, key = self.table, self.key

            def meta(handle, token):  # noqa: PLR0911 - un motivo de solo lectura por salida
                if table.lstrip().startswith("("):
                    return None, "consulta SQL"
                parts = [p.strip('"') for p in table.split(".")]
                name = parts[-1]
                db = parts[0] if len(parts) > 1 else None
                where = f"table_name = '{name}'" + (f" AND database_name = '{db}'" if db else "")
                vwhere = f"view_name = '{name}'" + (f" AND database_name = '{db}'" if db else "")
                if handle.execute(f"SELECT count(*) FROM duckdb_views() WHERE {vwhere}").rows[0][0]:
                    return None, "vista"
                rows = handle.execute(f"SELECT database_name FROM duckdb_tables() WHERE {where}").rows
                if not rows:
                    return None, "tabla no encontrada"
                dbname = rows[0][0]
                ro = handle.execute(
                    f"SELECT readonly FROM duckdb_databases() WHERE database_name = '{dbname}'"
                ).rows
                if ro and ro[0][0]:
                    return None, "base de datos READ_ONLY"
                pk = handle.execute(
                    f"SELECT constraint_column_names FROM duckdb_constraints() WHERE {where} "
                    "AND constraint_type = 'PRIMARY KEY'"
                ).rows
                if not pk or list(pk[0][0]) != [key]:
                    return None, f"sin clave primaria única en «{key}»"
                typ = handle.execute(
                    f"SELECT data_type FROM duckdb_columns() WHERE {where} AND column_name = '{key}'"
                ).rows
                if not typ or typ[0][0] not in {"BIGINT", "INTEGER", "HUGEINT", "UBIGINT"}:
                    return None, "la clave primaria no es entera"
                return True, ""

            ok, why = base.SESSIONS[self.session].submit(meta).future.result()
            self.editable = bool(ok)
            self.readonly_reason = why

        def capabilities(self):
            return caps_edit if self.editable else Qgis.VectorProviderCapability.SelectAtId

        # -- transacciones ---------------------------------------------------------------------
        def enterUpdateMode(self):
            CALLS.append("enterUpdateMode")
            return True

        def leaveUpdateMode(self):
            CALLS.append("leaveUpdateMode")
            if self.txn == "group" and self.group_open:
                ok = self._run(lambda h: h.execute("ROLLBACK" if self.group_failed else "COMMIT"), raw=True)
                self.group_open = False
                self.group_failed = False
                return ok is not False
            return True

        def _run(self, body, raw=False):
            """Ejecuta `body(handle)` en el worker dentro de la política de transacción. None si falla."""
            worker = base.SESSIONS.get(self.session)
            if worker is None:
                self.pushError("La sesión de GeoDuck ya no existe")
                return False
            group = self.txn == "group"

            def op(handle, token):
                if raw:
                    return body(handle)
                if group and self.group_open:
                    if self.group_failed:
                        raise RuntimeError("el guardado ya falló; se revertirá")
                    return body(handle)
                try:
                    handle.execute("BEGIN")
                except Exception as exc:  # transacción del usuario abierta: no se mezcla ni se anida
                    raise RuntimeError(
                        "La sesión tiene una transacción abierta: confírmela o reviértala antes de guardar"
                    ) from exc
                try:
                    out = body(handle)
                except Exception:
                    handle.execute("ROLLBACK")
                    raise
                if group:
                    self.group_open = True
                else:
                    handle.execute("COMMIT")
                return out

            try:
                return worker.submit(op).future.result()
            except Exception as exc:
                msg = next((line.strip() for line in str(exc).splitlines() if line.strip()), repr(exc))
                if group and self.group_open:
                    self.group_failed = True
                self.pushError(msg)
                self.last_error = msg
                return False

        def _cols(self):
            return [f.name() for f in self._fields]

        # -- edición ------------------------------------------------------------------------
        def addFeatures(self, flist, flags=None):
            CALLS.append(f"addFeatures({len(flist)})")
            cols = self._cols()
            rows = []
            for f in flist:
                values = {c: plain(f.attribute(c)) for c in cols if f.fields().indexOf(c) >= 0}
                wkb = bytes(f.geometry().asWkb()) if f.hasGeometry() else None
                rows.append((values, wkb))
            table, key, geom = self.table, self.key, self.geom

            def body(handle):
                ids = []
                for values, wkb in rows:
                    names = [n for n, v in values.items() if not (n == key and v is None)]
                    params = [values[n] for n in names]
                    exprs = ["?"] * len(names)
                    if wkb is not None:
                        names.append(geom)
                        exprs.append("ST_GeomFromWKB(?)")
                        params.append(wkb)
                    sql = (
                        f"INSERT INTO {table} ({', '.join(base._q(n) for n in names)}) "
                        f"VALUES ({', '.join(exprs)}) RETURNING {base._q(key)}"
                    )
                    ids.append(handle.execute(sql, params).rows[0][0])
                return ids

            ids = self._run(body)
            if ids is False:
                return False, flist
            for f, fid in zip(flist, ids, strict=True):
                f.setId(fid)
                if f.fields().indexOf(key) >= 0:
                    f.setAttribute(key, fid)
            self._count += len(ids)
            return True, flist

        def deleteFeatures(self, ids):
            CALLS.append(f"deleteFeatures({len(ids)})")
            fids = ", ".join(str(int(i)) for i in ids) or "NULL"
            table, key = self.table, self.key
            ok = self._run(lambda h: h.execute(f"DELETE FROM {table} WHERE {base._q(key)} IN ({fids})"))
            if ok is not False:
                self._count -= len(ids)
            return ok is not False

        def changeAttributeValues(self, attr_map):
            CALLS.append(f"changeAttributeValues({len(attr_map)})")
            fields, table, key = self._fields, self.table, self.key
            stmts = []
            for fid, changes in attr_map.items():
                sets, params = [], []
                for idx, value in changes.items():
                    name = fields.at(idx).name()
                    if name == key:
                        self.pushError("No se puede cambiar la clave primaria (es el FID de QGIS)")
                        return False
                    sets.append(f"{base._q(name)} = ?")
                    params.append(plain(value))
                stmts.append(
                    (f"UPDATE {table} SET {', '.join(sets)} WHERE {base._q(key)} = ?", [*params, int(fid)])
                )

            def body(handle):
                for sql, params in stmts:
                    handle.execute(sql, params)
                return True

            return self._run(body) is not False

        def changeGeometryValues(self, geometry_map):
            CALLS.append(f"changeGeometryValues({len(geometry_map)})")
            table, key, geom = self.table, self.key, self.geom
            stmts = [
                (int(fid), bytes(QgsGeometry(g).asWkb()) if not g.isNull() else None)
                for fid, g in geometry_map.items()
            ]

            def body(handle):
                for fid, wkb in stmts:
                    if wkb is None:
                        handle.execute(
                            f"UPDATE {table} SET {base._q(geom)} = NULL WHERE {base._q(key)} = ?", [fid]
                        )
                    else:
                        handle.execute(
                            f"UPDATE {table} SET {base._q(geom)} = ST_GeomFromWKB(?) "
                            f"WHERE {base._q(key)} = ?",
                            [wkb, fid],
                        )
                return True

            return self._run(body) is not False

    return Editable


def main() -> None:  # noqa: PLR0915 - secuencia de comprobaciones
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
        QgsRectangle,
        QgsVectorLayer,
    )

    app = QgsApplication([], False)
    app.initQgis()
    Provider = base.build_provider()
    Editable = build_editable(Provider)
    QgsProviderRegistry.instance().registerProvider(
        QgsProviderMetadata(Editable.providerKey(), "GeoDuck editable (prototipo)", Editable.createProvider)
    )
    from geoduck.engine.worker import SessionWorker

    worker = SessionWorker(":memory:")
    worker.start().result()
    base.SESSIONS["s1"] = worker
    work = tempfile.mkdtemp(prefix="geoduck-edit-")

    def run(sql, params=None):
        return worker.submit(lambda h, t: h.execute(sql, params, max_rows=50)).future.result()

    run("LOAD spatial")
    run(f"ATTACH '{work}/e.duckdb' AS e")
    run("CREATE SEQUENCE e.s START 10000000")
    run(
        "CREATE TABLE e.t (id BIGINT PRIMARY KEY DEFAULT nextval('e.s'), nombre VARCHAR NOT NULL, valor DOUBLE, "
        "geom GEOMETRY('OGC:CRS84'))"
    )
    run(
        "INSERT INTO e.t SELECT range, 'n' || range, range * 0.5, ST_Point(range % 100, range // 100)::GEOMETRY('OGC:CRS84') "
        "FROM range(10000)"
    )
    run("CREATE INDEX rt ON e.t USING RTREE (geom)")
    run("CREATE TABLE e.sin_pk AS SELECT * FROM e.t")
    run("CREATE VIEW e.v AS SELECT * FROM e.t WHERE id % 2 = 0")
    run("CREATE TEMP TABLE tmp (id BIGINT PRIMARY KEY, nombre VARCHAR NOT NULL, valor DOUBLE, geom GEOMETRY)")
    run(f"ATTACH '{work}/ro.duckdb' AS rosrc")
    run("CREATE TABLE rosrc.t AS SELECT * FROM e.t LIMIT 10")
    run("DETACH rosrc")
    run(f"ATTACH '{work}/ro.duckdb' AS ro (READ_ONLY)")

    def layer(table, txn="per-call", key="id", gtype=""):
        uri = f"session=s1|table={table}|geom=geom|key={key}|fetch=stream|pushdown=spatial|txn={txn}"
        if gtype:
            uri += f"|type={gtype}"
        return QgsVectorLayer(uri, table, "geoduck_edit")

    res: dict = {"qgis": Qgis.version()}
    res["editable"] = {}
    for table in ("e.t", "e.sin_pk", "e.v", "(SELECT * FROM e.t)", "ro.t", "temp.tmp"):
        lyr = layer(table)
        res["editable"][table] = {
            "valid": lyr.isValid(),
            "supports_editing": lyr.isValid()
            and bool(lyr.dataProvider().capabilities() & Qgis.VectorProviderCapability.AddFeatures),
            "start_editing": lyr.isValid() and lyr.startEditing(),
            "reason": lyr.dataProvider().readonly_reason if lyr.isValid() else "",
        }
        if lyr.isEditable():
            lyr.rollBack()

    def feature(lyr, nombre, x, y, fid_value=None):
        f = QgsFeature(lyr.fields())
        f.setAttribute("id", fid_value)
        f.setAttribute("nombre", nombre)
        f.setAttribute("valor", 1.5)
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        return f

    # Guardado completo correcto: alta (sin id → secuencia), cambio de atributo y geometría, baja.
    for txn in ("per-call", "group"):
        CALLS.clear()
        lyr = layer("e.t", txn)
        lyr.startEditing()
        lyr.addFeature(feature(lyr, f"alta-{txn}-1", 500, 500))
        lyr.addFeature(feature(lyr, f"alta-{txn}-2", 501, 501))
        lyr.changeAttributeValue(10, lyr.fields().indexOf("nombre"), f"cambiado-{txn}")
        lyr.changeGeometry(11, QgsGeometry.fromPointXY(QgsPointXY(900, 900)))
        lyr.deleteFeature(12 if txn == "per-call" else 13)
        t0 = time.perf_counter()
        ok = lyr.commitChanges()
        new = run(f"SELECT id FROM e.t WHERE nombre LIKE 'alta-{txn}-%' ORDER BY id").rows
        moved = run("SELECT id FROM e.t WHERE ST_Intersects(geom, ST_MakeEnvelope(899, 899, 901, 901))").rows
        fids_layer = sorted(
            f.id()
            for f in lyr.getFeatures(QgsFeatureRequest().setFilterRect(QgsRectangle(499, 499, 502, 502)))
        )
        res[f"commit_ok_{txn}"] = {
            "ok": ok,
            "s": round(time.perf_counter() - t0, 3),
            "calls": list(CALLS),
            "new_ids_db": [r[0] for r in new],
            "new_fids_layer": fids_layer,
            "attr_changed": run("SELECT nombre FROM e.t WHERE id = 10").rows[0][0],
            "geom_moved_found_by_rtree": [r[0] for r in moved],
            "deleted_gone": run(
                f"SELECT count(*) FROM e.t WHERE id = {12 if txn == 'per-call' else 13}"
            ).rows[0][0]
            == 0,
        }

    # Guardado que falla a mitad: cambio de atributo válido + alta con PK duplicada.
    for txn in ("per-call", "group"):
        CALLS.clear()
        lyr = layer("e.t", txn)
        lyr.startEditing()
        lyr.changeAttributeValue(20, lyr.fields().indexOf("nombre"), f"parcial-{txn}")
        lyr.addFeature(feature(lyr, "duplicada", 1, 1, fid_value=21))
        ok = lyr.commitChanges()
        res[f"commit_fail_{txn}"] = {
            "ok": ok,
            "errors": [e for e in lyr.commitErrors()][:4],
            "calls": list(CALLS),
            "attr_change_persisted": run("SELECT nombre FROM e.t WHERE id = 20").rows[0][0]
            == f"parcial-{txn}",
            "still_editing": lyr.isEditable(),
            # ¿Sigue el cambio de atributo en el búfer de QGIS para reintentar, o QGIS lo dio por guardado?
            "attr_change_still_in_buffer": 20 in lyr.editBuffer().changedAttributeValues(),
            "value_qgis_shows": next(lyr.getFeatures(QgsFeatureRequest(20)))["nombre"],
            "added_still_in_buffer": len(lyr.editBuffer().addedFeatures()),
        }
        if lyr.isEditable():
            lyr.rollBack()
        run("UPDATE e.t SET nombre = 'n20' WHERE id = 20")

    # NOT NULL violado y cambio de clave primaria
    lyr = layer("e.t")
    lyr.startEditing()
    lyr.changeAttributeValue(30, lyr.fields().indexOf("nombre"), None)
    res["not_null"] = {"ok": lyr.commitChanges(), "errors": lyr.commitErrors()[:3]}
    lyr.rollBack()
    lyr.startEditing()
    lyr.changeAttributeValue(31, lyr.fields().indexOf("id"), 777777)
    res["change_pk"] = {"ok": lyr.commitChanges(), "errors": lyr.commitErrors()[:3]}
    lyr.rollBack()

    # Transacción del usuario abierta en la sesión
    run("BEGIN")
    run("UPDATE e.t SET valor = -1 WHERE id = 40")
    lyr = layer("e.t")
    lyr.startEditing()
    lyr.changeAttributeValue(41, lyr.fields().indexOf("nombre"), "durante-transaccion")
    ok = lyr.commitChanges()
    res["user_transaction_open"] = {
        "ok": ok,
        "errors": lyr.commitErrors()[:3],
        "buffer_kept": lyr.isEditable(),
    }
    run("ROLLBACK")
    res["user_transaction_open"]["commit_after_user_rollback"] = lyr.commitChanges()
    res["user_transaction_open"]["value"] = run("SELECT nombre FROM e.t WHERE id = 41").rows[0][0]

    # Cambio concurrente desde el panel SQL durante la edición: gana la última escritura
    lyr = layer("e.t")
    lyr.startEditing()
    lyr.changeAttributeValue(50, lyr.fields().indexOf("nombre"), "desde-qgis")
    run("UPDATE e.t SET nombre = 'desde-sql' WHERE id = 50")
    lyr.commitChanges()
    res["concurrent_sql_edit"] = run("SELECT nombre FROM e.t WHERE id = 50").rows[0][0]

    # Tabla TEMP con PK: editable
    lyr = layer("temp.tmp")
    lyr.startEditing()
    lyr.addFeature(feature(lyr, "temporal", 1, 1, fid_value=1))
    res["temp_table_commit_without_type"] = {"ok": lyr.commitChanges(), "errors": lyr.commitErrors()[:2]}
    lyr.rollBack()
    lyr = layer("temp.tmp", gtype="Point")
    lyr.startEditing()
    lyr.addFeature(feature(lyr, "temporal", 1, 1, fid_value=1))
    res["temp_table_commit"] = {
        "ok": lyr.commitChanges(),
        "errors": lyr.commitErrors()[:4],
        "rows": run("SELECT count(*) FROM temp.tmp").rows[0][0],
    }

    # Rendimiento: 5 000 altas y 5 000 cambios de atributo en un guardado (una sentencia por entidad)
    lyr = layer("e.t", "group")
    lyr.startEditing()
    for i in range(5000):
        lyr.addFeature(feature(lyr, f"masa-{i}", 2000 + i % 100, 2000 + i // 100))
    t0 = time.perf_counter()
    ok = lyr.commitChanges()
    res["bulk_add_5000"] = {"ok": ok, "s": round(time.perf_counter() - t0, 3)}
    lyr.startEditing()
    idx = lyr.fields().indexOf("valor")
    for fid in range(1000, 6000):
        lyr.changeAttributeValue(fid, idx, 42.0)
    t0 = time.perf_counter()
    ok = lyr.commitChanges()
    res["bulk_update_5000"] = {"ok": ok, "s": round(time.perf_counter() - t0, 3)}

    # DETACH con cambios pendientes en QGIS
    lyr = layer("e.t")
    lyr.startEditing()
    lyr.changeAttributeValue(60, lyr.fields().indexOf("nombre"), "tras-detach")
    run("DETACH e")
    res["detach_with_pending_edits"] = {
        "ok": lyr.commitChanges(),
        "errors": lyr.commitErrors()[:2],
        "buffer_kept": lyr.isEditable(),
    }
    lyr.rollBack()

    worker.close().result()
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    app.exitQgis()


if __name__ == "__main__":
    main()
