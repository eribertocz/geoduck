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
