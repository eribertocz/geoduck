# G10 · `v0.11.0a1` Rendimiento — plan

**Estado:** Aprobado por el propietario (2026-11-12). **Requisitos:** GD-PERF-001..010 (detallan GD-BRD-003 y
GD-QA-001). **Contrato:** `spec/specs/performance-spec.md`; protocolo `spec/qa/benchmarks.md`.

**Gate:** AT-PERF-001..010 en la matriz de CI (QGIS 3.34, 3.40, 3.44, 4.2 × DuckDB 1.5.0, 2.0.0); línea base
publicada; estrés de 1 h sin cierres; guía manual en Windows con los números del equipo del propietario;
regresiones G0–G9. Tag y release `v0.11.0a1` solo los hace el propietario.

## 1. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC (performance-spec), requisitos GD-PERF, roadmap, este plan | `spec_sync --check` |
| **E0b** | Spike G10-A: cancelación por tipo de operación en DuckDB 1.5 y 2.0; bloqueos de la interfaz y RAM pico con la interfaz real; casos que no responden | Medidas en `docs/evidence/g10/spike/` |
| **E1** | Banco de medidas `tools/perf/` (T1–T7) y línea base; trabajo informativo de la CI | AT-PERF-001 |
| **E2** | Cancelación robusta: «Cancelar» en todo lo largo, puntos de control, sin restos | AT-PERF-002 |
| **E2b** | Resultados bajo demanda: una ejecución, tabla temporal, scroll continuo (maqueta antes), ordenar, exportar y cargar sin repetir | AT-PERF-007 |
| **E2c** | Tablas: scroll continuo, páginas por posición, total estimado | AT-PERF-008 |
| **E3** | Memoria: presupuesto por transferencia, aviso con alternativa, `temp_directory` de la sesión, «Diagnóstico» | AT-PERF-003 |
| **E4** | Interfaz sin bloqueos: lo pesado fuera del hilo de la interfaz, primera apertura de tabla ≤ 100 ms, F-129 | AT-PERF-004 |
| **E4b** | «Copia» por DuckDB directo, «Conectada» con caché y cancelación, selección por DuckDB, progreso real; catálogo por partes | AT-PERF-009, 010 |
| **E5** | Estrés de 1 h y datos rotos (T7) | AT-PERF-005 |
| **E6** | Aceptación: `docs/performance.md`, guía de Windows con números, versión `0.11.0a1` | AT-PERF-006; gate |

## 2. Decisiones del propietario (2026-11-12)

| | Decisión |
|---|---|
| Plan | Aprobado; optimizar «de primer nivel» |
| Metas | Las propuestas: cancelar p95 ≤ 1 s; pausas de la interfaz p95 ≤ 50 ms (máx. 200 ms); copia a QGIS ≤ mitad de la RAM libre con aviso y alternativa; `temp_directory` de GeoDuck; medir también en el Windows del propietario |
| Resultados | Bajo demanda (paginación o scroll), sin llevar todo a la interfaz ni repetir la consulta (performance-spec §8) |

## 3. Avance

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, requisitos, roadmap y plan | Fusionado | #134 |
| E0b Spike G10-A | Fusionado (#135): guardar siempre el resultado no conviene (diseño adaptativo, SPEC §8); `rowid` escala mejor que `OFFSET`; cancelar ≤ 0,7 s en el peor caso medido; F-133 (DuckDB 1.5 deja a medias un `COPY` cancelado). `docs/evidence/g10/spike/` | — |
| E1 Banco de medidas y línea base | Fusionado (#136): `tools/perf/bench.py` (complemento real: consulta, cargar Copia/Conectada, capa y archivo → DuckDB, exportar, cancelar; tiempo, pausas de la interfaz y RAM pico → JSON y Markdown), línea base en `docs/evidence/g10/base/` (QGIS 3.44 y 4.2 × DuckDB 2.0), trabajo informativo en la CI. Decisión del propietario (2026-11-12, «tú decide»): resultados adaptativos. En la CI (4 núcleos, DuckDB 2.0): cancelar una exportación 1,3–2,6 s y pausa de 75 ms en la primera página → E2 | #136 |
| E2 Cancelación robusta (parte 1) | En revisión: causa de la exportación lenta al cancelar = `preserve_insertion_order` (los hilos se esperan): se apaga solo durante una exportación sin `ORDER BY` y se deja como estaba (propietario, 2026-11-12) → 14–77 ms; primera página: detalle de fila diferido y sin reconstruir, ancho de columnas por muestra de 25 filas, caché por columna → pausa de hasta 73 ms a ≤ 28 ms (local) | — |
| E2c Desplazamiento continuo en tablas y en la grilla (#170) | Fusionado (#179): sin ‹ ›; barra propia (mil millones de filas), bloques de 100 por `rowid` o `OFFSET`, total estimado | — |
| E2b Resultado guardado de una consulta cara (#170) | Fusionado (#180): se guarda una vez en `temp` (> 300 ms), «Preparando… N % · Cancelar», todo se lee de ahí; el tope de disco va con E3 (#172, `max_temp_directory_size`) | — |
| E2 (resto) «Cancelar» en todo lo largo (#171, #157) | En revisión: p95 ≤ 66 ms en todo con 1 millón de filas (1.5 y 2.0), sin restos; BEGIN dentro del bloque que revierte; leer archivos se cancela al cerrar | — |
| E3 Memoria (#172) | Fusionado (#185): presupuesto de la Copia (mitad de la RAM libre, estimado tras 10 000 filas), ventana «no cabe como Copia» con «Cargar como Conectada», `temp_directory` propio por sesión con tope de disco, «Diagnóstico» | — |
| Interfaz sin «DuckDB» (#184) | Fusionado (#186): textos aprobados (2026-11-14); solo «Acerca de» y los componentes de «Diagnóstico»; prueba que lo comprueba | — |
| Capas Conectadas al cerrar su base (#183) | Fusionado (#188): nunca huérfanas; no disponibles nativas de QGIS, guardar una base en memoria como archivo, abrir las bases al abrir un proyecto, identidad del archivo, tablas temporales solo Copia | — |
| Errores de DuckDB tal cual (#189) | En revisión: lo que GeoDuck no reconoce, con el texto de DuckDB como título; abrir y cerrar bases y los errores del motor, con el mensaje completo | — |
