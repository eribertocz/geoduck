# G5 · `v0.6.0a1` Workspace UX — evidencia de aceptación (AT-UX-001..015)

**Estado:** En revisión (E5). El cierre de G5 lo decide el propietario; no autoriza tag ni release `v0.6.0a1`.
**Base verificada:** rama de E4b (#82, commit `5541c4e`), sobre E1–E4 (#78–#81), CI 18/18. Las cifras de este
PR (E5) se anotan en un comentario del PR. **Contrato:** `spec/specs/ui-ux-spec.md` §8, ADR-0013,
`spec/qa/test-strategy.md` (AT-UX), `docs/g5/plan.md` (gate), `docs/g5/maqueta/` (aprobada) e
`inventario.md` (componentes y decisiones). Versión en `metadata.txt`: `0.4.0a2` (sin cambios).

## 1. Matriz verificada

Cada celda es una ejecución completa de `tests/qgis` (QGIS headless) en la CI de GitHub (Linux), commit
`5541c4e`:

| QGIS | DuckDB 1.5.0 | DuckDB 2.0.0 |
|---|---|---|
| 3.34.6 (mínima, Qt 5) | 242 pasan, 1 omitida | 243 pasan |
| 3.40.3 LTR (Qt 5) | 242 pasan, 1 omitida | 243 pasan |
| 3.44.14 LTR (Qt 5) | 242 pasan, 1 omitida | 243 pasan |
| 4.2.3 (Qt 6) | 242 pasan, 1 omitida | 243 pasan |

La omitida es AX-3 de G4 (solo existe en DuckDB 2.0). Motor y unitarias: 505 en DuckDB 1.5.0, 1.5.6 y 2.0.0
(Python 3.12 y 3.14, PyArrow 25.0.1 y 18.1.0). Lint, mypy, arquitectura (ADR-0010) y `spec_sync --check`:
limpios (504). E5 añade 3 pruebas (AT-UX-001).

Además, cada entrega se probó en local antes del PR (micromamba, conda-forge): QGIS 3.34.6, 3.44.14 y 4.2.3.

Linux headless **no** certifica Windows: la prueba manual de G5 está en
[`docs/certification/workspace.md`](../certification/workspace.md) (#10 sigue abierta y no bloquea).

## 2. Criterios de aceptación

Archivos en `tests/qgis/`: `test_workspace.py` (W), `test_workspace_content.py` (C),
`test_workspace_actions.py` (A).

| AT | Escenario | Evidencia |
|---|---|---|
| AT-UX-001 | Acciones visibles y accesibles; tema; dock; Qt 5 y 6 | C `test_every_visible_action_has_a_name_and_help[ventana/panel]`, C `test_the_palette_follows_the_qgis_theme_and_stays_inside_geoduck` (paleta clara/oscura, contraste WCAG AA, nunca en QGIS entero), C `test_every_action_is_reachable_with_the_keyboard`; matriz Qt 5 (3.34–3.44) y Qt 6 (4.2) |
| AT-UX-002 | Instalación limpia; el modo elegido se recuerda | W `test_clean_install_opens_in_its_own_window_child_of_qgis`, W `test_the_chosen_mode_is_remembered_after_restarting`, W `test_missing_corrupt_or_newer_settings_fall_back_to_the_window` (5 casos) |
| AT-UX-003 | Alternar ida y vuelta: misma sesión, worker y contenido | W `test_round_trip_keeps_the_same_session_worker_and_content` (ningún evento de la aplicación al alternar) |
| AT-UX-004 | Texto, cursor, selección, scroll, resultados y pestañas intactos | W `test_toggling_keeps_text_cursor_selection_scroll_results_and_tabs` |
| AT-UX-005 | Alternar durante SQL, carga o cancelación: un solo resultado | W `test_toggling_during_sql_delivers_exactly_one_result`, W `test_toggling_during_a_load_publishes_exactly_one_layer` (1,5 M de puntos), W `test_toggling_during_a_cancellation_delivers_exactly_one_cancellation` |
| AT-UX-006 | Explorador: varias bases, vistas y temporales; búsqueda sin leer filas; acceso | C `test_explorer_groups_objects_and_shows_the_access_of_each_database`, C `test_search_filters_and_keeps_the_groups_without_reading_rows`, C `test_double_click_loads_by_the_object_name`; `test_explorer.py` (G1, con grupos) |
| AT-UX-007 | Resultados: tipo por columna, `NULL` ≠ "", «hay más» | C `test_results_show_each_column_type_and_tell_null_from_empty`, C `test_there_is_more_only_when_rows_exceed_the_limit[49/50/51]` |
| AT-UX-008 | Tres modalidades desde ambos modos; el menú abre el diálogo de G4 con el modo marcado; «Ver en el mapa» | A `test_load_menu_opens_the_g4_dialog_with_that_mode_and_loads_one_layer` (3 × ventana/panel), A `test_unavailable_modes_are_disabled_with_their_reason`, A `test_a_statement_ending_in_semicolon_and_comment_loads` (3), A `test_view_on_map_selects_and_zooms_to_a_valid_extent`, A `test_view_on_map_without_a_valid_extent_selects_without_zoom` (2), A `test_view_on_map_minimizes_the_window_and_the_toolbar_button_restores_it` |
| AT-UX-009 | Registro Todo/OK/Error: filtra sin borrar; mensaje completo accesible | A `test_log_filters_hide_rows_without_deleting_and_keep_the_full_message`, A `test_the_panel_log_tab_counts_errors_and_the_filter_is_remembered` |
| AT-UX-010 | Restaurar modo, ventana, panel y divisores; pantalla ausente; ajustes corruptos | W `test_mode_window_dock_area_splitters_tab_and_limit_are_restored`, W `test_a_window_saved_on_a_missing_screen_reopens_on_screen`, W `test_corrupt_settings_give_safe_values` |
| AT-UX-011 | Cerrar u ocultar la ventana o el panel: sin cierre, DETACH ni ROLLBACK | W `test_closing_or_hiding_a_shell_never_closes_detaches_or_rolls_back` (base adjunta, capa Conectada y transacción abierta) |
| AT-UX-012 | 20 alternancias: sin señales dobles, huérfanos ni sesiones extra | W `test_twenty_toggles_leave_no_double_signals_orphans_or_extra_sessions` |
| AT-UX-013 | Teclado, panel estrecho, DPI y tema | C `test_shortcuts_run_only_with_the_focus_inside_geoduck` (QTest fuera y dentro de GeoDuck), C `test_a_narrow_panel_compacts_labels_but_keeps_every_action`, C `test_every_action_is_reachable_with_the_keyboard`. **DPI y tema en Windows: manual** (`workspace.md` §4) |
| AT-UX-014 | Fallo inyectado durante el traslado | W `test_a_failed_move_leaves_the_previous_shell_working[put/add_dock]` |
| AT-UX-015 | Regresión G0–G4 | Toda la suite en verde en cada celda (§1). Pruebas anteriores adaptadas solo donde cambió la interfaz (nombres de acciones, árbol con grupos, registro, títulos de pestaña); las 3 de «Activar spatial…» se quitaron al retirarse la acción (R2) |

Ubicación de las acciones (§8 e inventario §5): A `test_existing_actions_are_where_section_8_puts_them`;
diálogo de bases: `test_explorer.py::test_attach_dialog_builds_requests`.

## 3. Gate (`docs/g5/plan.md`)

| Condición | Estado |
|---|---|
| Ambos modos funcionales con un único estado (ADR-0013) | Cumplida (AT-UX-002..005, 011, 012, 014) |
| AT-UX-001..015 en la matriz de CI | Cumplida (§1, §2), salvo DPI y tema en Windows (manual) |
| Las tres cargas de G3/G4 en ambos modos | Cumplida (AT-UX-008) |
| Revisión visual conforme a la maqueta | Inventario aprobado y aplicado (E4b, #82); capturas en `docs/g5/capturas/`. **Pendiente:** revisión del propietario en Windows (`workspace.md` §5) |
| Regresiones G0–G4 completas | Cumplida (AT-UX-015) |

## 4. Decisiones del propietario (2026-11-02), aplicadas

Las de `docs/g5/plan.md` §1 y, durante la revisión de E4/E4b (`docs/g5/maqueta/inventario.md` §5):
«Ver en el mapa» minimiza la ventana propia; identidad visual con paleta corporativa casi idéntica a la
maqueta; sin «Activar spatial…»; «Iniciar/Cerrar sesión» al pie de «Bases de datos»; ayuda de carga en cada
tabla; diálogo de bases con «Solo lectura» y «Alias»; rediseño (solo aspecto) de «Cargar en QGIS» y
«Acerca de». F-100 (sufijo automático en nombres repetidos): decidido, para un PR aparte.

## 5. Hallazgos durante G5

| ID | Hallazgo | Resolución |
|---|---|---|
| F-101 | «Cargar en QGIS» fallaba con «Parser Error» si la sentencia terminaba en `;` o tenía un comentario detrás (desde G3) | `domain/sql_text.load_sql` en el coordinador (E4b, #82); prueba `test_a_statement_ending_in_semicolon_and_comment_loads` |

## 6. Limitaciones conocidas

- La variante oscura se elige por la paleta de Qt. Con un tema de QGIS que solo cambie la hoja de estilo,
  GeoDuck podría quedarse en la variante clara: se verifica en Windows (`workspace.md` §4d).
- El editor SQL usa el esquema de colores de QGIS (fondo, cursor); GeoDuck solo fija el color de las
  palabras clave en su propio editor.
- La ventana propia es hija de QGIS: queda siempre encima de la ventana de QGIS (por eso «Ver en el mapa» la
  minimiza).
- En un panel estrecho se ocultan los atajos y las etiquetas largas, nunca las acciones (probado con 320 px).
