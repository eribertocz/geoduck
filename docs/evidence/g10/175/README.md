# #175 — Estrés de 1 hora (GD-PERF-005, AT-PERF-005)

Herramienta: `tools/perf/stress.py` (cada vuelta: sesión, `ATTACH`/`DETACH`, consultas, cargar Copia y Conectada,
cancelar una carga grande, enviar y «Deshacer», exportar y cancelar, datos rotos T7, abrir la base desde otro
proceso, cerrar la sesión). `--minutes 60 --rows 200000`, DuckDB 2.0.0.

## Resultado

| QGIS | Qt | Dónde | Vueltas | Fallos | RAM inicio | RAM minuto 10 | RAM final | Desde el minuto 10 | Máximo tras el minuto 10 |
|---|---|---|---|---|---|---|---|---|---|
| 3.34.6 | 5.15.8 | local, 2 núcleos | 1293 | 0 | 487 MB | 688 MB (vuelta 217) | 703 MB | **+2,3 %** | +5,2 % |
| 3.44.14 | 5.15.15 | CI (`workflow_dispatch`), 4 núcleos | 1225 | 0 | 519 MB | 837 MB (vuelta 206) | 842 MB | **+0,6 %** | +4,8 % |
| 4.2.3 | 6.11.2 | CI (`workflow_dispatch`), 4 núcleos | 1928 | 0 | 560 MB | 911 MB (vuelta 314) | 920 MB | **+1,0 %** | +2,9 % |

**0 cierres, 0 filas perdidas, 0 capas a medias** en 4446 vueltas. La RAM sube los primeros minutos
(calentamiento: cachés de QGIS y memoria que DuckDB y el sistema guardan para reutilizar) y después queda plana;
el criterio mide desde el minuto 10 (`performance-spec §6`, aprobado el 2026-11-14). Curvas por vuelta:
`ram-*.csv`.

## Lo que encontró el estrés

1. **Ventana de exportar que no se liberaba** (~2 MB por exportación): `ExportProgress` usa
   `WA_DeleteOnClose`. Prueba: `test_a_closed_export_window_is_freed`.
2. **Interrupción perdida.** Un «Cancelar» que llegaba justo antes de que DuckDB empezara la sentencia se perdía;
   ahora se repite mientras la sentencia cancelable siga en curso (`ConnectionHandle.execute(..., token=)`,
   exportar y el editor SQL). Prueba: `test_a_lost_interrupt_is_repeated_while_the_statement_runs`.
3. **Cuelgue de DuckDB 2.0 al cancelar un `COPY … TO`.** Reproducido solo con DuckDB (sin GeoDuck ni QGIS):
   `COPY` de 6 millones de filas a Parquet cancelado con `interrupt()` a un tiempo al azar (`copy_cancel_hang.py N`, con `TMPD` y `PRESET`; varias
   pruebas a la vez para cambiar el ritmo). Los ajustes no causan el bloqueo: solo lo adelantan.

   | DuckDB | Ajuste | Resultado |
   |---|---|---|
   | 2.0.0 | por defecto | se bloqueó en la vuelta 326 |
   | 2.0.0 | `preserve_insertion_order = false` | se bloqueó en la vuelta 8 |
   | 2.0.0 | barra de progreso | se bloqueó en la vuelta 29 |
   | 2.0.0 | `async_threads = 0` | 0 bloqueos en 2000 vueltas |
   | 1.5.0 | (sin escritura asíncrona) | 0 bloqueos en 300 vueltas |

   Traza (gdb): un hilo en `AsyncFileWriter::AbortWrites → DrainTasks` espera a otro en
   `ManagedAsyncWriteStreamQueue::SchedulePendingWritesInternal`, que espera al primero; 0 % de CPU. Arreglo:
   `ConnectionHandle.sync_writes()` pone `async_threads = 0` solo durante un `COPY … TO` (exportar o el editor) y
   lo deja como estaba; escribir va igual de rápido (Parquet 0,59 s contra 0,62 s; CSV 0,9 s contra 1,0 s) y las
   lecturas siguen asíncronas. Prueba: `test_writes_are_synchronous_only_during_a_copy`,
   `test_cancelled_copies_always_finish`.
4. **RAM de QGIS 3.34 en el arnés:** sin el bucle de eventos de QGIS, Qt 5 no borra lo que espera
   `deleteLater()`; el arnés lo hace en cada vuelta, como QGIS (antes se acumulaban 334 ventanas).
