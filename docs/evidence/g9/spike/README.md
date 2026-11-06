# Spike G9 (E0b): la pestaña de tabla en Qt Widgets y la «Copia» al guardar el proyecto

**Fecha:** 2026-11-05 · **Entornos:** QGIS 3.44.14 (Qt 5.15.15) y 4.2.3 (Qt 6.11.2), DuckDB 2.0.0, Linux sin
pantalla (contenedor de 2 núcleos). **No es código de GeoDuck**: prueba de viabilidad para ADR-0016 y
workspace-pro-spec §3, §4, §7, §13.

## 1. Aspecto (G9-A, `g9a_tabla.py`)

La pantalla 1 de la maqueta aprobada (`docs/g8/maqueta/1-tabla.dc.html`) hecha con Qt Widgets, tokens de diseño
en un solo diccionario por tema y estilos generados de ellos: barra lateral (Recientes, ★, Bases con filas por
tabla), pestañas, chips de filtro, búsqueda, grilla con el tipo bajo cada columna y número de fila, detalle de
fila, «Datos / Estructura», paginación, «Cargar en QGIS ▾» y el aviso con «Abrir» / «Deshacer».

| | Qt 5 (QGIS 3.44) | Qt 6 (QGIS 4.2) |
|---|---|---|
| Claro | `tabla-claro-qt5.png` | `tabla-claro-qt6.png` |
| Oscuro | `tabla-oscuro-qt5.png` | `tabla-oscuro-qt6.png` |

**Lectura:** Qt Widgets alcanza la maqueta: mismas proporciones, colores, jerarquía y estados (NULL en gris
cursiva, fila elegida, chips, aviso). Diferencias pendientes para E1: la fuente (en Windows, Segoe UI; aquí,
Inter), iconos SVG propios en lugar de caracteres (▦, ◫, ◈), y el ajuste fino de anchos de columna.

Hallazgos técnicos:
- F-123: con una hoja de estilos, Qt **no propaga** la fuente del contenedor a sus hijos (vuelven a la de la
  aplicación); y la hoja de Qt 5 no admite varias familias. El sistema de diseño fija la fuente en la regla
  general (`QWidget { font-family; font-size; color }`), con la primera familia instalada de su lista.
- `QFontDatabase` es estático en Qt 6 y necesita instancia en Qt 5.

## 2. Rendimiento (tabla de 1 millón de filas, filtro de dos chips y orden)

| Medida | Qt 5 | Qt 6 | Objetivo (§13) |
|---|---|---|---|
| Primera página (100 filas) | 8–23 ms | 14–18 ms | < 500 ms |
| Conteo con filtro | 7–10 ms | 7 ms | sin bloquear |
| Página siguiente (media de 10) | 6–9 ms | 5–6 ms | — |
| Pantalla completa construida y pintada | 154–294 ms | 183–263 ms | — |
| Paso de desplazamiento pintado | 5–6 ms | 4–5 ms | fluido |

Muy por debajo de los objetivos. En GeoDuck la lectura pasará por el worker (una operación por página), que
añade poco (G3: < 1 ms por operación).

## 3. «Copia» al guardar y reabrir el proyecto (G9-B, `g9b_copia_proyecto.py`, `copia-proyecto.txt`)

| | Antes de guardar | Proyecto reabierto |
|---|---|---|
| Copia en memoria (`memory`) | 100 entidades | capa válida pero **vacía** (QGIS avisa al cerrar de que es temporal) |
| Copia rápida (GeoPackage `/vsimem`) | 100 entidades | **capa rota** (el archivo en memoria ya no existe; QGIS ofrece «Manejar capas no disponibles») |

Ninguna de las dos sobrevive a guardar y reabrir el proyecto: son copias de la sesión. La rápida, además, no
la marca QGIS como temporal, así que no avisa al cerrar y al reabrir aparece rota.

**Propuesta para la «Copia» unificada (decisión del propietario en este E0b):** al guardar el proyecto con alguna
«Copia», GeoDuck lo dice y ofrece en un clic **«Guardar las copias junto al proyecto»** (un GeoPackage al lado
del `.qgz`; la capa pasa a leer ese archivo y sobrevive). Sin elegirlo, al reabrir la capa se muestra como no
disponible con su motivo, no rota sin explicación.
