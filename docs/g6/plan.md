# G6 · `v0.7.0a1` SQL Professional — plan

**Estado:** En curso (alcance aprobado por el propietario, 2026-11-02; propuesta de arquitectura revisada
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

- `duckdb_functions()` en DuckDB 1.5.0 y 2.0.0: columnas y funciones duplicadas por sobrecarga (E2).
- `EXPLAIN` de una sentencia DML o DDL no la ejecuta (E3); si no se confirma, «Explicar» solo para lecturas.
- Herramienta para compilar `.ts` → `.qm` disponible en la CI y en local; si el `.qm` se versiona o se genera
  al construir el ZIP (`tools/build_zip.py` rechaza archivos generados) (E4).

## 4. Estado

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC y plan | En revisión | — |
