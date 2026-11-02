# G1 · `v0.2.0a1` Connections — Documento de aceptación

**Estado:** **Aprobado para cierre** por el arquitecto y el propietario (2026-11-01). G1 queda cerrado al
fusionar este documento (roadmap §1). No se ha creado ningún tag ni release.

**Commit verificado:** `dc9544b` en `main` (merge del PR #48).

## 1. Requisitos de G1

| Requisito | Prueba de aceptación | Evidencia (pruebas) | Resultado |
|---|---|---|---|
| GD-SES-002 · adjuntar archivo de inicio RO/RW | AT-SES-002 | `tests/engine/test_attach.py`; StartSession(mode=file) en `tests/unit/test_coordinator.py` y `tests/qgis/test_explorer.py` | Cumple |
| GD-SES-003 · ATTACH/DETACH por UI | AT-SES-003 | `tests/qgis/test_explorer.py` | Cumple la parte de UI. **La parte SQL pasa a G2** (decisión del 2026-11-01) |
| GD-SES-004 · DETACH real que libera el uso propio | AT-SES-004 | `tests/engine/test_detach.py` (otro proceso abre el archivo tras el DETACH) | Cumple. «No afecta capas QGIS ya entregadas» se prueba en G3, cuando existan capas |
| GD-SES-005 · USE, temporales, parámetros y transacciones coherentes | AT-SES-005 | `tests/engine/test_transactions.py`, `tests/engine/test_detach.py` | Cumple |
| GD-CAT-001 · explorar catálogos, esquemas, vistas y tablas | AT-CAT-001 | `tests/engine/test_catalog.py`, `tests/qgis/test_explorer.py` | Cumple |
| Invalidación de sesión, requisito obligatorio de G1 (C13 §4 bis) | INV-1..INV-5 | `tests/engine/test_invalidation.py`, `tests/unit/test_coordinator.py`, `tests/qgis/test_plugin.py` | Cumple |

**Gate de salida (roadmap §2): «lock release real y temporales coherentes; invalidación de sesión notificada
una sola vez (INV-1..INV-5)».**

- Liberación real del bloqueo: tras el `DETACH`, y al cerrar o descargar el complemento, un proceso
  independiente abre el archivo en lectura y escritura.
- Temporales coherentes: persisten entre operaciones, desaparecen con `ROLLBACK` y con una sesión nueva.
- Invalidación: un único aviso `SESSION_INVALIDATED`, nada posterior llega a DuckDB y no se vuelve a
  `READY` con la misma conexión.

## 2. Casos mínimos de `session-spec` §6

| Caso | Prueba | Resultado |
|---|---|---|
| Memoria: tabla temporal y cierre | `test_use_temporaries_and_settings_persist_across_operations`, `test_a_new_session_starts_clean` | Cumple |
| Archivo existente en RO: lectura sí, escritura rechazada | `test_open_existing_attaches_with_requested_access[READ_ONLY]` | Cumple |
| Archivo RW: escritura, persistencia y bloqueo liberado al DETACH | `test_committed_writes_are_in_the_file_after_detach`, `test_detach_removes_the_database_and_releases_the_lock` | Cumple |
| ATTACH en SQL reflejado en la UI | — | **G2** (decisión del 2026-11-01) |
| DETACH en la UI invalida lecturas futuras de ese alias | `test_detach_invalidates_future_reads_of_that_alias` (añadida en este PR) | Cumple |
| Capa entregada sigue funcional tras DETACH y cierre | — | **G3** (aún no hay capas) |
| `USE <alias>` + `DETACH <alias>` → catálogo raíz | `test_detaching_the_default_switches_to_the_real_root_first` | Cumple |
| Lector Arrow abierto: el DETACH no se adelanta | `test_detach_waits_for_a_read_in_progress`, `test_detach_inside_an_open_reader_is_rejected_before_duckdb` | Cumple |
| Base bloqueada por otro proceso: error claro, sin estado fantasma | `test_file_locked_by_another_process_is_db_locked` | Cumple |

## 3. Decisiones del arquitecto aplicadas en G1

- Catálogo leído en `READY`, serializado por el worker (#37).
- «Abrir existente» y «Crear nueva»; nunca se crea un archivo implícitamente (#39).
- `DEFAULT_CATALOG` para la raíz (#41).
- **DETACH bloqueado con transacciones abiertas en todas las versiones** (#43).
- Cierre con COMMIT, ROLLBACK o Cancelar; COMMIT deshabilitado si no es válido (#45).
- Al salir de QGIS o descargar GeoDuck, ROLLBACK si es posible; nunca COMMIT automático (#46).

## 4. Defectos encontrados y corregidos durante G1

| PR | Defecto |
|---|---|
| #35 | La verificación posterior a `interrupt()` no se ejecutaba al interrumpir una lectura Arrow |
| #39 | Un error fatal durante el `ATTACH` devolvía la sesión a `READY` con la base invalidada |
| #43 | Cancelar dentro de una transacción invalidaba la sesión (la verificación con `SELECT 1` fallaba al estar abortada) |
| #45 | Una elección no válida en el diálogo de cierre cerraba la pregunta |
| #48 | «Iniciar» con una transacción abortada creaba otro motor y dejaba vivo el anterior, con sus bloqueos |

## 5. Verificación de `main`

| Comprobación | Resultado |
|---|---|
| CI sobre `dc9544b` (14 jobs) | 14/14 en verde |
| `ruff check`, `ruff format --check`, `mypy` | Sin errores |
| Pruebas unitarias, de arquitectura y de motor | 398 en verde con DuckDB 1.5.0, 1.5.6 y 2.0.0, y con PyArrow 18.1.0 + NumPy 1.26.4 |
| Suite de motor repetida 3 veces | 115/115 las tres veces |
| PyQGIS 3.44.14 y 4.2.3 (Linux, sin interfaz) | 22/22 |
| `spec/` | Maestra y `manifest.json` coherentes |
| ZIP del complemento | Reproducible (mismo SHA-256 en dos construcciones) |

## 6. Abierto, sin bloquear el cierre

| Tema | Estado | Seguimiento |
|---|---|---|
| Certificación Windows (QGIS 3.44 LTR, 4.2.x y regresión en 3.34) | Pendiente; trabajo de calidad que no bloquea | #10 |
| Comprobaciones Windows de G1: que `ATTACH` no cambie la fecha del archivo (F-20) y «Permission denied» → `DB_READ_ONLY` | Pendiente | #10, `docs/evidence/g1/README.md` |
| **Modernización visual del panel** | La UI es funcional; la modernización va en su fase (GD-UX-001, roadmap G5). No bloquea G1 | #49, hito `v0.6.0a1` |
| ATTACH/DETACH desde SQL | Pasa a G2 | `docs/g2/plan.md` |
| Capas intactas tras DETACH y cierre | G3 | — |
| Spike G0-B (editor SQL en PyQGIS 3/4) | Necesario antes del editor de G2 | #11 |

Mientras #10 no termine, no se afirma compatibilidad certificada en Windows: las notas de cualquier
release deben decirlo.

## 7. Aprobación

1. **Aprobado** (2026-11-01): cierre de G1, con lo pendiente de §6 como trabajo no bloqueante.
2. **Pendiente:** tag y release `v0.2.0a1`. Requieren aprobación expresa aparte.
