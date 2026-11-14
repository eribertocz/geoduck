QGIS 4.2.3 · Qt 6.11.2 · DuckDB 2.0.0 · 2 núcleos · 1,000,000 filas · 3 repeticiones · RAM pico 1430.1 MB

| Operación | Mediana | Máximo | Pausa máx. de la interfaz | Pausa p95 |
|---|---|---|---|---|
| Consulta: primera página (10 columnas) | 39 ms | 46 ms | 10 ms | 10 ms |
| Consulta: agregado por zona | 9 ms | 11 ms | 6 ms | 6 ms |
| Cargar en QGIS · Copia (puntos) | 2,243 ms | 2,567 ms | 16 ms | 5 ms |
| Cargar en QGIS · Conectada (puntos) | 104 ms | 126 ms | 6 ms | 6 ms |
| Capa de QGIS → DuckDB (por QGIS, puntos) | 4,635 ms | 4,744 ms | 53 ms | 5 ms |
| Archivo Parquet → DuckDB (por DuckDB) | 50 ms | 50 ms | 6 ms | 6 ms |
| Exportar ▾ · parquet | 246 ms | 247 ms | 12 ms | 9 ms |
| Exportar ▾ · csv | 339 ms | 381 ms | 17 ms | 7 ms |
| Cancelar · consulta pesada | 6 ms | 7 ms | 5 ms | 5 ms |
| Cancelar · exportar | 32 ms | 40 ms | 5 ms | 5 ms |
| Cancelar · cargar en QGIS (Copia) | 65 ms | 66 ms | 5 ms | 5 ms |
| Cancelar · capa de QGIS → DuckDB | 51 ms | 52 ms | 5 ms | 5 ms |
| Cancelar · archivo → DuckDB | 29 ms | 29 ms | 5 ms | 5 ms |
| Cancelar · guardar el resultado de una consulta | 6 ms | 8 ms | 5 ms | 5 ms |
