# G4 · `v0.5.0a1` Spatial Confidence — plan

**Estado:** En curso (SPEC aprobada por el propietario, 2026-11-02).
**Requisitos:** GD-SPA-001..004 (IDs originales de product-spec). **Contrato:** `spec/specs/spatial-spec.md`;
`qgis-bridge-spec.md` §5.1, §7, §9; `ui-ux-spec.md` §2; propuesta C4 y pruebas AX; ADR-0008, ADR-0011, ADR-0012.

**Gate:** AT-SPA-001..004 verdes en la matriz de CI (QGIS 3.34, 3.40, 3.44, 4.2 × DuckDB 1.5.0, 2.0.0),
contratos de G3 intactos (AT-BRD-001..012 siguen pasando), C4 y ADR-0011 demostrados por pruebas (AX-1..AX-5),
ninguna pérdida silenciosa ni entrega parcial. Evidencia manual Windows de G4 registrada (no sustituye #10).
El cierre de G4 no autoriza `v0.5.0a1`: tag y release los decide el propietario.

## 1. Decisiones del propietario (2026-11-02)

| | Decisión | Dónde |
|---|---|---|
| D1 | Selector múltiple; una capa por columna marcada; entrega atómica; también en Conectada | spatial-spec §3, §7 |
| D2 | Diagnóstico bajo demanda; reparación explícita en una copia (QGIS/GEOS), sin tocar el origen | §9 |
| D3 | `spatial` nunca se instala ni carga sola; «Activar spatial…» con consentimiento de `LOAD` y, aparte, de `INSTALL`, válido para la sesión; ninguna función de G4 la necesita | §10 |
| D4 | Reproyección con QGIS/PROJ solo en Memoria e Instantánea («Reproyectar a…»); la Conectada reproyecta al vuelo; ejes según C4 (no se toca `geometry_always_xy`) | §4 |
| D5 | Conectada: `Unknown` por defecto, «Separar por tipo» opcional con filtro empujado; copias: una capa por familia (opción activada) o error | §6 |
| 8 | Columnas `BLOB` (WKB) y `VARCHAR` (WKT) como geometría solo por selección explícita; sin inferencia ni cambios en el origen | §2.2, §5 |
| 9 | Sin movimiento de entidades entre capas al editar: QGIS no admite otra familia en una capa de tipo fijo | §6 |

## 2. Entregas (un PR cada una)

| Entrega | Trabajo | Reutiliza (G3) | Requisitos / pruebas |
|---|---|---|---|
| **E0** | SPEC, este plan y spike G4-A reducido (`docs/evidence/g4/spike/`) | — | — |
| **E1** | Multi-geometría: selector múltiple en el diálogo, una capa por columna en las tres modalidades, publicación conjunta y atómica, nombres `<capa> · <columna>`. Columnas `BLOB`/`VARCHAR` «Usar como geometría: WKB/WKT»: conversión `TRY(…)` en la consulta de lectura, ilegibles detectados (copias: error con fila; Conectada: aviso con número) y escritura de vuelta en su formato | Diálogo, `LoadRequest`, lectores Memoria/Instantánea, proveedor (`geom`, `geomformat`) | GD-SPA-001, 002; AT-SPA-001, 002 |
| **E2** | SRC: pruebas AX-1..AX-4 en las tres modalidades; AX-2 (`geometry_always_xy` en diagnóstico y resultados); «Reproyectar a…» en copias (AX-5); «Activar spatial…» con doble consentimiento | `crs_from_field`, diagnóstico, coordinador de sesión | GD-SPA-003; AT-SPA-003 |
| **E3** | Familias y dimensiones: una capa por familia (o error) en Memoria; Instantánea con el mismo criterio; Conectada `Unknown` + «Separar por tipo» (`family=`); tipo con todas las dimensiones Z/M; colecciones | `layer_type_for`, lector Instantánea, proveedor | GD-SPA-004; AT-SPA-004 (mixtas) |
| **E4** | Validez: «Diagnosticar geometrías…» (tarea cancelable, contadores, selección) y «Reparar en una copia…» (`makeValid`, cambios informados) | Menú de capa, `QgsTask` | GD-SPA-004; AT-SPA-004 (validez) |
| **E5** | Aceptación: regresión completa, `docs/g4/acceptance.md`, `docs/certification/spatial.md` (Windows G4), sin funciones nuevas | Matriz CI | Gate |

## 3. Pruebas

- **Motor/unitarias** (sin QGIS): SQL de conversión WKB/WKT y de familia; detección de ilegibles; nombres.
- **QGIS** (`tests/qgis`, 3.34/3.40/3.44/4.2): fixtures pequeños con resultados numéricos (punto de La Paz,
  tolerancias de spatial-spec §8); dos geometrías con CRS distintos; mezcla de familias; Z/M/ZM; colecciones;
  `NULL`, vacías, ilegibles e inválidas; cancelación y error a mitad de una entrega múltiple.
- **Regresión:** toda la suite de G0–G3 en cada entrega. No se repiten los benchmarks de G3.

## 4. Avance

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, plan y spike | En revisión | #70 |
| E1 Multi-geometría y WKB/WKT | En revisión: una capa por columna en las tres modalidades (preparación privada y publicación conjunta), «Usar como geometría» con `TRY(…)` en DuckDB, ilegibles (copias: error con fila; Conectada: aviso), escritura de vuelta en WKB/WKT | #71 |
| E2 SRC y ejes | En revisión: AX-1..AX-5 en las tres modalidades (las de `spatial` se omiten si no está instalada; la CI la instala para las pruebas); `geometry_always_xy` visible en el diagnóstico y en resultados con geometría, nunca modificado; «Reproyectar a…» en copias con QGIS/PROJ; SRC no reconocido conservado en el aviso y preguntado en el diálogo; «Activar spatial…» con consentimiento de `LOAD` y, aparte, de `INSTALL` | #72 |
| E3 Familias y dimensiones | En revisión: Memoria con una capa por familia (o error si se desactiva) y tipo con todas las dimensiones y Multi (F-96, F-97); Instantánea con el mismo criterio; Conectada `Unknown` o «Separar por tipo» con filtro de familia en DuckDB por cabecera WKB; Z/M mixtas con NaN y aviso | #73 |
| E4 Validez y reparación | En revisión: «Diagnosticar geometrías…» en el menú de las capas de GeoDuck (QgsTask cancelable, contadores NULL/vacía/ilegible/inválida/válida, motivos de GEOS, selección); «Reparar en una copia…» con `makeValid` y cambios informados | — |

Hallazgo de E1: cada columna se lee con su propia consulta (una lectura por capa). Para tablas el resultado es el mismo; una consulta no determinista (p. ej. `random()`) puede dar valores distintos en cada capa.
