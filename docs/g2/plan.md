# G2 · `v0.3.0a1` SQL Execution — plan de inicio

**Estado:** **Autorizado** (2026-11-01), con las decisiones de §4. El alcance es el del roadmap; no se
amplía.

**Objetivo (roadmap §2):** scripts mixtos, resultados y previews; ATTACH/DETACH desde SQL conciliados con la
UI (GD-SES-003, parte SQL).
**Requisitos P0:** GD-SQL-001..006, GD-SES-003 (SQL).
**Gate de salida:** «2 SELECT y CREATE correctos; no reejecución DML» (AT-SQL-001..006).
**Contrato:** `spec/specs/sql-editor-spec.md`, ADR-0004; ADR-0006 y ADR-0007 para la ejecución.

## 1. Orden de trabajo (un issue y un PR por paso)

| Paso | Trabajo | Requisito / prueba |
|---|---|---|
| 1 | **Pruebas breves** (decisión 1). **Spike G2-A** (roadmap §3): `extract_statements` en 1.5.x y 2.x (tipos de sentencia, posiciones en el texto para mapear errores y selección), multisentencia, `RETURNING`, `WITH … INSERT`. Junto con el **spike G0-B** (#11): editor SQL nativo en PyQGIS 3/4 (`QgsCodeEditorSQL` u otro), con una sola implementación principal | Evidencia en `docs/evidence/g2/`; decisión del arquitecto |
| 2 | Modelo de ejecución: `run_id`, `statement_id`, tipo, estado, `duration_ms`, mensaje, `error_range`, `catalog_epoch`; tipos de salida (estado, lectura tabular, escritura con filas, plan) | sql-editor-spec §2–§3 |
| 3 | Motor: división con el parser oficial (nunca `split(';')`), ejecución en orden en el worker serial, parada en el primer error. **Estado transaccional comprobado después de cada sentencia** (decisión 2) | GD-SQL-001, 002; AT-SQL-001, 002 |
| 4 | Vista previa acotada (50/200/500/1000; 200 por defecto) sin `fetchall()` y sin dejar lectores abiertos | GD-SQL-005; AT-SQL-005 |
| 5 | Caso de uso «ejecutar sentencia actual / selección / todo», cancelación y eventos por sentencia; conciliación del catálogo tras ATTACH/DETACH/CREATE/DROP en SQL; **invalidación conservadora de las previews** (decisión 3) | GD-SQL-004; GD-SES-003 (SQL); AT-SQL-004 |
| 6 | Política de repetición: qué resultados se pueden volver a ejecutar para G3 (solo lecturas) y cuáles nunca (DDL/DML, `RETURNING`, ATTACH/DETACH) | GD-SQL-006; AT-SQL-006 |
| 7 | UI: editor, acciones, pestañas de resultados con «Vista previa», registro de ejecuciones y errores con ubicación cuando DuckDB la dé | sql-editor-spec §1, §7 (P0); AT-SQL-003 |

Cada paso mantiene las fronteras de ADR-0010 y se prueba con DuckDB 1.5.0, 1.5.6 y 2.0.0, y con PyQGIS 3.44
y 4.2 cuando toca la UI.

## 2. Lo que ya existe de G1 y se reutiliza

- Worker serial con guardia de lector abierto, cancelación e invalidación (ADR-0006, ADR-0007, C13).
- Comprobación del estado transaccional, `TRANSACTION_ABORTED`, COMMIT/ROLLBACK y recuperación segura.
- Catálogo conciliado con DuckDB y explorador; el `BEGIN`, `COMMIT` y `ROLLBACK` escritos en SQL se
  reflejarán con la misma comprobación.

## 3. En paralelo, sin bloquear

- Certificación Windows (#10).
- Modernización visual del panel: GD-UX-001, en G5 (decisión del 2026-11-01).

## 4. Decisiones del arquitecto (2026-11-01)

1. **Pruebas breves primero:** parser de DuckDB (spike G2-A) y editor SQL en QGIS 3 y 4 (spike G0-B, #11),
   con evidencia, antes de construir la UI.
2. **Estado transaccional después de cada sentencia ejecutada**, sin excepciones por tipo de sentencia. Se
   usa la comprobación de G1 (dos lecturas de `txid_current()`).
3. **Invalidación conservadora de vistas previas.** Toda sentencia que pueda cambiar estructura o datos
   (cualquiera que no sea una lectura, según el tipo que da el parser, y también un error o una
   cancelación) marca como **posiblemente obsoletas** todas las vistas previas anteriores de la sesión.
   GeoDuck **no promete** detectar cambios hechos fuera de la sesión (otros procesos, archivos externos):
   una vista previa nunca se presenta como el estado actual de los datos.
