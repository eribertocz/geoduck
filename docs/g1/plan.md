# G1 · `v0.2.0a1` Connections — plan de inicio

**Estado:** **Autorizado** (2026-11-01). El alcance es el del roadmap, con las decisiones de §4; no se amplía.

**Objetivo (roadmap §2):** archivo RO/RW, catálogo, ATTACH/DETACH por UI. ATTACH/DETACH escritos en SQL
pasan a G2.
**Requisitos P0:** GD-SES-002, 003 (solo la UI), 004 y 005; GD-CAT-001; invalidación de sesión (C13, #31).
**Gate de salida:** liberación real de bloqueos y temporales coherentes; invalidación de sesión notificada una
sola vez (INV-1..INV-5).

## 1. Orden de trabajo (un issue y un PR por paso)

| Paso | Trabajo | Requisito / prueba | Capas |
|---|---|---|---|
| 1 | Invalidación de sesión: evento único `SessionInvalidated`, código `SESSION_INVALIDATED`, `READY → ERROR_RECOVERABLE`, sin retorno a `READY` con la misma conexión | #31, INV-1..INV-5 | domain, engine, app, ui |
| 2 | Modelo de catálogo: bases adjuntas (alias, ruta, acceso, predeterminada), conciliado siempre con `duckdb_databases()` | GD-CAT-001 (base) | domain, engine |
| 3 | `AttachDatabase` y `StartSession(mode=file)`: RO/RW explícito, acciones «Abrir existente» y «Crear nueva» (nunca se crea un archivo implícitamente), ruta y alias citados como literales (F-06: `ATTACH ?` no funciona en 1.5), errores `DB_NOT_FOUND`, `DB_LOCKED`, `DB_ALIAS_CONFLICT`, `DB_READ_ONLY` | GD-SES-002, AT-SES-002 | engine, app |
| 4 | `DetachDatabase`: estado `DETACHING`, rechazo o cola con lector Arrow abierto, `USE` del catálogo raíz real si el alias era el predeterminado, verificación de que el catálogo desaparece, `DETACH_FAILED`, `DEFAULT_CATALOG` | GD-SES-004, AT-SES-004 | engine, app |
| 5 | Liberación real de bloqueos: tras `DETACH`, otro proceso abre el archivo en RW | gate de G1 | tests/engine |
| 6 | Coherencia de sesión: `USE`, temporales, parámetros y transacciones; `TRANSACTION_ABORTED` y validación transaccional antes de reutilizar la conexión | GD-SES-005, AT-SES-005; ADR-0007 puntos 5 y 6 | engine, app |
| 7 | Cierre con transacción abierta: diálogo `COMMIT` / `ROLLBACK` / Cancelar cierre; cancelar no modifica la transacción; `COMMIT` deshabilitado si no es válido | session-spec §2 `CloseSession` | app, ui |
| 8 | Explorador de catálogo en el panel: catálogos, esquemas, tablas y vistas; se actualiza después del éxito, nunca antes | GD-CAT-001, AT-CAT-001 | ui |

Cada paso cumple las fronteras de ADR-0010 (test de arquitectura) y se prueba con DuckDB 1.5.0, 1.5.6 y 2.0.0,
y con PyQGIS 3.44 y 4.2 cuando toca la UI.

## 2. Pruebas mínimas (session-spec §6)

Memoria con tabla temporal y cierre; archivo existente en RO (lectura sí, escritura rechazada); archivo RW
con escritura persistente y bloqueo liberado al `DETACH`; «Abrir existente» con archivo inexistente →
`DB_NOT_FOUND` sin crear nada; «Crear nueva» sobre un archivo existente → rechazo sin sobrescribir; `DETACH`
en la UI invalida lecturas futuras de ese alias; cierre con transacción abierta en sus tres opciones; `USE <alias>` seguido de `DETACH <alias>`; lector Arrow abierto
que bloquea el `DETACH` hasta liberarse; base bloqueada por otro proceso con error claro y sin estado
fantasma; INV-1..INV-5.

## 3. En paralelo, sin bloquear G1

- Certificación Windows (#10), un paso a la vez: QGIS 3.44 LTR, luego 4.2.x, luego regresión en 3.34.
- Spike G0-B (#11), antes de G2.

## 4. Decisiones del arquitecto (2026-11-01)

1. **ATTACH/DETACH desde SQL pasan a G2.** G1 no crea un editor SQL provisional. En G1, ATTACH y DETACH solo
   se hacen desde la UI. Actualizado en `spec/docs/roadmap.md`.
2. **«Abrir existente» y «Crear nueva»**, aprobadas. Nunca se crean archivos implícitamente. Actualizado en
   `spec/specs/session-spec.md` §2.
3. **Cierre con transacción abierta:** `COMMIT`, `ROLLBACK` o Cancelar cierre. Cancelar no modifica la
   transacción. Si `COMMIT` no es válido, se deshabilita. Actualizado en `spec/specs/session-spec.md` §2
   (`CloseSession`).
