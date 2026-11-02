# G4 · `v0.5.0a1` Spatial Confidence — evidencia de aceptación (AT-SPA-001..004)

**Estado:** En revisión (E5). El cierre de G4 lo decide el propietario; no autoriza tag ni release `v0.5.0a1`.
**Base verificada:** `483e199` en `main` (merge de #76, con E0–E4 fusionados en #70–#74), CI 18/18.
**Contrato:** `spec/specs/spatial-spec.md`, `spec/qa/test-strategy.md` (AT-SPA), `docs/g4/plan.md` (gate),
ADR-0008, ADR-0011, ADR-0012. Versión en `metadata.txt`: `0.4.0a2` (sin cambios en E5).

## 1. Matriz verificada

Cada celda es una ejecución completa de `tests/qgis` (QGIS headless, `QT_QPA_PLATFORM=offscreen`) en la CI de
GitHub (Linux), con la extensión `spatial` instalada por el entorno de pruebas (no por GeoDuck, §10):

| QGIS | DuckDB 1.5.0 | DuckDB 2.0.0 |
|---|---|---|
| 3.34.6 (mínima, Qt 5) | 198 pasan, 1 omitida | 199 pasan |
| 3.40.3 LTR (Qt 5) | 198 pasan, 1 omitida | 199 pasan |
| 3.44.14 LTR (Qt 5) | 198 pasan, 1 omitida | 199 pasan |
| 4.2.3 (Qt 6) | 198 pasan, 1 omitida | 199 pasan |

La omitida es AX-3 (`ST_Transform` sin orden de ejes declarado): solo existe en DuckDB 2.0, donde
`geometry_always_xy` no tiene valor por defecto. Es la omisión prevista por spatial-spec §8, no un fallo.

Motor y unitarias (`tests/unit tests/engine`): 498 pasan con DuckDB 1.5.0, 1.5.6 y 2.0.0, Python 3.12 y 3.14,
PyArrow 25.0.1 y 18.1.0 (las versiones de QGIS 3.34 para Windows). Lint: ruff, mypy, test de fronteras de
arquitectura (ADR-0010) y `tools/spec_sync.py --check`, limpios (489 pruebas unitarias y de arquitectura).

E5 añade una prueba (§2, AT-SPA-004): en este PR cada celda QGIS suma una (199/200). Las cifras de la CI del
PR se anotan en su descripción.

**Regresión de G0–G3:** toda la suite anterior sigue en verde en cada celda (AT-BRD-001..012, ver
`docs/g3/acceptance.md`); ninguna prueba de G3 se modificó para pasar.

Linux headless **no** certifica Windows: la prueba manual de G4 está en
[`docs/certification/spatial.md`](../certification/spatial.md) §7 (#10 sigue abierta y no bloquea).

## 2. Criterios de aceptación

Rutas relativas a `tests/qgis/` salvo que se indique `tests/engine/`.

### AT-SPA-001 — 0/1/2 geometrías; `BLOB`/`VARCHAR` marcadas y sin marcar

| Escenario | Evidencia |
|---|---|
| 0 geometrías → tabla QGIS sin geometría | `test_load_memory::test_empty_result_and_table_without_geometry` |
| 1 geometría → se elige sola; las demás se nombran en un aviso | `test_load_memory::test_prepare_reports_geometries_and_warnings`, `test_multi_geometry::test_one_column_checked_makes_exactly_one_layer` |
| 2 geometrías → selector múltiple (una marcada por defecto, al menos una obligatoria) | `test_multi_geometry::test_dialog_marks_geometries_and_candidates` |
| `BLOB` (WKB, también big-endian) y `VARCHAR` (WKT) marcadas → geometría en las tres modalidades; el origen no cambia | `test_multi_geometry::test_marked_blob_or_text_column_is_a_geometry[memory/snapshot/connected × wkb/wkt]` (6 casos; compara `hash()` del origen antes y después) |
| Sin marcar nunca son geometría (sin inferencia por nombre ni contenido) | `test_multi_geometry::test_unmarked_blob_and_text_are_never_geometries` |
| Conversión `TRY(…)` sin `spatial`; ilegible = valor no nulo → `NULL` | `tests/engine/test_geometry_sql::test_wkb_and_wkt_columns_convert_and_unreadable_is_null` |
| Conectada: la edición escribe de vuelta en WKB o WKT | `test_multi_geometry::test_connected_edit_writes_back_in_the_column_format[wkb/wkt]` |

### AT-SPA-002 — centroide + polígono: una y ambas capas, en las tres modalidades

| Escenario | Evidencia |
|---|---|
| Ambas marcadas → dos capas completas `<capa> · <columna>`, cada una con su CRS (uno declarado, otro elegido) y su tipo, mismos atributos sin la otra geometría | `test_multi_geometry::test_two_geometries_make_two_complete_layers[memory/snapshot/connected]` |
| Una marcada → exactamente una capa; la otra columna se avisa | `test_multi_geometry::test_one_column_checked_makes_exactly_one_layer` |
| Conectada: cada capa filtra la extensión por su propia columna y es editable | `test_multi_geometry::test_connected_filters_each_layer_by_its_own_column` |
| Error en una de las columnas → no se publica ninguna (y `/vsimem` queda libre) | `test_multi_geometry::test_error_in_any_column_publishes_nothing[memory/snapshot/connected]` |
| Cancelación a mitad (3 M de filas, dos columnas) → no se publica ninguna, sin GeoPackage huérfano | `test_multi_geometry::test_cancel_during_a_multiple_load_publishes_nothing[memory/snapshot]` |

La Conectada no tiene cancelación a mitad de lectura: crea el proveedor sin copiar datos (G3).

### AT-SPA-003 — CRS declarado y ausente; AX-1..AX-5; «Reproyectar a…»

Todas en `test_crs_axes`, con el punto de La Paz y las tolerancias de spatial-spec §8 (1e-9 grados, 0,01 m).
Cada prueba comprueba coordenadas **y** CRS.

| ID | Evidencia |
|---|---|
| AX-1a `OGC:CRS84` | `test_ax_1a_crs84[memory/snapshot/connected]` |
| AX-1b `EPSG:4326`, x = longitud aunque `hasAxisInverted()` | `test_ax_1b_epsg_4326_keeps_x_as_longitude[…]` |
| AX-1c `ST_Transform` del SQL del usuario; forma de cuatro argumentos sin CRS (F-99) | `test_ax_1c_st_transform_from_user_sql[…]`, `test_ax_1c_four_argument_form_declares_no_crs[…]` |
| AX-2 `geometry_always_xy` visible en diagnóstico y resultados, nunca modificado | `test_ax_2_axis_setting_is_shown_never_changed` |
| AX-3 sin orden declarado (DuckDB 2.0) → error del SQL del usuario, sin capa ni reintento | `test_ax_3_st_transform_without_axis_order_is_the_users_error` |
| AX-4a sin CRS: no se asigna ninguno | `test_ax_4a_without_crs_none_is_assigned[…]` |
| AX-4b `FOO:123`: se conserva en el mensaje y se pregunta en el diálogo | `test_ax_4b_unknown_crs_is_kept_in_the_message_not_replaced[…]`, `test_ax_4b_dialog_asks_when_qgis_does_not_recognize_the_crs` |
| AX-4c elegir `EPSG:4326` etiqueta y no mueve | `test_ax_4c_choosing_a_crs_labels_without_moving[…]` |
| AX-5 «Reproyectar a EPSG:32719» en copias con QGIS/PROJ | `test_ax_5_reproject_copies_with_qgis[memory/snapshot]`, `test_reproject_needs_a_source_crs[…]`, `test_reproject_after_choosing_the_source_crs` |
| La Conectada nunca se reproyecta; el diálogo solo ofrece reproyectar copias con CRS | `test_connected_is_never_reprojected`, `test_dialog_offers_reprojection_only_for_copies_with_crs` |
| «Activar spatial…» (ADR-0011, §10): sin consentimiento no carga; `LOAD` vale para la sesión; `INSTALL` se pregunta aparte y puede rechazarse | `test_spatial_is_not_loaded_without_consent`, `test_spatial_loads_for_this_session_with_consent`, `test_install_is_asked_separately_and_can_be_declined` |
| Sin CRS en la UI: se pregunta (G3, sigue igual) | `test_load_ui::test_unknown_crs_is_asked`, `test_load_memory::test_unknown_crs_warns_or_uses_the_user_choice` |

### AT-SPA-004 — ilegibles, mixtas, colecciones, Z/M/ZM, NULL, vacías, inválidas

| Escenario | Evidencia |
|---|---|
| WKB/WKT ilegible en copias → la carga falla con columna y fila, sin publicar | `test_multi_geometry::test_unreadable_value_fails_a_copy_with_its_row[memory/snapshot × wkb/wkt]` |
| WKB ilegible en Conectada → entidad sin geometría y aviso con su número | `test_multi_geometry::test_unreadable_value_in_connected_is_counted_and_shown_without_geometry` |
| Familias mixtas en copias → una capa por familia (más «sin geometría»), sin perder filas; opción desactivada → error con los tipos | `test_families::test_copies_split_mixed_families_without_losing_rows[memory/snapshot]`, `::test_copies_refuse_mixed_families_when_the_option_is_off[…]`, `test_load_snapshot::test_mixed_geometry_types_become_one_layer_per_type` |
| Una sola familia: las `NULL` quedan en su capa; una múltiple tardía hace la capa Multi | `test_families::test_memory_single_family_keeps_nulls_in_the_layer`, `::test_memory_multi_part_found_late_makes_the_layer_multi` |
| Z tardía se conserva; las 2D reciben `NaN` con aviso (F-97) | `test_families::test_z_found_late_is_kept_and_2d_rows_get_nan[memory/snapshot/connected]` |
| M, ZM y `GEOMETRYCOLLECTION` llegan tal cual | `test_families::test_m_zm_and_collections_load_as_they_are[…]` |
| Conectada mixta → una capa `Unknown` con todas las filas y aviso | `test_families::test_connected_mixed_is_one_unknown_layer_with_every_row` |
| «Separar por tipo» → una Conectada por familia con el filtro empujado a DuckDB; sin duplicados; las `NULL` se avisan | `test_families::test_connected_separate_types_pushes_the_family_filter`, `::test_editing_a_separated_layer_stays_in_its_family` |
| Tipo leído de todas las cabeceras WKB, no de una muestra (F-93, PR #73): un polígono en la última de 20 000 filas no se pierde | `test_families::test_connected_reads_the_type_of_every_row_not_a_sample` (**nueva en E5**), `test_load_connected::test_geometry_type_from_wkb_headers`, `tests/engine/test_geometry_sql::test_family_from_the_wkb_header_without_spatial` |
| Diagnóstico: cuenta NULL/vacía/ilegible/inválida/válida, con motivo de GEOS; no cambia la capa ni el origen | `test_validity::test_diagnosis_counts_each_state_and_changes_nothing[memory/snapshot/connected]`, `::test_connected_marked_wkb_counts_unreadable_apart_from_null` |
| Menú de capa «Diagnosticar geometrías…» selecciona inválidas e ilegibles | `test_validity::test_layer_menu_action_diagnoses_and_selects` |
| «Reparar en una copia…»: pide confirmación; copia nueva con `makeValid`, cambios de tipo/partes informados (F-98); la original no cambia | `test_validity::test_dialog_asks_before_repairing`, `::test_repair_makes_a_new_copy_and_reports_every_change` |
| Cancelar diagnóstico o reparación → no publica nada | `test_validity::test_cancel_publishes_nothing` |

## 3. Gate (`docs/g4/plan.md`)

| Condición | Estado |
|---|---|
| AT-SPA-001..004 verdes en QGIS 3.34/3.40/3.44/4.2 × DuckDB 1.5.0/2.0.0 | Cumplida (§1, §2) |
| Contratos de G3 intactos (AT-BRD-001..012) | Cumplida: suite completa en verde en cada celda |
| C4 y ADR-0011 demostrados (AX-1..AX-5) | Cumplida: AX-1..AX-5 y «Activar spatial…» (§2, AT-SPA-003) |
| Ninguna pérdida silenciosa ni entrega parcial | Cumplida: errores y cancelaciones sin publicar; cada fila en una capa o avisada (AT-SPA-002, 004) |
| Evidencia manual Windows de G4 registrada | **Pendiente**: guía en `docs/certification/spatial.md` §7; la ejecuta el propietario |

## 4. Decisiones del propietario (2026-11-02), aplicadas

Las de `docs/g4/plan.md` §1 (D1–D5, 8, 9) y, durante la revisión de E3 (PR #73), el tipo de la Conectada se
lee de **todas** las cabeceras WKB y no de una muestra (corregido en el spike, F-93).

## 5. Limitaciones conocidas

- Varias geometrías: cada capa se lee con su propia consulta. En tablas el resultado es idéntico; una consulta
  no determinista (p. ej. `random()`) puede dar valores distintos en cada capa (hallazgo de E1).
- Capa Conectada `Unknown` (tipos mixtos sin separar): QGIS no ofrece simbología por tipo; se avisa.
- Las capas por familia se llaman `<capa> — <Tipo>`; las de varias columnas, `<capa> · <columna>`. GeoDuck no
  renombra si ya existe en el proyecto una capa con el mismo nombre (QGIS lo permite). Ver §6.
- Copias: un valor ilegible detiene la carga (por diseño, §3 de la SPEC). Para ver cuáles son, cargar como
  Conectada y usar «Diagnosticar geometrías…».
- La reparación usa `makeValid` de QGIS/GEOS: no promete preservar la geometría exacta; puede cambiar la
  familia (anillo degenerado → línea, F-98) y entonces la copia se separa por familia.
- Las pruebas AX que necesitan `spatial` dependen de que el entorno la tenga instalada; sin red hacia
  `extensions.duckdb.org` se omiten (en la CI se instalan y se ejecutan).

## 6. Observación para el propietario (sin cambios en E5)

**F-100.** spatial-spec §7 dice que los nombres `<nombre> · <columna>` son «únicos en el proyecto». Son únicos
entre las capas de una misma carga, pero si se carga dos veces la misma consulta, QGIS tendrá dos capas con el
mismo nombre (como con cualquier capa de QGIS). No se cambia en E5 («sin funciones nuevas»); si se quiere un
sufijo automático, es una decisión de alcance.
