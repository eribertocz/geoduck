# Evidencia G1 — adjuntar archivos (paso 3)

Verificado en Linux con DuckDB 1.5.0, 1.5.6 y 2.0.0 (Python 3.12). Es evidencia de comportamiento del
motor, **no** certificación Windows (#10).

| ID | Hecho | Consecuencia en GeoDuck |
|---|---|---|
| F-18 | `ATTACH` en lectura y escritura de una ruta inexistente **crea el archivo sin avisar**. En solo lectura falla con «database does not exist» | «Abrir existente» comprueba que el archivo existe antes del `ATTACH` |
| F-19 | Un archivo vacío no es una base válida («not a valid DuckDB database file»), tanto en RO como en RW | No se puede reservar el nombre creando antes un archivo vacío |
| F-20 | Adjuntar un archivo existente, en RO o RW, y leerlo no cambia su dispositivo, inodo, tamaño ni fecha de modificación. Linux reutiliza al instante el inodo de un archivo borrado | «Abrir existente» compara los cuatro datos antes y después; solo el inodo no basta |
| F-21 | Nombres reservados: `system` y `temp`. `memory` choca porque es el nombre de la raíz | Alias reservados rechazados antes de DuckDB |
| F-22 | El mismo archivo dos veces en la sesión: en RO+RO se permite; si interviene RW, «Unique file handle conflict» (`BinderException` en 1.5, `ResourceInUseException` en 2.0) | Se informa `DB_ALIAS_CONFLICT` |
| F-23 | Archivo bloqueado en RW por otro proceso: tanto RO como RW fallan con «Could not set lock on file … Conflicting lock is held» (`IOException`). Mientras la sesión tiene el archivo en RW, otro proceso no puede abrirlo; al cerrar la sesión, sí | `DB_LOCKED`. La liberación al `DETACH` es el paso 5 |
| F-24 | Los mensajes de error de DuckDB incluyen la ruta del archivo | El `detail` técnico de GeoDuck guarda la clase y la regla, nunca el mensaje con la ruta |

Pendiente de comprobar en Windows (#10): F-20 (que `ATTACH` no cambie la fecha de modificación) y el
caso «Permission denied» → `DB_READ_ONLY`. Aquí no se puede reproducir, porque las pruebas corren como root.

Reproducir: `python attach_behaviour.py` y `python attach_identity.py` con la versión de DuckDB que se
quiera comprobar.

## Desadjuntar (pasos 4 y 5)

Verificado con DuckDB 1.5.0, 1.5.6 y 2.0.0 en Linux. Script: `detach_behaviour.py`.

| ID | Hecho | Consecuencia en GeoDuck |
|---|---|---|
| F-25 | DuckDB no desadjunta la base predeterminada («because it is the default database»), tampoco la raíz | Si es la predeterminada, primero `USE` de la raíz real. Si el `DETACH` falla, se restaura la predeterminada anterior. La raíz se rechaza con `DEFAULT_CATALOG` |
| F-26 | En 1.5.x, `DETACH` con un lector Arrow abierto sobre esa base se acepta y el lector entrega **0 filas sin error**; 2.0 lo rechaza («open result») | Lo impide el guardia de lector abierto (`ACTIVE_RESULT`) antes de llegar a DuckDB, y el worker serial hace que el `DETACH` espere a que termine la lectura |
| F-27 | `DETACH` hace checkpoint: el `.wal` desaparece, otro proceso abre el archivo en RW y ve los datos confirmados | Liberación real del bloqueo comprobada desde un proceso independiente |
| F-28 | Con una transacción abierta que tiene cambios en la base: 1.5.0 la desadjunta igualmente; 1.5.6 y 2.0 lo rechazan («outstanding work») | Se informa `DETACH_FAILED`. En G1 GeoDuck no abre transacciones (no hay SQL del usuario); la validación transaccional es del paso 6 |
| F-29 | En 1.5.6 y 2.0, ese `DETACH` rechazado deja la transacción **abortada** («Current transaction is aborted») | Entrada para el paso 6 (`TRANSACTION_ABORTED`, ADR-0007 punto 6) |

## Transacciones (paso 6)

Verificado con DuckDB 1.5.0, 1.5.6 y 2.0.0 en Linux. Script: `transaction_behaviour.py`.

| ID | Hecho | Consecuencia en GeoDuck |
|---|---|---|
| F-30 | No existe una función que informe si hay una transacción abierta, y un `BEGIN` dentro de otra transacción **aborta la del usuario** | No se usa `BEGIN` para comprobar |
| F-31 | `txid_current()` devuelve el mismo valor en dos sentencias seguidas solo dentro de una transacción explícita; en autocommit cambia en cada sentencia. Con la transacción abortada, cualquier sentencia falla con «Current transaction is aborted» | Comprobación sin efectos: dos lecturas seguidas en la misma operación serial distinguen `NONE`, `ACTIVE` y `ABORTED` |
| F-32 | Una interrupción dentro de una transacción la deja abortada en todas las versiones | Tras cancelar, el worker comprueba el estado y lo adjunta al error |
| F-33 | Un error de catálogo dentro de una transacción la aborta en 2.0, pero no en 1.5.x. Un error de restricción (clave duplicada) la aborta en todas | El estado siempre se comprueba en DuckDB; nunca se deduce del tipo de error. Matriz de 19 casos en `test_probe_has_no_false_positives_or_negatives` |
| F-07 (recordatorio) | `COMMIT` de una transacción abortada responde OK y revierte sin avisar | GeoDuck nunca lo envía: comprueba antes y rechaza con `TRANSACTION_ABORTED` |
