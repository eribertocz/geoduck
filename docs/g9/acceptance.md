# G9 · `v0.10.0a1` Workspace Pro — evidencia de aceptación (AT-WSP-001..012)

**Estado:** Propuesto para aceptación (E7). La aceptación la da el propietario; el tag y la release `v0.10.0a1`
también los hace él. Versión en `metadata.txt` y `geoduck/__init__.py`: `0.10.0a1` (en este PR).
**Base verificada:** E0–E6b (#114–#124), la corrección G8 de cancelar (#119) F-130 (#126) y las observaciones de la prueba en Windows (#127). Las cifras de la CI de este PR se
anotan en un comentario del PR. **Contrato:** `docs/g9/plan.md`, `spec/specs/workspace-pro-spec.md`
(GD-WSP-001..012), ADR-0016, `spec/qa/test-strategy.md`.

## 1. Matriz

La CI de GitHub ejecuta en cada PR la suite completa de `tests/qgis` en QGIS 3.34.6, 3.40.3, 3.44.14 (Qt 5) y
4.2.3 (Qt 6) × DuckDB 1.5.0 y 2.0.0; el motor y las unitarias en DuckDB 1.5.0, 1.5.6 y 2.0.0 (Python 3.12 y
3.14, PyArrow 25.0.1 y 18.1.0); lint, tipos, arquitectura (ADR-0010), `spec_sync --check`, `i18n --check` y
las capturas de Workspace Pro (`tools/pro_shots.py`).

En local, antes de cada PR (una suite cada vez): QGIS 3.34.6, 3.44.14 y 4.2.3 con DuckDB 2.0.0, y 4.2.3 con
DuckDB 1.5.0; sin QGIS, DuckDB 1.5.0 y 2.0.0.

Linux sin pantalla no certifica Windows: la prueba manual de G9 (que incluye la de G8, pendiente desde G8)
está en [`docs/certification/workspace-pro.md`](../certification/workspace-pro.md).

## 2. Criterios de aceptación

Archivos en `tests/`: `qgis/test_pro_design.py` (D), `qgis/test_pro_workspace.py` (W), `qgis/test_pro_table.py`
(T), `qgis/test_pro_query.py` (Q), `qgis/test_pro_load.py` (L), `qgis/test_pro_send.py` (S),
`qgis/test_pro_switch.py` (X), `qgis/test_completion_ui.py` (C), `qgis/test_i18n_ui.py` (I),
`unit/test_pro_tokens.py` (u-T), `unit/test_pro_fuzzy.py` (u-F), `unit/test_pro_places.py` (u-P).

| AT | Escenario | Evidencia |
|---|---|---|
| AT-WSP-001 | Tema claro y oscuro de QGIS, Qt 5 y Qt 6; estilos de QGIS antes y después; sin módulos web | D `test_the_style_stays_inside_geoduck`, `test_it_follows_the_qgis_theme`, `test_every_icon_renders_in_any_color`; W `test_the_style_stays_inside_geoduck_and_every_icon_button_has_a_name`; u-T `test_text_and_actions_reach_aa_on_every_background`; capturas claro/oscuro, Qt 5/Qt 6 en `docs/evidence/g9/` |
| AT-WSP-002 | Ventana ↔ panel con pestañas y una consulta; barra lateral plegada | W `test_window_and_panel_share_the_same_tabs_and_the_sidebar_choice_is_remembered`; X `test_window_and_panel_share_the_session_hiding_never_closes_it_and_the_mode_is_remembered`, `test_corrupt_presentation_settings_fall_back_to_the_window` |
| AT-WSP-003 | Tabla de 1 millón de filas: orden, dos chips, búsqueda, páginas, «Ver SQL» | T `test_a_million_rows_first_page_quickly_then_the_total`, `test_sort_filters_search_and_pages_match_sql` (frente a SQL), `test_the_filter_popup_adds_a_chip_and_no_rows_offers_to_clear`, `test_view_sql_opens_the_equivalent_query`; medidas en §5 |
| AT-WSP-004 | Detalle de fila con geometría y texto largo; «Estructura» de tabla y vista | T `test_row_detail_shows_full_values_and_a_geometry_summary`, `test_structure_of_a_table_and_a_view`, `test_ctrl_c_copies_the_selected_rows_as_text` |
| AT-WSP-005 | Sentencia, selección y todo; error con línea; cancelar; `.sql`; cuaderno de G7 | Q `test_run_runs_the_statement_under_the_cursor_and_shows_its_rows`, `test_all_shows_one_result_tab_per_statement_with_rows`, `test_selection_runs_only_the_selection`, `test_an_error_shows_messages_with_its_line_and_go_moves_the_cursor`, `test_cancel_stops_a_long_query`, `test_save_as_autosave_and_reopen`, `test_a_g7_notebook_opens_as_one_query`, `test_the_recovery_copy_brings_back_queries_after_a_crash`, `test_a_long_result_has_pages_its_total_and_the_row_detail_like_a_table`, `test_a_short_result_is_not_counted_again_and_a_write_has_no_pages`, `test_one_run_button_marks_what_will_run_and_runs_exactly_that`; U `test_statements.py` (4 pruebas); C (autocompletado, 8 pruebas); X `test_the_history_lists_what_ran_filters_errors_and_opens_without_running` |
| AT-WSP-006 | Ctrl+K con 1 000 objetos; sin acentos; Intro y Esc | W `test_ctrl_k_finds_without_accents_opens_with_enter_and_closes_with_esc`, `test_ctrl_k_with_a_thousand_objects_answers_under_50_ms_per_key`; u-F (5 pruebas) |
| AT-WSP-007 | «Copia» y «Conectada»; GDAL sin `WriteArrow`; guardar y reabrir con una «Copia»; «Más opciones…» | L `test_copy_is_the_fast_one_unless_gdal_cannot`, `test_copy_from_the_table_tab_loads_it_with_its_crs_and_without_questions`, `test_connected_from_the_table_is_the_table_itself_and_with_filters_only_those_rows`, `test_a_missing_crs_is_asked_once_and_cancel_loads_nothing`, `test_saving_the_project_offers_to_keep_the_copies_and_they_survive_reopening`, `test_no_thanks_is_not_asked_again_and_reopening_explains_the_lost_copies`, `test_reproject_to_on_a_copy`, `test_a_text_column_loads_as_geometry_with_the_crs_asked_once`, `test_choosing_one_of_two_geometries_loads_one_layer`; X `test_view_on_map_after_loading_selects_zooms_and_minimizes_the_window`; las cargas de G3–G4 (`test_crs_axes`, `test_families`, `test_multi_geometry`, `test_load_connected`) con el aviso nuevo |
| AT-WSP-008 | Recientes y ★ tras reiniciar; objeto borrado | W `test_favorites_survive_a_restart_and_a_dropped_table_is_dimmed_with_its_reason`, `test_new_queries_are_numbered_and_tabs_come_back_after_a_restart`; u-P (9 pruebas: solo nombres en las opciones) |
| AT-WSP-009 | «Capas de QGIS → DuckDB» en tres pasos desde arrastrar, el clic derecho y «+»/Ctrl+K; cada capa por separado | S `test_dropping_on_a_database_opens_the_three_steps_with_that_database`, `test_each_layer_is_saved_on_its_own_and_one_can_be_removed`, `test_cancel_all_before_it_starts_adds_nothing`, `test_a_layer_that_fails_is_marked_and_the_others_go_on`, `test_in_the_background_the_footer_brings_it_back_and_the_end_shows_a_closable_notice`, `test_an_existing_table_is_shown_and_skipped_unless_chosen`, `test_add_layers_shows_every_layer_grouped_and_an_empty_project_says_so`, `test_while_adding_another_drop_shows_the_progress`, `test_a_database_that_cannot_store_the_crs_says_so_in_step_two`, `test_dropping_on_empty_space_goes_to_the_current_database`, `test_a_layer_dropped_on_the_editor_is_copied_never_moved`, `test_a_copy_sent_back_to_duckdb_keeps_its_columns_and_loads_again` (en `test_pro_load.py`), `test_tables_dragged_to_the_map_ask_how_and_ask_the_crs_once`; X `test_the_layer_menu_opens_step_one_with_the_selected_layers`, `test_the_plus_entry_opens_step_one_with_every_layer`; AT-IMP-001..007 siguen en `test_send_ui.py` y `test_import_layers.py` |
| AT-WSP-010 | Solo teclado; inglés y español; sin sesión, cargando, vacío y error; panel estrecho | I (inglés, español y otro idioma, con QGIS real); Q `test_without_duckdb_everything_is_grey_except_start`; W `test_without_session_it_offers_to_start_and_then_welcomes`; X `test_a_narrow_panel_keeps_every_action_within_reach`, `test_an_aborted_transaction_offers_roll_back_and_the_session_recovers`; `test_plugin.py` `test_broken_environment_disables_start` (entorno incompleto); D `test_buttons_always_have_a_name_and_help` |
| AT-WSP-011 | Actualizar desde 0.9.0a1 con cuadernos guardados abiertos | X `test_updating_keeps_presentation_and_open_notebooks_come_back_as_queries` |
| AT-WSP-012 | Medidas de §13 en QGIS 3.44 y 4.2 | §5 y [`docs/evidence/g9/rendimiento/`](../evidence/g9/rendimiento/README.md) |

**Regresión G0–G8:** toda la suite pasa en cada celda. Las pruebas de G1–G8 que usaban la interfaz anterior se
reescribieron para la nueva (sesión, cierre con transacción, autocompletado, idioma, envío, validez, cargas);
las que probaban pantallas retiradas se quitaron con ellas, y lo que cubrían está en las de arriba.

## 3. Gate (`docs/g9/plan.md`)

| Condición | Estado |
|---|---|
| AT-WSP-001..012 en la matriz de CI | Cumplida (§2; cifras en el comentario del PR) |
| Rendimiento de §13 medido en QGIS 3.44 y 4.2 | Cumplida (§5) |
| Capturas aprobadas antes de construir cada pantalla | Cumplida: E0b, E1, E2, E3, E4, E5, E6 (historial) y E6b, aprobadas por el propietario |
| La interfaz anterior retirada sin perder funciones | Cumplida (E6, E6b; SPEC §12) |
| Guía manual en Windows | Cumplida: [`docs/certification/workspace-pro.md`](../certification/workspace-pro.md) (incluye G8); la ejecución en Windows la hace el propietario |
| Regresiones G0–G8 | Cumplida |

## 4. Revisión de la interfaz con el principio del balance (SPEC §1)

Cada pantalla, frente a «lo común en un clic, lo avanzado un paso atrás, solo lo que aplica, cada opción dice
qué pasará, antes de una acción una frase de lo que ocurrirá».

| Pantalla | Lo común | Lo avanzado | Veredicto |
|---|---|---|---|
| Inicio sin DuckDB | «Iniciar DuckDB» (primario) | Abrir o crear base; «Diagnóstico» solo si falta algo | Cumple; todo lo demás en gris, nunca oculto |
| Barra lateral | Doble clic abre; ★ y Recientes arriba | Menú contextual; «+» | Cumple |
| Pestaña de tabla | Datos al abrir; orden con un clic | «+ Filtro», búsqueda, detalle, «Estructura», «Ver SQL» | Cumple; el detalle se abre a pedido |
| Pestaña de consulta | Ejecutar (Ctrl+Intro) | «Todo», base, «⋯» | Cumple |
| Cargar en QGIS | Copia o Conectada, con una línea cada una | «Más opciones…», con resumen y una línea por opción | Cumple (E6b) |
| SRC que falta | Solo aparece si falta; una vez para todas | — | Cumple |
| Guardar copias | Un clic, con qué archivo se crea | «No, gracias» | Cumple |
| Capas de QGIS → DuckDB | Tres pasos claros, el mismo desde las tres formas; la base donde se soltó ya elegida | «Más opciones» en el paso 2; «×» por capa y «Cancelar todo» en el paso 3 | Cumple (F-131) |
| Tablas al mapa | Mini menú Copia / Conectada donde se soltó | — | Cumple |
| Ctrl+K | Escribir e Intro | Acciones en la misma lista | Cumple |
| Historial | Doble clic abre la sentencia | Filtro y «Limpiar» | Cumple |
| Avisos | Una frase y, a lo sumo, dos acciones | — | Cumple; el de la transacción dice que descarta los cambios |

Ninguna pantalla pierde opciones respecto a la interfaz anterior; ninguna muestra opciones que no apliquen.

## 5. Rendimiento

Ver [`docs/evidence/g9/rendimiento/README.md`](../evidence/g9/rendimiento/README.md). En resumen (QGIS 3.44 y
4.2, DuckDB 2.0.0, contenedor de 2 núcleos):

| Objetivo (§13) | Medido |
|---|---|
| Primera página de 1 millón de filas < 0,5 s | 35–68 ms |
| Ordenar, filtrar, buscar y paginar sin congelar | 37–65 ms; pausa máxima de la interfaz 44 ms |
| Ctrl+K con 1 000 objetos < 50 ms por tecla | mediana 6 ms, máximo 36 ms |
| Ventana ↔ panel < 0,2 s | 130–165 ms |

## 6. Decisiones del propietario durante G9

| Fecha | Decisión |
|---|---|
| 2026-11-05 | 100 filas por página sin selector; recientes y ★ entre reinicios (solo nombres); copia de recuperación activada |
| 2026-11-05 | «Copia» unificada (rápida, o en memoria si GDAL no la permite) y «Guardar las copias junto al proyecto» |
| 2026-11-06 | Estado de DuckDB arriba de la barra lateral y en la cabecera del panel; «Iniciar DuckDB» / «Cerrar DuckDB»; sin DuckDB todo en gris salvo iniciar, abrir, crear, diagnóstico y «Acerca de» |
| 2026-11-06 | Editor SQL oscuro con el tema oscuro |
| 2026-11-06 | Arrastrar en los dos sentidos; mini menú al soltar tablas en el mapa; SRC de la columna y una sola ventana si falta |
| 2026-11-06 | E5 («Tú decide»): enviar sin ventana si no hay nada que decidir; ventana más limpia; base resaltada al soltar; progreso en el pie |
| 2026-11-06 | E6 («Tú decide»): «Historial», «Revertir» y «Ver en el mapa» en la interfaz nueva; el menú de capa envía como soltar |
| 2026-11-06 | Las opciones avanzadas de carga no se pierden: «Más opciones…» (E6b) |
| 2026-11-06 | Tras la prueba en Windows: arrastrar, el clic derecho y «Añadir capas de QGIS a DuckDB…» abren la misma ventana de tres pasos (capas, dónde, progreso); cada capa se guarda por separado; «Añadir … a DuckDB» / «Cargar en QGIS»; GeoDuck es el complemento y DuckDB la base (F-131) |
| 2026-11-06 | Todos los avisos llevan «×» (F-132) |
| 2026-11-06 | **Principio de toda la interfaz:** el balance entre ofrecer opciones y no complicar (SPEC §1) |

## 7. Hallazgos

| ID | Hallazgo | Resolución |
|---|---|---|
| F-123 | Con una hoja de estilos, Qt no propaga la fuente a los hijos; Qt 5 no admite varias familias | Fuente en la regla general, la primera instalada de la lista (E1) |
| F-124 | `QgsCodeEditorSQL` en Qt 5: fuente proporcional, glifos superpuestos o diminutos | Fuente monoespaciada en puntos y la regla `QsciScintilla` de la hoja (E4a) |
| F-125 | Un atributo `palette` en el workspace tapaba `QWidget.palette()` y rompía los colores | Renombrado `command_palette` (E2); lo mismo con `sender` → `quick_send` (E5) |
| F-126 | Con DuckDB 1.5, una base nueva en archivo no guarda el SRC: el diálogo se abría dos veces y QGIS se caía | La decisión de abrirlo se toma una sola vez (E5, #122) |
| F-127 | El autocompletado de la consulta nueva no se refrescaba al llegar las columnas | Se refresca con `ColumnsListed` y `VocabularyChanged` (E6) |
| F-128 | DuckDB 1.5 no aborta la transacción por un error de catálogo (2.0 sí); el texto de la sentencia lleva «;» solo en 2.0 | Las pruebas usan una clave repetida, que aborta en las dos (E6) |
| F-129 | En QGIS 3.34, dos pruebas de `test_pro_load` fallan **corridas solas** (la capa queda sin SRC); dentro de la suite pasan. También en `main` antes de E6 | Abierto: se revisa en G10. No afecta a QGIS real (la base de SRC ya está iniciada) — por confirmar en la prueba de Windows, paso 4b |
| F-130 | En la prueba de Windows (QGIS 3.44.7 de OSGeo4W), GeoDuck no abría: la DLL de `pyarrow._parquet` no cargaba y `initGui` importaba `pyarrow.parquet` | `pyarrow.parquet` solo al mirar si una capa es GeoParquet; sin él, el camino general (#126) |
| F-131 | «Enviar capas de QGIS a DuckDB…» no se entendía y, sin capas vectoriales, solo lo decía una línea del pie; cada forma de añadir capas se comportaba distinto | Una ventana de tres pasos para las tres formas; sin capas lo dice dentro; progreso y cancelación por capa (#127) |
| F-132 | Los avisos no tenían cómo cerrarse | «×» en todos (#127) |
| — | Las capturas de la CI (`pro_shots`) se caían al cerrar Qt 5 tras escribirlas | Salen sin la limpieza de PyQt5 (E6) |

## 8. Limitaciones conocidas

- Editar celdas en la grilla, gráficos, diagramas y varias sesiones a la vez quedan fuera de G9 (SPEC §14).
- El worker sigue siendo serial: una consulta a la vez; una carga o un envío ocupan la sesión.
- Una «Copia» vive en memoria hasta guardarla junto al proyecto.
- Abrir una pestaña de tabla la primera vez pausa la interfaz 140–220 ms (construir y pintar; §5): para G10.
