QGIS 3.44.14 · Qt 5.15.15 · DuckDB 2.0.0 · 2 núcleos · 1,000,000 filas · 3 repeticiones · RAM pico 1637.8 MB

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
