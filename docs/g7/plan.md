# G7 · `v0.8.0a1` Notebook — plan

**Estado:** E0 en revisión (decisiones del propietario, 2026-11-03). **Requisitos:** GD-NB-001..006.
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

## 2. Verificado antes de la SPEC

| Qué (DuckDB 1.5.0 y 2.0.0) | Resultado |
|---|---|
| `USE a` + `SELECT * FROM t` | lee `a.t`; `b.t` sigue accesible con su nombre; las temporales se ven |
| `USE` dentro de una transacción | se admite; `ROLLBACK` no lo deshace |
| Escribir en dos bases en una transacción | error de DuckDB («Attempting to write to database … in a transaction»): se muestra tal cual |
| DuckDB UI (documentación oficial y repositorio) | interfaz descargada de `https://ui.duckdb.org`; código de la interfaz no publicado; servidor en `localhost:4213` |

## 3. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC, roadmap renumerado, maqueta y este plan | `spec_sync --check` |
| **E1** | Modelo de cuaderno y celda (dominio, sin Qt); ejecución de una celda con `USE` de su base en la misma operación del worker; «Ejecutar todo» en orden con parada en el primer fallo; base desadjuntada | AT-NB-002, 003, 004 |
| **E2** | Vista de celdas: editor, ▶ con menú, selector de base, resultado con «Cargar en QGIS ▾» y «Copiar»; añadir (también entre celdas), arrastrar con el asa «⠿», subir/bajar con el teclado, duplicar, borrar; plegar celda, editor y resultado; vista de hoja (Ctrl+E); atajos; sustituye a las pestañas de G6 | AT-NB-001, 005, 008 |
| **E3** | Lista de cuadernos y resumen del resultado; ventana y panel; rendimiento con muchas celdas | AT-NB-006, 007, 009 |
| **E4** | Accesibilidad, panel estrecho, idioma (catálogo), pulido visual según la maqueta aprobada | AT-NB-010 |
| **E5** | Aceptación: `docs/g7/acceptance.md`, guía manual en Windows, regresión completa | Gate |

## 4. Por verificar durante las entregas

- Mayús+Intro, Ctrl+E y Alt+Mayús+↑/↓ frente a los comandos de QScintilla (como Ctrl+T en G6) (E2).
- Arrastrar celdas con su editor QScintilla dentro, en Qt 5 y Qt 6 (E2).
- Coste de muchos `QgsCodeEditorSQL` en una sola vista en Qt 5 y Qt 6 (E3).
- «Explicar» de una celda con base propia: `USE` + `EXPLAIN` en la misma operación (E1).

## 5. Estado

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, maqueta y plan | En revisión | — |
