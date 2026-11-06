# SPDX-License-Identifier: GPL-2.0-or-later
"""Velocidad publicada de «Enviar a DuckDB» (G8 · E5; qgis-import-spec §3, gate de docs/g8/plan.md).

Mide el envío real de GeoDuck (`LayerSender`/`LayerImport`: `QgsTask` + lotes Arrow + transacción) de un
GeoPackage de puntos con tres campos, en una sesión en memoria. Camino general (§5.3) y, para comparar,
la misma tabla enviada como capa Conectada (§5.1).

    QT_QPA_PLATFORM=offscreen python bench_send.py <carpeta> [entidades ...]

Escribe una línea por medida: `camino entidades segundos entidades/s`.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import duckdb  # noqa: E402
from osgeo import ogr, osr  # noqa: E402
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication  # noqa: E402

app = QgsApplication([], False)
app.initQgis()

from geoduck.app.coordinator import SessionCoordinator  # noqa: E402
from geoduck.domain.importing import ImportMode, SendItem, SendRequest  # noqa: E402
from geoduck.domain.load import LoadMode, LoadRequest  # noqa: E402
from geoduck.domain.session import SessionState  # noqa: E402
from geoduck.engine.worker import SessionWorker  # noqa: E402
from geoduck.qgis_bridge.importer import LayerSender  # noqa: E402
from geoduck.qgis_bridge.loader import BridgeLoader  # noqa: E402
from geoduck.ui.dispatcher import QtDispatcher  # noqa: E402


def wait(predicate, timeout=3600.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise TimeoutError


def make_gpkg(path: Path, n: int) -> None:
    if path.exists():
        return
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32719)
    lyr = ds.CreateLayer("puntos", srs, ogr.wkbPoint)
    for name, kind in (("id", ogr.OFTInteger), ("nombre", ogr.OFTString), ("valor", ogr.OFTReal)):
        lyr.CreateField(ogr.FieldDefn(name, kind))
    lyr.StartTransaction()
    defn = lyr.GetLayerDefn()
    for i in range(n):
        f = ogr.Feature(defn)
        f.SetField(0, i)
        f.SetField(1, f"p{i}")
        f.SetField(2, i * 0.5)
        g = ogr.Geometry(ogr.wkbPoint)
        g.AddPoint_2D(300000 + i % 1000, 8000000 + i // 1000)
        f.SetGeometry(g)
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    ds = None


def main() -> None:
    folder = Path(sys.argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    sizes = [int(v) for v in sys.argv[2:]] or [100_000, 1_000_000]
    events: list = []
    loader = BridgeLoader()
    coordinator = SessionCoordinator(SessionWorker, QtDispatcher(), loader, LayerSender())
    coordinator.subscribe(events.append)
    coordinator.start_memory_session()
    wait(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    from qgis.core import Qgis  # noqa: PLC0415

    print(f"# QGIS {Qgis.version()} · DuckDB {duckdb.__version__}", flush=True)
    for n in sizes:
        path = folder / f"puntos_{n}.gpkg"
        make_gpkg(path, n)
        layer = QgsVectorLayer(f"{path}|layername=puntos", f"puntos_{n}", "ogr")
        QgsProject.instance().addMapLayer(layer)
        for path_name, source in (("general", layer), ("conectada", None)):
            if path_name == "conectada":
                before = len(events)
                coordinator.load(LoadRequest(sql=f"SELECT * FROM g_{n}", mode=LoadMode.CONNECTED, layer_name="c"))
                wait(lambda b=before: any(type(e).__name__ in ("LoadFinished", "LoadFailed") for e in events[b:]))
                wait(lambda: coordinator.state is SessionState.READY)
                source = next(lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() == "c")
            table = f"g_{n}" if path_name == "general" else f"c_{n}"
            request = SendRequest((SendItem(source.id(), table, ImportMode.CREATE),), "memory", "main", False)
            before = len(events)
            started = time.perf_counter()
            coordinator.send_layers(request)
            wait(lambda b=before: any(type(e).__name__ in ("SendFinished", "SendFailed") for e in events[b:]))
            seconds = time.perf_counter() - started
            done = next(e for e in events[before:] if type(e).__name__ in ("SendFinished", "SendFailed"))
            assert type(done).__name__ == "SendFinished", done
            wait(lambda: coordinator.state is SessionState.READY)
            print(f"{path_name} {n} {seconds:.2f} {n / seconds:,.0f}", flush=True)
    coordinator.shutdown()
    loader.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
