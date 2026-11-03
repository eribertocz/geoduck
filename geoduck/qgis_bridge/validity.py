# SPDX-License-Identifier: GPL-2.0-or-later
"""Diagnóstico y reparación de geometrías con QGIS/GEOS (spatial-spec §9; D2 del propietario, 2026-11-02).

- **Diagnosticar** recorre la capa en una `QgsTask` cancelable, desde una copia de su fuente
  (`QgsVectorLayerFeatureSource`, segura en otro hilo). No modifica la capa ni el origen; no usa `spatial`.
- **Reparar en una copia** aplica `QgsGeometry.makeValid()` a las inválidas y crea capas nuevas en memoria
  `<capa> (reparada)` (una por tipo si la reparación cambia de familia, F-98). Informa los cambios de
  tipo, dimensión y número de partes, y las que no se pudieron reparar. Cancelar o fallar no publica nada.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsTask,
    QgsVectorLayer,
    QgsVectorLayerFeatureSource,
    QgsWkbTypes,
)

from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.i18n import tr
from geoduck.domain.validity import MAX_REASONS, GeometryDiagnosis, RepairReport
from geoduck.qgis_bridge.families import FamilyLayers
from geoduck.qgis_bridge.provider import KEY

Done = Callable[[Any], None]


class CancelledError(GeoDuckError):
    code = ErrorCode.CANCELLED


def _geos_engine() -> Any:
    engine = getattr(Qgis, "GeometryValidationEngine", None)
    return engine.Geos if engine is not None else QgsGeometry.ValidatorGeos


def _reason(g: QgsGeometry) -> str:
    errors = g.validateGeometry(_geos_engine())
    return errors[0].what() if errors else tr("invalid according to GEOS")


def _parts(g: QgsGeometry) -> int:
    return int(g.constGet().partCount()) if g.constGet() is not None else 0


class DiagnoseTask(QgsTask):  # type: ignore[misc]
    """Recorre la capa y cuenta cada estado. El resultado llega a `on_done` en el hilo principal."""

    def __init__(self, layer: QgsVectorLayer, on_done: Done) -> None:
        super().__init__(
            tr("GeoDuck: diagnose geometries of «{0}»").format(layer.name()), QgsTask.Flag.CanCancel
        )
        self._source = QgsVectorLayerFeatureSource(layer)
        self._id, self._name = layer.id(), layer.name()
        self._total = max(layer.featureCount(), 1)
        provider = layer.dataProvider()
        self._unreadable_source = provider if layer.providerType() == KEY else None
        self._on_done = on_done
        self.diagnosis: GeometryDiagnosis | None = None
        self.error: BaseException | None = None

    def run(self) -> bool:
        try:
            self.diagnosis = self._diagnose()
        except BaseException as exc:
            self.error = exc
            return False
        return not self.isCanceled()

    def _diagnose(self) -> GeometryDiagnosis:
        unreadable_set: set[int] = set()
        if self._unreadable_source is not None:  # columnas WKB/WKT marcadas de una capa Conectada
            unreadable_set = set(self._unreadable_source.unreadable_fids())
        counts = dict.fromkeys(("valid", "invalid", "empty", "null", "unreadable"), 0)
        invalid: list[int] = []
        unreadable: list[int] = []
        reasons: list[tuple[int, str]] = []
        request = QgsFeatureRequest().setNoAttributes()
        examined = 0
        for f in self._source.getFeatures(request):
            if self.isCanceled():
                raise CancelledError(tr("Diagnosis cancelled"))
            examined += 1
            g = f.geometry()
            fid = int(f.id())
            if g is None or g.isNull():
                if fid in unreadable_set:
                    counts["unreadable"] += 1
                    unreadable.append(fid)
                else:
                    counts["null"] += 1
            elif g.isEmpty():
                counts["empty"] += 1
            elif g.isGeosValid():
                counts["valid"] += 1
            else:
                counts["invalid"] += 1
                invalid.append(fid)
                if len(reasons) < MAX_REASONS:
                    reasons.append((fid, _reason(g)))
            if examined % 1000 == 0:
                self.setProgress(min(99.0, 100.0 * examined / self._total))
        return GeometryDiagnosis(
            self._id,
            self._name,
            examined,
            counts["valid"],
            counts["invalid"],
            counts["empty"],
            counts["null"],
            counts["unreadable"],
            tuple(invalid),
            tuple(unreadable),
            tuple(reasons),
        )

    def finished(self, result: bool) -> None:  # hilo principal
        if result and self.diagnosis is not None:
            self._on_done(self.diagnosis)
        else:
            self._on_done(self.error or CancelledError(tr("Diagnosis cancelled")))


class RepairTask(QgsTask):  # type: ignore[misc]
    """Copia reparada de la capa: `makeValid` en las inválidas; el resto, tal cual."""

    def __init__(
        self,
        layer: QgsVectorLayer,
        invalid_fids: tuple[int, ...],
        on_done: Done,
        project: QgsProject | None = None,
    ) -> None:
        super().__init__(
            tr("GeoDuck: repair geometries of «{0}»").format(layer.name()), QgsTask.Flag.CanCancel
        )
        self._source = QgsVectorLayerFeatureSource(layer)
        self._name = layer.name()
        self._fields = layer.fields()
        self._crs = layer.crs()
        self._invalid = set(invalid_fids)
        self._total = max(layer.featureCount(), 1)
        self._on_done = on_done
        self._project = project or QgsProject.instance()
        self._features: list[QgsFeature] = []
        self._stats = {"repaired": 0, "type": 0, "dimension": 0, "parts": 0}
        self._failed: list[int] = []
        self.error: BaseException | None = None

    def run(self) -> bool:
        try:
            self._repair()
        except BaseException as exc:
            self.error = exc
            self._features = []
            return False
        return not self.isCanceled()

    def _repair(self) -> None:
        for done, f in enumerate(self._source.getFeatures(), start=1):
            if self.isCanceled():
                raise CancelledError(tr("Repair cancelled"))
            fid = int(f.id())
            copy = QgsFeature(self._fields)
            copy.setAttributes(f.attributes())
            g = f.geometry()
            if fid in self._invalid and g is not None and not g.isNull():
                fixed = g.makeValid()
                if fixed is None or fixed.isNull() or fixed.isEmpty() or not fixed.isGeosValid():
                    self._failed.append(fid)  # sin geometría en la copia, y se nombra
                    copy.clearGeometry()
                else:
                    self._stats["repaired"] += 1
                    before, after = g.wkbType(), fixed.wkbType()
                    if QgsWkbTypes.flatType(before) != QgsWkbTypes.flatType(after):
                        self._stats["type"] += 1
                    if (QgsWkbTypes.hasZ(before), QgsWkbTypes.hasM(before)) != (
                        QgsWkbTypes.hasZ(after),
                        QgsWkbTypes.hasM(after),
                    ):
                        self._stats["dimension"] += 1
                    if _parts(g) != _parts(fixed):
                        self._stats["parts"] += 1
                    copy.setGeometry(fixed)
            elif g is not None and not g.isNull():
                copy.setGeometry(g)
            self._features.append(copy)
            if done % 1000 == 0:
                self.setProgress(min(99.0, 100.0 * done / self._total))

    def finished(self, result: bool) -> None:  # hilo principal: crea y publica las capas
        if not result:
            self._on_done(self.error or CancelledError(tr("Repair cancelled")))
            return
        try:
            layers = FamilyLayers(f"{self._name} (reparada)", self._fields, self._crs, split=True)
            layers.add(self._features)
            created, notes = layers.finish()
            self._project.addMapLayers(created)  # todas o ninguna
        except BaseException as exc:
            self._on_done(exc)
            return
        self._on_done(
            RepairReport(
                self._name,
                self._stats["repaired"],
                self._stats["type"],
                self._stats["dimension"],
                self._stats["parts"],
                tuple(self._failed),
                tuple(layer.name() for layer in created),
                tuple(notes),
            )
        )
