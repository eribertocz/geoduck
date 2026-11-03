# G6 · `v0.7.0a1` SQL Professional — evidencia de aceptación (AT-CAT-002, AT-SQL-007..010, AT-I18N-001)

**Estado:** En revisión (E5). El cierre de G6 lo decide el propietario; no autoriza tag ni release `v0.7.0a1`.
**Base verificada:** E4 (#89) sobre E0–E3 (#85–#88). Las cifras de la CI de este PR se anotan en un comentario
del PR. **Contrato:** `docs/g6/plan.md` (alcance aprobado el 2026-11-02), session-spec §2 (`ListColumns`),
sql-editor-spec §7 («P1 en G6»), ui-ux-spec §5 y §9, `spec/qa/test-strategy.md`. Versión en `metadata.txt`:
`0.6.0a1` (sin cambios; la sube el PR de versión, como en G5).

## 1. Matriz

La CI de GitHub ejecuta en cada PR la suite completa de `tests/qgis` en QGIS 3.34.6, 3.40.3, 3.44.14 (Qt 5)
y 4.2.3 (Qt 6) × DuckDB 1.5.0 y 2.0.0; el motor y las unitarias en DuckDB 1.5.0, 1.5.6 y 2.0.0 (Python 3.12
y 3.14, PyArrow 25.0.1 y 18.1.0); lint, tipos, arquitectura (ADR-0010), `spec_sync --check` e
`i18n --check` (catálogo completo, marcadores iguales).

En local, antes de cada PR (una suite cada vez): QGIS 3.34.6 y 4.2.3 con DuckDB 2.0.0 → 279 pasan; motor
178 con DuckDB 1.5.0 y 2.0.0; unitarias y arquitectura 549.

Linux headless no certifica Windows: la prueba manual de G6 está en
[`docs/certification/sql-professional.md`](../certification/sql-professional.md) (#10 sigue abierta).

## 2. Criterios de aceptación

Archivos en `tests/`: `qgis/test_explorer_columns.py` (C), `qgis/test_completion_ui.py` (A),
`qgis/test_editor_tabs.py` (P), `qgis/test_i18n_ui.py` (I), `unit/test_completion.py` (u-A),
`unit/test_coordinator.py` (u-K), `unit/test_i18n.py` (u-I), `engine/test_columns.py` (m-C),
`engine/test_sql_execution.py` (m-S).

| AT | Escenario | Evidencia |
|---|---|---|
| AT-CAT-002 | Columnas de tablas, vistas y temporales en varias bases y esquemas; nombres con espacios y comillas; DDL, ATTACH/DETACH e invalidación | C `test_expanding_shows_each_column_with_its_exact_type_and_nulls`, `test_only_one_read_per_expansion_and_none_while_collapsed`, `test_double_click_inserts_the_name_quoted_only_when_needed`, `test_double_click_on_a_table_still_loads_and_does_not_toggle_its_columns`, `test_only_columns_can_be_dragged_as_text`, `test_search_filters_tables_not_columns`, `test_ddl_refreshes_open_tables_and_nothing_stale_remains`, `test_a_missing_object_says_so_in_its_node_and_retries_later`, `test_in_the_panel_double_click_goes_to_the_sql_tab`; m-C (6: orden, tipo exacto, nulos, otras bases y esquemas, objeto inexistente, sin inyección, palabras clave); u-K `test_an_answer_for_an_older_catalog_is_discarded` y 4 más |
| AT-SQL-007 | Autocompletado en bases adjuntas, tras DDL y ATTACH/DETACH, dentro de comentarios y cadenas | u-A (25 casos: alias, `x.`/`x.y.`, sentencia del cursor, citado, prefijo, comentarios y cadenas, columnas que faltan, sin catálogo, límite); A `test_typing_opens_the_list_and_enter_inserts_without_running`, `test_after_an_alias_dot_the_columns_arrive_from_the_worker_and_are_quoted`, `test_escape_closes_and_ctrl_space_reopens`, `test_nothing_opens_inside_strings_or_comments`, `test_enter_without_the_list_is_a_new_line`, `test_ddl_is_seen_by_the_completion`, `test_it_works_the_same_in_the_panel`, `test_the_qgis_keyword_list_is_replaced_by_ours`; m-C `test_vocabulary_has_keywords_and_named_functions_and_grows_after_load` |
| AT-SQL-008 | Varias pestañas, ejecutar en cada una, alternar ventana ↔ panel, cerrar con texto y con ejecución en curso | P `test_each_tab_keeps_its_text_and_only_the_active_one_runs`, `test_tabs_survive_toggling_window_and_panel_with_their_state`, `test_closing_a_tab_with_sql_asks_and_an_empty_one_does_not`, `test_a_tab_cannot_close_while_its_statement_runs`, `test_ctrl_t_and_ctrl_w_only_with_the_focus_in_geoduck`, `test_errors_are_shown_in_the_tab_that_ran` |
| AT-SQL-009 | «Abrir en el editor» desde el registro | P `test_open_in_editor_copies_the_exact_sql_to_a_new_tab_without_running`, `test_the_log_menu_offers_open_in_editor`, `test_the_history_is_not_written_to_disk` |
| AT-SQL-010 | «Explicar» sobre SELECT, DML y varias sentencias | m-S `test_explain_shows_the_plan_and_never_runs_the_statement` (SELECT, INSERT, UPDATE, DELETE), `test_explain_rejects_without_running_anything` (6), `test_explain_of_the_statement_at_the_cursor`; P `test_explain_shows_the_plan_and_the_table_does_not_change`, `test_explain_refuses_several_statements_or_other_types_without_running` (2) |
| AT-I18N-001 | QGIS en inglés y en español; paquete ZIP | I `test_qgis_in_english_shows_geoduck_in_english`, `test_qgis_in_spanish_shows_geoduck_in_spanish`, `test_another_language_falls_back_to_english` (procesos aparte; el idioma de QGIS no cambia), `test_translating_never_calls_qt_so_the_engine_thread_can_do_it`; u-I `test_every_text_of_the_code_is_in_the_catalog_and_translated`, `test_translations_keep_the_placeholders_so_format_never_fails`, `test_source_texts_are_english`, `test_without_translator_the_texts_are_english_and_never_empty`, `test_the_zip_contains_the_compiled_translation`, `test_the_check_command_passes` |
| Regresión G0–G5 | Toda la suite | Pasa entera en cada celda, con QGIS en español (los textos de G5 no cambian). Pruebas anteriores adaptadas solo donde comparaban una constante con el texto mostrado (`tr(NO_EXTENT)`, `tr(READ_ONLY_HELP)`) |

## 3. Gate (`docs/g6/plan.md`)

| Condición | Estado |
|---|---|
| AT-CAT-002, AT-SQL-007..010 y AT-I18N-001 en la matriz de CI | Cumplida (§2; cifras en el comentario del PR) |
| Regresiones G0–G5 completas | Cumplida |
| Nada de G3/G4/G5 cambia de comportamiento | Cumplida: único cambio visible, el doble clic en una tabla ya no abre/cierra sus columnas (sigue cargando, como en G5) |
| Teclado, Qt 5 y Qt 6 | Cumplida en CI (AT-UX-001/013 siguen pasando con las pestañas, «Explicar» y la «✕» de cada pestaña); Windows: manual |

## 4. Verificaciones hechas durante G6

| Qué | Resultado |
|---|---|
| `duckdb_columns()` y `duckdb_keywords()` en DuckDB 1.5.0 y 2.0.0 (E1) | Mismas columnas (`data_type` exacto, `is_nullable`); palabras clave por categoría |
| `duckdb_functions()` en 1.5.0 y 2.0.0 (E2) | Nombres repetidos por sobrecarga; `pragma` y operadores se descartan |
| `EXPLAIN` de INSERT/UPDATE/DELETE/CREATE/DROP/COPY/ALTER/SET/BEGIN (E3) | No los ejecuta en ninguna versión. Aun así «Explicar» se limita a lecturas y DML: `EXPLAIN INSTALL` no se pudo comprobar sin red (ADR-0011) |
| Traducción desde el hilo del motor (E4) | Sin llamadas a Qt: diccionario leído del `.ts` (F-107) |

## 5. Hallazgos

| ID | Hallazgo | Resolución |
|---|---|---|
| F-102 | DuckDB 1.5 y 2.0 delimitan distinto el `;` y los comentarios entre sentencias (`extract_statements`) | El historial quita espacios de los extremos y el `;` final: mismo SQL en ambas (E3, #88) |
| F-103 | `QgsCodeEditorSQL` trae su propio autocompletado de palabras (umbral 2) | Se desactiva en los editores de GeoDuck; el de GeoDuck incluye las palabras clave (E2, #87) |
| F-104 | QScintilla usa Ctrl+T (intercambiar líneas) antes que los atajos del panel | Ctrl+T y Ctrl+W se liberan solo en los editores de GeoDuck (E3) |
| F-105 | `QTranslator.translate` de PyQt6 solo admite ASCII | Ya no se usa: ver F-107 (E4) |
| F-106 | Instalar y quitar el traductor en cada carga y descarga envía «LanguageChange» a widgets que se están borrando; en la CI (QGIS 4.2.3 · DuckDB 2.0.0) terminó en un fallo de segmentación | GeoDuck no instala `QTranslator` (F-107) |
| F-107 | El motor traduce mensajes en su hilo, y `QCoreApplication.translate` llamado desde un hilo que Qt no creó terminaba a veces en un fallo de segmentación (QGIS 4.2.3 · DuckDB 2.0.0) | GeoDuck lee el `.ts` con la biblioteca estándar y traduce con un diccionario; sin `.qm` ni `lrelease` (E4, #89) |

## 6. Limitaciones conocidas

- Quedan en español los mensajes de registro técnico (`logging`) y algunos `detail` internos de errores: no
  son interfaz.
- Las capturas de la CI (`tools/screenshot_dock.py`) salen en inglés (QGIS sin idioma configurado); las de
  `docs/g5/capturas/` siguen en español.
- Pestañas e historial no se guardan entre reinicios de QGIS (GD-SQL-008, sin fase).
- El autocompletado sugiere funciones por nombre, sin firma ni ayuda.
