# GeoDuck — Registro ADR

| ADR | Estado | Decisión |
|---|---|---|
| [ADR-0001](0001-session-root-memory.md) | Aceptado para Alpha | DuckDB raíz en memoria, archivos mediante ATTACH |
| [ADR-0002](0002-ownership-boundary.md) | Aceptado para Alpha; enmendado por ADR-0012 | Capas nativas QGIS como entrega sin vínculo vivo (Memoria e Instantánea) |
| [ADR-0003](0003-arrow-qgis-bridge.md) | Aceptado; enmendado por ADR-0012 | Relaciones + Arrow por lotes como fuente común de lectura |
| [ADR-0004](0004-sql-execution.md) | Aceptado para Alpha | SQL completo y resultados por sentencia, replay seguro |
| [ADR-0005](0005-compatibility-alpha.md) | Aceptado sujeto a pruebas | Soporte probado QGIS3 y 4, Windows-first y Alpha prolongada |
| [ADR-0006](0006-connection-ownership.md) | Aceptado (2026-11-01) | Propiedad exclusiva de la conexión, cola serial y ciclo de vida de lectores Arrow |
| [ADR-0007](0007-cancellation-interrupt.md) | Aceptado (2026-11-01) | `interrupt()` solo en versiones verificadas; conexión no recuperable se invalida; validación transaccional antes de reutilizarla |
| [ADR-0008](0008-geoarrow-geometry-transport.md) | Aceptado (2026-11-01) | Geometría y CRS con la exportación GeoArrow nativa (`geoarrow.wkb` + PROJJSON); sin `ST_AsWKB` impuesto ni extensiones adicionales |
| [ADR-0009](0009-pyarrow-selection-by-matrix.md) | Aceptado (2026-11-01) | PyArrow ≥ 18.1.0; prioridad a la incluida por QGIS; matriz real |
| [ADR-0010](0010-package-boundaries.md) | Aceptado (2026-11-01) | Paquetes y fronteras de importación verificadas por test |
| [ADR-0011](0011-coexistence-with-other-duckdb-plugins.md) | Aceptado (2026-11-01) | Convivencia con otros complementos DuckDB; sin modificaciones silenciosas |
| [ADR-0012](0012-three-load-modes.md) | Aceptado (2026-11-02) | Tres modalidades de carga: Memoria, Instantánea (GeoPackage `/vsimem`) y Conectada (proveedor PyQGIS editable) |
| [ADR-0013](0013-single-workspace-dual-presentation.md) | Aceptado (2026-11-02) | Un solo workspace con dos presentaciones: ventana propia (por defecto) y panel acoplado |

Los ADR registran decisiones y compensaciones. Cambios que afecten compatibilidad, propiedad de capa o seguridad necesitan uno nuevo, no edición silenciosa del historial.
