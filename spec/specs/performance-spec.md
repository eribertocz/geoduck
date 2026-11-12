# GeoDuck — Rendimiento (G10 · `v0.11.0a1`)

**Estado:** Propuesta (E0), pendiente de aprobación del propietario. **Requisitos:** GD-PERF-001..006, que detallan
GD-BRD-003 (progreso y cancelación sin tocar QGIS desde el worker) y GD-QA-001 (benchmarks sin métricas
fabricadas). **Protocolo de medida:** `spec/qa/benchmarks.md`. **Plan:** `docs/g10/plan.md`.

## 1. Meta y principios

GeoDuck existe para el rendimiento (decisión del propietario, 2026-11-07). G10 lo convierte en garantías medidas:

1. **QGIS nunca se congela** por GeoDuck: el trabajo pesado va en el worker o en tareas; el hilo de la interfaz
   solo pinta y responde.
2. **Todo lo largo se puede cancelar**, rápido, y no deja nada a medias (tabla, archivo ni capa).
3. **La memoria está acotada**: ninguna operación crece sin límite; si no cabe, se dice antes, con una alternativa.
4. **Cada número publicado se midió** (equipo, versiones, repeticiones, mediana y p95). Sin medida, no hay promesa.

## 2. Banco de medidas (GD-PERF-001)

- `tools/perf/`: generadores T1–T7 de `benchmarks.md` (semilla fija, checksums) y un ejecutor que mide cada
  operación de punta a punta con la interfaz real (sin pantalla) y escribe JSON en `docs/evidence/g10/`.
- **Operaciones medidas:** consulta y primera página; abrir una tabla; «Cargar en QGIS» Copia y Conectada
  (dibujar y desplazar el mapa); capas y archivos → DuckDB por cada camino (§5 de qgis-import-spec);
  «Exportar ▾» por formato; cancelar cada una de ellas; `DETACH`.
- **Línea base** en el equipo de la CI (Linux) para QGIS 3.44 y 4.2 × DuckDB 1.5 y 2.0, y en el equipo Windows del
  propietario con la guía manual. No se mezclan números de equipos o versiones distintos.
- **Regresión:** en el mismo equipo, una mediana > 20 % peor exige justificar o revertir (benchmarks §6). En la CI,
  un trabajo de rendimiento informativo (no bloquea) compara con la línea base.

## 3. Cancelación robusta (GD-PERF-002; spike G10-A)

- **Toda operación larga tiene «Cancelar»** visible: consulta, exportar, archivos/capas → DuckDB, cargar en QGIS,
  leer los metadatos de archivos y el dibujo de una capa Conectada.
- **Tiempo de respuesta (propuesto):** p95 ≤ 1 s desde el clic hasta que el trabajo se detiene, en las operaciones
  de §2 con T2/T3 de 1 millón de filas. Se mide por versión de DuckDB (`interrupt()` en 1.5 y 2.0, ADR-0007) y se
  publica.
- **Sin restos:** una tabla a medias se revierte (transacción), un archivo a medias no aparece (carpeta temporal,
  #130), una capa a medias no se publica (GD-BRD-004). Tras cancelar, la sesión vuelve a `READY` o queda en un
  estado explícito con su motivo (session-spec §5); nunca en un estado desconocido.
- **Spike G10-A:** medir `interrupt()` y la cancelación cooperativa por tipo de operación (SQL largo, `COPY`,
  `CREATE TABLE AS` con `ST_Read`, lectura por lotes hacia QGIS, PyArrow) en DuckDB 1.5 y 2.0; casos que no
  responden y su arreglo (puntos de control entre lotes, lotes más pequeños, cierre del lector).

## 4. Contrapresión y memoria (GD-PERF-003)

- **Canales acotados** en ambos sentidos (ya existen, qgis-bridge-spec §2): se mide su ocupación y la RAM pico de
  QGIS y del worker por operación y tamaño (T1–T5, hasta 10 millones de filas).
- **Presupuesto por transferencia:** antes de copiar a QGIS un resultado que no cabe en el presupuesto (por defecto,
  propuesto: la mitad de la RAM libre), GeoDuck lo dice y ofrece «Conectada» o «Exportar». Nunca carga sin límite.
- **Memoria de DuckDB:** la sesión de GeoDuck es suya (ADR-0011 solo protege lo ajeno). Propuesto: dejar el
  `memory_limit` por defecto de DuckDB y fijar `temp_directory` en la carpeta temporal de GeoDuck para que DuckDB
  use disco en vez de fallar por memoria. Se informa en «Diagnóstico».

## 5. Respuesta de la interfaz (GD-PERF-004)

- **Bloqueos del hilo de la interfaz (propuesto):** p95 ≤ 50 ms y máximo ≤ 200 ms mientras corre cualquier
  operación de §2; medido con un temporizador de eventos (benchmarks §4.6).
- **Abrir una tabla la primera vez:** ≤ 100 ms (hoy 140–220 ms, hallazgo de G9).
- **Escribir en el editor** y desplazar la grilla no se ven afectados por una transferencia en curso.
- F-129 (dos pruebas de `test_pro_load` en QGIS 3.34 corridas solas) se resuelve aquí.

## 6. Estrés (GD-PERF-005)

- Ciclo automático de 1 hora en QGIS 3.44 y 4.2 (propuesto): iniciar/cerrar sesión, `ATTACH`/`DETACH`, consultas,
  cargar y cancelar, enviar y «Deshacer», exportar y cancelar, con datos T1–T7. **0 cierres de QGIS, 0 filas
  perdidas, 0 capas a medias**; la RAM de QGIS no crece más de 10 % entre la primera y la última vuelta.
- Archivos de datos inválidos (T7) y corte a mitad de un archivo: error claro, sin cierre.

## 7. Publicación (GD-PERF-006)

`docs/performance.md`: tabla por operación, tamaño, versión de QGIS y DuckDB, y equipo, con mediana y p95, enlazada
desde «Acerca de». Solo números medidos con el banco de §2.

## 8. Fuera de alcance de G10

Funciones nuevas de interfaz; la trazabilidad rediseñada (después de todas las fases, decisión del 2026-11-12);
paralelizar QGIS; cambiar el formato de transporte (ADR-0008).

## 9. Criterios de aceptación

| AT | Escenario |
|---|---|
| AT-PERF-001 | El banco produce la línea base reproducible (JSON con equipo, versiones y repeticiones) en QGIS 3.44 y 4.2 × DuckDB 1.5 y 2.0 |
| AT-PERF-002 | Cancelar cada operación de §2 con 1 millón de filas: se detiene en p95 ≤ 1 s, sin restos, sesión en `READY` |
| AT-PERF-003 | Un resultado que no cabe en el presupuesto avisa antes y ofrece «Conectada» / «Exportar»; con `temp_directory`, una consulta que excede la memoria termina usando disco |
| AT-PERF-004 | Interfaz: p95 ≤ 50 ms y máximo ≤ 200 ms durante las transferencias; primera apertura de tabla ≤ 100 ms |
| AT-PERF-005 | Estrés de 1 h sin cierres, pérdidas ni capas a medias; RAM de QGIS +10 % como máximo |
| AT-PERF-006 | `docs/performance.md` publicado con números medidos; regresiones > 20 % detectadas por el trabajo de la CI |
