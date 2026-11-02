# G3 · `v0.4.0a1` QGIS Bridge — plan integral (tres modalidades)

**Estado:** En ejecución (decisión del propietario, 2026-11-02). **ADR-0012.**
**Requisitos:** GD-BRD-001..012. **Contrato:** `spec/specs/qgis-bridge-spec.md`; `spatial-spec` §4–§5 (C4);
ADR-0006, ADR-0008, ADR-0010, ADR-0012.

**Gate:** G3 solo está completo cuando las tres modalidades funcionan y cumplen AT-BRD-001..012 en
QGIS 3.44 y 4.2, con DuckDB 1.5.0, 1.5.6 y 2.0.0. Recorrido completo: abrir GeoDuck → sesión → ATTACH →
SELECT → cargar con cada modalidad → editar la capa conectada → DETACH. Tras el DETACH, las capas Memoria
e Instantánea siguen intactas y la Conectada queda no disponible hasta adjuntar de nuevo.

La investigación está cerrada (spikes G3-A..D, PR #56). Los prototipos de `tools/bench/` son referencia:
el código del complemento se escribe de nuevo con las fronteras de ADR-0010 y sus pruebas.

## 1. Entregas (un PR cada una, apiladas)

| Entrega | Trabajo | Reutiliza | Requisitos / pruebas |
|---|---|---|---|
| **E0** | SPEC (ADR-0012, qgis-bridge-spec, session, editor, UI, arquitectura, roadmap, test-strategy) y este plan | Estudios del PR #56 | — |
| **E1** | Motor: lectura por lotes de una consulta repetible con contrapresión, cancelación y conteos (`engine/bridge_read.py`); normalización de tipos §7 en SQL (`domain/bridge_types.py`, puro) y su aplicación según `DESCRIBE`; API de lotes en `ConnectionHandle` | `ConnectionHandle.read_arrow`, `CancelToken`, `SessionWorker` | GD-BRD-002, 007; AT-BRD-002, 007 (parte de motor) |
| **E2** | `qgis_bridge` + Memoria: campos y entidades por tramos en el hilo principal, geometría `geoarrow.wkb`, CRS desde PROJJSON (C4), capa privada, publicación atómica, conteos | E1 | GD-BRD-001, 003, 004, 005; AT-BRD-001..005 |
| **E3** | Instantánea: `WriteArrow` en GeoPackage `/vsimem` dentro de la operación del worker; registro de archivos `/vsimem` y liberación al quitar la capa; desactivada si GDAL < 3.8 | E1, E2 (publicación) | GD-BRD-006; AT-BRD-006 |
| **E4** | Interfaz: «Cargar en QGIS» con las tres modalidades (pestaña de resultado y explorador), progreso, cancelación, nombre de capa, CRS desconocido | E2, E3 | GD-BRD-012; AT-BRD-012 |
| **E5** | Conectada, lectura: proveedor `geoduck`, URI, metadatos, compilador de expresiones, pushdown, páginas por clave, prioridad en el worker, cancelación por `QgsFeedback`, registro de capas conectadas | E1 (normalización), worker | GD-BRD-008, 009; AT-BRD-008, 009 |
| **E6** | Conectada, edición: editabilidad, huellas, guardado atómico desde `beforeCommitChanges`, escrituras por lotes Arrow, validación previa, transacción del usuario, época de datos | E1 (API de lotes), E5 | GD-BRD-010; AT-BRD-010 |
| **E7** | Ciclo de vida y cierre de G3: DETACH/ATTACH, cierre, descarga y reapertura del proyecto con capas conectadas; `docs/g3/acceptance.md` con la evidencia de AT-BRD-001..012 | E5, E6 | GD-BRD-011; AT-BRD-011 y gate |

## 2. Criterios de aceptación por modalidad

| Modalidad | Debe cumplir |
|---|---|
| Memoria | Íntegra fila a fila (huella de atributos + WKB); CRS según C4; tipos §7 sin pérdida silenciosa; cancelar no deja capas; capa intacta tras DETACH y cierre; bloqueo de la interfaz ≤ 200 ms por tramo |
| Instantánea | Lo mismo que Memoria; editable; `/vsimem` liberado al quitar la capa y en error o cancelación; opción desactivada con motivo si GDAL < 3.8 |
| Conectada | Tabla, vista y SQL; pushdown de extensión, FID, columnas y expresiones compilables; páginas ≤ 50 000 filas; el SQL del usuario no espera más de una página; edición atómica con conflictos (100/1 000/10 000 entidades), sin éxito sin COMMIT ni pérdida del búfer; no disponible y reconectable ante DETACH/ATTACH/cierre; DETACH y cierre bloqueados con cambios sin guardar |

## 3. Pruebas

- **Motor** (`tests/engine`, sin QGIS, DuckDB 1.5.0/1.5.6/2.0.0): lectura por lotes, cancelación,
  normalización por tipo, API de lotes, prioridad de la cola.
- **Unitarias** (`tests/unit`): reglas de normalización, compilador de expresiones (sin QGIS: árbol
  propio), reglas de editabilidad.
- **QGIS** (`tests/qgis`, 3.44 y 4.2): carga en las tres modalidades, integridad, cancelación, edición,
  conflictos, ciclo de vida.
- **Arquitectura:** fila de `qgis_bridge` (con `osgeo`) en el test de fronteras.
- **Regresión:** la suite actual (495 + 35) debe seguir pasando en cada entrega.

## 4. Decisiones previas que siguen vigentes (2026-11-01)

1. ADR-0008: geometría desde `geoarrow.wkb` con su CRS.
2. Sin `COUNT(*)` previo.
3. CRS desconocido: selector nativo de QGIS o continuar sin CRS con advertencia.
4. Pruebas obligatorias: carga completa, cancelación sin capas parciales y supervivencia tras DETACH y
   cierre (Memoria e Instantánea).

## 5. Avance (2026-11-02)

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC y plan | Hecha | #57 |
| E1 Lectura normalizada | Hecha | #58 |
| E2 Memoria | Hecha | #59 |
| E3 Instantánea | Hecha | #60 |
| E4 Interfaz «Cargar en QGIS» | Hecha | #61 |
| E5 Conectada (lectura) | Hecha: proveedor `geoduck`, metadatos en una operación, páginas por FID con prioridad, pushdown de extensión/FID/columnas/expresiones, «no disponible» sin sesión | en revisión |
| E6 Conectada (edición) | Hecha: guardado atómico desde `beforeCommitChanges`, huellas, lotes Arrow, validación previa, transacción del usuario, época de datos | en revisión |
| E7 Ciclo de vida y aceptación | Hecha: no disponible/reconexión tras DETACH, cierre y reapertura; cambios sin guardar bloquean DETACH y cierre; `docs/g3/acceptance.md` | en revisión |

Hallazgos de implementación: QGIS asigna `EPSG:4326` en silencio a una capa memory sin CRS (se fija
siempre explícito); GDAL mezclado en un GeoPackage → una capa por familia y otra «sin geometría» con
`subset="<geom>" IS NULL`; `/vsimem` solo se libera tras quitar la última capa que lo usa.

Hallazgos de E5 (Conectada, lectura):

- **FID estable** en los tres casos: clave primaria entera; `rowid` de una tabla sin clave adecuada;
  `row_number() OVER ()` para vistas y consultas. Con filtros de extensión el FID no puede ser la
  posición dentro del resultado filtrado (identificar o abrir la tabla de atributos devolvería otra
  fila), así que **todas** las páginas avanzan por FID (`FID > último ORDER BY FID LIMIT n`), también
  sin clave. Esto se aparta del `LIMIT n OFFSET m` que §5.2 prevé sin clave: **pendiente de decisión
  del propietario** (la SPEC no se ha cambiado). Coste: en vistas y consultas cada página vuelve a
  numerar la consulta entera.
- **Metadatos sin `spatial`:** el núcleo de DuckDB no tiene agregado de extensión ni tipo de geometría.
  El tipo sale de la cabecera WKB (`hex(st_aswkb(g))[1:10]`); la extensión, de `ST_Extent_Agg` si
  `spatial` ya está cargada y, si no, de `stats(geom)` (texto en 1.5, estructura en 2.x). No se carga
  ninguna extensión (ADR-0011).
- **Hilos de dibujo de QGIS:** Python creaba y destruía su estado de hilo en cada entidad (~13 µs). Se
  conserva una vez por hilo (`keep_thread_state`). Dibujar 1 M de puntos: 19 s → 5,3 s (GeoPackage:
  1,4 s); zoom de 5×5° o filtro compilado: ~0,05 s.
- **Hilo principal:** espera una página como mucho 5 s (`MAIN_WAIT`); si la sesión está ocupada (p. ej.
  por una carga Memoria, que a su vez espera al hilo principal), la petición termina vacía con aviso en
  vez de congelar QGIS.

Hallazgos de E6 (Conectada, edición):

- **Huellas sin lectura previa:** una fila editada sin haberse leído durante la edición (p. ej. desde una
  tabla de atributos abierta antes de activar la edición) obtiene su huella en cuanto se edita, en una
  sola consulta por ráfaga de cambios. Sin esto, esas ediciones darían siempre conflicto.
- **Reintento tras un conflicto:** se registra la huella actual de las filas en conflicto; guardar otra
  vez sobrescribe a sabiendas (§5.4). Mientras, el búfer de QGIS queda intacto.
- **Comprobación de filas afectadas:** si un `UPDATE` o `DELETE` afecta menos filas de las esperadas, se
  revierte todo.
- **Columnas convertidas (§7, `writable=False`)** y la clave: no se pueden cambiar; se rechaza el guardado
  antes de tocar DuckDB.
- **Capacidades del proveedor en QGIS 3.44:** las banderas se combinan de izquierda a derecha
  (`flag | Capabilities` falla y aborta el proceso).
- Lotes de 100 / 1 000 / 10 000 cambios (más 10 % de borrados): 0,15 / 0,12 / 0,23 s en el guardado.

Hallazgos de E7 (ciclo de vida):

- **Alcance de la sesión en la URI:** las capas de una base adjunta desde archivo (`scope=attached`) usan
  la sesión activa, sea cual sea: sobreviven al cierre y a la reapertura del proyecto y vuelven al
  adjuntar la base con el mismo alias. Las de `:memory:`, `TEMP` o de un resultado del editor
  (`scope=session`) quedan ligadas a su sesión y nunca leen una tabla homónima de otra sesión.
- **Aviso de «no disponible»:** una sola línea en el registro de QGIS (pestaña GeoDuck) por cada paso a
  no disponible; la capa queda vacía y sin errores.
