# G2 · `v0.3.0a1` SQL Execution — Documento de aceptación (propuesta de cierre)

**Estado:** Propuesta para aprobación (2026-11-01). G2 se cierra al aprobarse y fusionarse este documento.
Sin tag ni release. **Commit verificado:** `cb81e8a` en `main` (merge de #54).

## 1. Requisitos y gate

| Requisito | Prueba | Evidencia | Resultado |
|---|---|---|---|
| GD-SQL-001 · SQL nativo de DuckDB | AT-SQL-001 | `tests/engine/test_sql_execution.py` (CREATE, INSERT, UPDATE, RETURNING, EXPLAIN, SET, PRAGMA, ATTACH/DETACH, macros) | Cumple |
| GD-SQL-002 · script multisentencia en orden, con estado por sentencia | AT-SQL-002 | `test_create_and_two_selects_in_order_with_two_results`, `test_first_error_stops_the_rest`, `test_syntax_error_executes_nothing` | Cumple |
| GD-SQL-003 · resultados independientes por sentencia | AT-SQL-003 | `tests/qgis/test_sql_panel.py` (una pestaña por resultado, con nombre y SQL de origen) | Cumple |
| GD-SQL-004 · actual, selección o todo | AT-SQL-004 | `test_current_runs_only_the_statement_under_the_cursor`, `test_selection_runs_only_the_selected_text_with_editor_positions`, `test_current_statement_only` | Cumple |
| GD-SQL-005 · vista previa sin `fetchall()` | AT-SQL-005 | `test_preview_is_bounded` (1 000 000 filas, límites 50/200/500/1000), `test_no_reader_or_result_is_left_open` | Cumple |
| GD-SQL-006 · no repetir DDL/DML; política de SELECT explícita | AT-SQL-006 | `test_outputs_and_replayability_follow_the_parser_type`, `test_returning_is_executed_exactly_once` | Cumple la política: solo una lectura es repetible. **La carga en QGIS que la usa es G3** |
| GD-SES-003 (parte SQL) · ATTACH/DETACH escritos en SQL conciliados con la UI | AT-SES-003 | `test_attach_in_sql_is_reflected_in_the_explorer` | Cumple |

**Gate (roadmap §2): «2 SELECT y CREATE correctos; no reejecución DML».** Cumple: `test_create_and_two_selects…`
(motor y panel) y `test_returning_is_executed_exactly_once`.

## 2. Decisiones aplicadas

- Pruebas breves primero (#51): parser de DuckDB fiable (F-34..F-39) y `QgsCodeEditorSQL` como editor único
  en QGIS 3 y 4 (F-40, F-41). Cierra #11.
- Estado transaccional comprobado después de cada sentencia; transacción abortada → `ERROR_RECOVERABLE` con
  «Revertir transacción».
- Invalidación conservadora de vistas previas («Posiblemente obsoleta»); sin promesas sobre cambios externos.
- Interfaz SQL: divisor de tres zonas, pestañas descriptivas, «Acerca de GeoDuck» (#54); versión mostrada
  derivada de la del paquete.

## 3. Verificación de `main` (`cb81e8a`)

| Comprobación | Resultado |
|---|---|
| CI (14 jobs) | 14/14 |
| ruff, formato, mypy | Sin errores |
| Unitarias, arquitectura y motor | 495 con DuckDB 1.5.0, 1.5.6 y 2.0.0, y con PyArrow 18.1.0 + NumPy 1.26.4 |
| Motor repetido 3 veces | 137/137 las tres veces |
| PyQGIS 3.44.14 y 4.2.3 (Linux, sin interfaz) | 35/35 |
| `spec/` y ZIP | Coherentes; ZIP reproducible |

## 4. Abierto, sin bloquear

| Tema | Fase |
|---|---|
| «Cargar en QGIS» (usa `replayable`) | G3 |
| Autocompletado (AT-SQL-007) y editor P1 | G5 |
| Modernización visual (#49) | G5 |
| Certificación Windows (#10) | Calidad, en paralelo |

Tag y release `v0.3.0a1`: requieren aprobación expresa.
