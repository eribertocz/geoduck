# SPDX-License-Identifier: GPL-2.0-or-later
"""Evidencia C4: CRS ausente, desconocido y conocido entre DuckDB (GeoArrow) y QGIS.

Para cada caso: metadatos GeoArrow que exporta DuckDB, resultado de
`QgsCoordinateReferenceSystem.createFromUserInput` y coordenadas tras cargar el WKB en una capa memory.
Uso: QT_QPA_PLATFORM=offscreen python qgis_crs_unknown.py
"""
import json

import duckdb
from qgis.core import (
    Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsVectorLayer,
)

app = QgsApplication([], False)
app.initQgis()
con = duckdb.connect()
cases = {
    "sin_crs": "SELECT 'POINT(-68.15 -16.5)'::GEOMETRY AS g",
    "OGC:CRS84": "SELECT ST_SetCRS('POINT(-68.15 -16.5)'::GEOMETRY, 'OGC:CRS84') AS g",
    "FOO:123": "SELECT ST_SetCRS('POINT(-68.15 -16.5)'::GEOMETRY, 'FOO:123') AS g",
}
out = {"qgis": Qgis.version(), "duckdb": duckdb.__version__}
for name, sql in cases.items():
    reader = con.sql(sql).to_arrow_reader()
    field = reader.schema.field("g")
    meta = json.loads((field.metadata or {}).get(b"ARROW:extension:metadata", b"{}"))
    wkb = reader.read_all().column(0)[0].as_py()
    crs_in = meta.get("crs")
    text = json.dumps(crs_in) if isinstance(crs_in, dict) else crs_in
    crs = QgsCoordinateReferenceSystem()
    if text:
        crs.createFromUserInput(text)
    layer = QgsVectorLayer("Point", name, "memory")
    layer.setCrs(crs)
    feat = QgsFeature()
    geom = QgsGeometry()
    geom.fromWkb(wkb)
    feat.setGeometry(geom)
    layer.dataProvider().addFeatures([feat])
    p = next(layer.getFeatures()).geometry().asPoint()
    out[name] = {
        "geoarrow_crs_type": meta.get("crs_type"),
        "qgis_crs_valid": crs.isValid(),
        "qgis_authid": crs.authid(),
        "layer_crs_valid": layer.crs().isValid(),
        "x": round(p.x(), 6),
        "y": round(p.y(), 6),
    }
print(json.dumps(out, indent=1))
app.exitQgis()
