# Spike G8-A — QGIS → DuckDB (2026-11-05)

**Entorno:** Linux, datos sintéticos, sin la extensión `spatial` (`autoload_known_extensions = false`).
QGIS 3.34.6, 3.44.14 y 4.2.3 (conda-forge); DuckDB 1.5.0 y 2.0.0; PyArrow 25.0.1.
**Scripts:** `g8a_duckdb.py`, `g8a_qgis.py`. **Salidas:** `duckdb-*.txt`, `qgis-*.txt`.

## Hallazgos

| ID | Hecho | Versiones | Consecuencia (qgis-import-spec) |
|---|---|---|---|
| F-114 | Camino general (GeoPackage leído en otro hilo con `QgsVectorLayerFeatureSource` → lotes Arrow de 50 000 → `INSERT`): **1 millón de puntos en 4,9–7,0 s** (140–205 mil ent/s); 100 mil polígonos de 20 vértices en 0,7–1,0 s. Leer y armar el lote es ~90 % del tiempo; insertar en DuckDB, 0,4–0,6 s por millón | QGIS 3.34/3.44/4.2 × DuckDB 1.5.0/2.0.0 | El camino general sirve para el caso del propietario (≈1 M de suministros). Aviso de «capa grande» con una estimación prudente de 100 mil ent/s (§3) |
| F-115 | Sin `spatial`, **declarar** `GEOMETRY('EPSG:4326')` en `CREATE TABLE` falla («unrecognized coordinate system»); `CREATE TABLE … AS SELECT ST_SetCRS(…, 'EPSG:4326')` funciona y la columna queda `GEOMETRY('EPSG:4326')`; después `INSERT` con el mismo `ST_SetCRS` funciona | 1.5.0, 2.0.0 | La tabla se crea con `CREATE TABLE AS` desde el primer lote; nunca con tipos declarados (§7) |
| F-116 | `ST_SetCRS` sin `spatial` acepta `EPSG:`, `ESRI:`, `OGC:CRS84`, WKT2 y PROJJSON. En **DuckDB 1.5.0, un SRC en WKT2 se pierde** al leer la tabla por Arrow (metadatos vacíos); PROJJSON se conserva en 1.5.0 y 2.0.0 y QGIS lo reconoce como el mismo SRC | 1.5.0, 2.0.0; QGIS 3.34/3.44/4.2 | SRC con código de autoridad → `authid`; SRC personalizado → **PROJJSON** (QGIS 4.x: `toJsonString()`; 3.x: GDAL `osr` desde su WKT2) (§7) |
| F-117 | `QgsVectorLayerFeatureSource` se lee completa desde otro hilo con los proveedores `ogr` (GeoPackage), `memory` y `delimitedtext` (CSV). `postgres` no se pudo probar aquí | QGIS 3.34/3.44/4.2 | Lectura en `QgsTask`; PostGIS, en la guía manual de Windows (E5) |
| F-118 | Un GeoParquet con SRC (escrito con `GEOPARQUET_VERSION 'V2'`) se lee con `read_parquet` como `GEOMETRY` **sin SRC** si `spatial` no está cargada | 1.5.0, 2.0.0 | En el camino Parquet, el SRC se fija con `ST_SetCRS` usando el SRC de la capa de QGIS (§5.2) |
| F-119 | Selección de una capa Conectada: `IN (lista)` tarda 11–30 ms con 1 203 identificadores y 0,4–1,2 s con 100 000; un `JOIN` con una tabla Arrow de identificadores, 7–17 ms en ambos casos | 1.5.0, 2.0.0 | La selección se pasa siempre como tabla Arrow y `JOIN` (§5.1) |
| F-120 | Un archivo DuckDB con formato `v1.0.0+` (el que crea DuckDB 1.5.x por defecto; se lee en `duckdb_databases().tags['storage_version']`) **no guarda `GEOMETRY` con SRC**: «not supported in storage versions prior v1.5.0». Con `STORAGE_VERSION 'v1.5.0'` o creado con DuckDB 2.0 (`v2.0.0+`), sí | 1.5.0, 1.5.6, 2.0.0 (hallado en E1) | El envío lo comprueba antes de escribir; el diálogo ofrece «sin SRC» u otra base (§7) |
| F-121 | En QGIS de conda, GDAL comparte la biblioteca Arrow con pyarrow: **al abrir un GeoParquet en QGIS**, registra `geoarrow.wkb` y, desde entonces, pyarrow entrega la geometría de DuckDB como tipo de extensión: las cargas DuckDB → QGIS fallaban (`binary_slice`) o perdían el SRC (los metadatos dejan de verse en el campo) | 1.5.0, 2.0.0 · QGIS 3.44, 4.2 (hallado en E2) | `read_arrow` entrega cada lote sin tipos de extensión: el almacenamiento `binary` y los metadatos leídos por la interfaz C de Arrow (`engine/arrow_plain.py`); el registro ajeno no se toca (ADR-0011) |

## Reproducir

```bash
python g8a_duckdb.py /tmp/g8a                         # con cada versión de DuckDB
QT_QPA_PLATFORM=offscreen python g8a_qgis.py /tmp/g8a  # con el Python de QGIS
```
