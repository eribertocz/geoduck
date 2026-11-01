# ADR-0007: cancelación mediante `interrupt()` como excepción controlada

**Estado:** Propuesto · **Requiere:** aprobación del arquitecto
**Relacionado:** ADR-0006; `spec/docs/architecture.md` §5; `spec/specs/qgis-bridge-spec.md` §5

## Contexto

El contrato pide no llamar «APIs de interrupción DuckDB no verificadas desde otro hilo». La decisión
arquitectónica del 2026-11-01 admite la cancelación desde otro hilo «como excepción controlada,
únicamente después de comprobar su seguridad».

Evidencia G0 (F-09): `DuckDBPyConnection.interrupt()` invocado desde otro hilo detuvo `execute()` y
lectores Arrow en todas las versiones 1.5.0–1.5.6 y 2.0.0 (latencia observada entre 1,5 y 180 ms), y la
conexión siguió usable (`SELECT 1`).
Dentro de un lector, el error llega como `OSError` con texto `INTERRUPT Error`, no como
`InterruptException`.

## Decisión

1. **Dos niveles de cancelación.**
   - *Cooperativa* (siempre disponible): un `CancelToken` que el worker consulta entre lotes y entre
     sentencias.
   - *Interrupción del motor* (excepción controlada): `interrupt()` solo cuando la versión de DuckDB
     está en el conjunto **verificado por la suite de regresión** (`engine/compat.py`,
     `interrupt_verified`). Para versiones no verificadas, solo cancelación cooperativa.
2. **Único punto de llamada.** Solo `SessionWorker.cancel(op_id)` puede llamar a `interrupt()`, y solo
   si `op_id` es la operación en curso. Es la **única** llamada a la conexión permitida fuera del hilo
   propietario y está documentada como tal en el código.
3. **Verificación posterior.** Tras una interrupción, el worker clasifica el error
   (`InterruptException` u `OSError` con `INTERRUPT`) como `CANCELLED`, comprueba en su propio hilo
   que la conexión responde y, si había una transacción explícita, marca el estado
   `TRANSACTION_ABORTED` para que la UI ofrezca `ROLLBACK`.
4. **Nunca éxito tras cancelar.** Una operación cancelada devuelve siempre `completed=False`.

## Consecuencias

- Pro: cancelación inmediata de consultas largas sin lotes, imposible solo con la vía cooperativa.
- Contra: añadir una versión de DuckDB al conjunto verificado exige pasar los tests de cancelación.

## Verificación

`tests/engine/test_cancellation.py`: interrupción de `execute` largo y de lector en curso, conexión
usable después, operación marcada `completed=False`; versión no verificada → solo cooperativa.
