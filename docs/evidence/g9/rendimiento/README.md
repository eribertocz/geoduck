# G9 · Rendimiento de Workspace Pro (AT-WSP-012; workspace-pro-spec §13)

**Fecha:** 2026-11-06 · **Herramienta:** [`tools/pro_bench.py`](../../../../tools/pro_bench.py) (5 repeticiones) ·
**Entornos:** QGIS 3.44.14 (Qt 5.15.15) y 4.2.3 (Qt 6.11.2), DuckDB 2.0.0, Linux sin pantalla, contenedor de
2 núcleos (más lento que la máquina de referencia de `benchmarks.md`).

Con la interfaz real: un `ProWorkspace` con su sesión DuckDB (en memoria), una tabla de 1 millón de filas y
1 000 objetos más en el catálogo, y un `ProController` para alternar ventana y panel. «Pausa máx. de la
interfaz» es el mayor hueco de un temporizador de 5 ms del hilo principal mientras dura la acción: lo que el
usuario notaría como congelamiento.

## QGIS 3.44 (Qt 5)

| Medida (Qt 5.15.15, 5 repeticiones) | Mediana | Máximo | Pausa máx. de la interfaz |
|---|---|---|---|
| Abrir 1 millón de filas: primera página | 45.4 ms | 68.1 ms | 217 ms |
| Ordenar por una columna | 47.9 ms | 58.5 ms | 31 ms |
| Filtro: primer chip | 57.0 ms | 58.9 ms | 12 ms |
| Filtro: segundo chip | 52.2 ms | 57.2 ms | 44 ms |
| Buscar | 56.3 ms | 64.5 ms | 41 ms |
| Página siguiente | 51.5 ms | 52.8 ms | 36 ms |
| Ctrl+K: una tecla (1 000 objetos) | 6.1 ms | 36.4 ms | — |
| Alternar ventana ↔ panel | 130.3 ms | 165.1 ms | — |

## QGIS 4.2 (Qt 6)

| Medida (Qt 6.11.2, 5 repeticiones) | Mediana | Máximo | Pausa máx. de la interfaz |
|---|---|---|---|
| Abrir 1 millón de filas: primera página | 34.6 ms | 43.5 ms | 141 ms |
| Ordenar por una columna | 37.1 ms | 41.7 ms | 24 ms |
| Filtro: primer chip | 47.3 ms | 52.5 ms | 32 ms |
| Filtro: segundo chip | 40.7 ms | 50.3 ms | 38 ms |
| Buscar | 48.4 ms | 52.4 ms | 30 ms |
| Página siguiente | 44.0 ms | 67.6 ms | 9 ms |
| Ctrl+K: una tecla (1 000 objetos) | 5.5 ms | 15.7 ms | — |
| Alternar ventana ↔ panel | 142.1 ms | 149.3 ms | — |

## Frente a los objetivos (§13)

| Objetivo | Resultado |
|---|---|
| 1 millón de filas: primera página en menos de 0,5 s | **Cumple**: 35–68 ms |
| Desplazar, ordenar y filtrar sin congelar la interfaz | **Cumple**: cada acción 37–65 ms; la interfaz nunca se detiene más de 44 ms (la lectura va al worker) |
| Ctrl+K con 1 000 objetos: menos de 50 ms por tecla | **Cumple**: mediana 6 ms; máximo 36 ms |
| Alternar ventana y panel en menos de 0,2 s | **Cumple**: 130–165 ms |

La única pausa larga es al **abrir** la pestaña (140–220 ms): construir y pintar la pestaña de tabla la
primera vez, en el hilo principal, como cualquier ventana de Qt; la lectura de datos no la bloquea. Queda por
debajo de lo que el usuario percibe como espera al abrir algo y se anota para G10 (Performance).
