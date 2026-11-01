# ADR-0006: propiedad exclusiva de la conexión, serialización y ciclo de vida de lectores Arrow

**Estado:** Aprobado arquitectónicamente (dictamen del 2026-11-01) — revisión 2
**Recoge:** decisión arquitectónica del 2026-11-01 («ninguna conexión DuckDB puede ser utilizada
simultáneamente por dos hilos; propiedad exclusiva, serialización y control del ciclo de vida de lectores»)
**Relacionado:** ADR-0001, ADR-0003, ADR-0007; `spec/docs/architecture.md` §2, §5;
`spec/specs/qgis-bridge-spec.md` §3; `spec/specs/session-spec.md` §1, §5

**Cambios respecto de la revisión 1:** el cierre se describe como lo implementa el código (no
bloqueante; el plazo lo aplica la capa de aplicación). Se añaden dos reglas ya implementadas: lecturas
acotadas por `execute()` y uso de `con.sql()` solo para relaciones de lectura de GeoDuck (C11).

## Contexto

La arquitectura aprobada ya prevé «un único hilo propietario» de la conexión. La auditoría G0 mostró que
en DuckDB 1.5.x el motor **no** protege ese contrato:

- **F-02:** el uso simultáneo de una conexión desde dos hilos hace caer el proceso en 1.5.0 de forma no
  determinista (segfault, abort o bloqueo). En 1.5.6 no se observó en 3 corridas, lo que no prueba que
  sea seguro. En 2.0.0 el motor lo rechaza con `ResourceInUseException`.
- **F-01:** con un lector Arrow abierto, otra sentencia se acepta y el lector entrega 1 000 de 100 000
  filas **sin error** (1.5.0, 1.5.6). En 2.0.0 se rechaza.

La protección debe estar en GeoDuck y comportarse igual en 1.5.x y 2.x.

## Decisión

1. **Un hilo propietario.** `SessionWorker` crea la conexión `duckdb.connect(":memory:")` dentro de su
   propio hilo y es el único código que la referencia. Ningún otro módulo recibe el objeto conexión.
2. **Serialización.** Toda operación se encola en una cola FIFO y se ejecuta en ese hilo. Quien la envía
   recibe un `Future`. No hay operaciones concurrentes sobre la conexión.
3. **Comprobación de hilo.** `ConnectionHandle` verifica en cada llamada que el hilo actual es el
   propietario; si no, lanza `WrongThreadError` sin tocar DuckDB.
4. **Lectores con ciclo de vida explícito.** Los lectores Arrow solo se abren con el gestor de contexto
   `ConnectionHandle.arrow_batches()`. Mientras uno está abierto, cualquier otra sentencia lanza
   `ActiveResultError` (código `ACTIVE_RESULT` de `session-spec` §5) **antes** de llegar a DuckDB. Al salir
   del contexto, por fin, error o cancelación, el lector se cierra siempre.
5. **Lectura completa solo si se agota.** `read_arrow()` devuelve `ReadSummary.completed = True` solo si
   el lector se agotó sin cancelación. Cancelación o error devuelven `completed = False`, que las capas
   superiores tratan como fallo y nunca como éxito. Una excepción del consumidor de lotes se propaga.
6. **Lecturas acotadas.** `execute()` devuelve como mucho `max_rows` filas (200 por defecto) y nunca
   materializa resultados sin límite (NF-02). En 2.x libera el resultado abierto con `complete()`.
7. **`con.sql()` solo para relaciones de lectura construidas por GeoDuck.** Las sentencias del usuario
   pasan por `execute()`. En 1.5.x `con.sql()` de DDL devuelve `None` y en 2.x devuelve una relación que
   se re-ejecuta en cada lectura (F-08, C11).
8. **Cierre no bloqueante.** `close()` rechaza trabajos nuevos, cancela los pendientes y el actual
   (ADR-0007) y devuelve un `Future` que se completa cuando la conexión ya está cerrada en el hilo
   propietario. El hilo termina inmediatamente después. El plazo máximo de espera lo aplica la capa de
   aplicación (`SessionCoordinator.shutdown`, 10 s al descargar el complemento).
9. **Igual en 1.5.x y 2.x.** El guardia de GeoDuck se aplica en ambas ramas; en 2.x el error del motor
   queda como segunda barrera.

## Consecuencias

- Pro: elimina F-01 y F-02 por construcción, con el mismo comportamiento en todas las versiones.
- Pro: el estado de sesión (`USE`, `TEMP`, transacciones) es coherente porque hay un solo ejecutor.
- Contra: una consulta larga ocupa la cola; la UI debe mostrar «ocupado» y ofrecer cancelar (ADR-0007).
- Contra: dos lecturas no se pueden intercalar; «Cargar todos» procesará resultados en serie (G3).
- Dependencia: ADR-0007 define la única excepción a la regla 1 (la llamada `interrupt()`).

## Implementación y verificación vigentes

- Código: `geoduck/engine/worker.py` (`SessionWorker`, `ConnectionHandle`, `CancelToken`),
  `geoduck/domain/errors.py`, `geoduck/domain/operations.py`.
- Pruebas (`tests/engine/test_session_worker.py`, CI con DuckDB 1.5.0, 1.5.6 y 2.0.0 en Python 3.12 y
  3.14, y con PyArrow 18.1.0 + NumPy 1.26.4):
  - `test_open_reader_rejects_other_statements_and_stays_complete`: regresión de F-01;
  - `test_concurrent_submitters_are_serialized`: 4 hilos × 200 operaciones, el escenario de F-02;
  - `test_connection_cannot_be_used_from_another_thread`;
  - `test_read_arrow_complete_with_exact_counts`, `test_consumer_failure_propagates_and_reader_is_closed`;
  - `test_execute_is_bounded_and_frees_the_connection`, `test_insert_returning_runs_once`;
  - `test_queued_operations_fail_cleanly_when_session_closes`, `test_close_is_idempotent_and_safe_before_start`.
- Arquitectura: `tests/architecture` impide que otro paquete importe `duckdb` (ADR-0010).
- Windows: sesión iniciada y cerrada en QGIS 3.34.15 (prueba de humo, no certificación).
