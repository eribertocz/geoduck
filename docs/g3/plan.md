# G3 · `v0.4.0a1` QGIS Bridge MVP — plan de inicio

**Estado:** Propuesta (2026-11-01). Alcance del roadmap: **tabla plana y una geometría → capas memory**.
**Requisitos P0:** GD-BRD-001..005. **Gate:** primera Alpha útil de extremo a extremo (roadmap §4): abrir
GeoDuck → sesión → ATTACH → SELECT → cargar tabla o geometría en QGIS → DETACH → la capa permanece.
**Contrato:** `spec/specs/qgis-bridge-spec.md`; `spatial-spec` §4–§5 (C4 aprobado); ADR-0006, ADR-0010
(`qgis_bridge`).

## 1. Pasos (un PR por paso)

| Paso | Trabajo | Requisito / prueba |
|---|---|---|
| 1 | **Spike G3-A** (roadmap §3): memoria y paso worker → hilo principal con `RecordBatch`; tamaño de lote (8 192 / 16 384); 1–3 lotes en vuelo; coste de `addFeatures` en QGIS 3.44 y 4.2; viabilidad de cada tipo de la tabla de conversión (§7) | Evidencia; sin código del complemento |
| 2 | Motor: repetir **solo** una lectura repetible como relación + `to_arrow_reader`, con cola acotada y confirmación (backpressure), cancelación y conteos; nunca DDL/DML/`RETURNING` | GD-BRD-002, GD-SQL-006; AT-BRD-002, AT-SQL-006 |
| 3 | `qgis_bridge`: conversión por tipo a `QgsFields`/`QgsFeature` según §7, sin pérdidas silenciosas (BIGINT, HUGEINT, DECIMAL, TIMESTAMPTZ, LIST/STRUCT…) | §7; contrato probado por tipo |
| 4 | Capa memory **privada** construida en el hilo principal por tramos; publicación atómica en `QgsProject` al terminar; descarte en error o cancelación; `rows_read == rows_converted == rows_added` | GD-BRD-001, 003, 004; AT-BRD-001, 003, 004 |
| 5 | Una columna de geometría: WKB → `QgsGeometry`, tipo de geometría, CRS según C4 (sin reordenar ejes; CRS desconocido sin publicar sin decisión; AX-1..AX-4) | spatial-spec §4–§5 |
| 6 | Interfaz: «Cargar en QGIS» en la pestaña de un resultado repetible, con aviso de que se vuelve a ejecutar la consulta sobre el estado actual; progreso y cancelación; nombre de la capa a partir del título del resultado | sql-editor-spec §5 |
| 7 | Ciclo de vida: la capa sigue intacta tras DETACH y tras cerrar o descargar GeoDuck | GD-BRD-005; AT-BRD-005; caso pendiente de session-spec §6 |

## 2. Preguntas para el arquitecto

1. **ADR-0008 (GeoArrow).** ¿Se aprueba transportar la geometría con la exportación GeoArrow nativa
   (`geoarrow.wkb` + CRS en PROJJSON, F-10) en lugar de la proyección `ST_AsWKB` de `spatial-spec` §5? Es
   necesario antes del paso 5.
2. **Resultados grandes.** `qgis-bridge-spec` §3 pide estimar memoria, y sql-editor-spec §4 prohíbe un
   `COUNT(*)` automático en cada SELECT. ¿Se acepta un `COUNT(*)` **solo al pulsar «Cargar en QGIS»**, con
   aviso por encima de un umbral, cancelable?
3. **CRS desconocido en G3.** El selector de CRS completo es de G4. ¿Basta en G3 con el selector de CRS
   nativo de QGIS (`QgsProjectionSelectionDialog`) más «continuar sin CRS» con aviso, como pide C4 (AX-4)?
