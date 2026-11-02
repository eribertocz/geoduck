# Tablas del spike G3-A (generadas)

Generado por `tools/bench/summarize.py` a partir de los JSON de esta carpeta. No editar a mano.

## Comparación de rutas — `compare_q344.json`

| ruta | filas | proveedor | total s | bloqueo máx ms | RAM retenida MB | /vsimem MB | disco MB | CRS | íntegra | tras DETACH y cierre | tras reabrir proyecto | editable | dibujar s | leer todo s |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|---|---:|---:|
| memory | 100,000 | memory | 1.251 | 126.0 | 53.9 | 0 | 0 | OGC:CRS84 | sí | sí | **no** | sí | 0.157 | 0.813 |
| arrow-vsimem | 100,000 | ogr | 0.086 | 43.2 | 35.5 | 7.3 | 0 | EPSG:4326 | sí | sí | **no** | **no** | 0.173 | 1.004 |
| arrow-disk | 100,000 | ogr | 0.07 | 31.4 | 18.6 | 0 | 7.3 | EPSG:4326 | sí | sí | sí | **no** | 0.151 | 1.065 |
| gpkg-vsimem | 100,000 | ogr | 0.326 | 35.6 | 40.8 | 8.3 | 0 | OGC:CRS84 | sí | sí | **no** | sí | 0.211 | 1.168 |
| gdal-materialize | 100,000 | memory | 0.395 | 348.6 | 70.5 | 0 | 0 | EPSG:4326 | sí | sí | **no** | sí | 0.128 | 0.695 |
| geoparquet | 100,000 | ogr | 0.07 | 20.1 | 35.5 | 0 | 2.5 | EPSG:4326 | sí | sí | sí | sí | 0.141 | 1.018 |
| memory | 1,000,000 | memory | 10.107 | 69.5 | 453.8 | 0 | 0 | OGC:CRS84 | sí | sí | **no** | sí | 1.121 | 8.56 |
| arrow-vsimem | 1,000,000 | ogr | 0.298 | 60.4 | 138.1 | 73.6 | 0 | EPSG:4326 | sí | sí | **no** | **no** | 1.617 | 9.318 |
| arrow-disk | 1,000,000 | ogr | 0.238 | 70.8 | 40.7 | 0 | 73.6 | EPSG:4326 | sí | sí | sí | **no** | 1.532 | 8.715 |
| gpkg-vsimem | 1,000,000 | ogr | 1.802 | 33.5 | 149.7 | 83.2 | 0 | OGC:CRS84 | sí | sí | **no** | sí | 1.44 | 10.511 |
| gdal-materialize | 1,000,000 | memory | 3.395 | 3180.1 | 558.3 | 0 | 0 | EPSG:4326 | sí | sí | **no** | sí | 1.099 | 11.828 |
| geoparquet | 1,000,000 | ogr | 0.356 | 19.6 | 122.0 | 0 | 24.6 | EPSG:4326 | sí | sí | sí | sí | 1.403 | 9.988 |

Cancelación a mitad de la carga:

| ruta | filas | cancelada | filas antes de cancelar | capas en el proyecto | restos | sesión usable |
|---|---:|---|---:|---:|---|---|
| memory | 100,000 | sí | 50176 | 0 | no | sí |
| arrow-vsimem | 100,000 | sí | 57344 | 0 | no | sí |
| arrow-disk | 100,000 | sí | 57344 | 0 | no | sí |
| gpkg-vsimem | 100,000 | sí | 57344 | 0 | no | sí |
| gdal-materialize | 100,000 | sí | 57344 | 0 | no | sí |
| geoparquet | 100,000 | sí | 0 | 0 | no | sí |

## Comparación de rutas — `compare_q42.json`

| ruta | filas | proveedor | total s | bloqueo máx ms | RAM retenida MB | /vsimem MB | disco MB | CRS | íntegra | tras DETACH y cierre | tras reabrir proyecto | editable | dibujar s | leer todo s |
|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|---|---:|---:|
| memory | 100,000 | memory | 1.088 | 69.4 | 71.0 | 0 | 0 | OGC:CRS84 | sí | sí | **no** | sí | 0.099 | 0.722 |
| arrow-vsimem | 100,000 | ogr | 0.134 | 90.7 | 36.2 | 7.3 | 0 | EPSG:4326 | sí | sí | **no** | **no** | 0.197 | 5.199 |
| arrow-disk | 100,000 | ogr | 0.13 | 95.2 | 26.4 | 0 | 7.3 | EPSG:4326 | sí | sí | sí | **no** | 0.22 | 5.59 |
| gpkg-vsimem | 100,000 | ogr | 0.398 | 83.1 | 49.9 | 8.3 | 0 | OGC:CRS84 | sí | sí | **no** | sí | 0.146 | 5.23 |
| gdal-materialize | 100,000 | memory | 4.486 | 4442.1 | 73.9 | 0 | 0 | EPSG:4326 | sí | sí | **no** | sí | 0.146 | 0.673 |
| geoparquet | 100,000 | ogr | 0.142 | 85.5 | 48.6 | 0 | 2.5 | EPSG:4326 | sí | sí | sí | sí | 0.134 | 5.267 |
| memory | 1,000,000 | memory | 8.698 | 71.0 | 547.5 | 0 | 0 | OGC:CRS84 | sí | sí | **no** | sí | 1.048 | 10.482 |
| arrow-vsimem | 1,000,000 | ogr | 0.316 | 115.7 | 134.9 | 73.6 | 0 | EPSG:4326 | sí | sí | **no** | **no** | 1.429 | 54.772 |
| arrow-disk | 1,000,000 | ogr | 0.353 | 130.0 | 27.3 | 0 | 73.6 | EPSG:4326 | sí | sí | sí | **no** | 1.626 | 60.303 |
| gpkg-vsimem | 1,000,000 | ogr | 2.172 | 99.2 | 174.8 | 83.2 | 0 | OGC:CRS84 | sí | sí | **no** | sí | 1.634 | 60.615 |
| gdal-materialize | 1,000,000 | memory | 45.51 | 45307.6 | 655.2 | 0 | 0 | EPSG:4326 | sí | sí | **no** | sí | 1.024 | 10.849 |
| geoparquet | 1,000,000 | ogr | 0.407 | 75.7 | 77.1 | 0 | 24.6 | EPSG:4326 | sí | sí | sí | sí | 1.241 | 56.755 |

Cancelación a mitad de la carga:

| ruta | filas | cancelada | filas antes de cancelar | capas en el proyecto | restos | sesión usable |
|---|---:|---|---:|---:|---|---|
| memory | 100,000 | sí | 50176 | 0 | no | sí |
| arrow-vsimem | 100,000 | sí | 57344 | 0 | no | sí |
| arrow-disk | 100,000 | sí | 57344 | 0 | no | sí |
| gpkg-vsimem | 100,000 | sí | 57344 | 0 | no | sí |
| gdal-materialize | 100,000 | sí | 57344 | 0 | no | sí |
| geoparquet | 100,000 | sí | 0 | 0 | no | sí |

## Lectura bajo demanda — `ondemand_q344.json`

| ruta | filas | escribir s | abrir s | conteo s | filtro 1 % área (filas · s) | filtro atributo s | recorrer todo s | dibujar todo s | dibujar zoom s | CRS | editable |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|---|
| geoparquet | 1,000,000 | 0.222 | 0.022 | 0.0 | 10,201 · 0.347 | 0.012 | 0.992 | 1.433 | 0.076 | EPSG:4326 | sí |
| adbc-sql | 1,000,000 | — | 0.323 | 0.077 | 10,201 · 0.938 | 0.564 | 1.201 | 1.559 | 0.44 | (ninguno) | **no** |
| ↳ tablas que lista ADBC: `[]` | | | | | | | | | | | |
| geoparquet | 5,000,000 | 1.003 | 0.005 | 0.0 | 49,729 · 1.026 | 0.008 | 5.363 | 7.034 | 0.332 | EPSG:4326 | sí |
| adbc-sql | 5,000,000 | — | 0.289 | 0.375 | 49,729 · 3.12 | 3.025 | 6.034 | 8.214 | 2.62 | (ninguno) | **no** |
| ↳ tablas que lista ADBC: `[]` | | | | | | | | | | | |

## Lectura bajo demanda — `ondemand_q42.json`

| ruta | filas | escribir s | abrir s | conteo s | filtro 1 % área (filas · s) | filtro atributo s | recorrer todo s | dibujar todo s | dibujar zoom s | CRS | editable |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|---|
| geoparquet | 1,000,000 | 0.209 | 0.098 | 0.0 | 10,201 · 0.159 | 0.007 | 0.961 | 1.621 | 0.123 | EPSG:4326 | sí |
| adbc-sql | 1,000,000 | — | 0.309 | 0.081 | 10,201 · 0.815 | 0.596 | 1.121 | 1.334 | 0.434 | (ninguno) | **no** |
| ↳ tablas que lista ADBC: `[]` | | | | | | | | | | | |
| geoparquet | 5,000,000 | 0.881 | 0.003 | 0.0 | 49,729 · 0.962 | 0.008 | 5.164 | 7.461 | 0.445 | EPSG:4326 | sí |
| adbc-sql | 5,000,000 | — | 0.327 | 0.375 | 49,729 · 3.669 | 3.499 | 6.059 | 7.832 | 2.742 | (ninguno) | **no** |
| ↳ tablas que lista ADBC: `[]` | | | | | | | | | | | |

## Fidelidad de tipos (driver Arrow de GDAL) — `types_q344.json`

Geometría principal: tipo 1, CRS EPSG:4326, `Point (1 2)`. Segunda geometría accesible: **no**.

| columna | Arrow | campo QGIS | valor en QGIS |
|---|---|---|---|
| `b` | `bool` | Boolean | `True` |
| `ti` | `int8` | Integer | `127` |
| `i` | `int32` | Integer | `2147483647` |
| `bi` | `int64` | Integer64 | `9223372036854775807` |
| `ubi` | `uint64` | Real | `1.8446744073709552e+19` |
| `hi` | `decimal128(38, 0)` | Real | `1.7014118346046923e+38` |
| `f` | `float` | Float32 | `1.5` |
| `d_nan` | `double` | Real | `nan` |
| `d_inf` | `double` | Real | `inf` |
| `dec_9_2` | `decimal128(9, 2)` | Real | `1234567.89` |
| `dec_18_3` | `decimal128(18, 3)` | Real | `123456789012345.67` |
| `dec_38_10` | `decimal128(38, 10)` | Real | `1.2345678901234569e+27` |
| `vc` | `string` | String | `'ñandú 🦆'` |
| `en` | `dictionary<values=string, indices=uint8, ordered=0>` | Integer | `1` |
| `uu` | `string` | String | `'550e8400-e29b-41d4-a716-446655440000'` |
| `dt` | `date32[day]` | Date | `PyQt5.QtCore.QDate(2026, 11, 1)` |
| `ts` | `timestamp[us]` | DateTime | `PyQt5.QtCore.QDateTime(2026, 11, 1, 12, 34, 56, 789)` |
| `tstz` | `timestamp[us, tz=UTC]` | DateTime | `PyQt5.QtCore.QDateTime(2026, 11, 1, 10, 34, 56, 0, PyQt5.QtC` |
| `tm` | `time64[us]` | Integer64 | `45296000000` |
| `iv` | `month_day_nano_interval` | (no es campo) | `` |
| `bl` | `binary` | Binary | `PyQt5.QtCore.QByteArray(b'\xaa\xbb')` |
| `li` | `list<l: int32>` | IntegerList | `[1, 2, 3]` |
| `st` | `struct<x: int32, y: string>` | (no es campo) | `` |
| `mp` | `map<string, int32>` | JSON | `{'k': 1}` |
| `nul` | `int32` | Integer | `NULL` |
| `geom` | `binary` | (no es campo) | `` |
| `geom2` | `binary` | (no es campo) | `` |

## Fidelidad de tipos (driver Arrow de GDAL) — `types_q42.json`

Geometría principal: tipo 1, CRS EPSG:4326, `Point (1 2)`. Segunda geometría accesible: **no**.

| columna | Arrow | campo QGIS | valor en QGIS |
|---|---|---|---|
| `b` | `bool` | Boolean | `True` |
| `ti` | `int8` | Integer | `127` |
| `i` | `int32` | Integer | `2147483647` |
| `bi` | `int64` | Integer64 | `9223372036854775807` |
| `ubi` | `uint64` | Real | `1.8446744073709552e+19` |
| `hi` | `decimal128(38, 0)` | Real | `1.7014118346046923e+38` |
| `f` | `float` | Float32 | `1.5` |
| `d_nan` | `double` | Real | `nan` |
| `d_inf` | `double` | Real | `inf` |
| `dec_9_2` | `decimal128(9, 2)` | Real | `1234567.89` |
| `dec_18_3` | `decimal128(18, 3)` | Real | `123456789012345.67` |
| `dec_38_10` | `decimal128(38, 10)` | Real | `1.2345678901234569e+27` |
| `vc` | `string` | String | `'ñandú 🦆'` |
| `en` | `dictionary<values=string, indices=uint8, ordered=0>` | Integer | `1` |
| `uu` | `string` | String | `'550e8400-e29b-41d4-a716-446655440000'` |
| `dt` | `date32[day]` | Date | `PyQt6.QtCore.QDate(2026, 11, 1)` |
| `ts` | `timestamp[us]` | DateTime | `PyQt6.QtCore.QDateTime(2026, 11, 1, 12, 34, 56, 789)` |
| `tstz` | `timestamp[us, tz=UTC]` | DateTime | `PyQt6.QtCore.QDateTime(2026, 11, 1, 10, 34, 56, 0, PyQt6.QtC` |
| `tm` | `time64[us]` | Integer64 | `45296000000` |
| `iv` | `month_day_nano_interval` | (no es campo) | `` |
| `bl` | `binary` | Binary | `PyQt6.QtCore.QByteArray(b'\xaa\xbb')` |
| `li` | `list<l: int32>` | IntegerList | `[1, 2, 3]` |
| `st` | `struct<x: int32, y: string>` | (no es campo) | `` |
| `mp` | `map<string, int32>` | JSON | `{'k': 1}` |
| `nul` | `int32` | Integer | `None` |
| `geom` | `binary` | (no es campo) | `` |
| `geom2` | `binary` | (no es campo) | `` |

## Bench de transferencia a capa memory — `result_q344.json`

| datos | filas | lote | etapa | estrategia | tramo | fechas | total s | filas/s | hilo principal s | bloqueo máx ms | ΔRSS MB |
|---|---:|---:|---|---|---:|---|---:|---:|---:|---:|---:|
| tabular | 10,000 | 8192 | engine | - | — | — | 0.096 | 104,166 | — | — | 44.9 |
| tabular | 10,000 | 8192 | pylist | - | — | — | 0.114 | 87,719 | — | — | 48.9 |
| tabular | 10,000 | 8192 | qgis | main | — | qdatetime | 0.187 | 53,475 | 0.11 | 93.4 | 41.8 |
| tabular | 10,000 | 8192 | qgis | worker-lists | — | qdatetime | 0.199 | 50,251 | 0.042 | 30.8 | 45.0 |
| tabular | 10,000 | 8192 | qgis | worker-features | — | qdatetime | 0.232 | 43,103 | 0.024 | 13.8 | 42.6 |
| tabular | 10,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.107 | 93,457 | 0.027 | 26.8 | 27.1 |
| tabular | 10,000 | 8192 | qgis | main | 1024 | qdatetime | 0.194 | 51,546 | 0.109 | 48.5 | 38.0 |
| tabular | 100,000 | 8192 | engine | - | — | — | 0.125 | 800,000 | — | — | 49.7 |
| tabular | 100,000 | 8192 | pylist | - | — | — | 0.291 | 343,642 | — | — | 55.5 |
| tabular | 100,000 | 8192 | qgis | main | — | qdatetime | 1.493 | 66,979 | 1.28 | 175.9 | 81.0 |
| tabular | 100,000 | 8192 | qgis | worker-lists | — | qdatetime | 1.223 | 81,766 | 0.972 | 130.6 | 92.3 |
| tabular | 100,000 | 8192 | qgis | worker-features | — | qdatetime | 1.219 | 82,034 | 0.691 | 91.5 | 81.2 |
| tabular | 100,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.094 | 1,063,829 | 0.01 | 9.6 | 34.1 |
| tabular | 100,000 | 8192 | qgis | main | 1024 | qdatetime | 1.102 | 90,744 | 0.914 | 53.0 | 71.5 |
| tabular | 1,000,000 | 8192 | engine | - | — | — | 0.233 | 4,291,845 | — | — | 54.2 |
| tabular | 1,000,000 | 8192 | pylist | - | — | — | 1.665 | 600,600 | — | — | 63.6 |
| tabular | 1,000,000 | 8192 | qgis | main | — | qdatetime | 13.099 | 76,341 | 11.963 | 195.4 | 400.5 |
| tabular | 1,000,000 | 8192 | qgis | worker-lists | — | qdatetime | 13.376 | 74,760 | 11.864 | 194.5 | 411.6 |
| tabular | 1,000,000 | 8192 | qgis | worker-features | — | qdatetime | 23.906 | 41,830 | 22.346 | 400.9 | 415.5 |
| tabular | 1,000,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.229 | 4,366,812 | 0.019 | 19.4 | 35.6 |
| tabular | 1,000,000 | 8192 | qgis | main | 1024 | qdatetime | 8.934 | 111,931 | 7.968 | 60.3 | 390.3 |
| tabular | 1,000,000 | 8192 | qgis | main | — | msecs | 13.816 | 72,379 | 12.731 | 196.4 | 400.0 |
| points | 10,000 | 8192 | engine | - | — | — | 0.105 | 95,238 | — | — | 44.8 |
| points | 10,000 | 8192 | pylist | - | — | — | 0.095 | 105,263 | — | — | 46.3 |
| points | 10,000 | 8192 | qgis | main | — | qdatetime | 0.12 | 83,333 | 0.055 | 39.4 | 26.8 |
| points | 10,000 | 8192 | qgis | worker-lists | — | qdatetime | 0.135 | 74,074 | 0.051 | 37.9 | 28.0 |
| points | 10,000 | 8192 | qgis | worker-features | — | qdatetime | 0.097 | 103,092 | 0.017 | 10.4 | 28.1 |
| points | 10,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.063 | 158,730 | 0.007 | 7.1 | 27.2 |
| points | 10,000 | 8192 | qgis | main | 1024 | qdatetime | 0.1 | 100,000 | 0.039 | 5.0 | 23.1 |
| points | 100,000 | 8192 | engine | - | — | — | 0.119 | 840,336 | — | — | 47.8 |
| points | 100,000 | 8192 | pylist | - | — | — | 0.197 | 507,614 | — | — | 50.1 |
| points | 100,000 | 8192 | qgis | main | — | qdatetime | 1.08 | 92,592 | 0.751 | 111.6 | 57.0 |
| points | 100,000 | 8192 | qgis | worker-lists | — | qdatetime | 1.578 | 63,371 | 0.831 | 119.9 | 60.0 |
| points | 100,000 | 8192 | qgis | worker-features | — | qdatetime | 2.43 | 41,152 | 2.237 | 322.4 | 62.6 |
| points | 100,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.118 | 847,457 | 0.011 | 11.5 | 30.5 |
| points | 100,000 | 8192 | qgis | main | 1024 | qdatetime | 0.684 | 146,198 | 0.522 | 40.5 | 50.1 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.456 | 2,192,982 | — | — | 50.0 |
| points | 1,000,000 | 8192 | pylist | - | — | — | 0.463 | 2,159,827 | — | — | 52.5 |
| points | 1,000,000 | 8192 | qgis | main | — | qdatetime | 8.736 | 114,468 | 7.638 | 139.8 | 321.4 |
| points | 1,000,000 | 8192 | qgis | worker-lists | — | qdatetime | 9.439 | 105,943 | 8.195 | 138.4 | 320.4 |
| points | 1,000,000 | 8192 | qgis | worker-features | — | qdatetime | 19.337 | 51,714 | 18.047 | 405.8 | 326.4 |
| points | 1,000,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.564 | 1,773,049 | 0.065 | 64.9 | 32.7 |
| points | 1,000,000 | 8192 | qgis | main | 1024 | qdatetime | 6.729 | 148,610 | 5.605 | 67.9 | 314.8 |
| points | 1,000,000 | 8192 | qgis | main | — | msecs | 9.056 | 110,424 | 7.877 | 142.7 | 321.6 |
| polygons | 10,000 | 8192 | engine | - | — | — | 0.127 | 78,740 | — | — | 47.9 |
| polygons | 10,000 | 8192 | pylist | - | — | — | 0.118 | 84,745 | — | — | 49.9 |
| polygons | 10,000 | 8192 | qgis | main | — | qdatetime | 0.137 | 72,992 | 0.053 | 37.5 | 34.3 |
| polygons | 10,000 | 8192 | qgis | worker-lists | — | qdatetime | 0.136 | 73,529 | 0.052 | 37.7 | 35.3 |
| polygons | 10,000 | 8192 | qgis | worker-features | — | qdatetime | 0.139 | 71,942 | 0.022 | 13.9 | 34.4 |
| polygons | 10,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.078 | 128,205 | 0.009 | 8.6 | 30.1 |
| polygons | 10,000 | 8192 | qgis | main | 1024 | qdatetime | 0.162 | 61,728 | 0.058 | 8.2 | 31.4 |
| polygons | 100,000 | 8192 | engine | - | — | — | 0.222 | 450,450 | — | — | 57.6 |
| polygons | 100,000 | 8192 | pylist | - | — | — | 0.281 | 355,871 | — | — | 60.7 |
| polygons | 100,000 | 8192 | qgis | main | — | qdatetime | 1.144 | 87,412 | 0.831 | 117.2 | 108.2 |
| polygons | 100,000 | 8192 | qgis | worker-lists | — | qdatetime | 0.975 | 102,564 | 0.747 | 91.1 | 111.7 |
| polygons | 100,000 | 8192 | qgis | worker-features | — | qdatetime | 2.349 | 42,571 | 1.986 | 239.2 | 108.9 |
| polygons | 100,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.19 | 526,315 | 0.013 | 13.1 | 40.1 |
| polygons | 100,000 | 8192 | qgis | main | 1024 | qdatetime | 1.029 | 97,181 | 0.685 | 78.1 | 99.3 |
| polygons | 1,000,000 | 8192 | engine | - | — | — | 1.388 | 720,461 | — | — | 64.4 |
| polygons | 1,000,000 | 8192 | pylist | - | — | — | 1.306 | 765,696 | — | — | 68.5 |
| polygons | 1,000,000 | 8192 | qgis | main | — | qdatetime | 11.471 | 87,176 | 9.706 | 172.4 | 797.7 |
| polygons | 1,000,000 | 8192 | qgis | worker-lists | — | qdatetime | 11.298 | 88,511 | 9.513 | 164.3 | 791.6 |
| polygons | 1,000,000 | 8192 | qgis | worker-features | — | qdatetime | 23.956 | 41,743 | 21.008 | 328.5 | 787.7 |
| polygons | 1,000,000 | 8192 | qgis | arrow-file | — | qdatetime | 1.273 | 785,545 | 0.072 | 72.3 | 48.4 |
| polygons | 1,000,000 | 8192 | qgis | main | 1024 | qdatetime | 7.806 | 128,106 | 6.381 | 64.7 | 776.0 |
| polygons | 1,000,000 | 8192 | qgis | main | — | msecs | 11.336 | 88,214 | 9.194 | 161.7 | 797.6 |
| points | 1,000,000 | 2048 | qgis | main | — | qdatetime | 6.77 | 147,710 | 5.833 | 66.4 | 314.2 |
| points | 1,000,000 | 2048 | engine | - | — | — | 0.402 | 2,487,562 | — | — | 49.4 |
| points | 1,000,000 | 8192 | qgis | main | — | qdatetime | 9.233 | 108,307 | 7.785 | 159.8 | 321.8 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.42 | 2,380,952 | — | — | 50.2 |
| points | 1,000,000 | 16384 | qgis | main | — | qdatetime | 9.771 | 102,343 | 8.567 | 225.7 | 328.6 |
| points | 1,000,000 | 16384 | engine | - | — | — | 0.412 | 2,427,184 | — | — | 51.3 |
| points | 1,000,000 | 65536 | qgis | main | — | qdatetime | 9.497 | 105,296 | 8.414 | 636.7 | 390.4 |
| points | 1,000,000 | 65536 | engine | - | — | — | 0.394 | 2,538,071 | — | — | 56.0 |

## Bench de transferencia a capa memory — `result_q42.json`

| datos | filas | lote | etapa | estrategia | tramo | fechas | total s | filas/s | hilo principal s | bloqueo máx ms | ΔRSS MB |
|---|---:|---:|---|---|---:|---|---:|---:|---:|---:|---:|
| tabular | 10,000 | 8192 | engine | - | — | — | 0.096 | 104,166 | — | — | 44.8 |
| tabular | 10,000 | 8192 | pylist | - | — | — | 0.116 | 86,206 | — | — | 48.1 |
| tabular | 10,000 | 8192 | qgis | main | — | qdatetime | 0.824 | 12,135 | 0.601 | 447.1 | 51.6 |
| tabular | 10,000 | 8192 | qgis | worker-lists | — | qdatetime | 0.706 | 14,164 | 0.169 | 157.6 | 53.7 |
| tabular | 10,000 | 8192 | qgis | worker-features | — | qdatetime | 0.818 | 12,224 | 0.048 | 31.7 | 52.5 |
| tabular | 10,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.162 | 61,728 | 0.084 | 84.1 | 36.8 |
| tabular | 10,000 | 8192 | qgis | main | 1024 | qdatetime | 0.666 | 15,015 | 0.535 | 85.4 | 46.4 |
| tabular | 100,000 | 8192 | engine | - | — | — | 0.113 | 884,955 | — | — | 49.5 |
| tabular | 100,000 | 8192 | pylist | - | — | — | 0.259 | 386,100 | — | — | 55.0 |
| tabular | 100,000 | 8192 | qgis | main | — | qdatetime | 5.563 | 17,975 | 5.358 | 517.9 | 101.0 |
| tabular | 100,000 | 8192 | qgis | worker-lists | — | qdatetime | 6.73 | 14,858 | 6.023 | 1028.4 | 113.0 |
| tabular | 100,000 | 8192 | qgis | worker-features | — | qdatetime | 7.057 | 14,170 | 5.976 | 1667.0 | 106.8 |
| tabular | 100,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.175 | 571,428 | 0.09 | 89.8 | 43.4 |
| tabular | 100,000 | 8192 | qgis | main | 1024 | qdatetime | 5.783 | 17,292 | 5.53 | 146.9 | 92.7 |
| tabular | 1,000,000 | 8192 | engine | - | — | — | 0.249 | 4,016,064 | — | — | 50.8 |
| tabular | 1,000,000 | 8192 | pylist | - | — | — | 1.919 | 521,104 | — | — | 57.0 |
| tabular | 1,000,000 | 8192 | qgis | main | — | qdatetime | 54.782 | 18,254 | 53.783 | 615.2 | 517.5 |
| tabular | 1,000,000 | 8192 | qgis | worker-lists | — | qdatetime | 65.836 | 15,189 | 62.617 | 1432.4 | 527.2 |
| tabular | 1,000,000 | 8192 | qgis | worker-features | — | qdatetime | 63.565 | 15,731 | 49.137 | 1630.6 | 517.7 |
| tabular | 1,000,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.338 | 2,958,579 | 0.107 | 107.2 | 44.9 |
| tabular | 1,000,000 | 8192 | qgis | main | 1024 | qdatetime | 55.423 | 18,043 | 54.47 | 199.1 | 507.8 |
| tabular | 1,000,000 | 8192 | qgis | main | — | msecs | 11.157 | 89,629 | 10.276 | 153.1 | 516.2 |
| points | 10,000 | 8192 | engine | - | — | — | 0.089 | 112,359 | — | — | 45.2 |
| points | 10,000 | 8192 | pylist | - | — | — | 0.095 | 105,263 | — | — | 46.4 |
| points | 10,000 | 8192 | qgis | main | — | qdatetime | 0.184 | 54,347 | 0.039 | 28.7 | 35.9 |
| points | 10,000 | 8192 | qgis | worker-lists | — | qdatetime | 0.25 | 40,000 | 0.041 | 30.4 | 36.5 |
| points | 10,000 | 8192 | qgis | worker-features | — | qdatetime | 0.175 | 57,142 | 0.018 | 12.1 | 35.9 |
| points | 10,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.15 | 66,666 | 0.079 | 78.7 | 37.1 |
| points | 10,000 | 8192 | qgis | main | 1024 | qdatetime | 0.18 | 55,555 | 0.04 | 4.6 | 31.5 |
| points | 100,000 | 8192 | engine | - | — | — | 0.128 | 781,250 | — | — | 48.0 |
| points | 100,000 | 8192 | pylist | - | — | — | 0.129 | 775,193 | — | — | 50.1 |
| points | 100,000 | 8192 | qgis | main | — | qdatetime | 0.839 | 119,189 | 0.615 | 80.7 | 69.2 |
| points | 100,000 | 8192 | qgis | worker-lists | — | qdatetime | 0.93 | 107,526 | 0.651 | 83.1 | 71.2 |
| points | 100,000 | 8192 | qgis | worker-features | — | qdatetime | 2.133 | 46,882 | 1.874 | 369.7 | 79.4 |
| points | 100,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.17 | 588,235 | 0.081 | 80.9 | 39.4 |
| points | 100,000 | 8192 | qgis | main | 1024 | qdatetime | 0.791 | 126,422 | 0.562 | 69.9 | 62.2 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.471 | 2,123,142 | — | — | 50.1 |
| points | 1,000,000 | 8192 | pylist | - | — | — | 0.428 | 2,336,448 | — | — | 52.2 |
| points | 1,000,000 | 8192 | qgis | main | — | qdatetime | 7.544 | 132,555 | 6.67 | 136.0 | 374.7 |
| points | 1,000,000 | 8192 | qgis | worker-lists | — | qdatetime | 7.448 | 134,264 | 6.681 | 114.4 | 378.8 |
| points | 1,000,000 | 8192 | qgis | worker-features | — | qdatetime | 22.911 | 43,647 | 22.317 | 333.4 | 388.8 |
| points | 1,000,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.506 | 1,976,284 | 0.119 | 118.8 | 42.6 |
| points | 1,000,000 | 8192 | qgis | main | 1024 | qdatetime | 5.657 | 176,772 | 4.882 | 71.5 | 369.4 |
| points | 1,000,000 | 8192 | qgis | main | — | msecs | 7.432 | 134,553 | 6.561 | 151.3 | 377.1 |
| polygons | 10,000 | 8192 | engine | - | — | — | 0.202 | 49,504 | — | — | 48.9 |
| polygons | 10,000 | 8192 | pylist | - | — | — | 0.145 | 68,965 | — | — | 50.3 |
| polygons | 10,000 | 8192 | qgis | main | — | qdatetime | 0.203 | 49,261 | 0.053 | 35.8 | 43.9 |
| polygons | 10,000 | 8192 | qgis | worker-lists | — | qdatetime | 0.218 | 45,871 | 0.048 | 34.2 | 45.0 |
| polygons | 10,000 | 8192 | qgis | worker-features | — | qdatetime | 0.203 | 49,261 | 0.017 | 8.7 | 43.0 |
| polygons | 10,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.134 | 74,626 | 0.064 | 63.6 | 40.0 |
| polygons | 10,000 | 8192 | qgis | main | 1024 | qdatetime | 0.172 | 58,139 | 0.043 | 5.0 | 39.5 |
| polygons | 100,000 | 8192 | engine | - | — | — | 0.216 | 462,962 | — | — | 57.7 |
| polygons | 100,000 | 8192 | pylist | - | — | — | 0.226 | 442,477 | — | — | 61.1 |
| polygons | 100,000 | 8192 | qgis | main | — | qdatetime | 1.101 | 90,826 | 0.803 | 113.7 | 120.0 |
| polygons | 100,000 | 8192 | qgis | worker-lists | — | qdatetime | 1.054 | 94,876 | 0.682 | 88.9 | 122.8 |
| polygons | 100,000 | 8192 | qgis | worker-features | — | qdatetime | 0.936 | 106,837 | 0.404 | 68.6 | 126.5 |
| polygons | 100,000 | 8192 | qgis | arrow-file | — | qdatetime | 0.254 | 393,700 | 0.069 | 68.6 | 50.2 |
| polygons | 100,000 | 8192 | qgis | main | 1024 | qdatetime | 0.895 | 111,731 | 0.525 | 41.9 | 119.4 |
| polygons | 1,000,000 | 8192 | engine | - | — | — | 1.247 | 801,924 | — | — | 53.9 |
| polygons | 1,000,000 | 8192 | pylist | - | — | — | 1.391 | 718,907 | — | — | 57.0 |
| polygons | 1,000,000 | 8192 | qgis | main | — | qdatetime | 12.637 | 79,132 | 11.171 | 212.9 | 839.7 |
| polygons | 1,000,000 | 8192 | qgis | worker-lists | — | qdatetime | 11.394 | 87,765 | 9.942 | 194.4 | 846.4 |
| polygons | 1,000,000 | 8192 | qgis | worker-features | — | qdatetime | 11.363 | 88,004 | 6.377 | 179.1 | 850.4 |
| polygons | 1,000,000 | 8192 | qgis | arrow-file | — | qdatetime | 1.433 | 697,836 | 0.129 | 129.4 | 58.1 |
| polygons | 1,000,000 | 8192 | qgis | main | 1024 | qdatetime | 9.237 | 108,260 | 7.677 | 65.2 | 844.3 |
| polygons | 1,000,000 | 8192 | qgis | main | — | msecs | 11.159 | 89,613 | 9.846 | 204.2 | 843.8 |
| points | 1,000,000 | 2048 | qgis | main | — | qdatetime | 6.732 | 148,544 | 5.926 | 71.5 | 374.5 |
| points | 1,000,000 | 2048 | engine | - | — | — | 0.37 | 2,702,702 | — | — | 49.5 |
| points | 1,000,000 | 8192 | qgis | main | — | qdatetime | 7.575 | 132,013 | 6.748 | 139.1 | 382.2 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.452 | 2,212,389 | — | — | 50.2 |
| points | 1,000,000 | 16384 | qgis | main | — | qdatetime | 8.599 | 116,292 | 7.683 | 229.4 | 385.9 |
| points | 1,000,000 | 16384 | engine | - | — | — | 0.52 | 1,923,076 | — | — | 48.8 |
| points | 1,000,000 | 65536 | qgis | main | — | qdatetime | 9.019 | 110,877 | 8.068 | 633.7 | 437.9 |
| points | 1,000,000 | 65536 | engine | - | — | — | 0.409 | 2,444,987 | — | — | 55.1 |

## Etapa de motor (sin QGIS) — `result_engine_duckdb1.5.0.json`

| datos | filas | lote | etapa | estrategia | tramo | fechas | total s | filas/s | hilo principal s | bloqueo máx ms | ΔRSS MB |
|---|---:|---:|---|---|---:|---|---:|---:|---:|---:|---:|
| tabular | 10,000 | 8192 | engine | - | — | — | 0.179 | 55,865 | — | — | 29.0 |
| tabular | 10,000 | 8192 | pylist | - | — | — | 0.07 | 142,857 | — | — | 32.4 |
| tabular | 100,000 | 8192 | engine | - | — | — | 0.048 | 2,083,333 | — | — | 30.5 |
| tabular | 100,000 | 8192 | pylist | - | — | — | 0.222 | 450,450 | — | — | 37.1 |
| tabular | 1,000,000 | 8192 | engine | - | — | — | 0.203 | 4,926,108 | — | — | 32.3 |
| tabular | 1,000,000 | 8192 | pylist | - | — | — | 1.972 | 507,099 | — | — | 37.3 |
| points | 10,000 | 8192 | engine | - | — | — | 0.051 | 196,078 | — | — | 28.9 |
| points | 10,000 | 8192 | pylist | - | — | — | 0.049 | 204,081 | — | — | 30.9 |
| points | 100,000 | 8192 | engine | - | — | — | 0.09 | 1,111,111 | — | — | 32.2 |
| points | 100,000 | 8192 | pylist | - | — | — | 0.097 | 1,030,927 | — | — | 34.5 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.456 | 2,192,982 | — | — | 33.3 |
| points | 1,000,000 | 8192 | pylist | - | — | — | 0.426 | 2,347,417 | — | — | 36.7 |
| polygons | 10,000 | 8192 | engine | - | — | — | 0.041 | 243,902 | — | — | 31.5 |
| polygons | 10,000 | 8192 | pylist | - | — | — | 0.049 | 204,081 | — | — | 34.0 |
| polygons | 100,000 | 8192 | engine | - | — | — | 0.189 | 529,100 | — | — | 39.4 |
| polygons | 100,000 | 8192 | pylist | - | — | — | 0.149 | 671,140 | — | — | 43.2 |
| polygons | 1,000,000 | 8192 | engine | - | — | — | 1.255 | 796,812 | — | — | 49.1 |
| polygons | 1,000,000 | 8192 | pylist | - | — | — | 1.223 | 817,661 | — | — | 53.2 |
| points | 1,000,000 | 2048 | engine | - | — | — | 0.457 | 2,188,183 | — | — | 31.1 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.385 | 2,597,402 | — | — | 34.4 |
| points | 1,000,000 | 16384 | engine | - | — | — | 0.418 | 2,392,344 | — | — | 35.2 |
| points | 1,000,000 | 65536 | engine | - | — | — | 0.376 | 2,659,574 | — | — | 35.2 |

## Etapa de motor (sin QGIS) — `result_engine_duckdb1.5.6.json`

| datos | filas | lote | etapa | estrategia | tramo | fechas | total s | filas/s | hilo principal s | bloqueo máx ms | ΔRSS MB |
|---|---:|---:|---|---|---:|---|---:|---:|---:|---:|---:|
| tabular | 10,000 | 8192 | engine | - | — | — | 0.048 | 208,333 | — | — | 30.0 |
| tabular | 10,000 | 8192 | pylist | - | — | — | 0.05 | 200,000 | — | — | 33.1 |
| tabular | 100,000 | 8192 | engine | - | — | — | 0.042 | 2,380,952 | — | — | 30.4 |
| tabular | 100,000 | 8192 | pylist | - | — | — | 0.314 | 318,471 | — | — | 36.9 |
| tabular | 1,000,000 | 8192 | engine | - | — | — | 0.198 | 5,050,505 | — | — | 31.0 |
| tabular | 1,000,000 | 8192 | pylist | - | — | — | 1.861 | 537,345 | — | — | 37.6 |
| points | 10,000 | 8192 | engine | - | — | — | 0.035 | 285,714 | — | — | 29.3 |
| points | 10,000 | 8192 | pylist | - | — | — | 0.035 | 285,714 | — | — | 30.9 |
| points | 100,000 | 8192 | engine | - | — | — | 0.069 | 1,449,275 | — | — | 31.3 |
| points | 100,000 | 8192 | pylist | - | — | — | 0.083 | 1,204,819 | — | — | 33.8 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.455 | 2,197,802 | — | — | 31.6 |
| points | 1,000,000 | 8192 | pylist | - | — | — | 0.479 | 2,087,682 | — | — | 38.3 |
| polygons | 10,000 | 8192 | engine | - | — | — | 0.052 | 192,307 | — | — | 33.3 |
| polygons | 10,000 | 8192 | pylist | - | — | — | 0.046 | 217,391 | — | — | 35.3 |
| polygons | 100,000 | 8192 | engine | - | — | — | 0.152 | 657,894 | — | — | 38.6 |
| polygons | 100,000 | 8192 | pylist | - | — | — | 0.229 | 436,681 | — | — | 43.2 |
| polygons | 1,000,000 | 8192 | engine | - | — | — | 1.366 | 732,064 | — | — | 42.7 |
| polygons | 1,000,000 | 8192 | pylist | - | — | — | 1.313 | 761,614 | — | — | 43.5 |
| points | 1,000,000 | 2048 | engine | - | — | — | 0.449 | 2,227,171 | — | — | 35.3 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.458 | 2,183,406 | — | — | 35.6 |
| points | 1,000,000 | 16384 | engine | - | — | — | 0.39 | 2,564,102 | — | — | 31.7 |
| points | 1,000,000 | 65536 | engine | - | — | — | 0.486 | 2,057,613 | — | — | 35.5 |

## Etapa de motor (sin QGIS) — `result_engine_duckdb2.0.0.json`

| datos | filas | lote | etapa | estrategia | tramo | fechas | total s | filas/s | hilo principal s | bloqueo máx ms | ΔRSS MB |
|---|---:|---:|---|---|---:|---|---:|---:|---:|---:|---:|
| tabular | 10,000 | 8192 | engine | - | — | — | 0.075 | 133,333 | — | — | 31.9 |
| tabular | 10,000 | 8192 | pylist | - | — | — | 0.07 | 142,857 | — | — | 35.0 |
| tabular | 100,000 | 8192 | engine | - | — | — | 0.045 | 2,222,222 | — | — | 35.9 |
| tabular | 100,000 | 8192 | pylist | - | — | — | 0.203 | 492,610 | — | — | 42.1 |
| tabular | 1,000,000 | 8192 | engine | - | — | — | 0.136 | 7,352,941 | — | — | 37.6 |
| tabular | 1,000,000 | 8192 | pylist | - | — | — | 1.845 | 542,005 | — | — | 43.7 |
| points | 10,000 | 8192 | engine | - | — | — | 0.038 | 263,157 | — | — | 31.4 |
| points | 10,000 | 8192 | pylist | - | — | — | 0.035 | 285,714 | — | — | 32.8 |
| points | 100,000 | 8192 | engine | - | — | — | 0.099 | 1,010,101 | — | — | 34.3 |
| points | 100,000 | 8192 | pylist | - | — | — | 0.058 | 1,724,137 | — | — | 36.7 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.3 | 3,333,333 | — | — | 36.3 |
| points | 1,000,000 | 8192 | pylist | - | — | — | 0.352 | 2,840,909 | — | — | 38.7 |
| polygons | 10,000 | 8192 | engine | - | — | — | 0.045 | 222,222 | — | — | 34.3 |
| polygons | 10,000 | 8192 | pylist | - | — | — | 0.046 | 217,391 | — | — | 36.4 |
| polygons | 100,000 | 8192 | engine | - | — | — | 0.179 | 558,659 | — | — | 44.1 |
| polygons | 100,000 | 8192 | pylist | - | — | — | 0.158 | 632,911 | — | — | 47.3 |
| polygons | 1,000,000 | 8192 | engine | - | — | — | 1.025 | 975,609 | — | — | 48.4 |
| polygons | 1,000,000 | 8192 | pylist | - | — | — | 1.054 | 948,766 | — | — | 57.1 |
| points | 1,000,000 | 2048 | engine | - | — | — | 0.416 | 2,403,846 | — | — | 35.8 |
| points | 1,000,000 | 8192 | engine | - | — | — | 0.294 | 3,401,360 | — | — | 35.9 |
| points | 1,000,000 | 16384 | engine | - | — | — | 0.299 | 3,344,481 | — | — | 38.7 |
| points | 1,000,000 | 65536 | engine | - | — | — | 0.359 | 2,785,515 | — | — | 43.8 |
