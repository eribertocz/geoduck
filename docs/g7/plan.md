# G7 · `v0.8.0a1` Notebook — plan

**Estado:** En curso (E0 fusionado, #91; decisiones del propietario, 2026-11-03). **Requisitos:** GD-NB-001..006.
**Contrato:** sql-editor-spec §7 («G7 · Notebook»), ui-ux-spec §10, `docs/g7/maqueta/` (maqueta propuesta, a
aprobar). Parte del workspace de G5 y del editor de G6: nada de G3/G4 cambia.

**Gate:** AT-NB-001..010 en la matriz de CI (QGIS 3.34, 3.40, 3.44, 4.2 × DuckDB 1.5.0, 2.0.0; Qt 5 y Qt 6);
regresiones G0–G6 completas. Tag y release `v0.8.0a1` solo con autorización del propietario.

## 1. Decisiones del propietario (2026-11-03)

| | Decisión |
|---|---|
| Rumbo | Interfaz de cuadernos de celdas parecida a la DuckDB UI, **nativa en Qt**. No se incrusta la DuckDB UI: su interfaz no es libre y se descarga de `ui.duckdb.org`, abre un servidor HTTP local sin autenticación y ejecuta fuera del worker (ADR-0006, ADR-0011) |
| Fase | G7 · Notebook antes de Performance (G8); las siguientes se desplazan un número |
| Celdas | Sustituyen a las pestañas de editor de G6: un solo modo. Cada pestaña de G6 pasa a ser un cuaderno |
| Base por celda | Selector en cada celda, como en la DuckDB UI; la celda también consulta otras bases con su nombre (`otra.esquema.tabla`). Referencia del propietario: celda en `memory` con `load spatial; select … from db.main.consumidores…` y celda en `db` con `select * from memory.tabla_memoria` |
| Estadísticas por columna | Fuera de G7 (costosas en tablas grandes). Entra el resumen simple: filas, columnas y tipos |
| Guardar cuadernos | Fuera de G7 (GD-SQL-008): solo en memoria |
| Exportar | Sí: CSV y Parquet de la **consulta completa** con `COPY (…) TO …`, no de la vista previa (la DuckDB UI exporta solo lo mostrado) |
| Panel acoplado | Minimalista: solo lo esencial; el resumen como ayuda (ⓘ) |

## 2. Verificado antes de la SPEC

| Qué (DuckDB 1.5.0 y 2.0.0) | Resultado |
|---|---|
| `USE a` + `SELECT * FROM t` | lee `a.t`; `b.t` sigue accesible con su nombre; las temporales se ven |
| `USE` dentro de una transacción | se admite; `ROLLBACK` no lo deshace |
| Escribir en dos bases en una transacción | error de DuckDB («Attempting to write to database … in a transaction»): se muestra tal cual |
| `COPY (consulta) TO` CSV y Parquet, 1 millón de filas con geometría | todas las filas; CSV con geometría en WKT; Parquet incluido y cargado; sobrescribe sin avisar; al releer el Parquet, la geometría sin SRC vuelve como `OGC:CRS84` (a resolver en E3) |
| DuckDB UI (documentación oficial y repositorio) | interfaz descargada de `https://ui.duckdb.org`; código de la interfaz no publicado; servidor en `localhost:4213` |

## 3. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC, roadmap renumerado, maqueta y este plan | `spec_sync --check` |
| **E1** | Modelo de cuaderno y celda (dominio, sin Qt); ejecución de una celda con `USE` de su base en la misma operación del worker; «Ejecutar todo» en orden con parada en el primer fallo; base desadjuntada | AT-NB-002, 003, 004 |
| **E2** | Vista de celdas: editor, ▶ con menú, selector de base, resultado con «Cargar en QGIS ▾» y «Copiar»; añadir (también entre celdas), arrastrar con el asa «⠿», subir/bajar con el teclado, duplicar, borrar; plegar celda, editor y resultado; vista de hoja (Ctrl+E); atajos; sustituye a las pestañas de G6 | AT-NB-001, 005, 008 |
| **E3** | Lista de cuadernos y resumen del resultado; «Exportar ▾» CSV/Parquet con `COPY` (consulta completa, confirmación al sobrescribir, cancelable, sin archivos a medias); ventana y panel; rendimiento con muchas celdas | AT-NB-006, 007, 009, 011 |
| **E4** | Accesibilidad, panel estrecho, idioma (catálogo), pulido visual según la maqueta aprobada | AT-NB-010 |
| **E5** | Aceptación: `docs/g7/acceptance.md`, guía manual en Windows, regresión completa | Gate |

## 4. Por verificar durante las entregas

- Mayús+Intro, Ctrl+E y Ctrl+↑/↓ frente a los comandos de QScintilla (como Ctrl+T en G6) (E2).
- Arrastrar celdas con su editor QScintilla dentro, en Qt 5 y Qt 6 (E2).
- ~~Parquet con geometría sin SRC~~ Decidido en E3 (propietario, 2026-11-03): sin SRC, GeoParquet 1.0 y aviso (`OGC:CRS84`); con SRC, `GEOPARQUET_VERSION 'V2'` (la opción por defecto falla). Verificado en DuckDB 1.5.0 y 2.0.0.
- ~~Exportación cancelada o fallida~~ Hecho en E3: temporal oculto en la misma carpeta y renombrado al terminar; si se cancela o falla, se borra y el archivo previo no cambia.
- ~~Coste de muchos `QgsCodeEditorSQL`~~ Medido en E3: 100 celdas en <1 s (antes ~15 s: añadir una celda rehacía todas); ejecutar las 100, 4–5 s; ~0,5 MB por resultado.
- ~~«Explicar» de una celda con base propia~~ Verificado en E1: `USE` + `EXPLAIN` en la misma operación (G7 retira «Explicar»; `EXPLAIN` escrito en la celda sigue igual).

## 4 bis. Para después (fuera de G7, decisión del propietario 2026-11-03)

- «Formatear sentencias» en el menú ⋯ de la celda, como la DuckDB UI (formato SQL, GD-SQL-008 P1 sin fase).

## 5. Estado

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, maqueta y plan | Fusionado | #91 |
| E1 Modelo y ejecución de celdas | Fusionado: `domain/notebook.py` (cuaderno y celda sin Qt: insertar, mover, duplicar, borrar; base desadjuntada; seguir el `USE` escrito en la celda); motor: `USE` de la base de la celda tras las comprobaciones y antes del SQL, en la misma operación, y `ScriptRun.current_database`; coordinador: relee el catálogo si cambia la base en uso; `app/notebook_runner.py`: una celda o todas en orden, parada en el primer fallo, rechazo o celda sin base. AT-NB-002, 003, 004 (motor y unitarias; la vista llega en E2) | #92 |
| E2 Vista de celdas | Fusionado: `ui/notebook_view.py` (celda con ⠿, tres pliegues, ▶ con menú, selector de base, resultado propio con «Cargar en QGIS ▾» y «Copiar», ⛶ y ⋯; «＋» entre celdas y al final; arrastrar, Alt+Mayús+↑/↓, Alt+↑/↓, Ctrl+E); cada pestaña de G6 es un cuaderno; atajos como la DuckDB UI (decisión del propietario: Ctrl+Intro la celda, Ctrl+Mayús+Intro la selección, Mayús+Intro la celda y avanzar); barra superior con solo «Ejecutar todo», «Cancelar» y filas; sin «Sentencia» ni «Explicar» (el plan, escribiendo `EXPLAIN`); menú ⋯ como la DuckDB UI (subir y bajar con Ctrl+↑/↓, duplicar, eliminar); «Cargar ▾» corto. Los eventos de cada ejecución van a la celda que la pidió (`run_id`). AT-NB-001, 005, 008 (`tests/qgis/test_notebook_ui.py`) | #93 |
| E2b Quitar «Explicar» del motor | Fusionado: sin parámetro `explain` en motor, worker, puertos y coordinador; el plan se pide con `EXPLAIN` escrito en la celda (AT-SQL-010) | #94 |
| E2c Cargar con la base de la celda | Fusionado: cada resultado recuerda la base donde se ejecutó (`StatementResult.database`); «Cargar en QGIS» (Memoria, Copia rápida y Conectada, también sus lecturas posteriores) repite la consulta en ella y deja la base en uso como estaba (`SessionWorker.submit(database=…)`). Antes fallaba si otra celda había cambiado la base en uso | #95 |
| E3 Exportar, cuadernos y resumen | Fusionado: «Exportar ▾» CSV/Parquet con `COPY` de la consulta completa (en la base del resultado, cancelable, temporal y renombrado, aviso de SRC); lista «Cuadernos» (ventana: nuevo, renombrar, cerrar) y selector en el panel; resumen del resultado (columna derecha plegable; en el panel, ayuda ⓘ); rendimiento: añadir una celda ya no rehace las demás. AT-NB-006, 007, 009, 011 | #96 |
| E4 Pulido, panel estrecho y accesibilidad | En revisión: celda como tarjeta (borde de acento en la activa, márgenes fuera, base como etiqueta, editor desde una línea); resultado con fondo propio, sin pestaña si es uno solo y sin botones sin tabla (opción A); vista previa de 50 filas por defecto (10/50/200/1000); ventana: nombre del cuaderno arriba, resumen con «Celda N · base» y marcas de tipo; panel: selector y acciones en una fila, «Copiar», «Exportar ▾» y «Cargar» al pie para la celda activa; nombres accesibles, ayuda y foco de teclado en todas las acciones; inglés y español. AT-NB-010 | — |
