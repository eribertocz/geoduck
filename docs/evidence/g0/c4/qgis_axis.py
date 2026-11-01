"""C4: ¿cómo interpreta QGIS (x, y) de un WKB en una capa EPSG:4326? Compara con DuckDB ST_Transform."""
import os, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer)
import duckdb
app = QgsApplication([], False); app.initQgis()
con = duckdb.connect()
wkb = con.execute("SELECT ST_AsWKB('POINT(-68.15 -16.5)'::GEOMETRY('OGC:CRS84')) AS w").fetchone()[0]
out = {"qgis": Qgis.version(), "duckdb": duckdb.__version__}
for authid in ("EPSG:4326", "OGC:CRS84"):
    src = QgsCoordinateReferenceSystem(authid)
    layer = QgsVectorLayer(f"Point?crs={authid}", "t", "memory")
    f = QgsFeature(); g = QgsGeometry(); g.fromWkb(bytes(wkb)); f.setGeometry(g)
    layer.dataProvider().addFeatures([f])
    p = next(layer.getFeatures()).geometry().asPoint()
    xf = QgsCoordinateTransform(src, QgsCoordinateReferenceSystem("EPSG:32719"), QgsProject.instance())
    t = xf.transform(QgsPointXY(p.x(), p.y()))
    out[authid] = {"hasAxisInverted": src.hasAxisInverted(), "x": p.x(), "y": p.y(),
                   "to_32719": [round(t.x(), 2), round(t.y(), 2)]}
print(json.dumps(out, indent=1))
