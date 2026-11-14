# G10 · E4b · Catálogo por partes (#174, punto 4)

**Fecha:** 2026-11-14. **Equipo:** contenedor de desarrollo (2 núcleos), DuckDB 2.0.0. Meta (performance-spec
§9, GD-PERF-010): con 10 000 tablas, el explorador ≤ 100 ms al desplegar y Ctrl+K ≤ 50 ms por tecla.

Medido con `tools/pro_bench.py` y 10 000 tablas en una base (`o_00000` … `o_09999`).

| Medida | Antes | Después (QGIS 4.2) | Después (QGIS 3.34) |
|---|---|---|---|
| Rehacer el explorador (base desplegada, 10 000 filas) | 85–131 ms | 49–108 ms* | 58–92 ms |
| Rehacer el explorador con la base plegada | 85–131 ms | ≈ 5 ms | ≈ 5 ms |
| Desplegar una base plegada de 10 000 tablas | — | ≈ 65 ms | ≈ 65 ms |
| Ctrl+K, una tecla (máximo de 7 teclas × 3) | 50–60 ms | 15 ms | 20 ms |

\* Los máximos coinciden con una recolección completa de memoria de Python (generación 2), que corre en todo
el proceso de QGIS y no depende de GeoDuck.

## Qué cambia

- Lo plegado (bases, esquemas y el grupo «Vistas») guarda sus objetos y crea las filas al desplegarse. Buscar,
  revelar desde el SQL (Ctrl+clic) y marcar lo nuevo crean lo que falta.
- Sin búsqueda, rehacer el explorador ya no recorre todas las filas otra vez.
- Cada icono (QIcon) se crea una vez por nombre, color y tamaño.
- Ctrl+K: cada letra más busca solo entre las entradas que ya tenían esas letras en orden (nunca pierde
  resultados) y se queda con las 50 mejores sin ordenar todas las coincidencias.
