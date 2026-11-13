# Spike #140: ¿cómo sacar los bucles de Python de la conversión QGIS ↔ DuckDB? (2026-11-12)

Regla del propietario: **primero evitar los bucles; si no se puede, optimizarlos**, y decidir con números.

Equipo: el contenedor Linux de desarrollo (**2 núcleos**), QGIS 4.2.3, DuckDB 2.0.0, 1 000 000 de puntos (id
entero, valor real, nombre texto, EPSG:32719), mediana de 3 repeticiones. Sirve para comparar los caminos
entre sí, no para comparar equipos.

## 1. Solo la conversión (`tools/perf/spike_140.py`, `spike140-2.0.0.json`)

| QGIS → DuckDB | s | | DuckDB → QGIS (Copia en memoria) | s |
|---|---|---|---|---|
| bucle de hoy (`_value` por valor) | 3,89 | | bucle de hoy (`QgsFeature` uno por uno) | 5,35 |
| bucle afinado (columnas, sin `_value`) | 2,81 | | `COPY … parquet` + `materialize()` (C++) | 2,60 |
| escritor de QGIS (C++) → GeoParquet + `read_parquet` | 2,64 | | `COPY … FlatGeobuf` + `materialize()` | 4,81 |
| escritor de QGIS → Arrow IPC + PyArrow | 2,25 | | | |
| escritor de QGIS → FlatGeobuf + `ST_Read` | 4,98 | | | |

## 2. De punta a punta, como lo usa GeoDuck

El camino general ya trabaja en paralelo: la tarea de QGIS lee y arma los lotes mientras el worker de DuckDB
escribe el lote anterior.

- **Capa en memoria de QGIS → DuckDB** (`LayerImport`, 1 M de puntos): **2,95 s** con el bucle de hoy y **3,00 s**
  con el bucle afinado. **Sin mejora:** el cuello de botella es la lectura de entidades de QGIS
  (`getFeatures`, `asWkb`), no la conversión en Python.
- **Cargar en QGIS · Copia** (línea base de G10): **2,9 s**, con la interfaz respondiendo (pausa máxima de unos
  100 ms). `materialize()` tarda unos 2,6 s, pero corre en el hilo principal: bloquearía la interfaz unos
  1,9 s, salvo que se haga en otro hilo.

## Decisión

1. **Evitar QGIS cuando hay un archivo: sí** (es la gran ganancia). El camino directo, en el que DuckDB lee el
   archivo de la capa, ya daba 23× en GeoPackage. Ahora cubre también **Parquet, Arrow, CSV y JSON**, sin
   `spatial`, y el GeoParquet sin `pyarrow.parquet` (F-130).
2. **Capas que solo QGIS sabe leer** (memoria, PostGIS, WFS): **no se adopta** el escritor a archivo temporal.
   Gana como mucho un 25 %, necesita el controlador Arrow o Parquet de GDAL (que falta en algunos QGIS, por
   ejemplo el 3.34 de conda-forge), escribe y borra un archivo del tamaño de la capa, y agrega una conversión
   de tipos más (OGR). El bucle afinado tampoco se adopta: 0 % de punta a punta.
3. **Copia hacia QGIS:** **no se adopta** `materialize()`. Daría como mucho un 10 % y, en el hilo principal,
   congelaría la interfaz. Hecho en otro hilo, quedaría pendiente de un spike propio, con las familias de
   geometría y la reproyección.

Para medir de nuevo: `QT_QPA_PLATFORM=offscreen python tools/perf/spike_140.py --rows 1000000 --repeat 3`.
