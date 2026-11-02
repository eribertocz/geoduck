# G3 · `v0.4.0a1` QGIS Bridge MVP — plan de inicio

**Estado:** **Autorizado** (2026-11-01), con las decisiones de §2. Alcance del roadmap: **tabla plana y una geometría → capas memory**.
**Requisitos P0:** GD-BRD-001..005. **Gate:** primera Alpha útil de extremo a extremo (roadmap §4): abrir
GeoDuck → sesión → ATTACH → SELECT → cargar tabla o geometría en QGIS → DETACH → la capa permanece.
**Contrato:** `spec/specs/qgis-bridge-spec.md`; `spatial-spec` §4–§5 (C4 aprobado); ADR-0006, ADR-0010
(`qgis_bridge`).

## 1. Pasos (un PR por paso)

| Paso | Trabajo | Requisito / prueba |
|---|---|---|
| 1 | **Spike G3-A** (roadmap §3): memoria y paso worker → hilo principal con `RecordBatch`; tamaño de lote (8 192 / 16 384); 1–3 lotes en vuelo; coste de `addFeatures` en QGIS 3.44 y 4.2; viabilidad de cada tipo de la tabla de conversión (§7) | Evidencia; sin código del complemento |
| 2 | Motor: repetir **solo** una lectura repetible como relación + `to_arrow_reader`, por lotes, con cola acotada y confirmación (backpressure), progreso cuando sea posible, cancelación y conteos; sin `COUNT(*)` previo; nunca DDL/DML/`RETURNING` | GD-BRD-002, GD-SQL-006; AT-BRD-002, AT-SQL-006 |
| 3 | `qgis_bridge`: conversión por tipo a `QgsFields`/`QgsFeature` según §7, sin pérdidas silenciosas (BIGINT, HUGEINT, DECIMAL, TIMESTAMPTZ, LIST/STRUCT…) | §7; contrato probado por tipo |
| 4 | Capa memory **privada** construida en el hilo principal por tramos; publicación atómica en `QgsProject` al terminar; descarte en error o cancelación; `rows_read == rows_converted == rows_added` | GD-BRD-001, 003, 004; AT-BRD-001, 003, 004 |
| 5 | Una columna de geometría desde `geoarrow.wkb` (ADR-0008): WKB → `QgsGeometry`, tipo de geometría, CRS desde PROJJSON según C4 (sin reordenar ejes; AX-1..AX-4); CRS desconocido → selector nativo de QGIS o continuar sin CRS con advertencia | spatial-spec §4–§5 |
| 6 | Interfaz: «Cargar en QGIS» en la pestaña de un resultado repetible, con aviso de que se vuelve a ejecutar la consulta sobre el estado actual; progreso y cancelación; nombre de la capa a partir del título del resultado | sql-editor-spec §5 |
| 7 | Ciclo de vida: la capa sigue intacta tras DETACH y tras cerrar o descargar GeoDuck | GD-BRD-005; AT-BRD-005; caso pendiente de session-spec §6 |

## 2. Decisiones del arquitecto (2026-11-01)

1. **ADR-0008 aprobado:** geometría desde `geoarrow.wkb` preservando el CRS; no se impone `ST_AsWKB` ni se
   añade `duck_geoarrow` ni otra extensión. `spatial-spec` §5 enmendada.
2. **Sin `COUNT(*)` previo** para cargar: transferencia por lotes, progreso cuando sea posible (filas
   recibidas; total solo si se conoce sin coste extra) y cancelación en todo momento.
3. **CRS desconocido:** selector nativo de QGIS (`QgsProjectionSelectionDialog`) o continuar sin CRS con
   advertencia.
4. **Pruebas obligatorias de G3:** carga completa, cancelación sin capas parciales y supervivencia de las
   capas tras DETACH y tras cerrar GeoDuck.
