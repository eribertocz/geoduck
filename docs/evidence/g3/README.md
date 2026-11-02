# Evidencia G3 — spike G3-A: transferencia DuckDB → QGIS

Linux (2 CPU, 8 GB); QGIS 3.44.14 (Qt 5.15) y 4.2.3 (Qt 6.11) de conda-forge, ambos con GDAL 3.13.3,
PyArrow 25.0.1 y DuckDB 2.0.0; etapa de motor también con DuckDB 1.5.0 y 1.5.6. **No es certificación
Windows** (#10). Los tiempos son de una ejecución por escenario, en un proceso nuevo y con la máquina
sin otras mediciones; sirven para comparar órdenes de magnitud, no para fijar umbrales.

El estudio y la recomendación están en [`docs/g3/estudio-modalidades.md`](../../g3/estudio-modalidades.md).
Todas las tablas: [`tablas.md`](tablas.md) (generadas con `tools/bench/summarize.py`).

## Cómo reproducir

```bash
# QGIS (en un entorno con PyQGIS):
python tools/bench/transfer_bench.py matrix --out docs/evidence/g3/result_<entorno>.json
python tools/bench/transfer_compare.py matrix --out docs/evidence/g3/compare_<entorno>.json
python tools/bench/connected_probe.py types --out docs/evidence/g3/types_<entorno>.json
python tools/bench/connected_probe.py ondemand --libduckdb <libduckdb> --out docs/evidence/g3/ondemand_<entorno>.json
# Solo motor (sin QGIS), por versión de DuckDB:
python tools/bench/transfer_bench.py matrix --engine-only --out docs/evidence/g3/result_engine_duckdb<v>.json
python tools/bench/summarize.py docs/evidence/g3
```

`ondemand` con ADBC necesita la extensión `spatial` (aquí, de la rueda `duckdb-extension-spatial` 2.0.0
de PyPI, sin red hacia extensions.duckdb.org) y una biblioteca con `duckdb_adbc_init`; en la prueba se
usó el propio módulo `_duckdb` de cada entorno, enlazado como `libduckdb.so`.

| Archivo | Contenido |
|---|---|
| `result_engine_duckdb{1.5.0,1.5.6,2.0.0}.json` | Etapas de motor (lector Arrow) y listas de Python |
| `result_q42.json`, `result_q344.json` | Ruta propia a capa memory: estrategias de hilo, tramos, fechas, tamaño de lote |
| `compare_q42.json`, `compare_q344.json` | Seis rutas: tiempo, RAM, integridad, CRS, cancelación, DETACH/cierre, reapertura del proyecto, edición, uso |
| `types_q42.json`, `types_q344.json` | Fidelidad de tipos a través del driver Arrow de GDAL frente a qgis-bridge-spec §7 |
| `ondemand_q42.json`, `ondemand_q344.json` | Lectura bajo demanda (GeoParquet y ADBC) con 1 y 5 M de puntos |

## Hallazgos

| ID | Hecho | Consecuencia |
|---|---|---|
| F-42 | El coste está en construir en Python cada `QgsFeature`/`QgsGeometry`/`QDateTime`: 24 µs/fila en 3.44 y 56 µs/fila en 4.2 con 5 columnas + punto. DuckDB y Arrow cuestan < 1 µs/fila (2–7 M filas/s en las tres versiones de DuckDB) | El cuello de botella no es el motor sino la conversión por fila en Python |
| F-43 | `QDateTime(datetime)` cuesta 40 µs/valor en QGIS 4.2 (PyQt6) y 3,3 µs en 3.44; `QDateTime.fromMSecsSinceEpoch(int)` cuesta 1,4–2,6 µs. Con 1 M de filas tabulares en 4.2: 55 s → 11 s | Si hay conversión propia, las fechas se construyen desde enteros |
| F-44 | Pasar la conversión al hilo del motor no acelera (GIL) y empeora el bloqueo máximo (hasta 1,6 s en 4.2). Trocear cada lote en tramos de 1 024 filas en el hilo principal baja el bloqueo máximo a 53–200 ms sin cambiar el total | §5: el troceo funciona; el hilo del motor no debe crear objetos de QGIS |
| F-45 | DuckDB entrega `range * 0.5` como `DECIMAL`; PyArrow lo da como `decimal.Decimal`: QGIS 3.44 lo rechaza (`addFeatures` falla) y 4.2 lo guarda como texto | Una conversión propia necesita reglas explícitas por tipo (§7); confiar en QVariant falla |
| F-46 | GDAL convierte el lote Arrow entero en C++: 1 M de filas en 0,24–0,41 s (archivo Arrow, `/vsimem` o GeoParquet) y 1,8–2,2 s (GeoPackage), frente a 8,7–10,1 s de la mejor ruta propia (`compare_*`). RAM retenida para 1 M: 27–175 MB frente a 450–550 MB | La ruta GDAL es 5–30 × más rápida y usa 3–15 × menos RAM |
| F-47 | Fidelidad del driver Arrow de GDAL (igual en 3.44 y 4.2): correctos BOOLEAN, enteros ≤ 64 bits, DOUBLE (NaN/Inf), VARCHAR/UUID (UTF-8), DATE, TIMESTAMP, TIMESTAMPTZ (UTC), BLOB, LIST, MAP (JSON), NULL. **Con pérdida silenciosa**: `UBIGINT`, `HUGEINT` y `DECIMAL` de cualquier precisión → Real; ENUM → índice entero; TIME → microsegundos. **Descartados**: INTERVAL, STRUCT y la segunda geometría | Incumple §7 («nunca convertir silenciosamente»): GeoDuck debe normalizar tipos en el SQL de DuckDB antes de entregar el lote |
| F-48 | El CRS viaja solo en los metadatos GeoArrow: GDAL lo lee sin código de GeoDuck. Arrow/Parquet lo presentan como `EPSG:4326`; GeoPackage y la capa memory conservan `OGC:CRS84`. Las coordenadas son idénticas (huella WKB) | C4 se cumple sin traducir CRS a mano; con Arrow/Parquet el identificador mostrado cambia |
| F-49 | En QGIS 4.2, leer entidades de una capa OGR cuesta ≈ 40 µs/entidad (C++ con DateTime y también desde Python); en 3.44, ≈ 2 µs. `materialize()` de 1 M de filas con DateTime: 45 s en 4.2, 3,4 s en 3.44. Sin el campo DateTime, 2,2 µs/entidad. No depende de la zona horaria | Copiar una capa GDAL a memory no sirve como camino general en 4.2. **Por confirmar en la compilación oficial de Windows** (puede ser propio de este Qt 6.11) |
| F-50 | QGIS 3.44 no tiene API Arrow; la de 4.2 (`QgsArrowIterator`, `__arrow_c_stream__`) solo **exporta** capas a Arrow. No existe proveedor DuckDB en QGIS ni forma de abrir un dataset MEM de GDAL por nombre | No hay ruta sin archivo intermedio; la más cercana es un archivo virtual `/vsimem` (RAM de GDAL) |
| F-51 | `/vsimem` retiene su RAM hasta `gdal.Unlink`; QGIS no lo libera al quitar la capa | Una capa en `/vsimem` obliga a GeoDuck a liberar el archivo cuando QGIS elimina la capa, lo que roza §10 |
| F-52 | Edición real (alta, cambio, `commitChanges`, reapertura) en GeoPackage `/vsimem` y en GeoParquet, en 3.44 y 4.2. El archivo Arrow IPC es de solo lectura | Si la capa entregada debe ser editable, GeoPackage o memory |
| F-53 | GeoPackage no admite `DECIMAL` con precisión > 19 (`CreateFieldFromPyArrowSchema` falla) | Coincide con la normalización de F-47 |
| F-54 | DuckDB 1.5.0, 1.5.6 y 2.0.0 escriben GeoParquet 1.0 por defecto (`GEOPARQUET_VERSION 'V1'` lo fija); `V2`/`BOTH` usan el tipo lógico GEOMETRY de Parquet, que necesita arrow-cpp ≥ 21 (OSGeo4W #900, cerrado en 2026) | Para archivos que abran QGIS antiguos, escribir siempre `V1` |
| F-55 | GeoParquet escrito por DuckDB (C++) y leído por OGR bajo demanda: 1 M de puntos en 0,2 s de escritura y 14–25 MB; 5 M en 0,9–1,0 s y 72 MB. Filtro por extensión (1 % del área): 0,16–0,35 s con 1 M y 0,96–1,03 s con 5 M; filtro de atributo ≈ 0,01 s; sobrevive a DETACH, cierre y reapertura del proyecto | Alternativa escalable sin cargar todo en RAM, pero es un archivo que alguien gestiona |
| F-56 | Driver ADBC de GDAL (3.11+) con DuckDB: solo abre capas definidas por `SQL=`; **no lista tablas ni vistas** con DuckDB 2.0; la capa SQL **pierde el CRS**; necesita `libduckdb` y la extensión `spatial`; solo lectura; empuja a DuckDB los filtros de extensión y de atributo, pero es más lento que GeoParquet: extensión 0,8–0,9 s con 1 M y 3,1–3,7 s con 5 M; atributo 0,6 s y 3,0–3,5 s. No ve `:memory:`, `TEMP` ni cambios sin confirmar de la sesión | Hoy no sirve como modalidad conectada de GeoDuck sin trabajo previo aguas arriba |
| F-57 | QDuckDB 2.3.1 (Oslandia, QGIS 3.34.6–4.x) es un proveedor DuckDB de solo lectura distribuido como complemento, que instala su propio `duckdb` con QPIP | Convivir con GeoDuck en el mismo Python (un solo módulo `duckdb`) choca con ADR-0009/0011 |
| F-58 | Cancelar a mitad deja 0 capas en el proyecto, ningún archivo en `/vsimem` ni en disco y la sesión usable, en las seis rutas; en GeoParquet, `interrupt()` corta el `COPY` antes de escribir | La atomicidad de §6 se cumple en todas |
| F-59 | En las seis rutas la capa se lee entera e idéntica (huella SHA-256 de atributos + WKB por fila) tras `DETACH`, cierre de la conexión y borrado del `.duckdb` de origen. Solo los archivos en disco (Arrow, GeoParquet) sobreviven a la reapertura del proyecto | §10 se cumple en todas; la persistencia depende del destino, no de la ruta |
| F-60 | Defecto del propio script: si el hilo principal falla, el productor queda bloqueado en `put()` y el proceso no termina | Regla para el paso 2: el productor se detiene cuando el consumidor falla o cancela |
