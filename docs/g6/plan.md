# G6 · `v0.7.0a1` SQL Professional — plan

**Estado:** En aceptación (E0–E4 en revisión, #85–#89; alcance aprobado por el propietario, 2026-11-02; propuesta de arquitectura revisada
contra el repositorio). **Requisitos:** GD-CAT-002, GD-SQL-007, GD-I18N-001 (issue #68).
**Contrato:** session-spec §2 (`ListColumns`), sql-editor-spec §7 («P1 en G6»), ui-ux-spec §5 y §9.
Parte del workspace de G5 (ADR-0013): todo se integra en `WorkspaceContent`, sin shells ni conexiones nuevas.

**Gate:** AT-CAT-002, AT-SQL-007..010 y AT-I18N-001 en la matriz de CI (QGIS 3.34, 3.40, 3.44, 4.2 ×
DuckDB 1.5.0, 2.0.0; Qt 5 y Qt 6); regresiones G0–G5 completas; nada de G3/G4/G5 cambia de comportamiento.
Tag y release `v0.7.0a1` solo con autorización del propietario.

## 1. Decisiones del propietario (2026-11-02)

| | Decisión |
|---|---|
| Alcance | «Balance»: columnas en el explorador, autocompletado, pestañas de editor, historial de la sesión, «Explicar», interfaz en inglés. Fuera (GD-SQL-008, sin fase): formato SQL, historial en disco, búsqueda y reemplazo, snippets, `EXPLAIN ANALYZE` |
| Columnas | Pedido del propietario. Se leen al expandir; la búsqueda no busca columnas; doble clic o arrastre inserta el nombre citado |
| Historial | Dentro del registro de G5 («Abrir en el editor»), solo en memoria; sin segunda lista |
| «Explicar» | Solo `EXPLAIN`, nunca `ANALYZE`; una sentencia |
| Idioma | Textos del código en inglés; español por `.ts`/`.qm` según el idioma de QGIS; sin opción propia |
| Doble clic | Tabla o vista: «Cargar en QGIS…» (G5, sin cambios). Columna: insertar su nombre |
| Arquitectura | Propuesta de un arquitecto externo (ChatGPT), revisada: GD-CAT-002 en session-spec (no hay `catalog-spec.md`); se usa el `catalog_epoch` existente; GD-I18N-001 añadido a product-spec |

## 2. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC, roadmap y este plan | `spec_sync --check` |
| **E1** | `ListColumns` en el worker y el coordinador; nodos de columnas perezosos en el explorador, icono de geometría, ayuda; doble clic y arrastre insertan el nombre citado; invalidación por `catalog_epoch` | AT-CAT-002 |
| **E2** | Autocompletado (QScintilla) con bases, esquemas, tablas, vistas, columnas y funciones (`duckdb_functions()`); contexto, comentarios y cadenas; citado | AT-SQL-007 |
| **E3** | Pestañas de editor; «Abrir en el editor» desde el registro; «Explicar» | AT-SQL-008, 009, 010 |
| **E4** | Textos en inglés, `i18n/geoduck_es.ts` y `.qm`, carga según el idioma de QGIS, ZIP con la traducción | AT-I18N-001 |
| **E5** | Aceptación: `docs/g6/acceptance.md`, guía manual en Windows, regresión completa, sin funciones nuevas | Gate |

## 3. Por verificar (durante las entregas)

- ~~`duckdb_functions()` en DuckDB 1.5.0 y 2.0.0~~ Verificado en E2: nombres repetidos por sobrecarga, se toman sin repetir.
- ~~`EXPLAIN` de una sentencia DML o DDL no la ejecuta (E3)~~ Verificado en E3 (ver fila E3).
- ~~Compilar `.ts` → `.qm`~~ Resuelto en E4: `lrelease` viene con QGIS en conda-forge (Qt 5 y Qt 6, mismo resultado); el `.qm` se versiona y la CI comprueba que está al día.

## 4. Estado

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC y plan | En revisión | #85 |
| E1 Columnas en el explorador | En revisión: `ListColumns` (worker, `duckdb_columns()` filtrado y citado), palabras clave de `duckdb_keywords()` para citar solo cuando hace falta, nodos perezosos («Cargando…», error en el nodo y reintento), icono de geometría por tipo, ayuda con tipo y nulos, doble clic y arrastre; tablas abiertas se reabren y releen tras DDL; respuestas de un catálogo anterior descartadas. AT-CAT-002 | #86 |
| E2 Autocompletado | En revisión: `domain/completion.py` (sin Qt: comentarios y cadenas, sentencia del cursor, alias de FROM/JOIN/UPDATE, `x.`/`x.y.`, orden por grupos, máximo 200), vocabulario `duckdb_keywords()` + `duckdb_functions()` releído tras cambios de catálogo, columnas que faltan pedidas al worker; lista de QScintilla con iconos de QGIS, Ctrl+Espacio, Escape, Intro/Tab; autocompletado de `QgsCodeEditorSQL` desactivado. `duckdb_functions()` verificado en 1.5.0 y 2.0.0 (sin `pragma` ni operadores). AT-SQL-007 | #87 |
| E3 Pestañas, historial y «Explicar» | En revisión: pestañas de editor en la misma sesión (cada ejecución ligada a su pestaña: errores y doble clic en el registro vuelven a ella; confirmación al cerrar con SQL; no se cierra la que se ejecuta; siempre queda una; Ctrl+T/Ctrl+W); «Abrir en el editor» en el registro (SQL exacto que delimitó DuckDB, solo en memoria); «Explicar» = `EXPLAIN` de una sentencia SELECT/INSERT/UPDATE/DELETE, rechazo sin ejecutar del resto. **Verificado** con DuckDB 1.5.0 y 2.0.0: `EXPLAIN` de INSERT/UPDATE/DELETE/CREATE/DROP/COPY/ALTER/SET/BEGIN no los ejecuta; aun así, solo lecturas y DML (ADR-0011: `EXPLAIN INSTALL` no se pudo comprobar sin red). AT-SQL-008, 009, 010 | #88 |
| E4 Idioma | En revisión: textos del código en inglés (≈500: interfaz, motor, puente con QGIS, diagnóstico); `geoduck/domain/i18n.py` (`tr`, `N_`, sin Qt) y `geoduck/ui/i18n.py` (instala el catálogo según el idioma de QGIS antes de importar la interfaz, lo quita al descargar); `geoduck/i18n/geoduck_es.ts` → `.qm` con `lrelease` (idéntico en Qt 5 y Qt 6); `tools/i18n.py --check` en la CI. El español resultante es el texto de G5, sin cambios. Quedan en español los mensajes de registro técnico (`logging`) y los `detail` internos: no son interfaz. AT-I18N-001 | #89 |
| E5 Aceptación | En revisión: `docs/g6/acceptance.md` (AT → pruebas, verificaciones, hallazgos F-102..106, limitaciones) y guía manual en Windows `docs/certification/sql-professional.md`; sin funciones nuevas | — |
