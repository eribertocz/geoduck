# ADR-0007: cancelación mediante `interrupt()` como excepción controlada

**Estado:** Propuesto — revisión 2 (2026-11-01) · **Requiere:** aprobación del arquitecto
**Recoge:** decisión arquitectónica del 2026-11-01 («la cancelación desde otro hilo será una excepción
controlada, únicamente después de comprobar su seguridad»)
**Relacionado:** ADR-0006; `spec/docs/architecture.md` §5; `spec/specs/qgis-bridge-spec.md` §5;
`spec/specs/session-spec.md` §4 (transacciones)

**Cambios respecto de la revisión 1:** se corrige la latencia observada (1,5–180 ms, no 1–3 ms); se fija el
conjunto exacto de versiones verificadas; y se separa lo implementado en G0 de lo que queda para G1/G2:
el marcado `TRANSACTION_ABORTED` no existe todavía, porque G0 no ejecuta SQL del usuario.

## Contexto

El contrato prohíbe llamar «APIs de interrupción DuckDB no verificadas desde otro hilo». La decisión del
2026-11-01 las admite solo como excepción controlada y tras comprobar su seguridad.

Evidencia (F-09, `docs/evidence/g0/results/F-09_interrupt_all_versions.txt`): `interrupt()` invocado desde
otro hilo detuvo un `execute()` largo y un lector Arrow en **todas** las versiones 1.5.0, 1.5.1, 1.5.2,
1.5.3, 1.5.4, 1.5.5, 1.5.6 y 2.0.0, con latencias observadas entre 1,5 y 180 ms. En todas, la conexión
respondió `SELECT 1` después. En `execute()` el error llega como `InterruptException`; dentro de un lector,
como `OSError` con el texto `INTERRUPT Error`.

## Decisión

1. **Dos niveles de cancelación.**
   - *Cooperativa*, siempre disponible: un `CancelToken` que el worker consulta entre lotes y antes de
     cada operación. Una operación aún en cola se cancela sin llegar a ejecutarse.
   - *Interrupción del motor*, la excepción controlada: `interrupt()` solo si la versión exacta de DuckDB
     está en `INTERRUPT_VERIFIED` (`engine/compat.py`). Hoy contiene 1.5.0–1.5.6 y 2.0.0. Con cualquier
     otra versión, incluidas 1.5.7, 2.0.1 y las pre-releases, solo hay cancelación cooperativa.
2. **Único punto de llamada.** Solo `SessionWorker._interrupt_current_locked()`, invocado desde
   `cancel(op_id)` o `close()`, llama a `interrupt()`. Lo hace con el *lock* del worker adquirido y solo
   si hay una operación en curso: el worker no puede cambiar de operación mientras tanto, así que la
   interrupción solo alcanza a la operación actual. Es la **única** llamada a la conexión permitida fuera
   del hilo propietario.
3. **Clasificación y verificación posterior.** El worker clasifica `InterruptException` y `OSError` con
   `INTERRUPT` como `OperationCancelledError` (código `CANCELLED`). Después comprueba en su propio hilo
   que la conexión responde (`SELECT 1`); si no responde, cierra la sesión en lugar de seguir con una
   conexión dudosa.
4. **Nunca éxito tras cancelar.** Una lectura cancelada devuelve `completed = False` aunque ya se hubieran
   leído todos los lotes.
5. **Pendiente para G1/G2 (no implementado en G0).** Si la operación cancelada estaba dentro de una
   transacción explícita, la sesión debe quedar marcada `TRANSACTION_ABORTED` para que la UI ofrezca
   `ROLLBACK` (relacionado con C12: tras un error, `COMMIT` revierte sin avisar). Se implementará cuando
   GeoDuck ejecute SQL del usuario.

## Consecuencias

- Pro: se pueden cancelar consultas largas sin lotes, algo imposible solo con la vía cooperativa.
- Contra: cada versión nueva de DuckDB empieza sin `interrupt()` hasta que la suite de cancelación pase
  en ella y se añada a `INTERRUPT_VERIFIED`.
- Dependencias: ADR-0006 (hilo propietario y cola); D5 (las versiones de la matriz de CI definen qué se
  puede verificar).

## Implementación y verificación vigentes

- Código: `geoduck/engine/worker.py` (`cancel`, `cancel_current`, `_interrupt_current_locked`,
  `_connection_responds`), `geoduck/engine/compat.py` (`INTERRUPT_VERIFIED`, `is_interrupt_error`).
- Pruebas (`tests/engine/test_cancellation.py` y `tests/unit/test_engine_compat.py`):
  - `test_interrupt_stops_long_execute_and_session_recovers` (menos de 5 s y conexión usable después);
  - `test_interrupt_during_arrow_read_is_never_complete`;
  - `test_cooperative_cancel_between_batches`, `test_cancel_queued_operation_never_runs`;
  - `test_unverified_version_does_not_call_interrupt`;
  - tabla de capacidades: 1.5.7 y 2.0.1 sin interrupción verificada.
- La UI muestra «cancelación inmediata disponible» o «cancelación entre lotes» según la versión
  (verificado en Windows con DuckDB 2.0.0).
