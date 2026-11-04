# G7 · `v0.8.0a1` Notebook — evidencia de aceptación (AT-NB-001..011)

**Estado:** En revisión (E5). El cierre de G7 lo decide el propietario; no autoriza tag ni release `v0.8.0a1`.
**Base verificada:** E4 (#97) sobre E0–E3 y sus correcciones (#91–#96). Las cifras de la CI de este PR se anotan
en un comentario del PR. **Contrato:** `docs/g7/plan.md`, sql-editor-spec §4 y §7 («G7 · Notebook»), ui-ux-spec
§10, `docs/g7/maqueta/`, `spec/qa/test-strategy.md`. Versión en `metadata.txt`: `0.6.0a1` (sin cambios; la sube
el PR de versión, como en G5 y G6).

## 1. Matriz

La CI de GitHub ejecuta en cada PR la suite completa de `tests/qgis` en QGIS 3.34.6, 3.40.3, 3.44.14 (Qt 5)
y 4.2.3 (Qt 6) × DuckDB 1.5.0 y 2.0.0; el motor y las unitarias en DuckDB 1.5.0, 1.5.6 y 2.0.0 (Python 3.12
y 3.14, PyArrow 25.0.1 y 18.1.0); lint, tipos, arquitectura (ADR-0010), `spec_sync --check` e `i18n --check`.

En local, antes de cada PR (una suite cada vez): QGIS 3.34.6 y 4.2.3 con DuckDB 2.0.0 → 295 pasan; motor 192 y
unitarias con arquitectura 578, con DuckDB 1.5.0 y 2.0.0.

Linux headless no certifica Windows: la prueba manual de G7 está en
[`docs/certification/notebook.md`](../certification/notebook.md) (#10 sigue abierta).

## 2. Criterios de aceptación

Archivos en `tests/`: `qgis/test_notebook_ui.py` (N), `qgis/test_editor_tabs.py` (P), `qgis/test_i18n_ui.py`
(I), `qgis/test_workspace_content.py` (W), `unit/test_notebook.py` (u-N), `unit/test_export.py` (u-E),
`engine/test_cell_database.py` (m-B), `engine/test_export.py` (m-E), `engine/test_sql_execution.py` (m-S).

| AT | Escenario | Evidencia |
|---|---|---|
| AT-NB-001 | Añadir, mover, duplicar, borrar, plegar, vista de hoja; varios cuadernos | N `test_cells_are_added_moved_folded_and_deleted` (también Ctrl+↑/↓ con la tecla real), `test_duplicate_keeps_sql_and_database`, `test_the_notebook_list_creates_renames_switches_and_closes`; u-N `test_a_notebook_always_has_a_cell_and_keeps_the_order`. Arrastrar con el ratón: prueba manual (§4 de la guía) |
| AT-NB-002 | «Ejecutar todo» con una celda que falla | u-N `test_run_all_goes_in_order_with_the_base_of_each_cell`, `test_run_all_stops_at_the_first_failure`, `test_only_one_batch_at_a_time`; N `test_a_failing_cell_stops_the_notebook_and_a_detached_database_is_flagged` |
| AT-NB-003 | Dos celdas con bases distintas, en cualquier orden | m-B `test_each_cell_reads_its_own_base_in_any_order`; N `test_each_cell_runs_on_its_database_and_keeps_its_result`; u-N `test_the_catalog_is_read_again_when_the_base_in_use_changes` |
| AT-NB-004 | Otras bases por su nombre; varias sentencias; `USE` en la celda; base desadjuntada | m-B `test_a_cell_reads_other_bases_by_their_name_like_the_owner_example`, `test_several_statements_run_in_order_and_the_last_result_is_the_one_shown`, `test_a_use_written_in_the_cell_wins`, `test_temporaries_are_seen_from_any_base`, `test_a_detached_base_runs_nothing`, `test_a_transaction_can_write_only_to_one_base`; u-N `test_a_detached_base_is_reported_by_the_cell`, `test_a_cell_with_a_detached_base_stops_without_running`, `test_a_use_written_in_the_cell_updates_its_selector`; N `test_use_in_a_cell_changes_only_that_cell` |
| AT-NB-005 | Resultado y «Cargar en QGIS ▾» en cada celda (tres modalidades) | N `test_each_cell_runs_on_its_database_and_keeps_its_result`, `test_a_cell_result_loads_from_its_own_base_after_another_cell_changed_it` (Memoria, Copia rápida y Conectada, también sus lecturas posteriores); m-B `test_each_result_remembers_the_base_where_it_ran`, `test_operations_run_in_the_base_of_the_result_and_restore_the_base_in_use`, `test_an_operation_on_a_detached_base_fails_and_keeps_the_base_in_use`, `test_the_base_in_use_comes_back_even_when_the_read_fails`. La geometría de cada modalidad la siguen probando las pruebas de G3–G4 |
| AT-NB-006 | Resumen del resultado sin consultas nuevas | N `test_the_summary_shows_rows_columns_and_types_without_querying` (ventana y ayuda ⓘ del panel; ninguna operación del worker) |
| AT-NB-007 | Lista de cuadernos; nada en disco | N `test_the_notebook_list_creates_renames_switches_and_closes`, `test_in_the_panel_the_selector_shows_the_same_notebooks`; P `test_the_history_is_not_written_to_disk` |
| AT-NB-008 | Autocompletado, atajos e historial dentro de una celda | N `test_cell_shortcuts_like_the_duckdb_ui` (Ctrl+Intro celda, Ctrl+Mayús+Intro selección, Mayús+Intro celda y avanzar); P (las 10 de G6, ahora sobre la celda activa); `qgis/test_completion_ui.py` (las 8 de G6); P `test_explain_written_in_the_cell_shows_the_plan_and_the_table_does_not_change` |
| AT-NB-009 | Ventana ↔ panel con varias celdas, resultados y una ejecución en curso | N `test_toggling_keeps_cells_results_and_a_running_cell`; P `test_tabs_survive_toggling_window_and_panel_with_their_state` |
| AT-NB-010 | Teclado, panel estrecho, Qt 5 y Qt 6, inglés y español | N `test_every_cell_action_has_a_name_help_and_keyboard_focus`, `test_one_result_has_no_tab_and_a_cell_without_table_has_no_buttons`; W `test_a_narrow_panel_compacts_labels_but_keeps_every_action`, `test_every_action_is_reachable_with_the_keyboard`; I `test_qgis_in_english_shows_geoduck_in_english`, `test_qgis_in_spanish_shows_geoduck_in_spanish` (también textos de G7) |
| AT-NB-011 | Exportar 1 millón de filas con geometría a CSV y Parquet; archivo existente; cancelar; DML | m-E (8: 1 millón de filas en CSV y Parquet, WKT, Parquet sin y con SRC, fallo a mitad, cancelar, base de la celda, el resto de la celda no se repite); u-E (6: opciones de `COPY`, avisos de SRC, sesión ocupada, cancelar y fallo); N `test_export_writes_the_whole_query_from_the_base_of_the_cell`, `test_write_results_cannot_be_exported_and_the_cell_script_is_not_repeated`, `test_cancel_an_export_leaves_no_file`. La confirmación al sobrescribir la da el diálogo de Windows: prueba manual |
| Regresión G0–G6 | Toda la suite | Pasa entera en cada celda. Pruebas de G2–G6 adaptadas solo donde dependían de la forma de G6: el divisor (cuaderno · registro), «Sentencia», «Selección» y «Explicar» retirados, 50 filas por defecto |

## 3. Gate (`docs/g7/plan.md`)

| Condición | Estado |
|---|---|
| AT-NB-001..011 en la matriz de CI | Cumplida (§2; cifras en el comentario del PR). Arrastrar con el ratón y el diálogo de sobrescribir: manual |
| Regresiones G0–G6 completas | Cumplida |
| Nada de G3/G4 cambia de comportamiento | Cumplida: «Cargar en QGIS» y sus tres modalidades no cambian; ahora repiten la consulta en la base de la celda (#95) |
| Teclado, Qt 5 y Qt 6 | Cumplida en CI; Windows: manual |

## 4. Decisiones del propietario durante G7

| Fecha | Decisión |
|---|---|
| 2026-11-03 | Cuadernos de celdas nativos en Qt, parecidos a la DuckDB UI (sin incrustarla); base por celda; exportar la consulta completa; panel minimalista |
| 2026-11-03 | Atajos de la DuckDB UI: Ctrl+Intro ejecuta la celda, Ctrl+Mayús+Intro la selección, Mayús+Intro la celda y avanza; Ctrl+↑/↓ mueve la celda. Barra superior: solo «Ejecutar todo», «Cancelar» y filas |
| 2026-11-03 | Se retira «Explicar» de la interfaz y del motor (#94): el plan se pide escribiendo `EXPLAIN` |
| 2026-11-03 | «Cargar ▾» con texto corto; menú ⋯ como la DuckDB UI. «Formatear sentencias», para después |
| 2026-11-03 | Geometría en Parquet: sin SRC, GeoParquet 1.0 y aviso; con SRC, `GEOPARQUET_VERSION 'V2'` |
| 2026-11-03 | Todas las celdas conservan su tabla (medido: no hace falta liberar las que no se ven) |
| 2026-11-03 | Resultado con fondo propio y botones arriba, sin pestaña si es uno solo (opción A); vista previa de 50 filas (10/50/200/1000) |

## 5. Verificaciones hechas durante G7

| Qué | Resultado |
|---|---|
| `USE` en la misma operación que la celda, dentro de transacciones, temporales, escritura en dos bases (E0–E1) | Ver `docs/g7/plan.md` §2; las pruebas m-B lo comprueban en 1.5.0 y 2.0.0 |
| `COPY … TO` a Parquet con geometría (E3) | Sin SRC: GeoParquet 1.0, se relee como `OGC:CRS84`. Con SRC: la opción por defecto falla («GeoParquet V1 only supports PROJJSON»); `V2` guarda el SRC (GDAL 3.13 lo lee como EPSG:32719). Igual en 1.5.0 y 2.0.0 |
| Rendimiento con 100 celdas (E3, Qt 5 y Qt 6) | Crear: <1 s (12 ms la siguiente); ejecutar: 4–5 s con 200 filas cada una; ~0,5 MB por resultado; desplazamiento fluido |

## 6. Hallazgos

| ID | Hallazgo | Resolución |
|---|---|---|
| F-108 | «Cargar en QGIS» de una celda repetía la consulta en la base en uso: si otra celda la había cambiado, fallaba («Table … does not exist») | Cada resultado recuerda su base; la carga (y cada lectura de una capa Conectada) corre en ella y deja la base en uso como estaba (#95) |
| F-109 | Añadir una celda sacaba y volvía a meter todas las demás (`setParent`): ~15 s para 100 celdas | Solo se reordena el layout: <1 s (#96) |
| F-110 | `COPY … (FORMAT parquet)` falla con una geometría con SRC | `GEOPARQUET_VERSION 'V2'` en ese caso (#96) |
| F-111 | Al cerrar el último cuaderno, una señal de Qt llegaba sin cuaderno activo; una excepción en un slot cierra QGIS con PyQt6 | El panel lo comprueba antes de leer el resultado activo (#97) |
| F-112 | QScintilla usa Ctrl+↑/↓ (desplazar líneas) antes que los atajos de la celda | Se liberan solo en los editores de GeoDuck, como Ctrl+T en G6 (F-104) |
| F-113 | Carrera en `tests/qgis/test_crs_axes.py`: la prueba ejecutaba la siguiente sentencia antes de que la sesión quedara libre | La prueba espera a la sesión libre (#93); no era un fallo de GeoDuck |

## 7. Limitaciones conocidas

- Los cuadernos no se guardan entre reinicios de QGIS (GD-SQL-008, sin fase).
- Sin estadísticas por columna ni «Formatear sentencias» (fuera de G7).
- Un `USE` escrito en mitad de una celda: cada resultado recuerda la base donde se ejecutó, pero el selector de
  la celda muestra la del último `USE`.
- En CSV la geometría sale como WKT, sin SRC.
- Un valor de filas guardado que ya no existe (500) vuelve a 50.
