# SPDX-License-Identifier: GPL-2.0-or-later
# ruff: noqa: N802, N803 - nombres de métodos impuestos por la API de QGIS
"""Proveedor `geoduck`: capa Conectada leída bajo demanda (qgis-bridge-spec §5, ADR-0012).

Cada petición de QGIS (dibujo, identificar, tabla de atributos) se traduce a SQL sobre la consulta
normalizada de §7 y se pide al worker de la sesión en **páginas** de como mucho `PAGE` filas, con
prioridad sobre el trabajo en cola (§5.3). El proveedor nunca toca la conexión: solo envía operaciones al
worker y espera su resultado (desde los hilos de dibujo de QGIS, o brevemente desde el principal).

La URI lleva todo lo necesario para construir el proveedor sin hablar con la sesión (columnas y tipos,
identificador, CRS, extensión, conteo). Si la sesión no existe o la lectura falla (p. ej. tras un
DETACH), la capa sigue siendo válida pero queda «no disponible»: vacía y sin errores (§5.5).

Identificador de entidad (FID), como el proveedor `postgres` de QGIS (§5.1):
- `fid=key`: clave primaria o columna `UNIQUE NOT NULL` entera de una columna: su valor es el FID;
- `fid=map`: cualquier otra clave de la tabla (texto, UUID, fecha, varias columnas): el FID se asigna en
  memoria a cada valor (`PktFidMap`);
- `fid=rowid`: tabla sin clave, como `ctid` en PostgreSQL. Puede cambiar si DuckDB compacta la tabla tras
  borrar filas; el guardado lo detecta por la huella de cada fila y nunca escribe en otra (§5.4);
- `fid=content`: vista o consulta, automático: huella del contenido de la fila (solo lectura). Filas
  idénticas comparten FID; las páginas saltan los empates ya entregados.
Las páginas avanzan por el identificador (`> último ORDER BY identificador LIMIT n`); nunca `OFFSET`.
"""

from __future__ import annotations

import ctypes
import json
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any
from urllib.parse import parse_qsl, urlencode

from qgis.core import (
    Qgis,
    QgsAbstractFeatureIterator,
    QgsAbstractFeatureSource,
    QgsCoordinateReferenceSystem,
    QgsCsException,
    QgsDataProvider,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFeatureIterator,
    QgsFeatureRequest,
    QgsFields,
    QgsGeometry,
    QgsProviderMetadata,
    QgsProviderRegistry,
    QgsRectangle,
    QgsVectorDataProvider,
)

from geoduck.domain.bridge_types import LoadPlan, build_load_plan, strip_terminator
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.qgis_bridge import sessions
from geoduck.qgis_bridge.convert import column_converter, fields_for, geometry_from_wkb
from geoduck.qgis_bridge.sql_compile import compile_expression

KEY = "geoduck"
DESCRIPTION = "GeoDuck (DuckDB conectada)"
#: Filas por página (qgis-bridge-spec §5.2): el worker queda libre entre páginas.
PAGE = 50_000
#: Columna interna con el FID en la consulta base.
FID = "__geoduck_fid"
#: Desempate determinista entre filas distintas con el mismo FID de contenido (segunda huella).
ORD = "__geoduck_ord"
#: Espera máxima de una página desde el hilo principal: la interfaz no se congela más que esto si la
#: sesión está ocupada (p. ej. con una carga Memoria que, a su vez, espera al hilo principal).
MAIN_WAIT = 5.0
#: Espera máxima desde un hilo de dibujo (se corta antes si QGIS cancela el dibujado).
RENDER_WAIT = 600.0
_POLL = 0.05

_pinned: set[int] = set()
_pinned_lock = threading.Lock()


def keep_thread_state() -> None:
    """Conserva el estado de Python del hilo de QGIS que llama al proveedor.

    QGIS dibuja en hilos que Python no creó. En cada llamada a `fetchFeature`, Python crea el estado del
    hilo y lo destruye al volver (`PyGILState_Ensure`/`Release` con el contador a cero): ~13 µs por
    entidad, más del doble de lo que cuesta construirla (19 s frente a 5,7 s al dibujar 1 M de puntos).
    Una llamada extra a `PyGILState_Ensure`, sin su `Release`, deja vivo ese estado mientras viva el hilo
    (los de QGIS son de un grupo reutilizable). Solo afecta a hilos ajenos a Python que ya ejecutan
    código del proveedor; si `ctypes` no lo permite, todo sigue funcionando, más despacio.
    """
    if threading.current_thread() is threading.main_thread():
        return
    ident = threading.get_ident()
    with _pinned_lock:
        if ident in _pinned:
            return
        _pinned.add(ident)
    try:
        ctypes.pythonapi.PyGILState_Ensure.restype = ctypes.c_int
        ctypes.pythonapi.PyGILState_Ensure()
    except (AttributeError, OSError):  # pragma: no cover - Python sin símbolos exportados
        pass


def encode_uri(params: dict[str, Any]) -> str:
    """URI de la capa: pares `clave=valor` codificados como en una URL; las columnas, en JSON."""
    out = dict(params)
    out["columns"] = json.dumps([list(c) for c in params["columns"]])
    return urlencode({k: v for k, v in out.items() if v is not None})


def decode_uri(uri: str) -> dict[str, Any]:
    params: dict[str, Any] = dict(parse_qsl(uri, keep_blank_values=True))
    params["columns"] = [tuple(c) for c in json.loads(params.get("columns", "[]"))]
    return params


def content_fid_sql(columns: list[str]) -> tuple[str, str]:
    """(FID, desempate) de una fila sin clave: dos huellas de su contenido, en BIGINT no negativo."""
    cols = ", ".join(quote_identifier(c) for c in columns)
    return f"(hash({cols}) >> 1)::BIGINT", f"hash({cols}, 1)"


def key_alias(i: int) -> str:
    """Columna interna con la i-ésima columna de la clave (modo `map`), sin chocar con los campos."""
    return f"__geoduck_k{i}"


def id_columns(fid: str, keys: list[str] | None) -> list[str]:
    """Columnas internas que identifican la fila y ordenan las páginas, según el modo de FID."""
    if fid == "map":
        return [key_alias(i) for i in range(len(keys or []))]
    if fid == "content":
        return [FID, ORD]
    return [FID]


def base_sql(  # noqa: PLR0917 - las piezas de la URI que definen la consulta
    plan: LoadPlan,
    inner: str,
    fid: str,
    key: str | None,
    columns: list[str],
    keys: list[str] | None = None,
    source: str | None = None,
) -> str:
    """Consulta base de la capa: identificador, columnas normalizadas (§7) y geometría primaria.

    `fid`: `key` (clave entera: su valor es el FID), `map` (otra clave: `keys` en columnas internas; el FID
    se asigna en memoria), `rowid` (tabla sin clave, como `ctid` en PostgreSQL) o `content` (vista o
    consulta sin identificador: huella del contenido). `columns`: todas las columnas de `inner`.
    """
    body = strip_terminator(inner)
    fid_col = quote_identifier(FID)
    if fid == "key" and key:
        numbered = f"SELECT {quote_identifier(key)} AS {fid_col}, * FROM (\n{body}\n) AS __geoduck_s"
    elif fid == "map" and keys:
        ident = ", ".join(
            f"{quote_identifier(k)} AS {quote_identifier(key_alias(i))}" for i, k in enumerate(keys)
        )
        numbered = f"SELECT {ident}, * FROM (\n{body}\n) AS __geoduck_s"
    elif fid == "rowid" and source:
        numbered = f"SELECT rowid AS {fid_col}, * FROM {source}"
    else:
        content, order = content_fid_sql(columns)
        ident = f"{content} AS {fid_col}, {order} AS {quote_identifier(ORD)}"
        numbered = f"SELECT {ident}, * FROM (\n{body}\n) AS __geoduck_s"
        fid = "content"
    ids = [quote_identifier(c) for c in id_columns(fid, keys)]
    cols = ids + [f"{f.expression} AS {quote_identifier(f.name)}" for f in plan.fields]
    if plan.geometry is not None:
        cols.append(quote_identifier(plan.geometry.name))
    return f"SELECT {', '.join(cols)} FROM ({numbered}) AS __geoduck_q"


def sql_literal(value: Any, duck_type: str) -> str:
    """Valor de una clave leído de DuckDB → literal SQL del mismo tipo (páginas y filtros por FID)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return f"CAST({value} AS {duck_type})"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"CAST(unhex('{bytes(value).hex()}') AS {duck_type})"
    if isinstance(value, float):
        return f"CAST({value!r} AS {duck_type})"
    return f"CAST({quote_string_literal(str(value))} AS {duck_type})"


def _extent_polygon(rect: QgsRectangle) -> str:
    x0, y0, x1, y1 = rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()
    ring = f"{x0!r} {y0!r}, {x1!r} {y0!r}, {x1!r} {y1!r}, {x0!r} {y1!r}, {x0!r} {y0!r}"
    return f"'POLYGON(({ring}))'::GEOMETRY"


class _Source(QgsAbstractFeatureSource):  # type: ignore[misc]
    def __init__(self, provider: GeoDuckProvider) -> None:
        super().__init__()
        self.p = provider

    def getFeatures(self, request: QgsFeatureRequest = QgsFeatureRequest()) -> QgsFeatureIterator:  # noqa: B008
        return QgsFeatureIterator(_Iterator(self.p, request))


class _Iterator(QgsAbstractFeatureIterator):  # type: ignore[misc]
    def __init__(self, provider: GeoDuckProvider, request: QgsFeatureRequest) -> None:
        keep_thread_state()
        super().__init__(request)
        self.p = provider
        self.r = QgsFeatureRequest(request)
        self.closed = False
        self.local: QgsExpression | None = None
        self.limit: int | None = int(self.r.limit()) if self.r.limit() >= 0 else None
        self._reset()
        self.transform = self.r.calculateTransform(provider.crs())
        try:
            self.rect = self.filterRectToSourceCrs(self.transform)
        except QgsCsException:
            self.closed = True
            return
        if not provider.isValid():
            self.closed = True
            return
        self._prepare()

    def _reset(self) -> None:
        self.batches: list[Any] = []
        self.batch_index = 0
        self.n = 0
        self.pos = 0
        self.after: int | None = None
        #: Filas ya consumidas con FID == `after` (empates de filas idénticas).
        self.ties = 0
        #: Filas con FID == `page_after` que la página actual repite al principio y se saltan.
        self.skip = 0
        self.page_after: int | None = None
        #: Modo `map`: la última clave leída (las claves son únicas: sin empates).
        self.after_key: tuple[Any, ...] | None = None
        self.exhausted = False
        self.returned = 0

    # -- SQL de la petición ------------------------------------------------------------------------

    def _prepare(self) -> None:
        p, r = self.p, self.r
        plan = p.plan
        geometry = plan.geometry
        flags = r.flags()
        names = [f.name for f in plan.fields]
        if flags & Qgis.FeatureRequestFlag.SubsetOfAttributes:
            self.wanted = [names[i] for i in r.subsetOfAttributes() if 0 <= i < len(names)]
        else:
            self.wanted = names
        has_rect = not self.rect.isNull() and geometry is not None
        self.exact = has_rect and bool(flags & Qgis.FeatureRequestFlag.ExactIntersect)
        self.return_geom = geometry is not None and not flags & Qgis.FeatureRequestFlag.NoGeometry
        self.mapped = p.fid_mode == "map"
        self.ids = id_columns(p.fid_mode, p.keys)
        cols = [quote_identifier(c) for c in self.ids] + [quote_identifier(n) for n in self.wanted]
        self.geom: str | None = None
        if geometry is not None and (self.return_geom or self.exact):
            self.geom = geometry.name
            cols.append(quote_identifier(geometry.name))
        where: list[str] = []
        if has_rect:
            g = quote_identifier(geometry.name)  # type: ignore[union-attr]
            where.append(f"st_intersects_extent({g}, {_extent_polygon(self.rect)})")
        ft = r.filterType()
        if ft in (Qgis.FeatureRequestFilterType.Fid, Qgis.FeatureRequestFilterType.Fids):
            if ft == Qgis.FeatureRequestFilterType.Fid:
                fids = [int(r.filterFid())]
            else:
                fids = sorted(int(x) for x in r.filterFids())
            where.append(self._fid_filter(fids))
        elif ft == Qgis.FeatureRequestFilterType.Expression and r.filterExpression() is not None:
            expr = r.filterExpression()
            compiled = compile_expression(expr.rootNode(), p.comparable)
            if compiled:
                where.append(compiled)
            else:  # misma semántica que QGIS: se evalúa en Python sobre lo ya filtrado en SQL
                self.local = QgsExpression(expr.expression())
                self.ctx = QgsExpressionContext()
                self.ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(None))
                self.local.prepare(self.ctx)
        self.select = ", ".join(cols)
        self.where = where

    def _key_tuple_sql(self, values: tuple[Any, ...]) -> str:
        p = self.p
        lits = [sql_literal(v, p.key_types[i]) for i, v in enumerate(values)]
        return lits[0] if len(lits) == 1 else "(" + ", ".join(lits) + ")"

    def _key_columns_sql(self) -> str:
        cols = [quote_identifier(c) for c in self.ids]
        return cols[0] if len(cols) == 1 else "(" + ", ".join(cols) + ")"

    def _fid_filter(self, fids: list[int]) -> str:
        if not self.mapped:
            return f"{quote_identifier(FID)} IN ({', '.join(map(str, fids)) or 'NULL'})"
        keys = self.p.keys_for(fids)  # FID asignados en esta sesión de QGIS; uno desconocido no existe
        if not keys:
            return "FALSE"
        return f"{self._key_columns_sql()} IN ({', '.join(self._key_tuple_sql(k) for k in keys)})"

    def page_size(self) -> int:
        if self.limit is not None and self.local is None and not self.exact:
            return max(0, min(PAGE, self.limit - self.returned))
        return PAGE

    def page_sql(self, size: int) -> str:
        where = list(self.where)
        if self.mapped:
            if self.after_key is not None:
                where.append(f"{self._key_columns_sql()} > {self._key_tuple_sql(self.after_key)}")
            clause = (" WHERE " + " AND ".join(where)) if where else ""
            order = ", ".join(quote_identifier(c) for c in self.ids)
            base = f"SELECT {self.select} FROM ({self.p.base}) AS __geoduck_c{clause}"
            return f"{base} ORDER BY {order} LIMIT {size}"
        if self.after is not None:
            where.append(f"{quote_identifier(FID)} >= {self.after}")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        order = (
            quote_identifier(FID)
            if self.p.fid_mode != "content"
            else f"{quote_identifier(FID)}, {quote_identifier(ORD)}"
        )
        return (
            f"SELECT {self.select} FROM ({self.p.base}) AS __geoduck_c{clause} "
            f"ORDER BY {order} LIMIT {size + self.ties}"
        )

    # -- páginas -------------------------------------------------------------------------------

    def _wait(self, engine: Any, handle: Any) -> list[Any] | None:
        main = threading.current_thread() is threading.main_thread()
        budget = MAIN_WAIT if main else RENDER_WAIT
        feedback = self.r.feedback() if hasattr(self.r, "feedback") else None
        waited = 0.0
        while True:
            try:
                return handle.future.result(_POLL)  # type: ignore[no-any-return]
            except FutureTimeout:
                waited += _POLL
            if self.closed or (feedback is not None and feedback.isCanceled()) or waited >= budget:
                engine.cancel(handle.op_id)  # descarta la página pendiente (§5.3)
                if waited >= budget:
                    self.p.note_error("La sesión está ocupada; la capa se completará al repintar")
                return None

    def _next_page(self) -> bool:
        if self.exhausted or self.closed:
            return False
        size = self.page_size()
        if size == 0:
            return False
        engine = sessions.get(self.p.session)
        if engine is None:
            self.p.note_error("Sesión no disponible")
            return False
        requested = size + self.ties
        try:
            handle = engine.read_table(self.page_sql(size), priority=True)
            batches = self._wait(engine, handle)
        except Exception as exc:
            self.p.note_error(str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
            return False
        if batches is None:
            return False
        self.p.note_ok()
        rows = int(sum(b.num_rows for b in batches))
        if rows < requested:
            self.exhausted = True
        self.batches, self.batch_index = batches, 0
        self.skip, self.page_after = self.ties, self.after
        return rows > self.ties

    def _load_batch(self) -> bool:
        while self.batch_index < len(self.batches):
            batch = self.batches[self.batch_index]
            self.batch_index += 1
            if batch.num_rows == 0:
                continue
            names = batch.schema.names
            kinds = self.p.kinds
            self.cols = [
                (self.p.field_index[name], column_converter(kinds[name])(batch.column(names.index(name))))
                for name in self.wanted
            ]
            if self.mapped:
                columns = [batch.column(names.index(c)).to_pylist() for c in self.ids]
                self.keyrows = list(zip(*columns, strict=True))
                self.fids = [self.p.fid_for(k) for k in self.keyrows]
            else:
                self.fids = batch.column(names.index(FID)).to_pylist()
            self.wkbs = batch.column(names.index(self.geom)).to_pylist() if self.geom else None
            self.n, self.pos = batch.num_rows, 0
            return True
        self.n, self.pos = 0, 0
        return False

    def fetchFeature(self, f: QgsFeature) -> bool:  # noqa: PLR0912 - un bucle por fila, con sus filtros
        if self.closed:
            return False
        while True:
            if self.limit is not None and self.returned >= self.limit:
                self.close()
                return False
            if self.pos >= self.n:
                if self._load_batch():
                    continue
                if not self._next_page():
                    self.close()
                    return False
                continue
            i = self.pos
            self.pos += 1
            fid = int(self.fids[i])
            if self.mapped:
                self.after_key = self.keyrows[i]
            else:
                if self.skip and fid == self.page_after:  # ya entregada en la página anterior
                    self.skip -= 1
                    continue
                self.skip = 0
                if fid == self.after:
                    self.ties += 1
                else:
                    self.after, self.ties = fid, 1
            g: QgsGeometry | None = geometry_from_wkb(self.wkbs[i]) if self.wkbs is not None else None
            if self.exact and (g is None or g.isNull() or not g.intersects(self.rect)):
                continue
            f.setFields(self.p.fields_, True)
            for index, col in self.cols:
                f.setAttribute(index, col[i])
            f.setId(fid)
            if self.return_geom and g is not None and not g.isNull():
                f.setGeometry(g)
                self.geometryToDestinationCrs(f, self.transform)
            else:
                f.clearGeometry()
            f.setValid(True)
            if self.local is not None:
                self.ctx.setFeature(f)
                if not bool(self.local.evaluate(self.ctx)):
                    continue
            self.returned += 1
            return True

    def rewind(self) -> bool:
        if self.closed:
            return False
        self._reset()
        return True

    def close(self) -> bool:
        self.closed = True
        self.batches = []
        self.n = self.pos = 0
        return True


class GeoDuckProvider(QgsVectorDataProvider):  # type: ignore[misc]
    @classmethod
    def providerKey(cls) -> str:
        return KEY

    @classmethod
    def description(cls) -> str:
        return DESCRIPTION

    @classmethod
    def createProvider(cls, uri: str, options: Any, flags: Any = None) -> GeoDuckProvider:
        return GeoDuckProvider(uri, options, flags)

    def __init__(self, uri: str = "", options: Any = None, flags: Any = None) -> None:
        super().__init__(
            uri,
            options if options is not None else QgsDataProvider.ProviderOptions(),
            flags if flags is not None else Qgis.DataProviderReadFlags(),
        )
        self._uri = uri
        self._fid_lock = threading.Lock()
        self._fid_of: dict[tuple[Any, ...], int] = {}
        self._key_of: list[tuple[Any, ...]] = []
        self.unavailable = False
        self.last_error = ""
        self._valid = False
        self.fields_ = QgsFields()
        self._crs = QgsCoordinateReferenceSystem()
        self._extent = QgsRectangle()
        self._count = -1
        self._wkb = Qgis.WkbType.Unknown
        try:
            params = decode_uri(uri)
            self.session: str = params.get("session", "")
            self.source: str | None = params.get("source") or None
            self.inner: str = params["sql"]
            self.key: str | None = params.get("key") or None
            self.fid_mode: str = params.get("fid", "content")
            self.plan: LoadPlan = build_load_plan(
                self.inner, list(params["columns"]), geometry=params.get("geom") or None
            )
            self.keys: list[str] = json.loads(params.get("keys") or "[]")
            types = {c[0]: c[1] for c in params["columns"]}
            self.key_types = [types[k] for k in self.keys]
            valid = {
                "key": bool(self.key),
                "map": bool(self.keys),
                "rowid": bool(self.source),
                "content": True,
            }
            if not valid.get(self.fid_mode, False):
                self.fid_mode = "content"
            self.base = base_sql(
                self.plan,
                self.inner,
                self.fid_mode,
                self.key,
                [c[0] for c in params["columns"]],
                self.keys,
                self.source,
            )
            ext = [float(v) for v in params.get("extent", "").split(",") if v]
            count = int(params.get("count", "-1"))
            wkb = params.get("type") or ""
        except Exception as exc:
            self.last_error = f"URI no válida: {exc}"
            return
        self.fields_ = fields_for(self.plan)
        self.kinds = {f.name: f.kind for f in self.plan.fields}
        self.field_index = {f.name: i for i, f in enumerate(self.plan.fields)}
        #: Columnas que DuckDB compara igual que QGIS: las que llegan sin convertir (§7).
        self.comparable = {f.name for f in self.plan.fields if f.expression == quote_identifier(f.name)}
        if params.get("crs"):
            self._crs = QgsCoordinateReferenceSystem(params["crs"])
        if len(ext) == 4:
            self._extent = QgsRectangle(*ext)
        self._count = count
        if self.plan.geometry is None:
            self._wkb = Qgis.WkbType.NoGeometry
        elif wkb:
            self._wkb = getattr(Qgis.WkbType, wkb, Qgis.WkbType.Unknown)
        self._valid = True

    # -- estado de la sesión -------------------------------------------------------------------

    def fid_for(self, key: tuple[Any, ...]) -> int:
        """Modo `map` (PktFidMap de QGIS): FID estable en esta sesión de QGIS para un valor de la clave."""
        with self._fid_lock:
            fid = self._fid_of.get(key)
            if fid is None:
                self._key_of.append(key)
                fid = self._fid_of[key] = len(self._key_of)
            return fid

    def keys_for(self, fids: list[int]) -> list[tuple[Any, ...]]:
        with self._fid_lock:
            return [self._key_of[f - 1] for f in fids if 1 <= f <= len(self._key_of)]

    def note_error(self, message: str) -> None:
        self.unavailable = True
        self.last_error = message

    def note_ok(self) -> None:
        self.unavailable = False

    # -- QgsVectorDataProvider -----------------------------------------------------------------

    def featureSource(self) -> _Source:
        return _Source(self)

    def getFeatures(self, request: QgsFeatureRequest = QgsFeatureRequest()) -> QgsFeatureIterator:  # noqa: B008
        return QgsFeatureIterator(_Iterator(self, request))

    def fields(self) -> QgsFields:
        return self.fields_

    def wkbType(self) -> Any:
        return self._wkb

    def featureCount(self) -> int:
        return self._count

    def extent(self) -> QgsRectangle:
        return QgsRectangle(self._extent)

    def crs(self) -> QgsCoordinateReferenceSystem:
        return self._crs

    def isValid(self) -> bool:
        return self._valid

    def capabilities(self) -> Any:
        return Qgis.VectorProviderCapability.SelectAtId

    def dataSourceUri(self, expandAuthConfig: bool = True) -> str:
        return self._uri

    def name(self) -> str:
        return KEY

    def storageType(self) -> str:
        return DESCRIPTION


def register_provider() -> None:
    """Registra el proveedor una vez por proceso (QGIS no permite quitar un proveedor registrado)."""
    registry = QgsProviderRegistry.instance()
    if KEY not in registry.providerList():
        registry.registerProvider(QgsProviderMetadata(KEY, DESCRIPTION, GeoDuckProvider.createProvider))
