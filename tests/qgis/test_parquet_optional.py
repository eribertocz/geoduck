# SPDX-License-Identifier: GPL-2.0-or-later
"""F-130: GeoDuck abre aunque `pyarrow.parquet` no cargue.

En QGIS de Windows (OSGeo4W 3.44) la DLL de `pyarrow._parquet` falló al importarse y GeoDuck no llegaba a
iniciar: `initGui` importaba `pyarrow.parquet` al cargar el envío a DuckDB. Ahora se importa solo al mirar
si una capa es GeoParquet, y sin él la capa va por el camino general.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from geoduck.qgis_bridge import importer

pytestmark = pytest.mark.qgis


def test_geoduck_starts_without_pyarrow_parquet():
    """En otro proceso, sin poder importar `pyarrow.parquet`: el complemento se inicia y se descarga."""
    script = """
import os, sys
sys.modules["pyarrow.parquet"] = None  # importarlo da ImportError, como la DLL rota
from qgis.core import QgsApplication
app = QgsApplication([], False); app.initQgis()
import geoduck
from tests.qgis.conftest import FakeIface
plugin = geoduck.classFactory(FakeIface()); plugin.initGui()
assert plugin.content is not None
plugin.unload()
print("OK")
os._exit(0)
"""
    root = str(Path(__file__).resolve().parents[2])
    paths = os.pathsep.join([root, os.environ.get("PYTHONPATH", ""), *sys.path])
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": paths},
    )
    assert done.stdout.strip().endswith("OK"), done.stderr[-2000:]


def test_without_pyarrow_parquet_a_parquet_is_not_taken_as_geoparquet(tmp_path, monkeypatch):
    path = tmp_path / "capa.parquet"
    path.write_bytes(b"PAR1")
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
    assert importer._parquet_metadata(str(path)) is None
