# G8 · `v0.9.0a1` QGIS → DuckDB — evidencia de aceptación (AT-IMP-001..008)

**Estado:** Propuesto para aceptación (E5). El tag y la release `v0.9.0a1` los hace el propietario.
**Base verificada:** E5 sobre E0–E4 (#104, #105, #106, #108, #109, #110) y la corrección F-121 (#107). Las
cifras de la CI de este PR se anotan en un comentario del PR. **Contrato:** `docs/g8/plan.md`,
`spec/specs/qgis-import-spec.md` (GD-IMP-001..007), ADR-0015, `docs/g8/maqueta/`, `spec/qa/test-strategy.md`.

## 1. Matriz

La CI de GitHub ejecuta en cada PR la suite completa de `tests/qgis` en QGIS 3.34.6, 3.40.3, 3.44.14 (Qt 5)
y 4.2.3 (Qt 6) × DuckDB 1.5.0 y 2.0.0; el motor y las unitarias en DuckDB 1.5.0, 1.5.6 y 2.0.0 (Python 3.12
y 3.14, PyArrow 25.0.1 y 18.1.0); lint, tipos, arquitectura (ADR-0010), `spec_sync --check` e `i18n --check`.

En local, antes de cada PR (una suite cada vez): QGIS 3.34.6, 3.44.14 y 4.2.3 con DuckDB 2.0.0 y 3.44.14 con
DuckDB 1.5.0; sin QGIS, DuckDB 1.5.0 y 2.0.0.

Linux headless no certifica Windows: la prueba manual de G8 está en
[`docs/certification/send-to-duckdb.md`](../certification/send-to-duckdb.md).

## 2. Criterios de aceptación

Archivos en `tests/`: `qgis/test_send_ui.py` (S), `qgis/test_import_layers.py` (L),
`qgis/test_load_with_geoparquet_open.py` (P), `engine/test_import.py` (m-I), `engine/test_arrow_plain.py`
(m-A), `unit/test_importing.py` (u-I), `unit/test_coordinator_send.py` (u-C).

| AT | Escenario | Evidencia |
|---|---|---|
| AT-IMP-001 | Menú de capa con una y varias capas; «+» del workspace; ráster; sin sesión | S `test_plugin_registers_the_layer_action_and_the_plus_entry`, `test_raster_layer_is_shown_disabled_with_its_reason`, `test_from_the_plus_nothing_is_checked_without_a_selection`, `test_without_session_it_explains_what_to_do`, `test_two_layers_with_the_same_table_name` (dos capas en un diálogo) |
| AT-IMP-002 | Tabla nueva, existente y nombre repetido | S `test_new_table_and_send_with_defaults`, `test_existing_table_is_not_sent_by_default`, `test_replace_append_and_another_name`, `test_two_layers_with_the_same_table_name`, `test_open_and_undo_from_the_message_bar`, `test_failure_says_nothing_changed`; m-I `test_create_never_overwrites_an_existing_table`, `test_undo_drops_only_new_tables_and_views` |
| AT-IMP-003 | Solo seleccionadas; filtro; reproyectar; vista sobre Parquet | L `test_memory_layer_selection_and_filter`, `test_connected_layer_selection`, `test_geoparquet_copy_and_view`, `test_reproject_transforms_with_qgis_and_labels_the_target_crs` (0,01 m frente a `QgsCoordinateTransform`), `test_reproject_needs_a_source_crs`, `test_a_connected_layer_of_this_session_is_not_reprojected`; S `test_only_selected_appears_with_a_selection`, `test_reproject_from_the_dialog`, `test_reproject_without_source_crs_is_blocked`, `test_reproject_without_target_crs_cannot_send`; m-I `test_sql_path_view_and_append` |
| AT-IMP-004 | Fallo en la segunda capa; cancelar a mitad; conteo distinto forzado | L `test_all_or_nothing`, `test_cancel_rolls_back` (150 000 entidades), `test_a_forced_count_mismatch_rolls_back`, `test_open_user_transaction_is_left_intact`; m-I `test_all_or_nothing_when_the_second_layer_fails`, `test_reader_failure_rolls_back`, `test_cancel_rolls_back_and_stops_the_producer`, `test_sql_and_arrow_paths_share_the_transaction`; u-C `test_cancel_reports_cancelled_and_returns_to_ready`, `test_engine_failure_is_reported` |
| AT-IMP-005 | Conectada, Parquet, GeoPackage, Shapefile, memoria y CSV | L `test_connected_layer_is_copied_inside_duckdb`, `test_geoparquet_copy_and_view` (omitida en 3.34: GDAL de conda-forge sin Parquet), `test_geopackage_types_geometry_name_and_crs`, `test_shapefile_has_no_geometry_name_so_it_is_geom`, `test_memory_layer_selection_and_filter`, `test_csv_without_geometry`; el camino de cada una, en el resumen (S `test_new_table_and_send_with_defaults`) |
| AT-IMP-006 | Tipos de §6; `ID` e `id`; añadir con columnas incompatibles | L `test_geopackage_types_geometry_name_and_crs`, `test_lists_and_maps`, `test_fields_that_differ_only_in_case_are_renamed`; S `test_append_with_incompatible_columns_says_which`; m-I `test_types_are_cast_to_the_planned_duckdb_types`; u-I `test_duck_type_for`, `test_append_*` |
| AT-IMP-007 | EPSG:4326, EPSG:32719, personalizado, sin SRC; Z/M, colección, `NULL`, inválida | L `test_custom_crs_goes_as_projjson_and_comes_back`, `test_without_crs_is_explicit`, `test_z_m_collections_null_and_invalid_go_and_come_back` (WKB idéntico byte a byte; vuelta a QGIS con SRC y Z); S `test_old_file_format_offers_without_crs` (F-120), `test_custom_crs_is_announced`, `test_append_after_reprojecting_compares_the_target_crs`; m-I `test_custom_crs_as_projjson_and_no_crs`, `test_old_file_format_cannot_store_the_crs_and_nothing_is_written`. Sin `spatial` en todas |
| AT-IMP-008 | Regresión G0–G7 | Toda la suite pasa en cada celda. Pruebas adaptadas solo donde dependían del menú «+» (un elemento más) |

## 3. Gate (`docs/g8/plan.md`)

| Condición | Estado |
|---|---|
| AT-IMP-001..008 en la matriz de CI | Cumplida (§2; cifras en el comentario del PR) |
| Velocidad del camino general medida y publicada (100 mil y 1 millón) | Cumplida: [`docs/evidence/g8/velocidad/`](../evidence/g8/velocidad/README.md), 120–175 mil entidades/s; 1 millón en 5,7–8,3 s |
| Guía manual en Windows | Cumplida: [`docs/certification/send-to-duckdb.md`](../certification/send-to-duckdb.md); la ejecución en Windows la hace el propietario |
| Regresiones G0–G7 | Cumplida |
| Nada de G3–G7 cambia de comportamiento | Cumplida; F-121 (#107) corrige un fallo previo de las cargas |

## 4. Decisiones del propietario durante G8

| Fecha | Decisión |
|---|---|
| 2026-11-05 | QGIS → DuckDB aprobado como G8 (ADR-0015); orden A: G8, G9 Workspace Pro, G10 Performance, G11 Reliability & Distribution, G12 Public Alpha |
| 2026-11-05 | Si la tabla existe: por defecto «No enviar» |
| 2026-11-05 | Destino «Tabla temporal (solo esta sesión)»; geometría con el nombre que trae la capa o `geom`; aviso de capa grande (más de un minuto a 100 mil/s) sin bloquear |
| 2026-11-05 | F-120: una base de formato antiguo no guarda el SRC → el usuario elige «sin SRC» u otra base |
| 2026-11-05 | F-121 se corrige en un PR aparte (#107), antes de E2 |
| 2026-11-05 | E3 y E4 en el estilo actual de la interfaz; se rehacen en G9 (interfaz nueva desde cero, Qt Widgets con sistema de diseño propio, sin motor web; facilidad máxima sin perder detalle) |
| 2026-11-05 | «Reproyectar a…» global para todo el envío; por capa, solo como opción avanzada si G9 lo pide |
| 2026-11-05 | F-122 se corrige en un PR aparte antes de cerrar G8 |
| 2026-11-05 | Para G9: una sola «Copia» (por dentro la Copia rápida; la Copia en memoria solo como respaldo automático si GDAL no permite la rápida), además de «Conectada»; antes, comprobar en el spike de G9 guardar y reabrir el proyecto |

## 5. Velocidad

Ver [`docs/evidence/g8/velocidad/README.md`](../evidence/g8/velocidad/README.md).

## 6. Hallazgos

| ID | Hallazgo | Resolución |
|---|---|---|
| F-114..F-120 | Spike G8-A (velocidad, `ST_SetCRS` sin `spatial`, PROJJSON, hilos, Parquet, selección, formato antiguo) | `docs/evidence/g8/spike/README.md`; aplicados en E1–E4 |
| F-121 | Al abrir un GeoParquet en QGIS de conda, GDAL registra `geoarrow.wkb` y las cargas DuckDB → QGIS fallaban o perdían el SRC | Corregido en #107 |
| F-122 | Al cargar en QGIS una columna `GEOMETRY('EPSG:32719')`, la capa queda **sin SRC** si es **Conectada** con tipos de geometría mixtos o con `GEOMETRYCOLLECTION`, o si es **Copia rápida** (Instantánea) con `GEOMETRYCOLLECTION`. «Copia en memoria» y una sola familia simple, bien (verificado en QGIS 3.44, DuckDB 2.0.0). Previo a G8 (G4); la tabla enviada sí guarda el SRC | **Abierto**: corrección propuesta en un PR aparte, a decisión del propietario |
| — | PyQGIS pierde el `run` de una `QgsTask` sin referencia de Python, y QGIS la borra al terminar | La tarea se guarda viva y no se toca después (E2) |
| — | Qt 5 da el nombre del tipo de un campo como `QByteArray`; Qt 6 como `bytes` (subtipo `None`) | `type_name` cubre los dos (E2) |
| — | Cancelar a mitad de una sentencia: la interrupción de DuckDB llegaba como error y no como cancelación (1 vez en la suite de QGIS 3.44) | El envío la informa como cancelación (E5) |
| — | Reproyectar una capa Conectada de la misma sesión bloquearía el worker (QGIS le pediría páginas mientras escribe el envío) | Se rechaza con su motivo (E4) |

## 7. Limitaciones conocidas

- Es una copia puntual: sin sincronización ni vínculo vivo con la capa de QGIS (ADR-0015).
- Una capa Conectada de la sesión se envía con su SRC: no se reproyecta al enviar.
- «Añadir filas» con un SRC personalizado compara el texto PROJJSON: dos definiciones equivalentes escritas
  distinto se consideran distintas.
- Una capa con tipo de geometría «desconocido» (GeoPackage `GEOMETRY`) recibe de QGIS sus geometrías con la
  dimensión que QGIS asigna a la capa; GeoDuck guarda lo que QGIS entrega.
- La interfaz de E3 y E4 es la actual; la nueva llega en G9.
