# Spike G4-A — compatibilidades no demostradas (2026-11-02)

**Alcance (decisión del propietario, 2026-11-02):** solo lo que G0–G3 no había demostrado. El CRS
tipado, el transporte GeoArrow y el orden de ejes ya están demostrados (F-05, F-10, F-14, propuesta C4,
pruebas AX) y no se repiten.

**Entorno:** Linux. DuckDB 1.5.0, 1.5.6 y 2.0.0 **sin** `spatial`. QGIS 3.34.6 y 4.2.3 (conda).
**Scripts:** `g4a_duckdb.py`, `g4a_qgis.py`. **Salidas:** `duckdb-*.txt`, `qgis-3.34-4.2.txt`.

## Hallazgos

| ID | Hecho | Versiones | Consecuencia (SPEC) |
|---|---|---|---|
| F-91 | El núcleo de DuckDB (sin `spatial`) tiene `ST_AsWKB`, `ST_AsText`, `ST_GeomFromWKB`, `ST_Intersects_Extent`, `ST_CRS`, `ST_SetCRS`; **no** tiene `ST_GeometryType`, `ST_IsValid` ni `ST_HasZ` | DuckDB 1.5.0, 1.5.6, 2.0.0 | Ninguna función de G4 usa `spatial` (spatial-spec §10) |
| F-92 | `ST_AsWKB` siempre da WKB ISO little-endian (también desde un BLOB big-endian); el código de tipo `% 1000` da la familia (1/4 punto, 2/5 línea, 3/6 polígono, 7 colección) y el bloque 1000/2000/3000 las dimensiones Z/M/ZM | 1.5.0, 1.5.6, 2.0.0 | Filtro de familia en SQL sin `spatial` (§6) |
| F-93 | Filtro de familia sobre 1 M de filas: 98–177 ms; muestra de 1 000–10 000 filas: < 10 ms | 1.5.0, 1.5.6, 2.0.0 | Al abrir una Conectada, el tipo se lee de **todas** las cabeceras WKB (`DISTINCT` en DuckDB), no de una muestra: un tipo ausente de la muestra quedaría en una capa de otro tipo y QGIS no lo dibujaría (pérdida silenciosa). El coste medido (0,1–0,2 s por millón de filas) lo permite. Decisión del propietario en el PR #73 (§6); la propuesta inicial de este spike, una muestra acotada, queda descartada. Prueba: `test_families::test_connected_reads_the_type_of_every_row_not_a_sample` |
| F-94 | `TRY(ST_GeomFromWKB(blob))` y `TRY(texto::GEOMETRY)` convierten WKB/WKT y dan `NULL` si el valor es ilegible (truncado, basura, WKT inválido); `ST_Intersects_Extent` funciona sobre el resultado | 1.5.0, 1.5.6, 2.0.0 | Columnas `BLOB`/`VARCHAR` marcadas siguen el camino `GEOMETRY` en las tres modalidades; «ilegible» = valor no nulo → `NULL` (§5) |
| F-95 | `QgsGeometry.fromWkb` lee Z, M, ZM, Multi*, `GeometryCollection` y vacías tal como salen de GeoArrow | QGIS 3.34.6, 4.2.3 | Sin conversión intermedia |
| F-96 | El proveedor `memory` no admite el tipo `Unknown` (capa no válida); sí `GeometryCollection` | QGIS 3.34.6, 4.2.3 | En Memoria, varias familias = una capa por familia o error (§6) |
| F-97 | El proveedor `memory` **acepta en silencio** una geometría `PointZ` en una capa `Point` (y 2D en `PointZ`) sin cambiar el tipo de la capa; rechaza otra familia | QGIS 3.34.6, 4.2.3 | GeoDuck fija el tipo con todas las dimensiones presentes (§6) |
| F-98 | `isGeosValid`/`validateGeometry(GEOS)` y `makeValid()` dan el mismo resultado: pajarita → `MultiPolygon`; anillo degenerado → `LineString` (cambio de familia); Z conservada | QGIS 3.34.6, 4.2.3 | La reparación informa cambios de tipo y dimensión (§9) |
| F-99 | `ST_Transform(g, 'EPSG:4326', 'EPSG:32719', true)` (cuatro argumentos) devuelve `GEOMETRY` **sin** CRS; la forma de tres argumentos sobre `GEOMETRY('EPSG:4326')` devuelve `GEOMETRY('EPSG:32719')` | DuckDB 2.0.0 + spatial (E2) | AX-1c usa la forma tipada; la de cuatro argumentos queda sin CRS asignado (C4: no se inventa) |

## Reproducir

```bash
python g4a_duckdb.py                                   # con cada versión de DuckDB
QT_QPA_PLATFORM=offscreen python g4a_qgis.py           # con el Python de QGIS
```
