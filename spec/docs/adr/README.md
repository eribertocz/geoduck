# GeoDuck — Registro ADR

| ADR | Estado | Decisión |
|---|---|---|
| [ADR-0001](0001-session-root-memory.md) | Aceptado para Alpha | DuckDB raíz en memoria, archivos mediante ATTACH |
| [ADR-0002](0002-ownership-boundary.md) | Aceptado para Alpha | Capas nativas QGIS como entrega sin vínculo vivo |
| [ADR-0003](0003-arrow-qgis-bridge.md) | Aceptado sujeto a spike | Relaciones + Arrow por lotes + PyQGIS main-thread |
| [ADR-0004](0004-sql-execution.md) | Aceptado para Alpha | SQL completo y resultados por sentencia, replay seguro |
| [ADR-0005](0005-compatibility-alpha.md) | Aceptado sujeto a pruebas | Soporte probado QGIS3 y 4, Windows-first y Alpha prolongada |

Los ADR registran decisiones y compensaciones. Cambios que afecten compatibilidad, propiedad de capa o seguridad necesitan uno nuevo, no edición silenciosa del historial.
