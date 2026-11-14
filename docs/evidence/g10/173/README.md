# G10 · E4 · Interfaz sin bloqueos (#173)

**Fecha:** 2026-11-14. **Equipo:** el contenedor de desarrollo (2 núcleos), QGIS 4.2.3 (Qt 6.11.2) y QGIS 3.34
(Qt 5.15.8) locales, DuckDB 2.0.0. Solo números medidos aquí (benchmarks §6). Metas de performance-spec §5:
pausas del hilo de la interfaz p95 ≤ 50 ms y máximo ≤ 200 ms durante cualquier operación; primera apertura
de una tabla ≤ 100 ms.

## Transferencias (`tools/perf/bench.py --rows 1000000 --repeat 3`, QGIS 4.2)

| Operación | Mediana | Pausa máx. | Pausa p95 |
|---|---|---|---|
| Consulta: primera página (10 columnas) | 44 ms | 7 ms | 7 ms |
| Cargar en QGIS · Copia (puntos) | 2 633 ms | 17 ms | 6 ms |
| Cargar en QGIS · Conectada (puntos) | 105 ms | 6 ms | 6 ms |
| Capa de QGIS → DuckDB (por QGIS) | 4 637 ms | 66 ms | 6 ms |
| Archivo Parquet → DuckDB | 50 ms | 5 ms | 5 ms |
| Exportar · Parquet / CSV | 242 / 434 ms | 19 / 26 ms | 9 / 8 ms |
| Cancelar (todas las operaciones) | ≤ 48 ms | ≤ 8 ms | ≤ 8 ms |

Todo dentro de la meta: p95 ≤ 9 ms, máximo 66 ms.

## Interfaz (`tools/pro_bench.py 5`, tabla de 1 millón de filas y 1 000 objetos en el explorador)

| Medida | QGIS 4.2 antes | QGIS 4.2 después | QGIS 3.34 después |
|---|---|---|---|
| Abrir la tabla: primera página | 27 ms | 20 ms | 21 ms |
| **Pausa máxima al abrir** | **121 ms** | **32 ms** | **37 ms** |
| Ordenar / filtrar / buscar (pausa máx.) | ≤ 14 ms | ≤ 23 ms | ≤ 21 ms |
| Desplazar a la mitad (1 millón de filas) | 46 ms | 55 ms | 48 ms |
| Ctrl+K, una tecla | 4 ms | 6 ms | 5 ms |

**Causa de la pausa al abrir:** abrir una tabla rehacía todo el explorador (1 000 objetos), y cada objeto
volvía a pintar su icono SVG (~45 ms solo en iconos). Ahora abrir no rehace el explorador (ya no muestra
recientes) y cada icono se pinta una vez por nombre, color y tamaño.

## F-129

Dos pruebas de `test_pro_load` fallaban en QGIS 3.34 corridas solas (la Copia quedaba sin la autoridad de su
SRC). Causa: un `QgsSettings` creado por un fixture de las pruebas **antes** que la aplicación de QGIS. En QGIS
real la aplicación siempre existe primero. Arreglo en `tests/qgis/conftest.py`; ahora cada archivo
`tests/qgis/test_pro_*.py` pasa solo en QGIS 3.34.
