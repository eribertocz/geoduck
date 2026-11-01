# G1 · `v0.2.0a1` Connections — plan de inicio

**Estado:** Propuesta (2026-11-01). Empieza cuando se apruebe el cierre de G0. El alcance es el del roadmap; no se amplía.

**Objetivo (roadmap §2):** archivo RO/RW, catálogo, ATTACH/DETACH por UI y SQL.
**Requisitos P0:** GD-SES-002, 003, 004 y 005; GD-CAT-001; invalidación de sesión (C13, #31).
**Gate de salida:** liberación real de bloqueos y temporales coherentes; invalidación de sesión notificada una
sola vez (INV-1..INV-5).

## 1. Orden de trabajo (un issue y un PR por paso)

| Paso | Trabajo | Requisito / prueba | Capas |
|---|---|---|---|
| 1 | Invalidación de sesión: evento único `SessionInvalidated`, código `SESSION_INVALIDATED`, `READY → ERROR_RECOVERABLE`, sin retorno a `READY` con la misma conexión | #31, INV-1..INV-5 | domain, engine, app, ui |
| 2 | Modelo de catálogo: bases adjuntas (alias, ruta, acceso, predeterminada), conciliado siempre con `duckdb_databases()` | GD-CAT-001 (base) | domain, engine |
| 3 | `AttachDatabase` y `StartSession(mode=file)`: RO/RW explícito, «abrir existente» frente a «crear nueva», ruta y alias citados como literales (F-06: `ATTACH ?` no funciona en 1.5), errores `DB_NOT_FOUND`, `DB_LOCKED`, `DB_ALIAS_CONFLICT`, `DB_READ_ONLY` | GD-SES-002, AT-SES-002 | engine, app |
| 4 | `DetachDatabase`: estado `DETACHING`, rechazo o cola con lector Arrow abierto, `USE` del catálogo raíz real si el alias era el predeterminado, verificación de que el catálogo desaparece, `DETACH_FAILED`, `DEFAULT_CATALOG` | GD-SES-004, AT-SES-004 | engine, app |
| 5 | Liberación real de bloqueos: tras `DETACH`, otro proceso abre el archivo en RW | gate de G1 | tests/engine |
| 6 | ATTACH/DETACH escritos en SQL: conciliación del catálogo después de cada sentencia | GD-SES-003, AT-SES-003 | engine, app |
| 7 | Coherencia de sesión: `USE`, temporales, parámetros y transacciones; `TRANSACTION_ABORTED` y validación transaccional antes de reutilizar la conexión | GD-SES-005, AT-SES-005; ADR-0007 puntos 5 y 6 | engine, app |
| 8 | Explorador de catálogo en el panel: catálogos, esquemas, tablas y vistas; se actualiza después del éxito, nunca antes | GD-CAT-001, AT-CAT-001 | ui |

Cada paso cumple las fronteras de ADR-0010 (test de arquitectura) y se prueba con DuckDB 1.5.0, 1.5.6 y 2.0.0,
y con PyQGIS 3.44 y 4.2 cuando toca la UI.

## 2. Pruebas mínimas (session-spec §6)

Memoria con tabla temporal y cierre; archivo existente en RO (lectura sí, escritura rechazada); archivo RW
con escritura persistente y bloqueo liberado al `DETACH`; `ATTACH` en SQL reflejado en la UI; `DETACH` en la
UI invalida lecturas futuras de ese alias; `USE <alias>` seguido de `DETACH <alias>`; lector Arrow abierto
que bloquea el `DETACH` hasta liberarse; base bloqueada por otro proceso con error claro y sin estado
fantasma; INV-1..INV-5.

## 3. En paralelo, sin bloquear G1

- Certificación Windows (#10), un paso a la vez: QGIS 3.44 LTR, luego 4.2.x, luego regresión en 3.34.
- Spike G0-B (#11), antes de G2.

## 4. Preguntas para el arquitecto

1. **SQL en G1.** GD-SES-003 pide ATTACH/DETACH «por UI y SQL», pero el editor SQL llega en G2. ¿Se acepta
   una entrada mínima de una sola sentencia en G1 (sin scripts ni resultados múltiples), o la parte SQL de
   GD-SES-003 pasa a G2?
2. **Crear archivo.** Para RW, ¿se aprueban dos acciones explícitas, «Abrir existente» y «Crear nueva», sin
   crear nunca un archivo de forma implícita (session-spec §2)?
3. **Cierre con transacción abierta.** `CloseSession` pide «finalizar/rollback según política explicitada
   al usuario». ¿La política por defecto es preguntar, y `ROLLBACK` si el usuario cancela o cierra QGIS?
