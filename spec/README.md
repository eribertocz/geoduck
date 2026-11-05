# GeoDuck — Documentation & Specification Pack

> **Estado:** Draft de arquitectura v0.1 · **Fecha base:** 2026-11-01 · **Clasificación:** especificación, no software ejecutable.
> **Roles:** propietario del producto = usuario; arquitecto y especificador = ChatGPT; implementador = Claude Code. Claude Code no modifica unilateralmente decisiones de producto ni declara estable una versión.

## Propósito
GeoDuck es una **extensión de escritorio para QGIS, en Python**, que ofrece una sesión DuckDB de primera clase, un editor SQL profesional y un camino fiable para entregar tablas, vistas y resultados SQL como **capas nativas de memoria de QGIS**. Cuando la entrega concluye, QGIS administra esas capas sin vínculo vivo con GeoDuck o DuckDB.

**Flujo canónico:** abrir extensión → iniciar `:memory:` o seleccionar un archivo `.duckdb` (RO/RW) → opcionalmente `ATTACH` otras bases → elegir tabla/vista o ejecutar SQL → seleccionar resultado y, si corresponde, geometría/CRS → **Cargar en QGIS** → entregar capa(s) independientes → QGIS administra.

## Principios no negociables
1. No inventar otro SQL: DuckDB interpreta y ejecuta sus sentencias.
2. Priorizar `DuckDBPyRelation` para consultas y el lector Arrow por lotes; usar `DuckDBPyConnection.execute()` para administración/DDL/DML/transacciones.
3. **No** mezclar «Ejecutar SQL» con «Cargar en QGIS»; el usuario decide qué resultado entregar.
4. Una sola sesión lógica, propiedad de un ejecutor serializado; `ATTACH`/`DETACH` reales, desde SQL o UI.
5. Una transferencia incompleta **nunca** se registra como capa definitiva en el proyecto QGIS.
6. No prometer carga *zero-copy*: Arrow es transporte, PyQGIS realiza la conversión final.
7. UX moderna y minimalista, compatible con las ramas QGIS 3/4 certificadas.
8. Alpha prolongada. No existe fecha prevista para v1.0.0.

## Navegación

| Documento | Función |
|---|---|
| [Visión](docs/vision.md) | Problema, experiencia y límites |
| [Contrato de producto](docs/product-spec.md) | Requisitos verificables, ID y criterios |
| [Arquitectura](docs/architecture.md) | Componentes, hilos, estado y trazabilidad |
| [Tecnologías](docs/technology.md) | Stack, versiones y criterios de adopción |
| [Sesiones](specs/session-spec.md) | Raíz en memoria, ATTACH/DETACH, permisos y fallos |
| [SQL](specs/sql-editor-spec.md) | Scripts, resultados, editor, reejecución controlada |
| [Puente QGIS](specs/qgis-bridge-spec.md) | Arrow, tipos, atomicidad, entrega |
| [Espacial](specs/spatial-spec.md) | Multi-geometría, CRS, WKB, errores |
| [UI/UX](specs/ui-ux-spec.md) | Experiencia, componentes, estados y accesibilidad |
| [Seguridad](docs/security.md) | Riesgos y límites de confianza |
| [Compatibilidad](docs/compatibility-distribution.md) | Matriz QGIS/Python/Qt y entrega Windows |
| [Calidad](qa/test-strategy.md) | Pirámide CI, criterios y pruebas de aceptación |
| [Benchmarks](qa/benchmarks.md) | Metodología, escenarios y métricas |
| [Roadmap](docs/roadmap.md) | Fases Alpha, gates y dependencias |
| [Guía a Claude Code](docs/implementation-handoff.md) | Orden de trabajo, DoD y contrato de cambios |
| [ADRs](docs/adr/README.md) | Registro de decisiones arquitectónicas |
| [Fuentes](docs/references.md) | Referencias oficiales verificables |

## Alcance v0.x
- Incluye: conexión y exploración DuckDB, SQL completo local, scripts multi-sentencia, resultados, carga de tablas sin geometría y capas geográficas en memoria, resolución de CRS, gestión explícita de conexiones, pruebas y UX.
- Excluye por ahora: sincronización de capas, servidores, URLs, dashboards, colaboración y servicios web. Su inclusión requiere ADR y decisión del propietario. (La capa Conectada entró con ADR-0012; la copia puntual QGIS → DuckDB, con ADR-0015.)

## Instrucciones de uso de este paquete
- Leer primero `docs/vision.md`, `docs/product-spec.md`, `docs/architecture.md`, luego las cuatro SPEC.
- Cada implementación debe referenciar los IDs `GD-*` y sus pruebas `AT-*`.
- Los archivos de este paquete **no son código implementado** ni demuestran compatibilidad en un entorno QGIS instalado.
- No fijar automáticamente versiones nuevas de dependencias sin ensayar la matriz; los ejemplos SQL son orientativos, no pruebas de runtime.
