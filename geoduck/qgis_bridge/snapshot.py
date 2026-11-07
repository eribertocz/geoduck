# SPDX-License-Identifier: GPL-2.0-or-later
"""Modalidad Instantánea: DuckDB → GeoArrow → GDAL `WriteArrow` → GeoPackage en `/vsimem` (§4).

GDAL escribe cada lote dentro de la operación del worker (sin objetos de QGIS) en un GeoPackage nuevo y en
una transacción de GDAL. Al terminar, el hilo principal abre la capa con el proveedor `ogr`, comprueba el
conteo y la publica. En error o cancelación se revierte, se libera el archivo y no se publica nada.

GDAL se usa sin activar sus excepciones globales (ADR-0011): se comprueban los códigos de retorno y los
mensajes se silencian con un manejador propio del hilo del worker.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
from osgeo import gdal, ogr, osr
from qgis.core import QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QTimer

from geoduck.domain.bridge_types import FieldKind, LoadPlan, missing_crs_warning
from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.i18n import tr
from geoduck.domain.load import COPY_ACCESS, LoadMode, LoadReport, LoadRequest, describe_origin
from geoduck.domain.operations import ReadOutcome
from geoduck.qgis_bridge.convert import crs_from_field, strip_unreadable
from geoduck.qgis_bridge.copies import mark_copy
from geoduck.qgis_bridge.memory import LoadCancelledError
from geoduck.qgis_bridge.reproject import Reprojector
from geoduck.qgis_bridge.vsimem import PREFIX, VsimemRegistry, unlink

#: GDAL ≥ 3.8: `OGRLayer.WriteArrowBatch` con geometrías GeoArrow (qgis-bridge-spec §4).
MIN_GDAL = 3_08_00_00

_OGR_TYPE = {
    FieldKind.BOOL: (ogr.OFTInteger, ogr.OFSTBoolean),
    FieldKind.INT: (ogr.OFTInteger, ogr.OFSTNone),
    FieldKind.INT64: (ogr.OFTInteger64, ogr.OFSTNone),
    FieldKind.DOUBLE: (ogr.OFTReal, ogr.OFSTNone),
    FieldKind.TEXT: (ogr.OFTString, ogr.OFSTNone),
    FieldKind.DATE: (ogr.OFTDate, ogr.OFSTNone),
    FieldKind.DATETIME: (ogr.OFTDateTime, ogr.OFSTNone),
    FieldKind.DATETIME_TZ: (ogr.OFTDateTime, ogr.OFSTNone),
    FieldKind.BINARY: (ogr.OFTBinary, ogr.OFSTNone),
}

_WKB_NAMES = {
    1: "POINT",
    2: "LINESTRING",
    3: "POLYGON",
    4: "MULTIPOINT",
    5: "MULTILINESTRING",
    6: "MULTIPOLYGON",
    7: "GEOMETRYCOLLECTION",
}


def unavailable_reason() -> str | None:
    """None si la Instantánea está disponible; si no, el motivo para mostrarlo en la interfaz."""
    if int(gdal.VersionInfo()) < MIN_GDAL:
        return tr("Requires GDAL 3.8 or later (this QGIS comes with GDAL {0})").format(gdal.__version__)
    if not hasattr(ogr.Layer, "WritePyArrow") or ogr.GetDriverByName("GPKG") is None:
        return tr("The GDAL of this QGIS cannot write GeoPackage from Arrow")
    return None


def _crs_from_text(text: str) -> QgsCoordinateReferenceSystem:
    crs = QgsCoordinateReferenceSystem()
    crs.createFromUserInput(text)
    return crs


def _last_error(default: str) -> str:
    return gdal.GetLastErrorMsg() or default


def fid_column(names: set[str]) -> str:
    """El identificador que pide el GeoPackage: `fid`; si la tabla ya tiene una columna `fid`, `geoduck_fid`;
    si también la tiene (vuelta de una copia a DuckDB), `geoduck_fid_2`, `_3`… Nunca choca con una columna."""
    candidates = ["fid", "geoduck_fid"]
    candidates += [f"geoduck_fid_{n}" for n in range(2, len(names) + 3)]
    return next(name for name in candidates if name not in names)


class _Writer:
    """Escritor GDAL. Solo se usa en el hilo del worker (creación, lotes y cierre)."""

    def __init__(self, path: str, plan: LoadPlan, crs_override: str | None) -> None:
        self.path = path
        self.plan = plan
        self.crs_override = crs_override
        self.ds: Any = None
        self.layer: Any = None
        self.rows = 0
        self.nulls = 0
        self.geom_codes: set[int] = set()
        self.has_crs = False
        #: El SRC escrito en el GeoPackage, como texto para QGIS (`createFromUserInput`); "" sin SRC.
        self.crs_text = ""

    def _srs(self, schema: pa.Schema | None) -> Any:
        if self.crs_override is not None:
            if not self.crs_override:
                return None
            srs = osr.SpatialReference()
            if srs.SetFromUserInput(self.crs_override) != 0:
                raise GeoDuckError(
                    tr("CRS not recognized: {0}").format(self.crs_override), code=ErrorCode.INVALID_ARGUMENT
                )
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            self.crs_text = self.crs_override
            return srs
        info = None
        if schema is not None and self.plan.geometry is not None:
            meta = schema.field(self.plan.geometry.name).metadata or {}
            try:
                info = json.loads(meta.get(b"ARROW:extension:metadata") or b"{}").get("crs")
            except ValueError:
                info = None
        if info is None and self.plan.geometry is not None:
            info = self.plan.geometry.declared_crs
        if not info:
            return None
        text = json.dumps(info) if isinstance(info, dict) else str(info)
        srs = osr.SpatialReference()
        if srs.SetFromUserInput(text) != 0:
            return None
        self.crs_text = text
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)  # C4: sin reordenar ejes
        return srs

    def open(self, schema: pa.Schema | None) -> None:
        driver = ogr.GetDriverByName("GPKG")
        self.ds = driver.CreateDataSource(self.path)
        if self.ds is None:
            raise GeoDuckError(_last_error(tr("GDAL could not create the GeoPackage")))
        names = {f.name.lower() for f in self.plan.fields}
        fid = fid_column(names)
        geom = self.plan.geometry
        options = [f"FID={fid}", "SPATIAL_INDEX=YES"]
        if geom is not None:
            options.append(f"GEOMETRY_NAME={geom.name}")
        srs = self._srs(schema)
        self.has_crs = srs is not None
        self.layer = self.ds.CreateLayer(
            "datos", srs, ogr.wkbUnknown if geom is not None else ogr.wkbNone, options
        )
        if self.layer is None:
            raise GeoDuckError(_last_error(tr("GDAL could not create the layer")))
        for f in self.plan.fields:
            kind, subtype = _OGR_TYPE[f.kind]
            definition = ogr.FieldDefn(f.name, kind)
            definition.SetSubType(subtype)
            if self.layer.CreateField(definition) != 0:
                raise GeoDuckError(_last_error(tr("GDAL rejected the field «{0}»").format(f.name)))
        if self.ds.StartTransaction() != 0:
            raise GeoDuckError(_last_error(tr("GDAL could not start the transaction")))

    def write(self, batch: pa.RecordBatch) -> None:
        batch = strip_unreadable(batch, self.plan, self.rows)
        if self.ds is None:
            self.open(batch.schema)
        geom = self.plan.geometry
        options = [f"GEOMETRY_NAME={geom.name}"] if geom is not None else []
        if geom is not None:
            self._collect_types(batch.column(batch.schema.get_field_index(geom.name)))
        if self.layer.WritePyArrow(batch, options=options) != 0:
            raise GeoDuckError(_last_error(tr("GDAL could not write the batch")))
        self.rows += batch.num_rows

    def _collect_types(self, wkb: pa.Array) -> None:
        """Tipos de geometría presentes, leyendo solo la cabecera WKB de los valores distintos (C++)."""
        self.nulls += wkb.null_count
        heads = pc.unique(pc.binary_slice(wkb.drop_null(), 0, 5)).to_pylist()
        for head in heads:
            if head and len(head) == 5:
                self.geom_codes.add(int.from_bytes(head[1:5], "little" if head[0] == 1 else "big"))

    def commit(self) -> None:
        if self.ds is None:
            self.open(None)
        if self.ds.CommitTransaction() != 0:
            raise GeoDuckError(_last_error(tr("GDAL could not commit the GeoPackage")))
        self._declare_geometry_type()
        self.ds = None  # cierra y vuelca el archivo
        self.layer = None

    def families(self) -> dict[str, str]:
        """Familia de geometría → nombre para `geometrytype=` (X, o MultiX si hay alguna múltiple)."""
        found: dict[int, bool] = {}
        for code in self.geom_codes:
            base = code % 1000
            single = base - 3 if base in (4, 5, 6) else base
            found[single] = found.get(single, False) or base in (4, 5, 6)
        names = {1: "Point", 2: "LineString", 3: "Polygon", 7: "GeometryCollection"}
        return {
            names.get(k, "Unknown"): ("Multi" if multi and k != 7 else "") + names.get(k, "Unknown")
            for k, multi in sorted(found.items())
        }

    def mixed_dimensions(self) -> bool:
        """Alguna familia tiene geometrías con y sin Z/M (la capa declara todas: spatial-spec §6)."""
        dims: dict[int, set[int]] = {}
        for code in self.geom_codes:
            base = code % 1000
            dims.setdefault(base - 3 if base in (4, 5, 6) else base, set()).add(code // 1000)
        return any(len(d) > 1 for d in dims.values())

    def _declare_geometry_type(self) -> None:
        """Si todas las geometrías son de una familia (X o MultiX), la capa lo declara (si no, GEOMETRY)."""
        if self.plan.geometry is None or not self.geom_codes:
            return
        bases = {c % 1000 for c in self.geom_codes}
        dims = {c // 1000 for c in self.geom_codes}
        singles = {b - 3 if b in (4, 5, 6) else b for b in bases}
        if len(singles) != 1 or 7 in bases:
            return
        base = next(iter(singles)) + (3 if any(b in (4, 5, 6) for b in bases) else 0)
        name = _WKB_NAMES[base]
        # Todas las dimensiones presentes (spatial-spec §6): Z/M si alguna geometría la tiene
        z, m = int(any(d in (1, 3) for d in dims)), int(any(d in (2, 3) for d in dims))
        self.ds.ExecuteSQL(
            f"UPDATE gpkg_geometry_columns SET geometry_type_name = '{name}', z = {z}, m = {m} "
            "WHERE table_name = 'datos'"
        )

    def abort(self) -> None:
        if self.ds is not None:
            self.ds.RollbackTransaction()
        self.ds = None
        self.layer = None
        unlink(self.path)


class SnapshotLoad:
    """Una carga Instantánea. Se crea en el hilo principal; GDAL escribe en el hilo del worker."""

    mode = LoadMode.SNAPSHOT

    def __init__(
        self,
        engine: Any,
        request: LoadRequest,
        *,
        on_progress: Callable[[int], None],
        on_done: Callable[[LoadReport | BaseException], None],
        registry: VsimemRegistry,
        project: QgsProject | None = None,
    ) -> None:
        self._engine = engine
        self._request = request
        self._on_progress = on_progress
        self._on_done = on_done
        self._registry = registry
        self._project = project or QgsProject.instance()
        self._path = f"{PREFIX}{uuid.uuid4().hex}.gpkg"
        self._writer: _Writer | None = None
        self._handle: Any = None
        self._lock = threading.Lock()
        self._result: tuple[str, Any] | None = None  # ("ok", (plan, rows)) | ("error", exc)
        self._cancelled = threading.Event()
        self._finished = False
        self._reported = -1
        self._reprojector: Reprojector | None = None
        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._poll)

    @property
    def path(self) -> str:
        return self._path

    def start(self) -> None:
        target = self._request.reproject_to
        context = QgsProject.instance().transformContext()  # copia: se usa en el hilo del worker

        def on_plan(plan: LoadPlan) -> None:  # hilo del worker
            # Con «Reproyectar a…», el GeoPackage se crea ya en el SRC de destino (spatial-spec §4)
            self._writer = _Writer(self._path, plan, target or self._request.crs_override)

        def reproject(batch: pa.RecordBatch, writer: _Writer) -> pa.RecordBatch:  # hilo del worker
            geom = writer.plan.geometry
            if not target or geom is None:
                return batch
            if self._reprojector is None:
                source = crs_from_field(batch.schema.field(geom.name), self._request.crs_override)
                if not source.isValid() and geom.declared_crs and self._request.crs_override is None:
                    source = QgsCoordinateReferenceSystem(geom.declared_crs)
                self._reprojector = Reprojector(source, target, context)
            return self._reprojector.batch(batch, geom.name, writer.rows)

        def on_batch(batch: pa.RecordBatch) -> None:  # hilo del worker
            if self._cancelled.is_set():
                raise LoadCancelledError(tr("Loading cancelled"))
            assert self._writer is not None
            gdal.PushErrorHandler("CPLQuietErrorHandler")  # propio de este hilo: no toca a QGIS
            try:
                self._writer.write(reproject(batch, self._writer))
            finally:
                gdal.PopErrorHandler()

        self._handle = self._engine.load_query(
            self._request.sql,
            geometry=self._request.geometry,
            formats=self._request.format_map or None,
            database=self._request.database,
            on_plan=on_plan,
            on_batch=on_batch,
        )
        self._handle.future.add_done_callback(self._on_read_done)
        self._timer.start()

    def cancel(self) -> None:
        if self._finished:
            return
        self._cancelled.set()
        if self._handle is not None and not self._handle.future.done():
            self._engine.cancel(self._handle.op_id)

    def _on_read_done(self, fut: Any) -> None:  # hilo del worker: cierra GDAL aquí mismo
        writer = self._writer
        gdal.PushErrorHandler("CPLQuietErrorHandler")
        try:
            exc = fut.exception()
            if exc is None:
                outcome = fut.result()
                if self._cancelled.is_set() or outcome.summary.outcome is ReadOutcome.CANCELLED:
                    exc = LoadCancelledError(tr("Loading cancelled"))
                elif outcome.summary.outcome is not ReadOutcome.EXHAUSTED:
                    exc = GeoDuckError(tr("Reading failed: {0}").format(outcome.summary.error))
            if exc is None and writer is not None:
                writer.commit()
                families = writer.families() if writer.plan.geometry is not None else {}
                result: tuple[str, Any] = (
                    "ok",
                    (writer.plan, writer.rows, fut.result().summary.rows, families, writer.nulls),
                )
            else:
                if writer is not None:
                    writer.abort()
                else:
                    unlink(self._path)
                result = ("error", exc or GeoDuckError(tr("Reading ended without a plan")))
        except BaseException as err:
            if writer is not None:
                writer.abort()
            result = ("error", err)
        finally:
            gdal.PopErrorHandler()
        with self._lock:
            self._result = result

    # -- hilo principal --------------------------------------------------------------------------

    def _open_layers(self, families: dict[str, str], nulls: int) -> list[QgsVectorLayer]:
        """Una capa; o, con geometrías de varios tipos, una por familia (+ «sin geometría» si hay nulas)."""
        name = self._request.layer_name
        if len(families) <= 1:
            specs = [(self._path, name)]
        else:
            base = f"{self._path}|layername=datos|geometrytype="
            specs = [(base + gtype, f"{name} — {family}") for family, gtype in families.items()]
            if nulls:  # ningún `geometrytype=` selecciona las nulas: filtro por atributo (medido en E3)
                plan = self._writer.plan if self._writer is not None else None
                column = plan.geometry.name if plan is not None and plan.geometry is not None else "geom"
                quoted = '"' + column.replace('"', '""') + '"'
                specs.append(
                    (
                        f"{self._path}|layername=datos|subset={quoted} IS NULL",
                        tr("{0} — no geometry").format(name),
                    )
                )
        layers = []
        for uri, layer_name in specs:
            layer = QgsVectorLayer(uri, layer_name, "ogr")
            if not layer.isValid():
                raise GeoDuckError(tr("QGIS could not open the created GeoPackage"))
            if self._writer is not None and not self._writer.has_crs and layer.isSpatial():
                # Sin CRS en los datos: QGIS 3.34 asigna uno en silencio al abrir el GeoPackage (C4).
                layer.setCrs(QgsCoordinateReferenceSystem())
            elif self._writer is not None and self._writer.has_crs and not layer.crs().isValid():
                # F-122: con tipo de geometría «desconocido» (colecciones), QGIS no toma el SRC del archivo
                layer.setCrs(_crs_from_text(self._writer.crs_text))
            layers.append(layer)
        return layers

    def _poll(self) -> None:
        with self._lock:
            result = self._result
        writer = self._writer
        if result is None:
            if writer is not None and writer.rows != self._reported:
                self._reported = writer.rows
                self._on_progress(writer.rows)
            return
        self._timer.stop()
        self._finished = True
        kind, value = result
        if kind == "error":
            self._on_done(value)
            return
        plan, written, read, families, nulls = value
        try:
            if len(families) > 1 and not self._request.split_families:
                raise GeoDuckError(
                    tr(
                        "Geometries of different types ({0}) and the option «Mixed types: "
                        "one layer per type» is off: nothing was loaded"
                    ).format(", ".join(families.values())),
                    code=ErrorCode.INVALID_ARGUMENT,
                )
            layers = self._open_layers(families, nulls)
            count = sum(layer.featureCount() for layer in layers)
            if not (read == written == count):
                raise GeoDuckError(
                    tr("Different counts: read {0}, written {1}, in the layers {2}").format(
                        read, written, count
                    )
                )
            self._registry.track(self._path)
            for item in layers:
                mark_copy(item)  # «Guardar las copias junto al proyecto» (G9) la reconoce
            self._project.addMapLayers(layers)  # todas o ninguna (§8)
        except BaseException as exc:
            unlink(self._path)
            self._on_done(exc)
            return
        layer = layers[0]
        warnings = plan.warnings
        if self._reprojector is not None:
            warnings = (*warnings, self._reprojector.note)
        if self._writer is not None and self._writer.mixed_dimensions():
            warnings = (*warnings, tr("Mixed Z/M dimensions: geometries without them are shown with NaN"))
        if len(layers) > 1:
            warnings = (*warnings, tr("Mixed geometry types: {0} layers, one per type").format(len(layers)))
        if plan.geometry is not None and not layer.crs().isValid():
            warnings = (*warnings, missing_crs_warning(plan.geometry, self._request.crs_override))
        self._on_progress(written)
        self._on_done(
            LoadReport(
                layer.id(),
                layer.name(),
                LoadMode.SNAPSHOT,
                written,
                warnings,
                origin=describe_origin(self._request),
                access=COPY_ACCESS,
                layers=tuple((lyr.id(), lyr.name()) for lyr in layers) if len(layers) > 1 else (),
            )
        )
