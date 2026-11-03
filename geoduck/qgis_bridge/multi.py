# SPDX-License-Identifier: GPL-2.0-or-later
"""Varias geometrías: una capa por columna marcada, publicadas juntas (spatial-spec §7, GD-SPA-002).

Cada columna se carga con la modalidad elegida (Memoria, Instantánea o Conectada) como si fuera una carga
propia, pero sus capas quedan **privadas** en un proyecto de preparación. Cuando todas terminan, se
registran juntas en el proyecto real (`addMapLayers`). Un error o una cancelación en cualquiera descarta
todas: no se publica ninguna (qgis-bridge-spec §8).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsMapLayer, QgsProject
from qgis.PyQt.QtCore import QTimer

from geoduck.domain.i18n import tr
from geoduck.domain.load import LoadReport, LoadRequest
from geoduck.qgis_bridge.vsimem import VsimemRegistry

Done = Callable[[LoadReport | BaseException], None]
#: Crea la carga de una columna: (petición, proyecto de preparación, on_progress, on_done) → tarea.
Factory = Callable[[LoadRequest, Any, Callable[[int], None], Done], Any]


class StagingProject:
    """Sustituto de `QgsProject` para las cargas parciales: guarda las capas sin publicarlas."""

    def __init__(self) -> None:
        self.layers: list[QgsMapLayer] = []

    def addMapLayer(self, layer: QgsMapLayer) -> QgsMapLayer:  # noqa: N802 - API de QgsProject
        self.layers.append(layer)
        return layer

    def addMapLayers(self, layers: list[QgsMapLayer]) -> list[QgsMapLayer]:  # noqa: N802 - API de QgsProject
        self.layers.extend(layers)
        return layers


class MultiLoad:
    """Carga de varias columnas geométricas. Se crea y se usa en el hilo principal."""

    def __init__(
        self,
        requests: list[LoadRequest],
        factory: Factory,
        *,
        on_progress: Callable[[int], None],
        on_done: Done,
        project: QgsProject | None = None,
        registry: VsimemRegistry | None = None,
    ) -> None:
        self._requests = requests
        self._factory = factory
        self._on_progress = on_progress
        self._on_done = on_done
        self._project = project or QgsProject.instance()
        self._registry = registry
        self._staging = StagingProject()
        self._reports: list[LoadReport] = []
        self._current: Any = None
        self._finished = False

    def start(self) -> None:
        self._next()

    def cancel(self) -> None:
        if self._finished:
            return
        if self._current is not None:
            self._current.cancel()  # su on_done trae la cancelación y descarta todo
        else:
            self._fail(_cancelled())

    def _next(self) -> None:
        if self._finished:
            return
        request = self._requests[len(self._reports)]
        try:
            self._current = self._factory(request, self._staging, self._on_progress, self._sub_done)
            self._current.start()
        except BaseException as exc:
            self._fail(exc)

    def _sub_done(self, result: LoadReport | BaseException) -> None:
        self._current = None
        if self._finished:
            return
        if isinstance(result, BaseException):
            self._fail(result)
            return
        self._reports.append(result)
        if len(self._reports) < len(self._requests):
            QTimer.singleShot(0, self._next)  # fuera de la pila de la carga que acaba de terminar
            return
        self._publish()

    def _publish(self) -> None:
        self._finished = True
        layers = list(self._staging.layers)
        try:
            self._project.addMapLayers(layers)  # todas o ninguna
        except BaseException as exc:
            self._discard()
            self._on_done(exc)
            return
        first = self._reports[0]
        warnings: list[str] = []
        for report in self._reports:
            for w in report.warnings:
                text = w if len(self._reports) == 1 else f"{report.layer_name}: {w}"
                if text not in warnings:
                    warnings.append(text)
        self._on_done(
            LoadReport(
                first.layer_id,
                first.layer_name,
                first.mode,
                first.rows,
                tuple(warnings),
                origin=first.origin,
                access=first.access,
                layers=tuple((layer.id(), layer.name()) for layer in layers),
                rows_each=True,
            )
        )

    def _fail(self, exc: BaseException) -> None:
        if self._finished:
            return
        self._finished = True
        self._discard()
        self._on_done(exc)

    def _discard(self) -> None:
        """Capas preparadas que no se publican: se sueltan; los GeoPackage `/vsimem`, se liberan."""
        for layer in self._staging.layers:
            path = layer.source().split("|")[0]
            if self._registry is not None and path in self._registry.tracked:
                self._registry.release(path)
        self._staging.layers.clear()


def _cancelled() -> BaseException:
    from geoduck.qgis_bridge.memory import LoadCancelledError  # noqa: PLC0415 - evita ciclo

    return LoadCancelledError(tr("Loading cancelled"))
