# G8 · `v0.9.0a1` QGIS → DuckDB — plan

**Estado:** En curso. **ADR-0015.** **Requisitos:** GD-IMP-001..007. **Contrato:**
`spec/specs/qgis-import-spec.md`; maqueta `docs/g8/maqueta/4-enviar-a-duckdb.dc.html`.

**Gate:** AT-IMP-001..008 en la matriz de CI (QGIS 3.34, 3.40, 3.44, 4.2 × DuckDB 1.5.0, 2.0.0); velocidad del
camino general medida y publicada (100 mil y 1 millón de entidades); guía manual en Windows; regresiones
G0–G7. Tag y release `v0.9.0a1` solo con autorización del propietario.

## 1. Decisiones del propietario (2026-11-05)

| | Decisión |
|---|---|
| Alcance | Enviar capas de QGIS (o su selección) a DuckDB como **copia puntual**, con geometría y SRC; sin sincronización (ADR-0015) |
| Orden | A: G8 QGIS → DuckDB, G9 Workspace Pro (tipo TablePlus), G10 Performance, G11 Reliability & Distribution, G12 Public Alpha |
| Si la tabla existe | Por defecto **no enviar**; reemplazar, añadir u otro nombre solo si se elige |
| Diálogo | El de la maqueta, mejorado: «qué pasará» por capa, conflicto resuelto en línea, columnas desplegables, resumen, Ctrl+Intro |
| G9 | Rumbo aprobado (roadmap §3): pestañas de tabla y consulta, sin cuadernos, doble clic abre la tabla, edición en grilla después; UX cuidada al máximo |

## 2. Ya verificado (2026-11-05, DuckDB 1.5.0 y 2.0.0, sin `spatial`)

| Qué | Resultado |
|---|---|
| Tabla Arrow con geometría WKB (`geoarrow.wkb`) registrada en DuckDB | se lee como `GEOMETRY`; el SRC de los metadatos **se ignora** |
| `ST_SetCRS(ST_GeomFromWKB(…), 'EPSG:32719')` en `CREATE TABLE AS` | la columna queda `GEOMETRY('EPSG:32719')` y vuelve a QGIS con ese SRC |

## 3. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC (qgis-import-spec), ADR-0015, roadmap renumerado, maqueta y este plan | `spec_sync --check` |
| **E0b** | Spike G8-A (roadmap §3), con mediciones en `docs/evidence/g8/` | — |
| **E1** | Motor: envío por lotes Arrow en una transacción (crear, reemplazar, añadir), `ST_SetCRS`, conteo, cancelación; conversión de tipos y nombres | AT-IMP-004, 006, 007 (motor) |
| **E2** | QGIS: `QgsTask` que lee la capa (selección y filtro), contrapresión; caminos Conectada y Parquet (y vista) | AT-IMP-003, 005 |
| **E3** | Diálogo y puntos de entrada (menú de capa, «+» del workspace), aviso con «Abrir» / «Deshacer» | AT-IMP-001, 002 |
| **E4** | Reproyectar, SRC personalizados, mensajes, idioma, accesibilidad, panel estrecho | AT-IMP-003, 007 |
| **E5** | Aceptación: `docs/g8/acceptance.md`, velocidad publicada, guía de Windows, regresión | Gate |

## 4. Decisiones del propietario sobre las preguntas del E0 (2026-11-05)

Las tres, «sí» (qgis-import-spec §3 y §7): destino «Tabla temporal (solo esta sesión)»; la columna de
geometría con el nombre que trae la capa, o `geom`; aviso de capa grande si se estima más de un minuto,
sin bloquear.

## 5. Avance

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, ADR-0015, roadmap, maqueta y plan | Fusionado | #104 |
| E0b Spike G8-A y decisiones del E0 | Fusionado (#105): F-114..F-119 (`docs/evidence/g8/spike/`); 1 millón de puntos en 5–7 s; SRC personalizado como PROJJSON | #105 |
| E1 Motor | En revisión: `domain/importing.py` (modos, nombres de tabla y de columna, tipos, SQL de cada lote, estimación de capa grande) y `engine/importing.py` (una transacción: `CREATE [OR REPLACE] TABLE … AS` con el primer lote, `INSERT … BY NAME` después, conteo, `ROLLBACK` ante error, cancelación o fallo del lector; rechaza una transacción del usuario abierta sin abortarla; F-120: base que no guarda SRC). AT-IMP-004, 006, 007 (motor) | — |
