QGIS 4.2.3 · Qt 6.11.2 · DuckDB 2.0.0 · 2 núcleos · 1,000,000 filas · 3 repeticiones · RAM pico 1699.9 MB

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
