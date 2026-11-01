# G0 — Contradicciones documentales y propuestas de resolución

La auditoría registró 12 puntos (C1–C12). **Nueve son contradicciones documentales**: el texto
aprobado dice algo que la realidad verificada o el propio paquete contradicen. **Tres son defectos
técnicos** de DuckDB/PyArrow que invalidan una suposición del contrato; ya están cubiertos por las
decisiones arquitectónicas del 2026-11-01 y por ADR-0006/0009. Ninguna se resuelve modificando
`spec/` por iniciativa del implementador.

## Nueve contradicciones documentales

| # | Documento | Qué dice | Qué se verificó | Propuesta | Decide | Estado |
|---|---|---|---|---|---|---|
| C1 | `technology.md`, `compatibility-distribution.md` | Anclas «QGIS 4.2.x actual» y «3.44.15 LTR» | El calendario oficial programó 4.4.0 / 3.44.16 para el 30-oct-2026; 4.2 ya no será LTR (próxima: 4.4.4, 5-mar-2027). La descarga aún ofrece 4.2.3 / 3.44.15 | Certificar 3.44.x + 4.2.3 ahora; sumar 4.4.x como P0 cuando esté en la descarga | Propietario (D3) | Abierta |
| C2 | `architecture.md` §5, `qgis-bridge-spec.md` §5 | No llamar a la interrupción de DuckDB desde otro hilo «no verificada» | `interrupt()` verificado en 1.5.0/1.5.6/2.0.0 (F-09) | ADR-0007: excepción controlada, solo versiones verificadas | Arquitecto | Decidida en principio; ADR-0007 propuesto |
| C3 | `spatial-spec.md` §5 | Transportar geometría con `ST_AsWKB(...)` | `ST_AsWKB` descarta el CRS; la exportación nativa es GeoArrow con PROJJSON (F-10) | ADR-0008 + enmienda de §5 | Arquitecto | Decidida en principio; ADR-0008 propuesto |
| C4 | `spatial-spec.md` §4 | `geometry_always_xy` «de DuckDB 2.0» | Es un ajuste de la extensión `spatial` en 1.5 y 2.0; sin spatial no existe | Corregir el texto. Verificado en Windows (F-14): en DuckDB 2.0 + spatial el ajuste existe sin fijar (`None`), `ST_Transform` exige el orden de ejes explícito y en 2.1 pasará a `true` por defecto | Arquitecto | Hechos verificados; falta enmendar el texto |
| C5 | `technology.md`, `sql-editor-spec.md` §2 | `extract_statements()` conservando posiciones «si la API lo soporta» | `Statement` no expone offsets; `query` incluye comentarios y espacios previos | Mapeo incremental del texto con tests adversariales (G2) | Implementador, registrado | Propuesta |
| C6 | `session-spec.md` §2 | `ATTACH` con «sentencias parametrizadas cuando sea posible» | `ATTACH ?` falla en 1.5.x, funciona en 2.0 (F-06) | Un único camino: literal con comillas escapadas + identificador citado (GD-3, `geoduck/domain/sql_text.py`) | Implementador, registrado | Función en G0 (GD-3); uso en G1 |
| C9 | `qgis-bridge-spec.md` §7 | «NULL real de QGIS» como si fuera uniforme | QGIS 3 → `QVariant` NULL; QGIS 4.2 → `None`; `QgsField(QMetaType)` no existe en 3.34 (F-11) | Adaptador `qgis_bridge/compat.py` con tests Qt5/Qt6 (G3) | Implementador, registrado | Propuesta |
| C11 | `sql-editor-spec.md` §5, ADR-0004 | Supone que `con.sql()` de DDL/DML no se re-ejecuta | `con.sql()` cambia entre 1.5 y 2.0 y las relaciones se re-ejecutan en cada lectura (F-08) | Sentencias del usuario solo por `execute()`; `con.sql()` solo para relaciones de lectura de GeoDuck | Implementador, registrado | Aplicada en el motor de G0 |
| C12 | `session-spec.md` §4 | «No hacer COMMIT silencioso» | Tras un error en `BEGIN`, `COMMIT` se acepta y revierte sin error (F-07) | Detectar el estado abortado y mostrar «COMMIT ejecutado como ROLLBACK» (G1/G2) | Arquitecto | Abierta |

## Tres defectos técnicos (cubiertos por decisiones arquitectónicas)

| # | Suposición del contrato | Defecto verificado | Resolución |
|---|---|---|---|
| C7 | `qgis-bridge-spec.md` §3: «cualquier reader anterior está cerrado» (precondición) | DuckDB 1.5.x trunca el lector sin error (F-01) | ADR-0006: guardia de resultado abierto en GeoDuck; implementado en G0 |
| C8 | `technology.md`: mínimo funcional 1.5.0 | 1.5.0 cae con uso concurrente (F-02) y tiene defectos de geometría (F-04, F-05) | ADR-0006 evita el uso concurrente; decisión D5 sobre «mínimo 1.5.0 / recomendado 1.5.4+» |
| C10 | `technology.md`: PyArrow sin restricción de NumPy | PyArrow 26 no importa con NumPy 1.x (F-03) | ADR-0009: selección por matriz; regla aplicada en el diagnóstico de G0 |

## Observación adicional detectada al implementar

| # | Documentos | Qué dicen | Propuesta | Decide | Estado |
|---|---|---|---|---|---|
| C13 | `architecture.md` §3 frente a `session-spec.md` §5 | Dos conjuntos de estados de sesión: `STOPPED/STARTING/READY/BUSY/CLOSING/FAILED` y `DISCONNECTED/CONNECTING/READY/BUSY/DETACHING/CLOSING/ERROR_RECOVERABLE` | Se implementó el de `session-spec` §5 (más específico, incluye `DETACHING`); unificar el texto de `architecture.md` | Arquitecto | Abierta |

## Riesgo nuevo detectado en Windows

| # | Riesgo | Evidencia | Propuesta | Decide |
|---|---|---|---|---|
| R11 | Otro complemento que incrusta su propia versión de DuckDB (QDuckDB trae 1.4.4) comparte el proceso de QGIS con GeoDuck. Solo puede haber un módulo `duckdb` cargado, y prevalece el que se carga primero: GeoDuck podría recibir una versión por debajo de su mínimo, o el otro complemento una versión que no espera | `docs/evidence/g0/windows/win11-qgis-3.34.15/` §5 | El diagnóstico informa de dónde viene `duckdb` y avisa si proviene de otro complemento. Política de convivencia a decidir (G7, distribución) | Arquitecto |

## Integridad del paquete (no contractual)

- `docs/manifest.json` estaba desactualizado (hashes anteriores a la revisión «DuckDB ≥ 1.5.0»). **En
  resolución** en el PR de sincronización normativa: `tools/spec_sync.py` regenera el manifiesto y CI lo
  verifica en cada PR.
- `GEODUCK_SPEC_MAESTRA.md` difería de `docs/implementation-handoff.md` en una línea; como los archivos
  individuales son normativos, la maestra pasa a regenerarse desde ellos (mismo PR).
- `docs/references.md` repite el identificador REF-16.
