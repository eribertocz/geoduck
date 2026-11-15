# #154 — Índice espacial R-tree

## Medición (DuckDB 2.0.0, QGIS 4.2.3, puntos al azar en un archivo `.duckdb`)

`medir_vistas.py N archivo`: una capa Conectada real; cada vista se lee entera con `getFeatures` y un rectángulo,
como al dibujar el mapa (mejor de 3).

| Puntos | Vista | Sin índice | Con índice |
|---|---|---|---|
| 1 000 000 | 10×10 (95 puntos) | 5 ms | 4 ms |
| 1 000 000 | 100×100 (9954) | 60–129 ms | 124–128 ms |
| 10 000 000 | 10×10 (1009) | 233 ms | **26 ms** |
| 10 000 000 | 1000×1000 (2,5 millones) | 16,6 s | 16,5 s |

Crear el índice: 0,2 s con 1 millón, 3,6 s con 10 millones. `EXPLAIN` de la consulta de la capa: `Rtree Index
Scan`. Conclusión: ayuda con tablas grandes y vistas cercanas; con 1 millón DuckDB ya recorre la tabla rápido, y
en una vista grande el tiempo es pasar las geometrías a QGIS.

## Falla de DuckDB 2.0 con R-tree y `rowid`

`rtree_rowid.py`: con un índice R-tree, un filtro espacial junto a `rowid >= n` da
`INTERNAL Error: Attempted to access index -1 within vector of size 3` (con `id >= n`, bien). Las capas
Conectadas de una tabla sin clave piden sus páginas por `rowid`: la segunda página fallaba y la capa quedaba
incompleta (50 000 de 99 569). Arreglo: en `fid=rowid`, `(st_intersects_extent(…) IS TRUE)`, que no usa el
índice (`test_a_view_over_an_rtree_table_reads_every_feature[sin-clave]` falla sin él).

## Falla de DuckDB 1.5.0–1.5.3 al reabrir una base de archivo grande

La CI (DuckDB 1.5.0) la encontró: una base de archivo con 1 000 000 de puntos (varios grupos de filas), al
reabrirse, responde 0 filas a `st_intersects_extent(g, rectángulo)` y a `g && rectángulo`; con `IS TRUE`,
las 60 000 correctas. Pasa sin índice y sin `spatial`; con 100 000 puntos (un grupo) o sin reabrir, no.
Probado por versión: 1.5.0, 1.5.1, 1.5.2 y 1.5.3 fallan; 1.5.4, 1.5.5, 1.5.6 y 2.0.0 no. Primero, con esas
versiones el filtro iba como `(… IS TRUE)` (PR #198); después el propietario fijó el mínimo en **DuckDB 1.5.4**
(2026-11-15) y ese caso se quitó. La prueba `test_a_view_over_a_large_reopened_file_reads_every_feature` queda.

## Interfaz (maqueta `154`, aprobada el 2026-11-14)

`es-indice-aviso.png`, `es-indice-aviso-sin-clave.png`: el aviso antes de crear.
