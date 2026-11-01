# ADR-0006: propiedad exclusiva de la conexión, serialización y ciclo de vida de lectores Arrow

**Estado:** Propuesto — recoge la decisión arquitectónica del 2026-11-01 · **Requiere:** aprobación del arquitecto
**Relacionado:** ADR-0001, ADR-0003; `spec/docs/architecture.md` §2, §5; `spec/specs/qgis-bridge-spec.md` §3

## Contexto

La arquitectura aprobada ya prevé «un único hilo propietario» de la conexión. La auditoría G0 mostró
que, en DuckDB 1.5.x, el motor **no** protege ese contrato:

- F-02: el uso simultáneo de una conexión desde dos hilos hace caer el proceso en 1.5.0 (segfault,
  abort o bloqueo, de forma no determinista).
- F-01: con un lector Arrow abierto, otra sentencia se acepta y el lector entrega menos filas **sin
  error**. En 2.0.0 el motor rechaza ambos casos con `ResourceInUseException`.

Por tanto, la protección debe estar en GeoDuck y ser idéntica en 1.5.x y 2.x.

## Decisión

1. **Un hilo propietario.** `SessionWorker` crea la conexión `duckdb.connect(":memory:")` dentro de su
   propio hilo y es el único código que la referencia. Ningún otro módulo recibe el objeto conexión.
2. **Serialización.** Toda operación se encola como unidad de trabajo en una cola FIFO y se ejecuta en
   ese hilo. Los llamadores obtienen un `Future`. No hay operaciones concurrentes sobre la conexión.
3. **Comprobación de hilo.** El envoltorio de conexión (`ConnectionHandle`) verifica en cada llamada que
   el hilo actual es el propietario; si no, lanza `WrongThreadError` sin tocar DuckDB.
4. **Lectores con ciclo de vida explícito.** Los lectores Arrow solo se abren mediante un gestor de
   contexto del `ConnectionHandle`. Mientras uno está abierto, cualquier otra sentencia sobre la
   conexión lanza `ActiveResultError` (código `ACTIVE_RESULT` de `session-spec` §5), **antes** de
   llegar a DuckDB. Al salir del contexto (fin, error o cancelación) el lector se cierra siempre.
5. **Detección de lectura incompleta.** Una lectura solo es «completa» si el lector se agotó
   normalmente dentro del contexto. Cancelación, excepción o cierre anticipado producen un resultado
   `completed=False`, que las capas superiores tratan como fallo (nunca como éxito).
6. **Cierre.** `close()` rechaza trabajos nuevos, cancela el actual (ADR-0007), espera el fin del hilo
   con plazo y cierra la conexión en el hilo propietario.
7. **Lo mismo en 1.5.x y 2.x.** El guardia de GeoDuck se aplica en ambas ramas; en 2.x el error del
   motor queda como segunda barrera.

## Consecuencias

- Pro: elimina F-01 y F-02 por construcción; el comportamiento es igual en todas las versiones.
- Pro: el estado de sesión (`USE`, `TEMP`, transacciones) es coherente porque solo hay un ejecutor.
- Contra: una consulta larga bloquea la cola; la UI debe mostrar «ocupado» y ofrecer cancelar.
- Contra: dos lecturas no pueden intercalarse; «Cargar todos» procesa resultados en serie.

## Verificación

Tests de regresión en `tests/engine` (matriz DuckDB 1.5.0, última 1.5.x, última 2.x):
lectura completa con 1 000 lotes; sentencia intercalada rechazada con `ActiveResultError` y lector
íntegro; llamada desde otro hilo rechazada con `WrongThreadError`; 4 hilos enviando 200 operaciones
cada uno sin error ni caída; cierre sin hilos vivos.
