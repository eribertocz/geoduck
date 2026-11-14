# SPEC GD-SES — Sesiones y bases DuckDB

**Estado:** baseline para Alpha · **IDs:** GD-SES-001..005

## 1. Semántica general
GeoDuck mantiene una **única sesión lógica** con conexión física raíz en `:memory:`. Seleccionar archivo persistente en la pantalla de inicio equivale a adjuntarlo con alias asignado a su base principal visible. El archivo se puede `DETACH` sin cerrar todo GeoDuck. **Base activa** (#168, propietario, 2026-11-13): una sola por sesión, la predeterminada de DuckDB (`USE`); el explorador y el editor muestran la misma. Cualquier base se puede `DETACH`, también la `memory` del inicio, **salvo la activa y la última**: siempre queda una. Se puede adjuntar una base nueva en memoria con alias (`ATTACH ':memory:' AS <alias>`; por defecto `memory`, o `memory_2`… si ya existe).

La sesión es propiedad exclusiva del Session Worker; no existe un objeto `con` compartido simultáneamente con la UI. Los objetos temporales persisten durante la sesión; al salir de ella desaparecen.

## 2. Contratos de operación
### `StartSession(mode, path?, access?)`
- `mode=memory`: usa `duckdb.connect(":memory:")`; no requiere path adicional.
- `mode=file`: crea la raíz `:memory:`, comprueba archivo/path, solicita modo `READ_ONLY` o `READ_WRITE`, luego `ATTACH '...duckdb' AS <alias> (<modo>)`.
- No se inventan archivos por defecto sin que el usuario haya pedido crearlos. Hay dos acciones explícitas: **«Abrir existente»** (el archivo debe existir; si no, `DB_NOT_FOUND`) y **«Crear nueva»** (el archivo no debe existir; nunca se sobrescribe). Ningún archivo se crea de forma implícita (decisión del 2026-11-01).
- Si falla el attach inicial, la sesión puede quedarse en memoria y el usuario recibe información explícita de qué ocurrió.

### `AttachDatabase(path, alias?, access)`
- Valida un alias único, una ruta válida y un modo explícito.
- Usa sentencias parametrizadas cuando sea posible o quoting correcto de identificadores/rutas; jamás interpolación ingenua de texto del usuario.
- Actualiza explorador después del éxito, no antes.
- Permite `ATTACH` desde SQL sin interferir: el registro de bases se reconcilia con `duckdb_databases()` después de la sentencia.
- El motor decide cuándo un mismo archivo puede o no adjuntarse simultáneamente o en modo RW por bloqueos.

### `DetachDatabase(alias)`
- Comprueba que la base esté adjunta, que **no sea la activa** (predeterminada) ni **la última** (#168). Nunca cambia la activa en silencio para poder cerrarla: hay que activar otra antes. La `memory` del inicio se cierra como cualquier otra.
- Rechaza o encola la operación cuando hay transferencias/consultas activas o una transacción abierta; la interfaz deja «Cerrar base» en gris con el motivo.
- Una base en memoria con tablas pide confirmar («Cerrar y perder N tablas»), y avisa si la leen capas Conectadas (quedarán sin datos).
- Ejecuta `DETACH` real; verifica desaparición del catálogo; libera readers/resultados propios relacionados.
- **No modifica ni elimina capas QGIS previamente entregadas** (Memoria e Instantánea).
- Capas **Conectadas** de esa base (qgis-bridge-spec §5.5): si alguna tiene cambios sin guardar, el DETACH se rechaza con la lista de capas; si no, quedan «no disponibles» y vuelven al adjuntar de nuevo la base con el mismo alias.
- Si fracasa, informa el error y no marca la base como desconectada.
- Aun con `DETACH` exitoso no garantiza que otro proceso no mantenga bloqueos externos. Probar apertura RW desde proceso independiente.

### `ExecuteSQL("ATTACH ..." / "DETACH ...")`
- Se ejecuta a través del mismo worker serializado.
- Tras operaciones con cambios de catálogo, reconsulta estado real antes de actualizar UI.
- No convertir `DETACH` en borrado de archivo ni en cierre ficticio.

### `ListColumns(database, schema, object)` (G6 · GD-CAT-002)
- Lo pide el explorador al expandir una tabla o vista, y el autocompletado cuando necesita las columnas de un objeto. Nunca se enumeran todas las columnas de todas las bases.
- Se ejecuta en el mismo worker serializado, con `duckdb_columns()` filtrado por base, esquema y objeto; solo metadatos, nunca filas. Devuelve, en el orden de la tabla: nombre, tipo exacto tal como lo informa DuckDB y si admite `NULL`.
- La respuesta lleva el `catalog_epoch` de la petición (sql-editor-spec §2). Tras `ATTACH`/`DETACH`, DDL desde SQL o invalidación de sesión (INV-1..INV-5) las columnas guardadas se descartan, y una respuesta de un epoch anterior no se muestra.
- Si el objeto ya no existe, el error se muestra en el nodo y el catálogo se refresca; no bloquea la sesión.

### `CloseSession()`
Solo lo inicia «Cerrar sesión» o la descarga de GeoDuck. Ocultar o cerrar la ventana propia o el panel (ui-ux-spec §8) **no** es `CloseSession`: no hay `DETACH`, `ROLLBACK`, cancelación ni capas invalidadas.

- Solicitar cancelación cooperativa; cerrar los lectores; cerrar la conexión y no retener referencias.
- **Transacción abierta al cerrar** (decisión del 2026-11-01): se pregunta al usuario con tres opciones, `COMMIT`, `ROLLBACK` o **Cancelar cierre**. Cancelar no modifica la transacción y la sesión sigue abierta. Si `COMMIT` no es válido (por ejemplo, transacción abortada, `TRANSACTION_ABORTED`), la opción `COMMIT` se deshabilita.
- No borrar archivos de usuario ni capas QGIS.
- Capas **Conectadas** con cambios sin guardar: el cierre se cancela y se pide guardarlos o descartarlos. Tras el cierre, todas las capas conectadas quedan «no disponibles».

## 3. Read-only y escritura
- `READ_ONLY` protege esa base según reglas DuckDB. **No** es sandbox del proceso ni impide escribir en memoria u otros archivos permitidos.
- El SQL completo se conserva. Acciones potencialmente destructivas pueden requerir confirmación UX, pero la seguridad no dependerá exclusivamente de heurísticas de parsing.
- No pretender elevar permisos con un segundo canal de escritura a una base RO.

## 4. Transacciones
- `BEGIN`, `COMMIT`, `ROLLBACK` admitidos como SQL real.
- En DuckDB: en las versiones certificadas, una sentencia fallida dentro de transacción puede dejarla abortada hasta `ROLLBACK`; presentar recuperación clara, no hacer `COMMIT` silencioso.
- Un script ejecutado sin `BEGIN` explícito no se revierte globalmente si falla una sentencia posterior.
- La operación de carga QGIS que repite consulta debe saber si se apoya en objetos temporales o transacciones abiertas; no cambiar cursores/contextos arbitrariamente.
- Tras una cancelación o un error, la conexión solo se reutiliza si responde y su estado transaccional es conocido y utilizable; si no puede determinarse, o la transacción quedó abortada sin resolver, la sesión no vuelve a `READY` (ADR-0007). `TRANSACTION_ABORTED` se implementa en G1/G2.

## 5. Estados y errores
`DISCONNECTED`, `CONNECTING`, `READY`, `BUSY`, `DETACHING`, `CLOSING`, `ERROR_RECOVERABLE`.

Transiciones normativas:

| Desde | Puede pasar a |
|---|---|
| `DISCONNECTED` | `CONNECTING` |
| `CONNECTING` | `READY`, `ERROR_RECOVERABLE`, `CLOSING` |
| `READY` | `BUSY`, `DETACHING`, `CLOSING`, `ERROR_RECOVERABLE` (solo por invalidación) |
| `BUSY` | `READY`, `CLOSING`, `ERROR_RECOVERABLE` |
| `DETACHING` | `READY`, `ERROR_RECOVERABLE`, `CLOSING` |
| `CLOSING` | `DISCONNECTED` |
| `ERROR_RECOVERABLE` | `CONNECTING`, `READY` (solo si la conexión responde y su estado transaccional es utilizable; nunca tras una invalidación), `CLOSING`, `DISCONNECTED` |

Los estados de operación y de entrega no forman parte de esta máquina.

Mensajes operativos distinguibles: `DB_NOT_FOUND`, `DB_LOCKED`, `DB_ALIAS_CONFLICT`, `DB_READ_ONLY`, `ACTIVE_RESULT`, `DEFAULT_CATALOG`, `TRANSACTION_ABORTED`, `DETACH_FAILED`, `SESSION_INVALIDATED`.

`SESSION_INVALIDATED`: la conexión dejó de ser utilizable (no responde tras una interrupción, el hilo propietario terminó o el motor informó un error fatal). El motor lo notifica una sola vez, después de rechazar todo trabajo nuevo y de fallar el pendiente. La sesión pasa a `ERROR_RECOVERABLE` y solo puede salir hacia una sesión nueva (`CONNECTING`), `CLOSING` o `DISCONNECTED`; nunca vuelve a `READY` con la misma conexión. Ninguna operación posterior llega a DuckDB. Requisito obligatorio de G1.

## 6. Casos de prueba mínimos
- Memoria: crear/consultar tabla temporal y cerrar la sesión.
- Archivo existente en RO: lectura OK; escritura al mismo catálogo rechazada.
- Archivo RW: escritura y persistencia; bloqueos recuperados al `DETACH`.
- `ATTACH` en SQL se refleja en UI; `DETACH` en UI invalida futuras lecturas de ese alias.
- Capa ya entregada permanece funcional después de `DETACH` y del cierre del plugin.
- `USE <alias>` seguido de `DETACH <alias>`: rechazado (es la activa) sin cambio oculto; con otra activa, la `memory` del inicio se cierra y la referencia pasa a la activa (#168).
- Reader Arrow abierto: `DETACH` no se adelanta a la liberación del reader.
- Base externa bloqueada: error claro, catálogo coherente, sin estado fantasma.
- Invalidación de sesión (G1): INV-1 una sola notificación `SESSION_INVALIDATED`; INV-2 lo pendiente y la lectura Arrow en curso terminan con error, nunca con resultado ni como lectura completa; INV-3 toda operación posterior se rechaza sin llamar a DuckDB; INV-4 `ERROR_RECOVERABLE` sin retorno a `READY` y «Nueva sesión» con hilo y conexión nuevos; INV-5 el cierre pedido por el usuario no emite la notificación.
