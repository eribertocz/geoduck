# GeoDuck — Rendimiento (G10 · `v0.11.0a1`)

**Estado:** Aprobada por el propietario (2026-11-12: plan, metas propuestas y optimización «de primer nivel»). **Requisitos:** GD-PERF-001..010, que detallan
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
- **Medido (#171, `docs/evidence/g10/171/`):** con 1 millón de filas, cada operación se detiene en p95 ≤ 66 ms
  con DuckDB 1.5 y 2.0, sin restos; también enviar una capa o un archivo a DuckDB y guardar el resultado de una
  consulta (#170). Leer los metadatos de los archivos se cancela al cerrar la ventana. Un `BEGIN` interrumpido ya
  no deja una transacción abierta (#157).
- **Spike G10-A:** medir `interrupt()` y la cancelación cooperativa por tipo de operación (SQL largo, `COPY`,
  `CREATE TABLE AS` con `ST_Read`, lectura por lotes hacia QGIS, PyArrow) en DuckDB 1.5 y 2.0; casos que no
  responden y su arreglo (puntos de control entre lotes, lotes más pequeños, cierre del lector).

## 4. Contrapresión y memoria (GD-PERF-003)

- **Canales acotados** en ambos sentidos (ya existen, qgis-bridge-spec §2): se mide su ocupación y la RAM pico de
  QGIS y del worker por operación y tamaño (T1–T5, hasta 10 millones de filas).
- **Presupuesto de la Copia (#172):** la mitad de la memoria libre al empezar (Linux `/proc/meminfo`, Windows
  `GlobalMemoryStatusEx`, macOS `sysctl`; si no se sabe, sin presupuesto). Con el total de filas que ya muestra la
  grilla, tras las primeras 10 000 filas se estima el tamaño final (bytes escritos ÷ filas × total); sin total, se
  mide mientras se copia. Si no cabe, la Copia se detiene en ese momento: no publica nada y libera lo escrito.
- **Si no cabe:** una ventana de dos botones (principios de interfaz): «Predios» no cabe como Copia / «Ocuparía unos
  9,2 GB y QGIS tiene 6 GB libres. Como Conectada, QGIS lee los datos directamente de la base, sin copiarlos.»
  [Cancelar] [**Cargar como Conectada**]. La segunda carga la misma capa como Conectada (la línea de tiempo pasa a
  «Capa Conectada»). Si «Conectada» no se puede, no se ofrece: queda el error con el motivo.
- **Memoria de DuckDB:** la sesión de GeoDuck es suya (ADR-0011 solo protege lo ajeno). Se deja el `memory_limit`
  por defecto y cada sesión usa su propia carpeta `temp_directory` (`<temporal>/geoduck/duckdb-<pid>-<n>`, se borra
  al cerrar), con `max_temp_directory_size` = el menor entre 20 GB y la mitad del disco libre (al menos 1 GB), para
  que DuckDB use disco en vez de fallar por memoria sin llenar el disco. «Diagnóstico» muestra la carpeta y el tope.

## 5. Respuesta de la interfaz (GD-PERF-004)

- **Bloqueos del hilo de la interfaz (propuesto):** p95 ≤ 50 ms y máximo ≤ 200 ms mientras corre cualquier
  operación de §2; medido con un temporizador de eventos (benchmarks §4.6).
- **Abrir una tabla la primera vez:** ≤ 100 ms (hoy 140–220 ms, hallazgo de G9).
- **Escribir en el editor** y desplazar la grilla no se ven afectados por una transferencia en curso.
- F-129 (dos pruebas de `test_pro_load` en QGIS 3.34 corridas solas): resuelto en E4 (#173), era del entorno
  de pruebas. Medidas de E4: `docs/evidence/g10/173/`.

## 6. Estrés (GD-PERF-005)

- Ciclo automático de 1 hora en QGIS 3.44 y 4.2 (propuesto): iniciar/cerrar sesión, `ATTACH`/`DETACH`, consultas,
  cargar y cancelar, enviar y «Deshacer», exportar y cancelar, con datos T1–T7. **0 cierres de QGIS, 0 filas
  perdidas, 0 capas a medias**; la RAM de QGIS no crece más de 10 % entre la primera y la última vuelta.
- Archivos de datos inválidos (T7) y corte a mitad de un archivo: error claro, sin cierre.

## 7. Publicación (GD-PERF-006)

`docs/performance.md`: tabla por operación, tamaño, versión de QGIS y DuckDB, y equipo, con mediana y p95, enlazada
desde «Acerca de». Solo números medidos con el banco de §2.

## 8. Resultados de consulta bajo demanda (GD-PERF-007; propietario, 2026-11-12)

Hoy la interfaz recibe solo 100 filas, pero cada página siguiente **vuelve a ejecutar la consulta** (`LIMIT/OFFSET`)
y el total es otra ejecución. Nuevo contrato:

- **Adaptativo (spike G10-A, `docs/evidence/g10/spike/`):** guardar siempre no es lo mejor: en una consulta barata
  cuesta 3–4 veces la ejecución, y repetirla ya tarda < 0,2 s con 10 millones de filas. Por eso:
  1. La **primera página** llega por flujo, en cuanto DuckDB la produce (como hoy).
  2. Si la consulta fue **barata** (propuesto: el total se cuenta en ≤ 300 ms), las páginas siguientes la repiten
     con ventana; el usuario no nota diferencia.
  3. Si fue **cara**, el resultado se guarda **una vez** en una tabla temporal de la sesión de GeoDuck
     (`temp.geoduck_result_<n>`; DuckDB la pasa a disco si no cabe en memoria, §4), en segundo plano y con
     «Cancelar»; desde ahí, cualquier página se lee por posición en 1–4 ms y el total es inmediato. Mientras se
     guarda, el pie lo dice («Preparando el resultado completo… N filas»).
- **Scroll continuo** en la grilla: pide bloques de filas por número de fila a medida que se baja (y los suelta al
  alejarse: en la interfaz nunca hay más de unos miles de filas). Sin botones de página; el pie dice «Filas 1–100 de
  1 000 000» según lo visible. Maqueta aprobada antes de construir.
- **Ordenar por columna** en el resultado, resuelto por DuckDB sobre la tabla temporal.
- **«Exportar ▾» y «Cargar en QGIS»** leen ese resultado, sin ejecutar la consulta otra vez.
- **Vida:** el resultado se borra al volver a ejecutar, al cerrar la pestaña o la sesión. Tope de disco configurable
  (propuesto: 20 GB o el 50 % del espacio libre, lo menor): al superarlo se guarda hasta ahí y se dice claramente
  («Resultado parcial: N filas; exporta para tenerlo completo»).
- **Sentencias que no se pueden guardar** (`RETURNING`, `EXPLAIN`, `PRAGMA`): como hoy, la primera página.
- **Meta:** página siguiente y salto a cualquier fila ≤ 200 ms en una consulta barata y ≤ 50 ms en una guardada,
  con 10 millones de filas; una consulta cara nunca se ejecuta más de una vez.

## 9. Tablas, cargas y catálogo (GD-PERF-008..010)

- **Tabla (GD-PERF-008):** el mismo scroll continuo; páginas por posición (`rowid`) cuando no hay orden ni filtro,
  en vez de `OFFSET`; total estimado al instante (metadatos) y exacto después. Meta: ir a cualquier parte de una
  tabla de 100 millones de filas ≤ 100 ms sin filtro.
- **Cargar en QGIS (GD-PERF-009):** «Conectada»: cancelación inmediata de lo que ya no se ve y conversión por
  fila mínima (E4b: un caché por extensión no ayuda, el costo es por fila entregada; `docs/evidence/g10/174/`).
  La «Copia» escrita por DuckDB directo se descartó (2026-11-14): el índice espacial cuesta lo mismo en los dos
  caminos y no hubo mejora medida. Progreso real (E4b, #174): el avance que informa DuckDB (1.5 y 2.0, con
  `progress_bar_time = 0` desde el inicio de la sesión) en exportar, en las capas y archivos que lee DuckDB y en
  el resultado guardado. La selección de QGIS leída por DuckDB se descartó: el camino de QGIS ya es rápido.
- **Catálogo (GD-PERF-010):** columnas y autocompletado cargados por partes; bases con 10 000 tablas sin pausas
  (barra lateral ≤ 100 ms al desplegar, Ctrl+K ≤ 50 ms por tecla). Hecho en E4b (#174): lo plegado se crea al desplegarlo; Ctrl+K busca
  cada letra entre lo que ya coincidía (`docs/evidence/g10/174/`).

## 10. Fuera de alcance de G10

Funciones nuevas de interfaz; la trazabilidad rediseñada (después de todas las fases, decisión del 2026-11-12);
paralelizar QGIS; cambiar el formato de transporte (ADR-0008).

## 11. Criterios de aceptación

| AT | Escenario |
|---|---|
| AT-PERF-001 | El banco produce la línea base reproducible (JSON con equipo, versiones y repeticiones) en QGIS 3.44 y 4.2 × DuckDB 1.5 y 2.0 |
| AT-PERF-002 | Cancelar cada operación de §2 con 1 millón de filas: se detiene en p95 ≤ 1 s, sin restos, sesión en `READY` |
| AT-PERF-003 | Una Copia que no cabe en el presupuesto se detiene sin publicar nada y ofrece «Cargar como Conectada»; con `temp_directory`, una consulta que excede la memoria termina usando disco |
| AT-PERF-004 | Interfaz: p95 ≤ 50 ms y máximo ≤ 200 ms durante las transferencias; primera apertura de tabla ≤ 100 ms |
| AT-PERF-005 | Estrés de 1 h sin cierres, pérdidas ni capas a medias; RAM de QGIS +10 % como máximo |
| AT-PERF-006 | `docs/performance.md` publicado con números medidos; regresiones > 20 % detectadas por el trabajo de la CI |
| AT-PERF-007 | Una consulta cara de 10 millones de filas se ejecuta una vez; desplazarse, ordenar, contar, exportar y cargar no la repiten (página ≤ 50 ms); una barata responde ≤ 200 ms por página; el resultado guardado se borra al cerrar |
| AT-PERF-008 | Tabla de 100 millones de filas: scroll a cualquier parte ≤ 100 ms sin filtro; total estimado inmediato |
| AT-PERF-009 | «Copia» por DuckDB directo con las mismas filas y SRC que el camino actual, y su mejora medida; «Conectada» cancela lo que ya no se ve |
| AT-PERF-010 | Catálogo de 10 000 tablas sin pausas > 100 ms |
