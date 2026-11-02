# SPDX-License-Identifier: GPL-2.0-or-later
"""Spike G4-A (QGIS): Z/M y colecciones por GeoArrow, capas memory, makeValid.

Uso: QT_QPA_PLATFORM=offscreen python g4a_qgis.py  (con el Python de QGIS y duckdb + pyarrow)
"""
import duckdb
from qgis.core import Qgis, QgsApplication, QgsFeature, QgsGeometry, QgsVectorLayer, QgsWkbTypes

app = QgsApplication([], False)
app.initQgis()
print("QGIS", Qgis.version(), "· DuckDB", duckdb.__version__)

WKT = [
    "POINT(1 2)", "POINT Z(1 2 3)", "POINT M(1 2 4)", "POINT ZM(1 2 3 4)", "MULTIPOINT((1 2),(3 4))",
    "LINESTRING Z(0 0 1,1 1 2)", "POLYGON M((0 0 1,1 0 1,1 1 1,0 0 1))",
    "MULTIPOLYGON ZM(((0 0 1 2,1 0 1 2,1 1 1 2,0 0 1 2)))", "GEOMETRYCOLLECTION(POINT(1 2),LINESTRING(0 0,1 1))",
    "POINT EMPTY", "POLYGON EMPTY",
]
con = duckdb.connect()
values = ",".join(f"('{w}')" for w in WKT)
tbl = con.sql(f"SELECT w::GEOMETRY AS g, w FROM (VALUES {values}) t(w)").arrow()
tbl = tbl.read_all() if hasattr(tbl, "read_all") else tbl
print("\n1. GeoArrow → QgsGeometry.fromWkb")
for wkb, wkt in zip(tbl.column("g").to_pylist(), tbl.column("w").to_pylist()):
    g = QgsGeometry()
    g.fromWkb(wkb)
    print(f"  {wkt:55} → {QgsWkbTypes.displayString(g.wkbType()):22} empty={g.isEmpty()} {g.asWkt()[:40]}")

print("\n2. Capas memory")
for uri in ["Unknown", "GeometryCollection", "Point", "PointZ"]:
    lyr = QgsVectorLayer(uri, "t", "memory")
    print(f"  memory '{uri}': valid={lyr.isValid()} type={QgsWkbTypes.displayString(lyr.wkbType())}")
for layer_uri, wkt in [("Point", "POINT Z(1 2 3)"), ("PointZ", "POINT(1 2)"), ("Unknown", "POLYGON((0 0,1 0,1 1,0 0))"),
                       ("Unknown", "POINT Z(1 2 3)"), ("Point", "LINESTRING(0 0,1 1)")]:
    lyr = QgsVectorLayer(layer_uri, "t", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt(wkt))
    ok, _ = lyr.dataProvider().addFeatures([f])
    got = next(lyr.getFeatures()).geometry().asWkt() if lyr.featureCount() else "-"
    print(f"  {layer_uri:8} ← {wkt:28} ok={ok} stored={got}")

print("\n3. Validez y makeValid")
for wkt in ["POLYGON((0 0,1 1,1 0,0 1,0 0))", "POLYGON((0 0,1 0,1 1,0 1,0 0))", "POLYGON((0 0,1 0,0 0))",
            "POLYGON Z((0 0 1,1 1 1,1 0 1,0 1 1,0 0 1))"]:
    g = QgsGeometry.fromWkt(wkt)
    err = g.validateGeometry(Qgis.GeometryValidationEngine.Geos) if hasattr(Qgis, "GeometryValidationEngine") else g.validateGeometry(QgsGeometry.ValidatorGeos)
    fixed = g.makeValid()
    print(f"  {wkt:42} geosValid={g.isGeosValid()} errors={[e.what() for e in err][:1]} → "
          f"{QgsWkbTypes.displayString(fixed.wkbType())} {fixed.asWkt()[:50]}")
app.exitQgis()
