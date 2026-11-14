QGIS 4.2.3 · Qt 6.11.2 · DuckDB 1.5.0 · 2 núcleos · 1,000,000 filas · 3 repeticiones · RAM pico 1274.4 MB

| Operación | Mediana | Máximo | Pausa máx. de la interfaz | Pausa p95 |
|---|---|---|---|---|
| Consulta: primera página (10 columnas) | 8 ms | 8 ms | 6 ms | 6 ms |
| Consulta: agregado por zona | 6 ms | 11 ms | 5 ms | 5 ms |
| Cargar en QGIS · Copia (puntos) | 2,285 ms | 2,432 ms | 9 ms | 6 ms |
| Cargar en QGIS · Conectada (puntos) | 84 ms | 85 ms | 7 ms | 7 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 5,004 ms | 5,504 ms | 61 ms | 7 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 50 ms | 98 ms | 6 ms | 6 ms |
| Exportar ▾ · parquet | 199 ms | 233 ms | 12 ms | 10 ms |
| Exportar ▾ · csv | 273 ms | 313 ms | 17 ms | 10 ms |
| Cancelar · consulta pesada | 6 ms | 6 ms | 0 ms | 0 ms |
| Cancelar · exportar | 18 ms | 32 ms | 7 ms | 7 ms |
| Cancelar · cargar en QGIS (Copia) | 37 ms | 56 ms | 5 ms | 5 ms |
| Cancelar · capa de QGIS → DuckDB | 45 ms | 48 ms | 6 ms | 6 ms |
| Cancelar · archivo → DuckDB | 29 ms | 29 ms | 5 ms | 5 ms |
| Cancelar · guardar el resultado de una consulta | 7 ms | 8 ms | 6 ms | 6 ms |
