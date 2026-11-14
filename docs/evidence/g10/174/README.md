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

# Punto 2 · «Conectada» más rápida (2026-11-14)

1 millón de puntos en una capa Conectada, dibujados a 1200 × 800 (`QgsMapRendererSequentialJob`, 3 veces cada
uno; motor: DuckDB 2.0).

| Vista | QGIS 4.2 antes | QGIS 4.2 después | QGIS 3.34 antes | QGIS 3.34 después |
|---|---|---|---|---|
| Toda la capa (1 millón de puntos) | 4,1–4,6 s | 3,3–3,5 s | 4,8–4,9 s | 3,5–3,7 s |
| Con zoom (≈ 6 000 puntos) | 35 ms | 26 ms | 37 ms | 28 ms |
| Moviendo el mapa | 33–46 ms | 25–27 ms | 38–43 ms | 29–47 ms |

**Dónde se iba el tiempo:** convertir cada fila en Python (`fetchFeature`), no la consulta. Cancelar lo que ya no
se ve ya funcionaba (QGIS corta el dibujo y GeoDuck interrumpe la consulta), y un caché por extensión no
ayudaba: el costo es por fila entregada.

**Qué cambió:** lo que cada fila necesita se resuelve una vez por petición (campos, tipo de la capa, si hay que
reproyectar); la geometría se arma sin una función intermedia; el tipo de cada geometría solo se pregunta si su
cabecera WKB no es la de la capa; la reproyección solo se llama cuando la petición pide otro SRC.

**Punto 1 («Copia» escrita por DuckDB), descartado:** Copia actual 2,6 s; DuckDB con índice espacial 2,8–2,9 s;
sin índice 0,9 s, pero mover el mapa con zoom sería más lento. El índice cuesta lo mismo en los dos caminos.
