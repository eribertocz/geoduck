# G3 · `v0.4.0a1` — evidencia de aceptación (AT-BRD-001..012)

**Estado:** propuesta para revisión del propietario. El gate de G3 lo da por cumplido el propietario al
fusionar; este documento reúne la evidencia.
**Contrato:** `spec/specs/qgis-bridge-spec.md`, `spec/qa/test-strategy.md` (AT-BRD), ADR-0012.

## 1. Matriz verificada

Cada fila es una ejecución completa de `tests/qgis` (QGIS headless, `QT_QPA_PLATFORM=offscreen`) en Linux:

| QGIS | DuckDB 1.5.0 | DuckDB 1.5.6 | DuckDB 2.0.0 |
|---|---|---|---|
| 3.44.14 (Qt 5) | 96 pasan | 96 pasan | 96 pasan |
| 4.2.3 (Qt 6) | 96 pasan | 96 pasan | 96 pasan |

Motor y unitarias (`-m "not qgis"`): 616 pasan con DuckDB 1.5.0, 1.5.6 y 2.0.0. ruff, mypy y el test de
fronteras de arquitectura (ADR-0010), limpios. La CI de GitHub repite la matriz en cada PR a `main`.

Linux headless **no** certifica Windows (#10 sigue abierta y no bloquea).

## 2. Criterios de aceptación

| AT | Escenario | Evidencia (pruebas) |
|---|---|---|
| AT-BRD-001 | SELECT sin geometría → capa memory íntegra | `test_load_memory::test_empty_result_and_table_without_geometry`, `::test_full_load_is_identical_row_by_row` |
| AT-BRD-002 | Lector Arrow de varios lotes | `tests/engine/test_bridge_read::test_multibatch_read_keeps_every_row`, `test_channel::test_backpressure_limits_batches_in_flight` |
| AT-BRD-003 | Cancelar una carga larga | `test_load_memory::test_cancel_publishes_nothing_and_frees_the_session`, `test_load_snapshot::test_cancel_publishes_nothing_and_frees_vsimem`, `test_bridge_read::test_cancel_stops_the_read_and_frees_the_worker` |
| AT-BRD-004 | Fallo en la fila 30 001 | `test_load_memory::test_failure_at_row_30001_publishes_nothing`, `test_load_snapshot::test_engine_error_mid_read_publishes_nothing_and_frees_vsimem` |
| AT-BRD-005 | Memoria/Instantánea → DETACH y cierre | `test_load_memory::test_layers_survive_detach_and_close`, `test_load_snapshot::test_layers_survive_detach_and_close`, `test_lifecycle_connected::test_g3_gate_walkthrough` |
| AT-BRD-006 | Instantánea: íntegra, CRS, editable, `/vsimem` liberado | `test_load_snapshot::test_full_load_is_identical_and_editable`, `::test_vsimem_is_freed_only_after_the_last_layer_is_removed`, `::test_mixed_geometry_types_become_one_layer_per_type`, `::test_unavailable_with_old_gdal` |
| AT-BRD-007 | Tipos de §7 en las tres modalidades | `test_bridge_types` (una regla por tipo), `test_bridge_read::test_every_type_follows_section_7`, `test_load_memory::test_types_follow_section_7`, `test_load_connected::test_types_follow_section_7`; Instantánea escribe el mismo plan normalizado |
| AT-BRD-008 | Conectada: tabla, vista y SQL; extensión, expresión, FID | `test_load_connected::test_table_with_primary_key`, `::test_extent_fid_and_attribute_pushdown`, `::test_expressions` (compiladas y en Python), `::test_query_and_view_use_stable_row_numbers`, `::test_table_without_key_uses_rowid`, `::test_pages_cover_everything_once` |
| AT-BRD-009 | Contención SQL ↔ dibujado | `test_bridge_read::test_map_reads_go_before_queued_work_but_never_interrupt`, `test_load_connected::test_rendering_waits_for_user_sql_without_errors`, `::test_map_rendering_draws_the_layer` |
| AT-BRD-010 | Edición atómica con conflictos | `test_edit_connected` (12 pruebas): una transacción con altas, bajas y cambios; conflicto por cambio y por borrado (DuckDB intacto, búfer intacto, reintento); fallo a mitad con ROLLBACK total; validaciones; transacción abierta; lotes de 100/1 000/10 000 |
| AT-BRD-011 | ATTACH/DETACH, cierre, reapertura | `test_lifecycle_connected`: no disponible tras DETACH y de vuelta tras ATTACH; cambios sin guardar bloquean DETACH y cierre (también `test_coordinator_load::test_unsaved_connected_edits_block_detach_close_and_sql_detach`); cierre y sesión nueva; proyecto reabierto que se reconecta y sigue siendo editable |
| AT-BRD-012 | Interfaz con las tres modalidades | `test_load_ui::test_load_button_loads_the_result[memory/snapshot/connected]`, `::test_explorer_loads_a_table_connected_with_its_key`, `::test_unknown_crs_is_asked`, `::test_write_results_cannot_be_loaded` |

**Recorrido del gate** (`docs/g3/plan.md`, «Gate»): `test_lifecycle_connected::test_g3_gate_walkthrough`. Hace sesión →
ATTACH → SELECT → Memoria, Instantánea y Conectada → editar la Conectada → DETACH. Después, Memoria e
Instantánea siguen intactas; la Conectada queda vacía y no disponible y vuelve al adjuntar de nuevo la base.

## 3. Rendimiento medido (1 M de puntos, QGIS 4.2, DuckDB 2.0)

| Operación | Conectada | Referencia |
|---|---|---|
| Dibujo completo | 5,3 s | Instantánea (GeoPackage): 1,4 s |
| Zoom 5×5° (≈ 400 entidades) | 0,05 s | — |
| Filtro compilado (`c = 3 AND id < 100000`) | 0,05 s | — |
| Guardado de 10 000 cambios + 1 000 borrados | 0,23 s | — |

## 4. Decisiones del propietario (2026-11-02), aplicadas

1. **Identificadores sin clave primaria:** se sustituye `OFFSET` porque la identidad queda garantizada tras
   filtros y relecturas: el FID es la huella del contenido de la fila (§5.1). `rowid` (cambia tras
   borrar y compactar) y `row_number()` (orden no garantizado) se descartaron. Esas capas siguen siendo
   de solo lectura. Evidencia: `test_load_connected::test_keyless_fids_survive_filters_rereads_reordering_and_checkpoints`,
   `::test_identical_rows_are_never_lost_or_repeated_across_pages`.
2. **DETACH en SQL:** se reconoce por el tipo de sentencia del parser de DuckDB y su base, no por el
   texto. Si se rechaza, el script entero no se ejecuta. Evidencia:
   `test_lifecycle_connected::test_sql_detach_with_unsaved_edits_is_rejected_but_harmless_sql_runs`,
   `test_coordinator_load::test_sql_detach_is_vetoed_only_for_real_detach_statements`,
   `test_coordinator_load::test_detach_target`,
   `test_sql_execution::test_guard_vetoes_the_whole_script_before_running_anything`.
3. **Transacción abierta del usuario:** basta el aviso al guardar; los cambios pendientes se conservan y
   no hay indicador permanente. Evidencia: `test_edit_connected::test_open_user_transaction_rejects_the_save`.

## 5. Limitaciones conocidas

- El dibujo completo de una capa Conectada cuesta unas 4 veces lo de la Instantánea: cada entidad se
  construye en Python (el estudio lo había previsto). Para recorrer o dibujar todo, usar Memoria o
  Instantánea.
- Sin la extensión `spatial` cargada, la extensión de la capa sale de las estadísticas de DuckDB: en
  tablas es una cota superior; en consultas complejas puede faltar («Zoom a la capa» no disponible).
- Capas sin clave primaria (`fid=content`): filas idénticas comparten FID (QGIS no las distingue, pero
  se leen todas); cambiar una fila cambia su FID; el FID puede cambiar con otra versión de DuckDB. Dibujar
  1 M de filas sin clave: 9,4 s (con clave, 5,3 s).
- Las capas Conectadas de `:memory:`, `TEMP` o de un resultado del editor no sobreviven a la sesión:
  quedan no disponibles y nunca muestran datos homónimos de otra sesión.
