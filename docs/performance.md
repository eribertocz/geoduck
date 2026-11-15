# Rendimiento medido

Números medidos con el banco [`tools/perf/bench.py`](../tools/perf/bench.py) (performance-spec §2 y §7): el
complemento real, sin pantalla, con **1 000 000 de filas** (tabla T2 y puntos T3 de `spec/qa/benchmarks.md`,
semilla fija) y 3 repeticiones por corrida. **Solo se comparan números del mismo equipo.**

- **Mediana:** la mediana de las corridas (cada corrida da la mediana de sus 3 repeticiones).
- **Máximo:** la repetición más lenta de todas.
- **Pausa máx. de la interfaz:** el hilo de QGIS más tiempo sin responder durante la operación (lo que
  se notaría como un tirón). Ninguna pasa de 0,2 s.

Las demás versiones de QGIS (3.34 y 3.40) pasan las mismas pruebas en la CI; el banco corre en 3.44 y 4.2.

## QGIS 3.44.14 · Qt 5.15.15 · DuckDB 2.0.0 · CI (GitHub, Ubuntu 24.04, 4 núcleos) · 6 corridas

| Operación | Mediana | Máximo | Pausa máx. de la interfaz |
|---|---|---|---|
| Consulta: primera página (10 columnas) | 32 ms | 43 ms | 7 ms |
| Consulta: agregado por zona | 6 ms | 13 ms | 5 ms |
| Cargar en QGIS · Copia (puntos) | 1 993 ms | 2 894 ms | 18 ms |
| Cargar en QGIS · Conectada (puntos) | 83 ms | 114 ms | 7 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 3 701 ms | 6 028 ms | 49 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 50 ms | 50 ms | 8 ms |
| Exportar ▾ · parquet | 192 ms | 286 ms | 16 ms |
| Exportar ▾ · csv | 409 ms | 646 ms | 16 ms |
| Cancelar · consulta pesada | 4 ms | 5 ms | 0 ms |
| Cancelar · exportar | 87 ms | 194 ms | 7 ms |
| Cancelar · cargar en QGIS (Copia) | 25 ms | 65 ms | 5 ms |
| Cancelar · capa de QGIS → DuckDB | 48 ms | 53 ms | 5 ms |
| Cancelar · archivo → DuckDB | 29 ms | 33 ms | 5 ms |
| Cancelar · guardar el resultado de una consulta | 12 ms | 25 ms | 5 ms |

## QGIS 4.2.3 · Qt 6.11.2 · DuckDB 2.0.0 · CI (GitHub, Ubuntu 24.04, 4 núcleos) · 7 corridas

| Operación | Mediana | Máximo | Pausa máx. de la interfaz |
|---|---|---|---|
| Consulta: primera página (10 columnas) | 33 ms | 43 ms | 7 ms |
| Consulta: agregado por zona | 6 ms | 8 ms | 5 ms |
| Cargar en QGIS · Copia (puntos) | 2 046 ms | 2 927 ms | 53 ms |
| Cargar en QGIS · Conectada (puntos) | 91 ms | 114 ms | 7 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 3 854 ms | 5 732 ms | 47 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 50 ms | 50 ms | 8 ms |
| Exportar ▾ · parquet | 151 ms | 261 ms | 14 ms |
| Exportar ▾ · csv | 287 ms | 614 ms | 17 ms |
| Cancelar · consulta pesada | 4 ms | 13 ms | 8 ms |
| Cancelar · exportar | 40 ms | 168 ms | 6 ms |
| Cancelar · cargar en QGIS (Copia) | 39 ms | 65 ms | 5 ms |
| Cancelar · capa de QGIS → DuckDB | 49 ms | 58 ms | 5 ms |
| Cancelar · archivo → DuckDB | 29 ms | 33 ms | 5 ms |
| Cancelar · guardar el resultado de una consulta | 10 ms | 15 ms | 5 ms |

## QGIS 3.44.14 · Qt 5.15.15 · DuckDB 1.5.4 · CI (GitHub, Ubuntu 24.04, 4 núcleos) · 2 corridas

| Operación | Mediana | Máximo | Pausa máx. de la interfaz |
|---|---|---|---|
| Consulta: primera página (10 columnas) | 7 ms | 14 ms | 5 ms |
| Consulta: agregado por zona | 6 ms | 8 ms | 5 ms |
| Cargar en QGIS · Copia (puntos) | 2 316 ms | 2 800 ms | 14 ms |
| Cargar en QGIS · Conectada (puntos) | 82 ms | 119 ms | 7 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 4 712 ms | 5 914 ms | 37 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 50 ms | 50 ms | 5 ms |
| Exportar ▾ · parquet | 136 ms | 168 ms | 15 ms |
| Exportar ▾ · csv | 238 ms | 297 ms | 17 ms |
| Cancelar · consulta pesada | 4 ms | 5 ms | 0 ms |
| Cancelar · exportar | 34 ms | 39 ms | 6 ms |
| Cancelar · cargar en QGIS (Copia) | 50 ms | 65 ms | 5 ms |
| Cancelar · capa de QGIS → DuckDB | 48 ms | 49 ms | 5 ms |
| Cancelar · archivo → DuckDB | 30 ms | 30 ms | 5 ms |
| Cancelar · guardar el resultado de una consulta | 7 ms | 13 ms | 5 ms |

## QGIS 4.2.3 · Qt 6.11.2 · DuckDB 1.5.4 · CI (GitHub, Ubuntu 24.04, 4 núcleos) · 2 corridas

| Operación | Mediana | Máximo | Pausa máx. de la interfaz |
|---|---|---|---|
| Consulta: primera página (10 columnas) | 6 ms | 11 ms | 5 ms |
| Consulta: agregado por zona | 6 ms | 6 ms | 0 ms |
| Cargar en QGIS · Copia (puntos) | 2 470 ms | 2 924 ms | 14 ms |
| Cargar en QGIS · Conectada (puntos) | 82 ms | 119 ms | 7 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 4 670 ms | 5 799 ms | 44 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 50 ms | 50 ms | 6 ms |
| Exportar ▾ · parquet | 138 ms | 156 ms | 14 ms |
| Exportar ▾ · csv | 242 ms | 292 ms | 18 ms |
| Cancelar · consulta pesada | 4 ms | 9 ms | 5 ms |
| Cancelar · exportar | 30 ms | 44 ms | 6 ms |
| Cancelar · cargar en QGIS (Copia) | 46 ms | 65 ms | 5 ms |
| Cancelar · capa de QGIS → DuckDB | 46 ms | 48 ms | 5 ms |
| Cancelar · archivo → DuckDB | 30 ms | 30 ms | 5 ms |
| Cancelar · guardar el resultado de una consulta | 6 ms | 10 ms | 5 ms |

## QGIS 4.2.3 · Qt 6.11.2 · DuckDB 2.0.0 · contenedor Linux de desarrollo (2 núcleos) · 4 corridas

| Operación | Mediana | Máximo | Pausa máx. de la interfaz |
|---|---|---|---|
| Consulta: primera página (10 columnas) | 61 ms | 113 ms | 43 ms |
| Consulta: agregado por zona | 11 ms | 16 ms | 6 ms |
| Cargar en QGIS · Copia (puntos) | 2 494 ms | 2 902 ms | 200 ms |
| Cargar en QGIS · Conectada (puntos) | 123 ms | 157 ms | 7 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 5 016 ms | 6 070 ms | 87 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 50 ms | 100 ms | 10 ms |
| Exportar ▾ · parquet | 283 ms | 325 ms | 23 ms |
| Exportar ▾ · csv | 365 ms | 569 ms | 17 ms |
| Cancelar · consulta pesada | 6 ms | 9 ms | 6 ms |
| Cancelar · exportar | 36 ms | 57 ms | 8 ms |
| Cancelar · cargar en QGIS (Copia) | 53 ms | 102 ms | 7 ms |
| Cancelar · capa de QGIS → DuckDB | 48 ms | 54 ms | 5 ms |
| Cancelar · archivo → DuckDB | 29 ms | 30 ms | 5 ms |
| Cancelar · guardar el resultado de una consulta | 10 ms | 15 ms | 5 ms |

## Windows (equipo del propietario)

Pendiente: se mide con la guía manual [`docs/certification/performance-windows.md`](certification/performance-windows.md)
y se agrega aquí sin editar los números.

## Otras medidas

- **Estrés de 1 hora** (#175, [`docs/evidence/g10/175/`](evidence/g10/175/README.md)): QGIS 3.34, 3.44 y 4.2 con
  DuckDB 2.0, 4 446 vueltas sin un fallo; la RAM crece entre +0,6 % y +3,5 % desde el minuto 10.
- **Índice espacial** (#154, [`docs/evidence/g10/154/`](evidence/g10/154/README.md)): con 10 millones de puntos,
  una vista cercana de una capa Conectada pasa de 233 ms a 26 ms.
- **Línea base de G10** (2026-11-12, [`docs/evidence/g10/base/`](evidence/g10/base/README.md)), antes de las
  mejoras de G10.

## Regresiones

En cada PR, la CI corre el banco de la versión nueva y el de la base en el **mismo** runner, en rondas
alternadas, y falla si una operación tarda más del 20 % **y** más de 50 ms que en la base
([`tools/perf/compare.py`](../tools/perf/compare.py)). No se compara con estos números guardados: los runners de
la CI varían entre 30 % y 180 % de una corrida a otra.
