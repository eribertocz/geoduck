# #171 y #157 · «Cancelar» en todo lo largo (AT-PERF-002)

`tools/perf/bench.py --rows 1000000 --repeat 3`, QGIS 4.2.3 en la máquina de la sesión (sin pantalla), con DuckDB
1.5.0 y 2.0.0. Tiempo desde «Cancelar» hasta que el trabajo se detiene y la sesión vuelve a estar lista (p50 · p95).
Meta: p95 ≤ 1 s.

| Operación (1 millón de filas) | DuckDB 1.5.0 | DuckDB 2.0.0 |
|---|---|---|
| Consulta pesada | 6 · 6 ms | 6 · 7 ms |
| Exportar (Parquet) | 18 · 32 ms | 32 · 40 ms |
| Cargar en QGIS (Copia) | 37 · 56 ms | 65 · 66 ms |
| Capa de QGIS → DuckDB | 45 · 48 ms | 51 · 52 ms |
| Archivo → DuckDB | 29 · 29 ms | 29 · 29 ms |
| Guardar el resultado de una consulta (#170) | 6 · 8 ms | 7 · 8 ms |

Sin restos en ninguna: ni tablas `cancelad*` en DuckDB ni archivos `c_*` o temporales junto al destino (el banco
lo comprueba). Las tablas completas, en `bench-*.md`.

**#157 (causa):** el envío de capas y el guardado de una capa Conectada abrían la transacción con `BEGIN` fuera del
bloque que revierte. Si «Cancelar» caía justo sobre `BEGIN`, DuckDB abría la transacción y avisaba de la
interrupción: nadie la revertía. Ahora `BEGIN` va dentro y el `ROLLBACK` resiste una interrupción tardía (también
en el guardado, que solo lo intentaba una vez). Pruebas que lo fuerzan sin depender de los tiempos:
`test_an_interrupt_that_lands_on_begin_leaves_no_transaction` y
`test_an_interrupt_on_begin_or_rollback_never_leaves_a_transaction` (fallan sin el arreglo). Además, 600 envíos
cancelados en momentos al azar (300 con cada versión) no dejaron ninguna transacción abierta.
