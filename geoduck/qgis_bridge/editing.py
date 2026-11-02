# SPDX-License-Identifier: GPL-2.0-or-later
"""Edición de capas Conectadas: guardado atómico previo (qgis-bridge-spec §5.4, ADR-0012).

GeoDuck escucha `QgsVectorLayer.beforeCommitChanges`, lee el búfer de edición entero y lo aplica en
**una** operación del worker: `BEGIN` → comprobación de huellas (conflictos) → escrituras por lotes con
tablas Arrow registradas → `COMMIT`; ante cualquier error o cancelación, `ROLLBACK`. Después, los
métodos de edición del proveedor solo informan el veredicto: QGIS informa éxito solo si DuckDB confirmó
y, si no, conserva el búfer entero.

Huellas: `hash(fila completa)` de cada fila tal como QGIS la leyó durante la edición (el proveedor las
registra al leer). Una fila editada sin lectura previa en esta edición (p. ej. desde una tabla de
atributos abierta antes) se registra en cuanto se edita, en lote. Si al guardar la huella de DuckDB
difiere o la fila falta, se revierte y se informa el conflicto; la huella actual queda registrada, de
modo que guardar otra vez sobrescribe a sabiendas.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa
from qgis.core import Qgis, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QTimer

from geoduck.domain.bridge_types import FieldKind
from geoduck.domain.sql_text import quote_identifier
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.provider import KEY, row_hash_sql

#: Espera del hilo principal a que el worker empiece el guardado (si está ocupado con otra cosa, se
#: cancela y se informa; nunca se informa éxito sin COMMIT).
SAVE_WAIT = 30.0
_UPD, _GEO, _DEL, _ADD, _IDS = (
    "__geoduck_upd",
    "__geoduck_geo",
    "__geoduck_del",
    "__geoduck_add",
    "__geoduck_ids",
)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    error: str = ""
    fid_map: dict[int, int] = field(default_factory=dict)
    conflicts: tuple[int, ...] = ()


class SaveError(Exception):
    def __init__(self, message: str, conflicts: dict[int, int] | None = None) -> None:
        super().__init__(message)
        self.conflicts = conflicts or {}


def is_null(value: Any) -> bool:
    return value is None or (hasattr(value, "isNull") and bool(value.isNull()))


def to_python(value: Any, kind: FieldKind) -> Any:  # noqa: PLR0911 - una salida por tipo
    """Valor de QGIS → valor de Python para Arrow (el SQL hace el CAST al tipo de la columna)."""
    if value is None or (hasattr(value, "isNull") and value.isNull()):
        return None
    if kind is FieldKind.BOOL:
        return bool(value)
    if kind in (FieldKind.INT, FieldKind.INT64):
        return int(value)
    if kind is FieldKind.DOUBLE:
        return float(value)
    if kind is FieldKind.DATE:
        return value.toPyDate() if hasattr(value, "toPyDate") else value
    if kind in (FieldKind.DATETIME, FieldKind.DATETIME_TZ):
        if hasattr(value, "toMSecsSinceEpoch"):  # leído en UTC con los dígitos del reloj (convert.py)
            instant = dt.datetime.fromtimestamp(value.toMSecsSinceEpoch() / 1000, tz=dt.timezone.utc)
            return instant if kind is FieldKind.DATETIME_TZ else instant.replace(tzinfo=None)
        return value
    if kind is FieldKind.BINARY:
        return bytes(value)
    return str(value)


def compatible(layer_type: Any, geom: Any) -> bool:
    """La geometría cabe en la capa: misma familia y dimensiones (QGIS ya convierte simple ↔ multi)."""
    if geom is None or geom.isNull() or layer_type in (Qgis.WkbType.Unknown, Qgis.WkbType.NoGeometry):
        return True
    t = geom.wkbType()
    same_family = QgsWkbTypes.flatType(QgsWkbTypes.multiType(t)) == QgsWkbTypes.flatType(
        QgsWkbTypes.multiType(layer_type)
    )
    same_dims = QgsWkbTypes.hasZ(t) == QgsWkbTypes.hasZ(layer_type) and QgsWkbTypes.hasM(
        t
    ) == QgsWkbTypes.hasM(layer_type)
    return bool(same_family and same_dims)


@dataclass
class _Batch:
    """El búfer de edición, validado y convertido a columnas (hilo principal)."""

    touched: list[int]
    seen: dict[int, int | None]
    updates: list[tuple[tuple[str, ...], dict[str, list[Any]]]]
    geometries: dict[str, list[Any]]
    deleted: list[int]
    added: dict[str, list[Any]]
    added_tmp: list[int]
    added_ids: list[int | None]


def _wkb(geom: Any) -> bytes | None:
    return None if geom is None or geom.isNull() else bytes(geom.asWkb())


def collect(layer: QgsVectorLayer) -> _Batch:  # noqa: PLR0912 - una validación por regla de §5.4
    """Lee y valida el búfer de edición. Lanza `SaveError` antes de tocar DuckDB si algo no es válido."""
    p = layer.dataProvider()
    eb = layer.editBuffer()
    plans = list(p.plan.fields)
    count = len(plans)
    key = p.key
    added = {int(k): f for k, f in eb.addedFeatures().items()}
    changed = {int(k): dict(v) for k, v in eb.changedAttributeValues().items() if int(k) >= 0}
    geoms = {int(k): g for k, g in eb.changedGeometries().items() if int(k) >= 0}
    deleted = sorted(int(x) for x in eb.deletedFeatureIds() if int(x) >= 0)
    layer_type = p.wkbType()

    for fid, g in [*geoms.items(), *((k, f.geometry()) for k, f in added.items())]:
        if not compatible(layer_type, g):
            raise SaveError(
                f"Geometría incompatible con la capa ({QgsWkbTypes.displayString(layer_type)}) en {fid}"
            )
    updates: dict[tuple[str, ...], dict[str, list[Any]]] = {}
    for fid, ch in sorted(changed.items()):
        names = []
        for i in sorted(ch):
            if i >= count:
                continue  # campo virtual o unido: no es de la tabla
            plan = plans[i]
            if plan.name == key:
                raise SaveError("No se puede cambiar la clave primaria: es el identificador de la entidad")
            if not plan.writable:
                raise SaveError(f"«{plan.name}» es de solo lectura en QGIS ({plan.source_type})")
            names.append(plan.name)
        if not names:
            continue
        group = updates.setdefault(tuple(names), {"__fid": [], **{n: [] for n in names}})
        group["__fid"].append(fid)
        for i in sorted(ch):
            if i < count:
                group[plans[i].name].append(to_python(ch[i], plans[i].kind))

    add_cols: dict[str, list[Any]] = {"__fid": [], "__tmp": []}
    writable = [pl for pl in plans if pl.writable and pl.name != key]
    for pl in writable:
        add_cols[pl.name] = []
    if p.plan.geometry is not None:
        add_cols["__wkb"] = []
    added_tmp: list[int] = []
    added_ids: list[int | None] = []
    for tmp, f in sorted(added.items()):
        for i, pl in enumerate(plans):
            if not pl.writable and pl.name != key and not is_null(f.attribute(i)):
                raise SaveError(f"«{pl.name}» es de solo lectura en QGIS ({pl.source_type})")
        explicit = f.attribute(p.field_index[key]) if key in p.field_index else None
        added_ids.append(None if explicit is None or is_null(explicit) else int(explicit))
        added_tmp.append(tmp)
        for pl in writable:
            add_cols[pl.name].append(to_python(f.attribute(p.field_index[pl.name]), pl.kind))
        if "__wkb" in add_cols:
            add_cols["__wkb"].append(_wkb(f.geometry()))
    if any(i is None for i in added_ids) and p.key_default is None:
        raise SaveError(f"«{key}» no tiene secuencia: indique el identificador de cada entidad nueva")

    touched = sorted(set(changed) | set(geoms) | set(deleted))
    return _Batch(
        touched=touched,
        seen={fid: p.seen.get(fid) for fid in touched},
        updates=list(updates.items()),
        geometries={"__fid": list(geoms), "__wkb": [_wkb(g) for g in geoms.values()]},
        deleted=deleted,
        added=add_cols,
        added_tmp=added_tmp,
        added_ids=added_ids,
    )


def _table(values: dict[str, list[Any]]) -> pa.Table:
    return pa.table({k: pa.array(v) for k, v in values.items()})


def _affected(outcome: Any) -> int:
    rows = getattr(outcome, "rows", ())
    return int(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else -1


def apply(  # noqa: PLR0912, PLR0915 - los cuatro pasos de §5.4 en una sola transacción
    handle: Any, token: Any, provider: Any, batch: _Batch
) -> dict[int, int]:
    """Operación del worker: el guardado entero en una transacción. Devuelve el mapa de altas."""
    table = provider.source
    key = quote_identifier(provider.key)
    types = dict(provider.plan_types)
    geom = provider.plan.geometry.name if provider.plan.geometry is not None else None
    try:
        handle.execute("BEGIN")
    except Exception as exc:
        raise SaveError(
            "La sesión tiene una transacción abierta: confírmela o reviértala antes de guardar la capa"
        ) from exc
    try:
        if batch.touched:  # 1. conflictos
            with handle.registered(_IDS, _table({"__fid": batch.touched})):
                now = handle.execute(
                    f"SELECT {key}, {row_hash_sql(provider.columns)} FROM {table} "
                    f"WHERE {key} IN (SELECT __fid FROM {_IDS})",
                    max_rows=len(batch.touched) + 1,
                ).rows
            current = {int(k): int(h) for k, h in now}
            conflicts = {
                fid: current.get(fid, 0)
                for fid in batch.touched
                if fid not in current or batch.seen[fid] is None or current[fid] != batch.seen[fid]
            }
            if conflicts:
                sample = ", ".join(map(str, list(conflicts)[:5]))
                raise SaveError(
                    f"Conflicto: {len(conflicts)} entidad(es) cambiaron o ya no existen en DuckDB "
                    f"desde que QGIS las leyó (p. ej. {sample}). "
                    "Guarde de nuevo para sobrescribir, o descarte sus cambios.",
                    conflicts,
                )
        token.raise_if_cancelled()
        fid_map: dict[int, int] = {}  # 2. identificadores de las altas
        missing = [i for i, v in enumerate(batch.added_ids) if v is None]
        if missing:
            ids = handle.execute(
                f"SELECT {provider.key_default} FROM range({len(missing)})", max_rows=len(missing) + 1
            ).rows
            for i, (new,) in zip(missing, ids, strict=True):
                batch.added_ids[i] = int(new)
        for tmp, new in zip(batch.added_tmp, batch.added_ids, strict=True):
            fid_map[tmp] = int(new)  # type: ignore[arg-type]
        # 3. escrituras por lotes (tablas Arrow registradas solo durante la sentencia)
        for names, values in batch.updates:
            sets = ", ".join(
                f"{quote_identifier(n)} = CAST(u.{quote_identifier(n)} AS {types[n]})" for n in names
            )
            with handle.registered(_UPD, _table(values)):
                done = handle.execute(
                    f"UPDATE {table} SET {sets} FROM {_UPD} u WHERE {table}.{key} = u.__fid"
                )
            if _affected(done) not in (-1, len(values["__fid"])):
                raise SaveError("Actualización incompleta: alguna entidad ya no existe")
            token.raise_if_cancelled()
        if batch.geometries["__fid"] and geom is not None:
            with handle.registered(_GEO, _table(batch.geometries)):
                handle.execute(
                    f"UPDATE {table} SET {quote_identifier(geom)} = ST_GeomFromWKB(u.__wkb) FROM {_GEO} u "
                    f"WHERE {table}.{key} = u.__fid"
                )
            token.raise_if_cancelled()
        if batch.deleted:
            with handle.registered(_DEL, _table({"__fid": batch.deleted})):
                done = handle.execute(f"DELETE FROM {table} WHERE {key} IN (SELECT __fid FROM {_DEL})")
            if _affected(done) not in (-1, len(batch.deleted)):
                raise SaveError("Borrado incompleto: alguna entidad ya no existe")
            token.raise_if_cancelled()
        if batch.added_tmp:
            data = dict(batch.added)
            data["__fid"] = list(batch.added_ids)
            data["__tmp"] = list(batch.added_tmp)
            columns = [n for n in data if not n.startswith("__")]
            target = [key, *map(quote_identifier, columns)]
            select = ["__fid", *(f"CAST({quote_identifier(n)} AS {types[n]})" for n in columns)]
            if geom is not None:
                target.append(quote_identifier(geom))
                select.append("ST_GeomFromWKB(__wkb)")
            with handle.registered(_ADD, _table(data)):
                handle.execute(
                    f"INSERT INTO {table} ({', '.join(target)}) SELECT {', '.join(select)} FROM {_ADD}"
                )
        token.raise_if_cancelled()
        handle.execute("COMMIT")  # 4. confirmación: lo único que permite informar éxito
        return fid_map
    except BaseException:
        with contextlib.suppress(Exception):  # el worker verifica la conexión después de cada operación
            handle.execute("ROLLBACK")
        raise


def _message(exc: BaseException) -> str:
    return next((line.strip() for line in str(exc).splitlines() if line.strip()), type(exc).__name__)


class EditSession:
    """Guardado atómico de una capa Conectada editable. Vive en el hilo principal."""

    def __init__(self, layer: QgsVectorLayer, on_saved: Callable[[], None] | None = None) -> None:
        self.layer = layer
        self.provider = layer.dataProvider()
        self._on_saved = on_saved
        self._pending: set[int] = set()
        self._captures: list[Future[Any]] = []
        self._flush_scheduled = False
        self._connections = [
            (layer.editingStarted, self._started),
            (layer.editingStopped, self._stopped),
            (layer.beforeCommitChanges, self._before_commit),
            (layer.afterCommitChanges, self._after_commit),
            (layer.attributeValueChanged, self._edited),
            (layer.geometryChanged, self._edited),
            (layer.featureDeleted, self._edited),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)
        if layer.isEditable():
            self._started()

    def detach(self) -> None:
        for signal, slot in self._connections:
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(slot)
        self._connections = []

    # -- huellas -------------------------------------------------------------------------------

    def _started(self) -> None:
        self.provider.seen.clear()
        self.provider.capture = True

    def _stopped(self) -> None:
        self.provider.capture = False
        self.provider.seen.clear()
        self.provider.verdict = None
        self._pending.clear()

    def _edited(self, fid: Any, *_: Any) -> None:
        fid = int(fid)
        if fid < 0 or fid in self.provider.seen:
            return
        self._pending.add(fid)
        if not self._flush_scheduled:  # una consulta por ráfaga (p. ej. la calculadora de campos)
            self._flush_scheduled = True
            QTimer.singleShot(0, self._flush)

    def _flush(self) -> None:
        self._flush_scheduled = False
        fids = sorted(self._pending)
        self._pending.clear()
        engine = sessions.get(self.provider.session)
        if not fids or engine is None:
            return
        p = self.provider
        key = quote_identifier(p.key)

        def op(handle: Any, _token: Any) -> None:
            with handle.registered(_IDS, _table({"__fid": fids})):
                rows = handle.execute(
                    f"SELECT {key}, {row_hash_sql(p.columns)} FROM {p.source} "
                    f"WHERE {key} IN (SELECT __fid FROM {_IDS})",
                    max_rows=len(fids) + 1,
                ).rows
            for k, h in rows:
                p.seen.setdefault(int(k), int(h))

        with contextlib.suppress(Exception):
            self._captures.append(engine.submit(op, priority=True).future)

    # -- guardado ------------------------------------------------------------------------------

    def _before_commit(self, *_: Any) -> None:
        self.provider.verdict = self.save()

    def _after_commit(self) -> None:
        verdict = self.provider.verdict
        self.provider.verdict = None
        if verdict is not None and verdict.ok and self._on_saved is not None:
            self._on_saved()

    def save(self) -> Verdict:  # noqa: PLR0911 - un veredicto por cada salida posible
        p = self.provider
        engine = sessions.get(p.session)
        if engine is None:
            return Verdict(False, "La sesión de DuckDB de esta capa no está disponible")
        if self._pending:
            self._flush()
        for fut in self._captures:  # huellas pendientes de las últimas ediciones
            with contextlib.suppress(Exception):
                fut.result(SAVE_WAIT)
        self._captures = []
        try:
            batch = collect(self.layer)
        except SaveError as exc:
            return Verdict(False, str(exc))
        if not batch.touched and not batch.added_tmp:
            return Verdict(True)
        handle = engine.submit(lambda h, t: apply(h, t, p, batch), priority=True)
        try:
            fid_map = handle.future.result(SAVE_WAIT)
        except FutureTimeout:
            engine.cancel(handle.op_id)  # en cola: se descarta; en curso: ROLLBACK
            try:
                fid_map = handle.future.result()  # el veredicto real: nunca éxito sin COMMIT
            except BaseException as exc:
                return Verdict(False, "La sesión está ocupada; guarde de nuevo al terminar: " + _message(exc))
        except SaveError as exc:
            for fid, h in exc.conflicts.items():
                p.seen[fid] = h  # guardar otra vez sobrescribe a sabiendas (§5.4)
            return Verdict(False, str(exc), conflicts=tuple(exc.conflicts))
        except BaseException as exc:
            return Verdict(False, "El guardado falló y se revirtió: " + _message(exc))
        for fid in batch.touched:
            p.seen.pop(fid, None)
        return Verdict(True, fid_map=fid_map)


def is_editable_layer(layer: Any) -> bool:
    return (
        isinstance(layer, QgsVectorLayer)
        and layer.providerType() == KEY
        and layer.dataProvider() is not None
        and bool(getattr(layer.dataProvider(), "editable", False))
    )
