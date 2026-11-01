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
| G3 · `v0.4.0a1` QGIS Bridge MVP | tabla plana y una geometría → capas memory | GD-BRD-001..005 | primera Alpha útil E2E; capas intactas tras DETACH |
| G4 · `v0.5.0a1` Spatial Confidence | multi-geometría, CRS, geometrías mixtas/invalidas | GD-SPA-001..004 | selección explícita; CRS correcto; sin pérdidas |
| G5 · `v0.6.0a1` SQL Professional | editor avanzado, historial, autocompletado | GD-SQL-007, GD-UX-001 | UX teclado/Qt5/Qt6 y errores profesionales |
| G6 · `v0.7.0a1` Performance | backpressure, cancelación robusta, memoria | GD-BRD-003, GD-QA-001 | perf baseline y estrés sin crashes |
| G7 · `v0.8.0a1` Reliability & Distribution | instalación limpia, recuperación, hardening | GD-SEC-001, GD-COMP-001, GD-CFG-001 | matriz Windows/QGIS certificada |
| G8 · `v0.9.0a1` Public Alpha | feedback externo, documentación, issues reproducibles | cobertura consolidada | pruebas E2E, checklist release, known issues |
| G9+ · `v0.10.0a1` ... | Alpha evolutiva | por decisión | sin fecha beta o stable |

## 3. Dependencias/gates críticos
- **Decisión 2026-11-01:** ATTACH/DETACH escritos en SQL pasan de G1 a G2; G1 no incluye un editor SQL provisional.
- **Spike G0-A**: validar QGIS 3.44/4.2 + DuckDB 1.5.x y 2.x + PyArrow + Spatial en Windows, sin ello no afirmar viabilidad del MVP.
- **Spike G0-B**: comprobar editor SQL en bindings PyQGIS3/4, elegir una sola implementación principal con fallback si procede.
- **Spike G2-A**: multi-statement en DuckDB 1.5.x/2.x y política para `RETURNING`/SELECT reejecutable.
- **Spike G3-A**: límites reales de memoria y cambio worker→main con RecordBatch.
- **Spike G4-A**: tipos `GEOMETRY('CRS')` y WKB en QGIS3/4.
- **Spike G6-A**: mecanismo de cancelación DuckDB compatible y seguro, mediciones reales.

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
