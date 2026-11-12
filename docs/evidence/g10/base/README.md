# Línea base de G10 (2026-11-12)

`tools/perf/bench.py --rows 1000000 --repeat 3` con el complemento real, sin pantalla, en el contenedor Linux de
desarrollo (**2 núcleos**). Vale para comparar cambios **en este mismo equipo** (regresión > 20 %: investigar);
no se compara con otros equipos. La CI guarda sus propias medidas en cada corrida (artefacto `perf/`), y la del
Windows del propietario se añade con la guía manual (E6).

## QGIS 3.44.14 · Qt 5.15.15 · DuckDB 2.0.0 · 2 núcleos · 1,000,000 filas · 3 repeticiones · RAM pico 1637.8 MB

| Operación | Mediana | Máximo | Pausa máx. de la interfaz | Pausa p95 |
|---|---|---|---|---|
| Consulta: primera página (10 columnas) | 47 ms | 63 ms | 11 ms | 11 ms |
| Consulta: agregado por zona | 11 ms | 11 ms | 5 ms | 5 ms |
| Cargar en QGIS · Copia (puntos) | 3,043 ms | 3,072 ms | 55 ms | 6 ms |
| Cargar en QGIS · Conectada (puntos) | 124 ms | 127 ms | 6 ms | 6 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 6,496 ms | 6,736 ms | 48 ms | 6 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 51 ms | 98 ms | 8 ms | 8 ms |
| Exportar ▾ · parquet | 290 ms | 315 ms | 11 ms | 6 ms |
| Exportar ▾ · csv | 440 ms | 442 ms | 15 ms | 8 ms |
| Cancelar · consulta pesada | 6 ms | 6 ms | 0 ms | 0 ms |
| Cancelar · exportar | 9 ms | 10 ms | 5 ms | 5 ms |
| Cancelar · cargar en QGIS (Copia) | 57 ms | 110 ms | 6 ms | 5 ms |

## QGIS 4.2.3 · Qt 6.11.2 · DuckDB 2.0.0 · 2 núcleos · 1,000,000 filas · 3 repeticiones · RAM pico 1699.9 MB

| Operación | Mediana | Máximo | Pausa máx. de la interfaz | Pausa p95 |
|---|---|---|---|---|
| Consulta: primera página (10 columnas) | 54 ms | 57 ms | 11 ms | 11 ms |
| Consulta: agregado por zona | 12 ms | 12 ms | 6 ms | 6 ms |
| Cargar en QGIS · Copia (puntos) | 2,889 ms | 3,374 ms | 103 ms | 6 ms |
| Cargar en QGIS · Conectada (puntos) | 124 ms | 125 ms | 8 ms | 5 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 6,128 ms | 6,363 ms | 58 ms | 5 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 98 ms | 99 ms | 8 ms | 8 ms |
| Exportar ▾ · parquet | 308 ms | 335 ms | 9 ms | 6 ms |
| Exportar ▾ · csv | 389 ms | 430 ms | 10 ms | 6 ms |
| Cancelar · consulta pesada | 9 ms | 11 ms | 5 ms | 5 ms |
| Cancelar · exportar | 9 ms | 13 ms | 5 ms | 5 ms |
| Cancelar · cargar en QGIS (Copia) | 65 ms | 65 ms | 5 ms | 5 ms |

## Lectura

- **Metas ya cumplidas aquí:** pausas de la interfaz p95 5–6 ms (meta ≤ 50 ms); cancelar 6–110 ms (meta ≤ 1 s), con
  la operación todavía en curso al cancelar (`seguia_en_curso` en el JSON).
- **Pausa máxima > 50 ms:** «Cargar en QGIS · Copia» (55–103 ms, al publicar la capa) y «Capa de QGIS → DuckDB»
  (48–58 ms). Dentro del máximo de 200 ms; se afinan en E4.
- **Lo más lento, con mucho:** lo que pasa fila por fila por QGIS: «Capa de QGIS → DuckDB» 6,1–6,5 s y «Copia»
  2,9–3,0 s por millón de puntos, contra 0,1 s de un Parquet leído por DuckDB. Ahí está la ganancia de E4b
  («Copia» escrita por DuckDB directo) y de #131 (capas de archivo por `ST_Read`).
- **Memoria:** pico del proceso 1,6–1,7 GB con 1 millón de filas y las tres repeticiones; el presupuesto es E3.
- **Falta en el banco** (se añade con cada entrega): T4–T7, capa de archivo por DuckDB con `spatial`, dibujar y
  desplazar una Conectada, `DETACH`, DuckDB 1.5.
