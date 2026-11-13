# SPDX-License-Identifier: GPL-2.0-or-later
"""«Enviar a DuckDB»: lectura de capas de QGIS (G8 · E2; AT-IMP-003..008; qgis-import-spec §4–§7).

QGIS, worker DuckDB y `QgsTask` reales; sin `spatial`. Se comprueban los tres caminos (§5), los tipos (§6),
la geometría con su SRC (§7), la selección y el filtro, el todo o nada y la cancelación (§4).
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from osgeo import ogr, osr
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

from geoduck.domain.errors import GeoDuckError, OperationCancelledError
from geoduck.domain.importing import ImportMode, ImportReport
from geoduck.qgis_bridge.importer import (
    PATH_CONNECTED,
    PATH_GDAL,
    PATH_PARQUET,
    PATH_QGIS,
    LayerImport,
    crs_text,
    plan_layer,
)
from tests.qgis.conftest import wait_for
from tests.qgis.test_load_connected import TABLE, Session

pytestmark = pytest.mark.qgis

TIMEOUT = 120


@pytest.fixture
def session(qgis_app):
    s = Session()
    yield s
    s.close()
    QgsProject.instance().removeAllMapLayers()


def rows(session, text):
    """Filas con sus tipos de Python (la consulta del panel las devuelve como texto)."""
    run = session.engine.submit(lambda h, t: h.execute(text, max_rows=1000))
    return run.future.result(TIMEOUT).rows


def tables(session):
    return {r[0] for r in rows(session, "SELECT table_name FROM duckdb_tables()")}


def send(session, plans, *, cancel=False):
    """Envía y espera; devuelve el `ImportReport` o la excepción, y el progreso visto."""
    out: list[object] = []
    progress: list[int] = []
    job = LayerImport(session.engine, plans, on_progress=progress.append, on_done=out.append)
    job.start()
    if cancel:
        job.cancel()
    assert wait_for(lambda: bool(out), TIMEOUT)
    assert wait_for(lambda: QgsApplication.taskManager().countActiveTasks() == 0, TIMEOUT)
    progress.append(job.read)
    return out[0], progress


def points(name, n, *, crs="EPSG:4326", first=0):
    layer = QgsVectorLayer(f"Point?crs={crs}&field=id:integer&field=nombre:string", name, "memory")
    feats = []
    for i in range(first, first + n):
        f = QgsFeature(layer.fields())
        f.setAttributes([i, None if i % 10 == 0 else f"p{i}"])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(-68 + i / 1000, -16)))
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    return layer


# -- camino general: lectura de QGIS por lotes Arrow (§5.3) ------------------------------------------------


def make_gpkg(path):
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32719)
    lyr = ds.CreateLayer("lotes", srs, ogr.wkbMultiPolygon, ["GEOMETRY_NAME=shape"])
    boolean = ogr.FieldDefn("activo", ogr.OFTInteger)
    boolean.SetSubType(ogr.OFSTBoolean)
    for defn in (
        ogr.FieldDefn("codigo", ogr.OFTInteger64),
        ogr.FieldDefn("nombre", ogr.OFTString),
        ogr.FieldDefn("area", ogr.OFTReal),
        ogr.FieldDefn("alta", ogr.OFTDate),
        ogr.FieldDefn("visto", ogr.OFTDateTime),
        boolean,
        ogr.FieldDefn("foto", ogr.OFTBinary),
    ):
        lyr.CreateField(defn)
    for i in range(3):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("codigo", 10_000_000_000 + i)
        f.SetField("nombre", f"lote {i}")
        f.SetField("area", 1.5 * i)
        if i < 2:
            f.SetField("alta", 2025, 1, 2 + i, 0, 0, 0, 0)
            f.SetField("visto", 2025, 3, 4, 5, 6, 7, 0)
            f.SetField("activo", i)
            f.SetFieldBinaryFromHexString("foto", "CAFE")
            x = 500_000 + i * 10
            f.SetGeometry(ogr.CreateGeometryFromWkt(f"MULTIPOLYGON((({x} 8e6,{x + 5} 8e6,{x} 8e6,{x} 8e6)))"))
        lyr.CreateFeature(f)
    ds = None


def test_geopackage_types_geometry_name_and_crs(session, tmp_path):
    make_gpkg(tmp_path / "lotes.gpkg")
    layer = QgsVectorLayer(f"{tmp_path / 'lotes.gpkg'}|layername=lotes", "Lotes rurales", "ogr")
    assert layer.isValid()
    plan = plan_layer(layer, table="lotes_rurales")
    assert plan.path == PATH_QGIS
    assert plan.job.geometry.name == "shape"  # el nombre que trae la capa (§7)
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    assert report.tables[0].rows == 3
    types = dict(
        rows(
            session, "SELECT column_name, data_type FROM duckdb_columns() WHERE table_name = 'lotes_rurales'"
        )
    )
    assert types["fid"] == "BIGINT"  # el FID solo se copia porque el GeoPackage lo da como campo
    assert types["codigo"] == "BIGINT"
    assert types["nombre"] == "VARCHAR"
    assert types["area"] == "DOUBLE"
    assert types["alta"] == "DATE" and types["visto"] == "TIMESTAMP"
    assert types["activo"] == "BOOLEAN" and types["foto"] == "BLOB"
    assert types["shape"] == "GEOMETRY('EPSG:32719')"
    got = rows(
        session,
        "SELECT codigo, nombre, alta, visto, activo, foto, shape IS NULL FROM lotes_rurales ORDER BY codigo",
    )
    assert got[0] == (
        10_000_000_000,
        "lote 0",
        dt.date(2025, 1, 2),
        dt.datetime(2025, 3, 4, 5, 6, 7),
        False,
        b"\xca\xfe",
        False,
    )
    assert got[2][2:] == (None, None, None, None, True)  # NULL sigue NULL, también la geometría


def test_memory_layer_selection_and_filter(session):
    layer = points("Puntos", 100)
    layer.setSubsetString('"id" >= 50')
    layer.selectByIds([1, 2, 3])  # FID 1..3 = id 0..2: fuera del filtro
    visible = [f.id() for f in layer.getFeatures()][:4]
    layer.selectByIds(visible)
    plan = plan_layer(layer, table="todos")
    selected = plan_layer(layer, table="elegidos", only_selected=True)
    assert plan.job.geometry.name == "geom" and selected.features == 4
    report, progress = send(session, [plan, selected])
    assert isinstance(report, ImportReport), report
    assert [t.rows for t in report.tables] == [50, 4]
    assert rows(session, "SELECT min(id), count(*), count(nombre) FROM todos") == ((50, 50, 45),)
    assert rows(session, "SELECT list(id ORDER BY id) FROM elegidos") == (([50, 51, 52, 53],),)
    assert progress and progress[-1] == 54
    assert layer.subsetString() == '"id" >= 50' and len(layer.selectedFeatureIds()) == 4  # la capa no cambia


def test_fields_that_differ_only_in_case_are_renamed(session):
    layer = QgsVectorLayer("Point?crs=EPSG:4326&field=ID:integer&field=id:string", "dos", "memory")
    f = QgsFeature(layer.fields())
    f.setAttributes([7, "siete"])
    layer.dataProvider().addFeatures([f])
    plan = plan_layer(layer, table="dos")
    assert any("id_2" in w for w in plan.warnings)  # DuckDB no distingue mayúsculas (§6)
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    assert any("id_2" in w for w in report.warnings)
    assert rows(session, 'SELECT "ID", id_2 FROM dos') == ((7, "siete"),)


def test_csv_without_geometry(session, tmp_path):
    csv = tmp_path / "datos.csv"
    csv.write_text("id,nombre,valor\n1,uno,1.5\n2,dos,\n", encoding="utf-8")
    uri = f"file://{csv}?delimiter=,&geomType=none&detectTypes=yes"
    layer = QgsVectorLayer(uri, "datos", "delimitedtext")
    assert layer.isValid()
    plan = plan_layer(layer, table="datos", temporary=True)
    assert plan.job.geometry is None
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    assert rows(session, "SELECT id, nombre, valor FROM temp.main.datos ORDER BY id") == (
        (1, "uno", 1.5),
        (2, "dos", None),
    )


def test_empty_layer_creates_the_table(session):
    report, _ = send(session, [plan_layer(points("vacía", 0), table="vacia")])
    assert isinstance(report, ImportReport), report
    assert rows(session, "SELECT count(*) FROM vacia") == ((0,),)
    assert "geom" in {r[0] for r in rows(session, "DESCRIBE vacia")}


def test_custom_crs_goes_as_projjson_and_comes_back(session):
    proj = (
        "+proj=tmerc +lat_0=0 +lon_0=-63.5 +k=0.9996 +x_0=500000 +y_0=10000000 +ellps=WGS84 +units=m +no_defs"
    )
    crs = QgsCoordinateReferenceSystem.fromProj(proj)
    assert crs.isValid() and not crs.authid()
    layer = points("propio", 5)
    layer.setCrs(crs)
    text = crs_text(layer.crs())
    assert text and json.loads(text)["type"] == "ProjectedCRS", text  # PROJJSON, no WKT2 (F-116)
    report, _ = send(session, [plan_layer(layer, table="propio")])
    assert isinstance(report, ImportReport), report
    declared = rows(session, "SELECT data_type FROM duckdb_columns() WHERE column_name = 'geom'")[0][0]
    back = QgsCoordinateReferenceSystem()
    back.createFromUserInput(declared[len("GEOMETRY('") : -2].replace("''", "'"))

    def parts(c):
        return sorted(set(c.toProj().split()) - {"+type=crs"})

    assert back.isValid() and parts(back) == parts(crs)


def test_without_crs_is_explicit(session):
    plan = plan_layer(points("a", 3), table="sin_src", without_crs=True)
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    assert rows(
        session,
        "SELECT data_type FROM duckdb_columns() WHERE table_name = 'sin_src' AND column_name = 'geom'",
    ) == (("GEOMETRY",),)
    assert any("sin_src" in w for w in report.warnings)


# -- garantías (§4) --------------------------------------------------------------------------------------


def test_all_or_nothing(session):
    rows(session, "CREATE TABLE ocupada AS SELECT 1 AS id")
    plans = [plan_layer(points("a", 10), table="nueva"), plan_layer(points("b", 10), table="ocupada")]
    result, _ = send(session, plans)
    assert isinstance(result, GeoDuckError), result
    assert "nueva" not in tables(session)
    assert rows(session, "SELECT count(*) FROM ocupada") == ((1,),)


def test_append_and_replace(session):
    send(session, [plan_layer(points("a", 10), table="t")])
    result, _ = send(session, [plan_layer(points("a", 5, first=10), table="t", mode=ImportMode.APPEND)])
    assert isinstance(result, ImportReport), result
    assert rows(session, "SELECT count(*), max(id) FROM t") == ((15, 14),)
    result, _ = send(session, [plan_layer(points("a", 2), table="t", mode=ImportMode.REPLACE)])
    assert isinstance(result, ImportReport), result
    assert rows(session, "SELECT count(*) FROM t") == ((2,),)


def test_cancel_rolls_back(session):
    layer = points("grande", 150_000)
    result, _ = send(session, [plan_layer(layer, table="grande")], cancel=True)
    assert isinstance(result, OperationCancelledError), result
    assert "grande" not in tables(session)
    assert rows(session, "SELECT 1") == ((1,),)  # la sesión sigue lista


def test_open_user_transaction_is_left_intact(session):
    rows(session, "BEGIN")
    result, _ = send(session, [plan_layer(points("a", 3), table="t")])
    assert isinstance(result, GeoDuckError), result
    rows(session, "ROLLBACK")


# -- camino Conectada: SQL dentro de DuckDB (§5.1) -------------------------------------------------------


def test_connected_layer_is_copied_inside_duckdb(session):
    session.sql(TABLE)
    _, layer = session.load("SELECT * FROM puntos", name="Puntos conectados")
    layer.setSubsetString('"id" < 1000')
    plan = plan_layer(layer, table="copia")
    assert plan.path == PATH_CONNECTED and plan.job.columns == ()
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    assert report.tables[0].rows == 1000
    assert rows(session, "SELECT typeof(geom), count(*), count(valor) FROM copia GROUP BY 1") == (
        ("GEOMETRY('OGC:CRS84')", 1000, 989),
    )


def test_connected_layer_selection(session):
    session.sql(TABLE)
    _, layer = session.load("SELECT * FROM puntos", name="Puntos conectados")
    picked = [f.id() for f in layer.getFeatures()][10:13]
    layer.selectByIds(picked)
    report, _ = send(session, [plan_layer(layer, table="sel", only_selected=True)])
    assert isinstance(report, ImportReport), report
    expected = sorted(f["id"] for f in layer.getFeatures(picked))
    assert rows(session, "SELECT list(id ORDER BY id) FROM sel") == ((expected,),)


# -- camino GeoParquet: read_parquet (§5.2) --------------------------------------------------------------


def make_parquet(path):
    driver = ogr.GetDriverByName("Parquet")
    if driver is None:
        pytest.skip("GDAL sin el controlador Parquet (QGIS 3.34 de conda-forge)")
    ds = driver.CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    lyr = ds.CreateLayer("rios", srs, ogr.wkbPoint)
    lyr.CreateField(ogr.FieldDefn("nombre", ogr.OFTString))
    for i in range(4):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("nombre", f"río {i}")
        f.SetGeometry(ogr.CreateGeometryFromWkt(f"POINT({-68 + i} -16)"))
        lyr.CreateFeature(f)
    ds = None


def test_geoparquet_copy_and_view(session, tmp_path):
    make_parquet(tmp_path / "rios.parquet")
    layer = QgsVectorLayer(str(tmp_path / "rios.parquet"), "rios", "ogr")
    assert layer.isValid()
    copy = plan_layer(layer, table="rios")
    view = plan_layer(layer, table="rios_vista", as_view=True)
    assert copy.path == PATH_PARQUET and view.path == PATH_PARQUET
    report, _ = send(session, [copy, view])
    assert isinstance(report, ImportReport), report
    for name in ("rios", "rios_vista"):
        assert rows(session, f"SELECT typeof({copy.job.geometry.name}), count(*) FROM {name} GROUP BY 1") == (
            ("GEOMETRY('EPSG:4326')", 4),
        )
    assert rows(session, "SELECT count(*) FROM duckdb_views() WHERE view_name = 'rios_vista'") == ((1,),)
    layer.setSubsetString("\"nombre\" = 'río 1'")  # con filtro: lo lee DuckDB con su `WHERE` (#140)
    assert plan_layer(layer, table="uno").path == PATH_GDAL
    assert plan_layer(layer, table="uno", direct=False).path == PATH_QGIS  # tras fallar, QGIS
    with pytest.raises(GeoDuckError):
        plan_layer(layer, table="uno", as_view=True)


def test_a_filtered_geoparquet_is_read_directly_by_duckdb(session, tmp_path):
    """#140: un GeoParquet con filtro ya no pasa por QGIS: `read_parquet` con el filtro como `WHERE` y la
    comprobación de filas; sin `spatial`."""
    make_parquet(tmp_path / "rios.parquet")
    layer = QgsVectorLayer(str(tmp_path / "rios.parquet"), "rios", "ogr")
    layer.setSubsetString("\"nombre\" IN ('río 1', 'río 2')")
    plan = plan_layer(layer, table="dos")
    assert plan.path == PATH_GDAL and plan.job.expected_rows == 2
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    geometry = plan.job.geometry.name
    assert rows(session, f"SELECT typeof({geometry}), count(*) FROM dos GROUP BY 1") == (
        ("GEOMETRY('EPSG:4326')", 2),
    )


def test_a_geoparquet_is_read_directly_even_without_pyarrow_parquet(session, tmp_path, monkeypatch):
    """#140: en algunos QGIS de Windows `pyarrow.parquet` no carga (F-130); antes el Parquet pasaba por QGIS.
    Ahora la geometría y el SRC salen de la capa de QGIS y lo lee DuckDB."""
    from geoduck.qgis_bridge import importer

    make_parquet(tmp_path / "rios.parquet")
    monkeypatch.setattr(importer, "_parquet_metadata", lambda _path: None)
    layer = QgsVectorLayer(str(tmp_path / "rios.parquet"), "rios", "ogr")
    plan = plan_layer(layer, table="rios")
    assert plan.path == PATH_GDAL
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    geometry = plan.job.geometry.name
    assert rows(session, f"SELECT typeof({geometry}), count(*) FROM rios GROUP BY 1") == (
        ("GEOMETRY('EPSG:4326')", 4),
    )


def test_a_csv_without_geometry_is_read_directly_and_checked(session, tmp_path):
    """#140: un CSV sin geometría lo lee DuckDB (`read_csv`) y se comprueba que dé las filas de QGIS; un CSV
    con geometría (QGIS la arma de una columna de texto) sigue por QGIS."""
    plain = tmp_path / "lecturas.csv"
    plain.write_text("id,zona,kwh\n1,Norte,50.8\n2,Sur,71.2\n3,Sur,88.1\n", encoding="utf-8")
    layer = QgsVectorLayer(str(plain), "lecturas", "ogr")
    assert layer.isValid() and not layer.isSpatial()
    plan = plan_layer(layer, table="lecturas")
    assert plan.path == PATH_GDAL and plan.job.expected_rows == 3
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    assert rows(session, "SELECT count(*), sum(kwh) FROM lecturas") == ((3, 210.1),)
    spatial = tmp_path / "puntos.csv"
    spatial.write_text('id,WKT\n1,"POINT (1 2)"\n', encoding="utf-8")
    with_geometry = QgsVectorLayer(str(spatial), "puntos", "ogr")
    assert with_geometry.isValid() and with_geometry.isSpatial()
    assert plan_layer(with_geometry, table="puntos").path == PATH_QGIS


# -- «Reproyectar a…» (E4; qgis-import-spec §3; AT-IMP-003, spatial-spec §8: 0,01 m) -------------------


def test_reproject_transforms_with_qgis_and_labels_the_target_crs(session):
    from qgis.core import QgsCoordinateTransform, QgsPointXY

    layer = points("geo", 3)
    plan = plan_layer(layer, table="utm", reproject_to="EPSG:32719")
    assert plan.path == PATH_QGIS and plan.job.geometry.crs == "EPSG:32719"
    assert any("EPSG:32719" in w for w in plan.warnings)
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    got = rows(session, "SELECT typeof(geom), geom::VARCHAR FROM utm ORDER BY id")
    assert {g[0] for g in got} == {"GEOMETRY('EPSG:32719')"}
    transform = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsCoordinateReferenceSystem("EPSG:32719"),
        QgsProject.instance(),
    )
    for i, (_, wkt) in enumerate(got):
        expected = transform.transform(QgsPointXY(-68 + i / 1000, -16))
        x, y = (float(v) for v in wkt.removeprefix("POINT (").removesuffix(")").split())
        assert abs(x - expected.x()) < 0.01 and abs(y - expected.y()) < 0.01


def test_a_connected_layer_of_this_session_is_not_reprojected(session):
    """Leerla con QGIS pediría páginas al worker que escribe el envío: se rechaza antes de empezar."""
    session.sql(TABLE)
    _, layer = session.load("SELECT * FROM puntos", name="P")
    with pytest.raises(GeoDuckError, match="Conectada"):
        plan_layer(layer, table="copia_utm", reproject_to="EPSG:32719")


def test_reproject_needs_a_source_crs(session):
    layer = QgsVectorLayer("Point?field=id:integer", "sin src", "memory")
    layer.setCrs(QgsCoordinateReferenceSystem())  # la capa en memoria trae EPSG:4326 por defecto
    with pytest.raises(GeoDuckError):
        plan_layer(layer, table="x", reproject_to="EPSG:32719")


# -- aceptación (E5): Shapefile, listas y mapas, geometrías de todo tipo y vuelta a QGIS -----------------


def test_shapefile_has_no_geometry_name_so_it_is_geom(session, tmp_path):
    ds = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(str(tmp_path / "rios.shp"))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32719)
    lyr = ds.CreateLayer("rios", srs, ogr.wkbLineString)
    lyr.CreateField(ogr.FieldDefn("nombre", ogr.OFTString))
    for i in range(3):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("nombre", f"río {i}")
        f.SetGeometry(ogr.CreateGeometryFromWkt(f"LINESTRING({i} 0, {i} 10)"))
        lyr.CreateFeature(f)
    ds = None
    layer = QgsVectorLayer(str(tmp_path / "rios.shp"), "rios", "ogr")
    plan = plan_layer(layer, table="rios")
    assert plan.path == PATH_QGIS and plan.job.geometry.name == "geom"
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    assert rows(session, "SELECT typeof(geom), count(*) FROM rios GROUP BY 1") == (
        ("GEOMETRY('EPSG:32719')", 3),
    )


def test_lists_and_maps(session):
    uri = "None?field=tags:stringlist&field=enteros:integerlist&field=reales:doublelist&field=datos:map"
    layer = QgsVectorLayer(uri, "listas", "memory")
    f = QgsFeature(layer.fields())
    f.setAttributes([["a", "b"], [1, 2], [1.5], {"k": 1}])
    empty = QgsFeature(layer.fields())
    empty.setAttributes([None, None, None, None])
    layer.dataProvider().addFeatures([f, empty])
    plan = plan_layer(layer, table="listas")
    assert any("datos" in w for w in plan.warnings)  # el mapa va como JSON, con aviso (§6)
    report, _ = send(session, [plan])
    assert isinstance(report, ImportReport), report
    types = dict(
        rows(session, "SELECT column_name, data_type FROM duckdb_columns() WHERE table_name = 'listas'")
    )
    assert types == {"tags": "VARCHAR[]", "enteros": "BIGINT[]", "reales": "DOUBLE[]", "datos": "JSON"}
    got = rows(session, "SELECT tags, enteros, reales, datos::VARCHAR FROM listas ORDER BY tags NULLS LAST")
    assert got[0][:3] == (["a", "b"], [1, 2], [1.5]) and json.loads(got[0][3]) == {"k": 1}
    assert got[1] == (None, None, None, None)


def test_z_m_collections_null_and_invalid_go_and_come_back(session, tmp_path):
    """AT-IMP-007: el WKB llega tal cual (Z/M, colecciones, inválidas) y vuelve a QGIS igual, con su SRC."""
    path = tmp_path / "mezcla.gpkg"
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32719)
    lyr = ds.CreateLayer("mezcla", srs, ogr.wkbUnknown)
    lyr.CreateField(ogr.FieldDefn("n", ogr.OFTInteger))
    wkts = [
        "POINT Z (500000 8000000 3500)",
        "LINESTRING M (0 0 1, 10 10 2)",
        "POINT ZM (1 2 3 4)",
        "GEOMETRYCOLLECTION (POINT (1 1), LINESTRING (0 0, 1 1))",
        "POLYGON ((0 0, 10 10, 10 0, 0 10, 0 0))",  # inválida (pajarita): se copia tal cual
        None,
    ]
    for i, wkt in enumerate(wkts):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("n", i)
        if wkt:
            f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        lyr.CreateFeature(f)
    ds = None
    layer = QgsVectorLayer(f"{path}|layername=mezcla", "mezcla", "ogr")
    report, _ = send(session, [plan_layer(layer, table="mezcla")])
    assert isinstance(report, ImportReport), report
    # Lo que QGIS entrega de cada entidad (con tipo «desconocido», QGIS puede ajustar Z/M al tipo de la capa)
    original = {f["n"]: f.geometry() for f in layer.getFeatures()}
    assert rows(session, "SELECT DISTINCT typeof(geom) FROM mezcla") == (("GEOMETRY('EPSG:32719')",),)
    # El WKB guardado es el mismo que da QGIS, byte a byte (Z, M, ZM, colección, inválida y NULL)
    batches = session.engine.read_table("SELECT n, geom FROM mezcla ORDER BY n").future.result(TIMEOUT)
    stored = {}
    for b in batches:
        stored.update(zip(b.column("n").to_pylist(), b.column("geom").to_pylist(), strict=True))
    for n, g in original.items():
        assert stored[n] == (None if g.isNull() else bytes(g.asWkb())), n
    # Y vuelve a QGIS con su SRC y su Z. Una capa de QGIS tiene un solo tipo: se prueba con uno (POINT Z);
    # con tipos mixtos, la capa Conectada pierde el SRC (F-122, aparte de G8)
    session.sql("CREATE TABLE puntos_z AS SELECT * FROM mezcla WHERE n = 0")
    _, back = session.load("SELECT * FROM puntos_z", name="vuelta")
    assert back.crs().authid() == "EPSG:32719"
    for f in back.getFeatures():
        assert bytes(f.geometry().asWkb()) == bytes(original[f["n"]].asWkb()), f["n"]


def test_a_forced_count_mismatch_rolls_back(session):
    """AT-IMP-004 «conteo distinto forzado»: una consulta que no da las mismas filas dos veces."""
    from geoduck.domain.importing import ImportJob
    from geoduck.qgis_bridge.importer import LayerPlan

    source = "SELECT range AS id FROM range(100000) WHERE random() < 0.5"
    job = ImportJob("azar", "azar", ImportMode.CREATE, (), None, source_sql=source)
    result, _ = send(session, [LayerPlan(points("azar", 1), job, PATH_CONNECTED)])
    assert isinstance(result, GeoDuckError), result
    assert "azar" not in tables(session)
