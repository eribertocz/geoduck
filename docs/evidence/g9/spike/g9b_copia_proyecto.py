# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G9-B (E0b): qué pasa al guardar y reabrir un proyecto con una «Copia» (workspace-pro-spec §7).

Carga la misma tabla como Copia en memoria y como Copia rápida (GeoPackage en `/vsimem`), guarda el proyecto,
lo cierra y lo vuelve a abrir en el mismo QGIS, y escribe qué queda de cada capa.

    QT_QPA_PLATFORM=offscreen python g9b_copia_proyecto.py <carpeta>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from qgis.core import QgsApplication, QgsProject

app = QgsApplication([], False)
app.initQgis()

from geoduck.app.events import LoadFailed, LoadFinished  # noqa: E402
from geoduck.domain.load import LoadMode, LoadRequest  # noqa: E402
from tests.qgis.conftest import wait_for  # noqa: E402
from tests.qgis.test_load_connected import Session  # noqa: E402


def load(session: Session, mode: LoadMode, name: str):
    before = len(session.events)
    session.coordinator.load(LoadRequest(sql="SELECT * FROM t", mode=mode, layer_name=name))
    assert wait_for(
        lambda: any(isinstance(e, (LoadFinished, LoadFailed)) for e in session.events[before:]), 60
    )
    event = next(e for e in session.events[before:] if isinstance(e, (LoadFinished, LoadFailed)))
    assert isinstance(event, LoadFinished), event
    return QgsProject.instance().mapLayer(event.report.layer_id)


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    session = Session()
    session.sql(
        "CREATE TABLE t AS SELECT range AS id, ST_SetCRS(('POINT(' || range || ' 1)')::GEOMETRY, 'EPSG:32719') AS geom FROM range(100)"
    )
    memory = load(session, LoadMode.MEMORY, "copia_memoria")
    snapshot = load(session, LoadMode.SNAPSHOT, "copia_rapida")
    lines = [f"QGIS {QgsApplication.instance().applicationName()} · antes de guardar:"]
    for layer in (memory, snapshot):
        lines.append(
            f"  {layer.name()}: proveedor {layer.providerType()}, válida {layer.isValid()}, {layer.featureCount()} entidades, origen {layer.source()[:60]}"
        )
    project = QgsProject.instance()
    path = out / "proyecto.qgz"
    ok = project.write(str(path))
    lines.append(f"guardado: {ok}")
    project.clear()
    ok = project.read(str(path))
    lines.append(f"reabierto (misma sesión de QGIS, el /vsimem sigue en RAM): {ok}")
    for layer in project.mapLayers().values():
        lines.append(
            f"  {layer.name()}: proveedor {layer.providerType()}, válida {layer.isValid()}, {layer.featureCount() if layer.isValid() else '-'} entidades"
        )
    # Simula cerrar QGIS: el /vsimem se libera al quitar la capa (ADR-0012); al reabrir ya no existe
    project.clear()
    from osgeo import gdal  # noqa: PLC0415

    for f in gdal.ReadDirRecursive("/vsimem/") or []:
        gdal.Unlink("/vsimem/" + f)
    ok = project.read(str(path))
    lines.append(f"reabierto tras cerrar QGIS (sin /vsimem): {ok}")
    for layer in project.mapLayers().values():
        lines.append(
            f"  {layer.name()}: proveedor {layer.providerType()}, válida {layer.isValid()}, {layer.featureCount() if layer.isValid() else '-'} entidades"
        )
    text = "\n".join(lines) + "\n"
    (out / "copia-proyecto.txt").write_text(text, encoding="utf-8")
    print(text)
    os._exit(0)


if __name__ == "__main__":
    main()
