# GeoDuck — Roadmap Alpha por fases y versiones tentativas

**Fecha base:** 2026-11-01 · **Estado:** propuesta aprobable por gates, **sin fechas comprometidas**.

## 1. Política de versiones
Usar SemVer con sufijo pre-release PEP 440 compatible en Python para la documentación de releases (`0.1.0a1`, `0.1.0a2`, ...); para Git/GitHub se puede etiquetar `v0.1.0a1`. Esta convención representa **Alpha**, incluso cuando funciones ya sean útiles.

No saltar a beta/RC/1.0.0 por completar una lista: estable requiere evidencia prolongada de compatibilidad, instalación, seguridad, rendimiento, casos límite y experiencia real. Se permite `0.10.0a1`, `0.11.0a1`, etc., si es necesario.

Cada gate se cierra solo cuando pasan pruebas e2e relevantes y se aprueba su documento de aceptación. Un release puede tener varios parches alpha antes de avanzar.

## 2. Hitos
| Fase / release | Resultado verificable | Requisitos P0 | Gate de salida |
|---|---|---|---|
| G0 · `v0.1.0a1` Foundation | plugin abre dock, diagnóstico y sesión memoria | GD-BOOT-*, GD-SES-001 | QGIS 3/4 ancla cargan; duckdb/arrow/spatial validado |
| G1 · `v0.2.0a1` Connections | archivo RO/RW, catálogo, ATTACH/DETACH por UI | GD-SES-002..005 (de GD-SES-003, solo la UI), GD-CAT-001 | lock release real y temporales coherentes; invalidación de sesión notificada una sola vez (INV-1..INV-5) |
| G2 · `v0.3.0a1` SQL Execution | scripts mixtos, resultados y previews; ATTACH/DETACH desde SQL conciliados con la UI | GD-SQL-001..006, GD-SES-003 (parte SQL) | 2 SELECT y CREATE correctos; no reejecución DML |
| G3 · `v0.4.0a1` QGIS Bridge | tabla plana y una geometría en tres modalidades: Memoria, Instantánea (GeoPackage `/vsimem`) y Conectada editable (ADR-0012) | GD-BRD-001..012 | primera Alpha útil E2E; las tres modalidades cumplen AT-BRD-001..012; Memoria e Instantánea intactas tras DETACH |
| G4 · `v0.5.0a1` Spatial Confidence | multi-geometría, CRS, geometrías mixtas/invalidas | GD-SPA-001..004 | selección explícita; CRS correcto; sin pérdidas |
| G5 · `v0.6.0a1` Workspace UX | un workspace con dos presentaciones: ventana propia (por defecto) y panel acoplado (ADR-0013, issue #49) | GD-UX-001..008 | AT-UX-001..015; las tres cargas de G3/G4 en ambos modos; alternar sin perder estado ni repetir operaciones |
| G6 · `v0.7.0a1` SQL Professional | columnas en el explorador, autocompletado, pestañas de editor, historial de la sesión, «Explicar»; interfaz en inglés (#68) | GD-CAT-002, GD-SQL-007, GD-I18N-001 | AT-CAT-002, AT-SQL-007..010, AT-I18N-001; regresiones G0–G5; teclado, Qt 5 y Qt 6 |
| G7 · `v0.8.0a1` Notebook | cuadernos de celdas SQL en el mismo workspace: cada celda con su base, su resultado y «Cargar en QGIS ▾» (decisión del propietario, 2026-11-03); exportar y guardar cuadernos `.sql` con copia de recuperación | GD-NB-001..008 | AT-NB-001..012; regresiones G0–G6 |
| G8 · `v0.9.0a1` QGIS → DuckDB | enviar capas de QGIS (o su selección) a tablas DuckDB con geometría y SRC; todo o nada (ADR-0015) | GD-IMP-001..007 | AT-IMP-001..008; velocidad medida y publicada; regresiones G0–G7 |
| G9 · `v0.10.0a1` Workspace Pro | interfaz de administrador de base de datos tipo TablePlus: pestañas de tabla y de consulta, sin cuadernos (decisión del propietario, 2026-11-05) | por definir en su E0 | AT por definir; regresiones G0–G8 |
| G10 · `v0.11.0a1` Performance | backpressure, cancelación robusta, memoria | GD-BRD-003, GD-QA-001 | perf baseline y estrés sin crashes |
| G11 · `v0.12.0a1` Reliability & Distribution | instalación limpia, recuperación, hardening | GD-SEC-001, GD-COMP-001, GD-CFG-001 | matriz Windows/QGIS certificada |
| G12 · `v0.13.0a1` Public Alpha | feedback externo, documentación, issues reproducibles | cobertura consolidada | pruebas E2E, checklist release, known issues |
| G13+ · `v0.14.0a1` ... | Alpha evolutiva | por decisión | sin fecha beta o stable |

## 3. Dependencias/gates críticos
- **Decisión 2026-11-01:** ATTACH/DETACH escritos en SQL pasan de G1 a G2; G1 no incluye un editor SQL provisional.
- **Spike G0-A**: validar QGIS 3.44/4.2 + DuckDB 1.5.x y 2.x + PyArrow + Spatial en Windows, sin ello no afirmar viabilidad del MVP.
- **Spike G0-B**: comprobar editor SQL en bindings PyQGIS3/4, elegir una sola implementación principal con fallback si procede.
- **Spike G2-A**: multi-statement en DuckDB 1.5.x/2.x y política para `RETURNING`/SELECT reejecutable.
- **Spike G3-A**: límites reales de memoria y cambio worker→main con RecordBatch.
- **Spike G4-A** (reducido, decisión 2026-11-02): solo compatibilidades no demostradas — Z/M y colecciones por GeoArrow en QGIS 3.34/4.x, cabecera WKB y `ST_GeomFromWKB` sin `spatial` en DuckDB 1.5/2.0, `makeValid` en QGIS 3.34/4.x, coste de la muestra de tipos. CRS tipado y orden de ejes ya están demostrados (C4, F-10/F-14, AX).
- **Decisión 2026-11-02:** G5 · Workspace UX (issue #49) entra antes de SQL Professional; las fases siguientes se desplazan un número (SQL Professional G6, Performance G7, Reliability & Distribution G8, Public Alpha G9). La issue #68 (inglés) pasa a `v0.7.0a1` con su mismo alcance. G6 parte del workspace de G5: el editor avanzado se integra en `WorkspaceContent`, sin volver a crear shells.
- **Decisión 2026-11-02 (alcance de G6):** G6 incluye columnas en el explorador (GD-CAT-002, pedido del propietario), autocompletado, varias pestañas de editor, historial de la sesión dentro del registro, «Explicar» y la interfaz en inglés (#68). Formato SQL, historial en disco, búsqueda y reemplazo, snippets y `EXPLAIN ANALYZE` pasan a GD-SQL-008, sin fase asignada.
- **Decisión 2026-11-03:** G7 · Notebook entra antes de Performance; Performance pasa a G8, Reliability & Distribution a G9, Public Alpha a G10. Inspirado en la DuckDB UI (cuadernos de celdas), pero nativo en Qt y sobre la sesión única: no se incrusta la DuckDB UI (interfaz no libre, descargada de internet, servidor HTTP sin autenticación y fuera del worker; ADR-0006, ADR-0011).
- **Decisión 2026-11-05:** G8 · QGIS → DuckDB (ADR-0015) y G9 · Workspace Pro entran antes de Performance; Performance pasa a G10, Reliability & Distribution a G11, Public Alpha a G12. Orden A (propietario): primero QGIS → DuckDB, que no depende de la interfaz nueva; arrastrar capas a la barra lateral llega con G9.
- **Decisión 2026-11-05 (rumbo de G9):** interfaz de administrador de base de datos, moderna y minimalista, tipo TablePlus: barra lateral con recientes, favoritos y bases; pestañas de tabla (datos con filtros en chips, orden, paginación, búsqueda, «Estructura», detalle de fila) y de consulta (editor y resultado); Ctrl+K para abrir tablas y acciones; aviso con «Abrir»/«Deshacer». Los cuadernos de G7 se retiran (los `.sql` guardados se abren como consulta). Doble clic en una tabla abre su pestaña de datos. Editar celdas en la grilla queda para después. Maqueta en `docs/g8/maqueta/` (pantallas 1–3); su SPEC se escribe en el E0 de G9.
- **Spike G8-A:** velocidad del camino general (QGIS → Arrow → DuckDB) con 100 mil y 1 millón de entidades en QGIS 3.34 y 4.2; `ST_SetCRS` con SRC personalizados (PROJJSON/WKT2) sin `spatial`; GeoParquet con `read_parquet` sin `spatial`; selección de una capa Conectada como lista de identificadores; lectura de `QgsVectorLayerFeatureSource` en una `QgsTask` con los proveedores ogr, postgres, memory y delimitedtext.
- **Spike G10-A** (antes G8-A, G7-A y G6-A): mecanismo de cancelación DuckDB compatible y seguro, mediciones reales.

## 4. Capacidad mínima de Alpha útil
A partir de **v0.4.0a1**: abrir plugin → sesión DuckDB → ATTACH archivo → SELECT → seleccionar resultado → cargar tabla o geometría en QGIS → DETACH → capa permanece. Una demo de carga sin tests de integridad no aprueba el gate.

## 5. Condición de cada entrega
- Contrato y especificaciones actualizados.
- Tests vinculados por ID pasan (o limitación claramente documentada y aceptada por el propietario).
- Notas de versión con compatibilidad exacta, riesgos y cambios.
- No prometer sobre rendimiento sin benchmark ni compatibilidad sin ejecución real.
- Ninguna funcionalidad fuera de fase sin issue, análisis de dependencia y decisión del propietario.

## 6. Estable posterior
No se propone v1.0.0 en este roadmap. Antes de iniciar una eventual beta, evaluar: madurez de API, ausencia de corrupción de datos, compatibilidad QGIS3/4 ampliamente testada, instalador fiable, cancelación y errores resilientes, experiencias de usuarios externos, soporte/mantenimiento y seguridad revisada.

## Regla transversal de versiones
Desde el primer spike, los criterios de aceptación requieren DuckDB **1.5.0+**, con pruebas representativas tanto de 1.5.x como de 2.x. Ninguna etapa podrá declararse terminada si solo funciona en 2.x y falla una combinación 1.5.x certificada.
