# SPDX-License-Identifier: GPL-2.0-or-later
"""La geometría llega como `binary` con su SRC aunque otro componente registre `geoarrow.wkb` (F-121).

GDAL lo registra al abrir un GeoParquet en QGIS de conda (comparte la biblioteca Arrow con pyarrow); aquí
se simula registrando un tipo de Python con el mismo nombre. Sin `spatial`.
"""

from __future__ import annotations

import json

import duckdb
import pyarrow as pa
import pytest

from geoduck.engine.arrow_plain import plain_batch
from geoduck.engine.worker import SessionWorker

pytestmark = pytest.mark.engine

TIMEOUT = 60
SQL = "SELECT 1 AS id, ST_SetCRS('POINT(1 2)'::GEOMETRY, 'EPSG:4326') AS geom"


class _OtherWkb(pa.ExtensionType):
    """Un `geoarrow.wkb` ajeno que, como el que registra GDAL, guarda sus metadatos (el SRC) en el tipo."""

    def __init__(self, metadata: bytes = b"") -> None:
        self.metadata = metadata
        super().__init__(pa.binary(), "geoarrow.wkb")

    def __arrow_ext_serialize__(self) -> bytes:
        return self.metadata

    @classmethod
    def __arrow_ext_deserialize__(cls, storage_type, serialized):
        return cls(serialized)


@pytest.fixture
def worker():
    w = SessionWorker()
    w.start().result(TIMEOUT)
    yield w
    w.close().result(TIMEOUT)


@pytest.fixture
def other_wkb():
    pa.register_extension_type(_OtherWkb())
    yield
    pa.unregister_extension_type("geoarrow.wkb")


def check(batch):
    field = batch.schema.field("geom")
    assert field.type == pa.binary()
    assert field.metadata[b"ARROW:extension:name"] == b"geoarrow.wkb"
    crs = json.loads(field.metadata[b"ARROW:extension:metadata"])["crs"]
    assert "4326" in json.dumps(crs)
    assert batch.column("geom").to_pylist()[0][:1] in (b"\x01", b"\x00")  # WKB


def test_without_a_foreign_type_the_batch_is_unchanged(worker):
    (batch,) = worker.read_table(SQL).future.result(TIMEOUT)
    check(batch)
    assert plain_batch(batch) is batch


def test_with_a_foreign_geoarrow_type_the_geometry_stays_binary_with_its_crs(worker, other_wkb):
    con = duckdb.connect()
    raw = con.sql(SQL).to_arrow_reader(batch_size=10).read_next_batch()  # la API que usa el worker
    con.close()
    assert isinstance(raw.schema.field("geom").type, _OtherWkb)  # sin GeoDuck, la geometría cambia de tipo
    (batch,) = worker.read_table(SQL).future.result(TIMEOUT)
    check(batch)
    assert plain_batch(batch) is batch  # ya sin tipos de extensión
    assert batch.column("id").to_pylist() == [1]
