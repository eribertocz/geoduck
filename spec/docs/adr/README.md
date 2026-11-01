# GeoDuck — Registro ADR

| ADR | Estado | Decisión |
|---|---|---|
| [ADR-0001](0001-session-root-memory.md) | Aceptado para Alpha | DuckDB raíz en memoria, archivos mediante ATTACH |
| [ADR-0002](0002-ownership-boundary.md) | Aceptado para Alpha | Capas nativas QGIS como entrega sin vínculo vivo |
| [ADR-0003](0003-arrow-qgis-bridge.md) | Aceptado sujeto a spike | Relaciones + Arrow por lotes + PyQGIS main-thread |
| [ADR-0004](0004-sql-execution.md) | Aceptado para Alpha | SQL completo y resultados por sentencia, replay seguro |
| [ADR-0005](0005-compatibility-alpha.md) | Aceptado sujeto a pruebas | Soporte probado QGIS3 y 4, Windows-first y Alpha prolongada |
| [ADR-0006](0006-connection-ownership.md) | Aceptado (2026-11-01) | Propiedad exclusiva de la conexión, cola serial y ciclo de vida de lectores Arrow |
| [ADR-0007](0007-cancellation-interrupt.md) | Aceptado en principios; pendiente de validación literal | `interrupt()` solo como excepción controlada en versiones verificadas |
| [ADR-0009](0009-pyarrow-selection-by-matrix.md) | Aceptado en principios; pendiente de validación literal | PyArrow según la matriz real; la de QGIS si existe |
| [ADR-0010](0010-package-boundaries.md) | Aceptado en principios; pendiente de validación literal | Paquetes y fronteras de importación verificadas por test |
| [ADR-0011](0011-coexistence-with-other-duckdb-plugins.md) | Aceptado (2026-11-01) | Convivencia con otros complementos DuckDB; sin modificaciones silenciosas |

Los ADR registran decisiones y compensaciones. Cambios que afecten compatibilidad, propiedad de capa o seguridad necesitan uno nuevo, no edición silenciosa del historial.
