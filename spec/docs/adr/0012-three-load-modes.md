# ADR-0012: Tres modalidades de carga en QGIS (Memoria, Instantánea y Conectada)

**Estado:** Aceptado (2026-11-02, decisión del propietario) · **Enmienda:** ADR-0002 y ADR-0003 ·
**Evidencia:** spikes G3-A..D (`docs/g3/estudio-modalidades.md`, `docs/g3/estudio-proveedor.md`,
`docs/evidence/g3/`, hallazgos F-42..F-80)

## Contexto

ADR-0002 fijaba una sola salida: una copia en una capa `memory` sin vínculo con DuckDB. Los spikes de G3
midieron que:

- la conversión por fila en Python es el cuello de botella de esa copia (F-42..F-45);
- GDAL convierte lotes GeoArrow en C++, de 5 a 30 veces más rápido (F-46);
- un proveedor PyQGIS que reutiliza el worker de la sesión permite leer bajo demanda y editar con
  seguridad si GeoDuck aplica el guardado de forma atómica (F-61..F-80).

El propietario decide que G3 entregue las tres modalidades.

## Decisión

| Modalidad | Para qué | Tecnología | Vínculo con DuckDB tras la entrega |
|---|---|---|---|
| **Memoria** | Copia nativa de QGIS, máxima compatibilidad | DuckDB → PyArrow → PyQGIS → `QgsVectorLayer("memory")` | Ninguno (ADR-0002 sin cambios) |
| **Instantánea** | Copia rápida y con poca RAM | DuckDB → GeoArrow → GDAL `OGRLayer.WriteArrow` → GeoPackage en `/vsimem` → proveedor `ogr` | Ninguno con DuckDB; GeoDuck libera el archivo `/vsimem` cuando QGIS quita la capa |
| **Conectada** | Tablas y vistas grandes sin copiar; edición en DuckDB | Proveedor PyQGIS `geoduck` que ejecuta cada petición como operación del worker de la sesión | Sí: la capa depende de la sesión y de la base adjunta |

Reglas comunes:

1. **Una sola fuente de lectura:** la relación repetible + `to_arrow_reader` por lotes del motor
   (ADR-0003), con cancelación y sin `COUNT(*)` previo. Las tres modalidades la reutilizan.
2. **Tipos según qgis-bridge-spec §7, decididos en un solo lugar.** GeoDuck envuelve la consulta en un
   `SELECT` de normalización: DuckDB convierte en C++ lo que QGIS o GDAL no representan sin pérdida. Nada
   se convierte en silencio; lo que no se puede representar se rechaza o se convierte a texto con aviso.
3. **Geometría y CRS** desde `geoarrow.wkb` + PROJJSON (ADR-0008, C4), sin reordenar ejes.
4. **El worker sigue siendo el único dueño de la conexión** (ADR-0006). GDAL escribe dentro de la
   operación del worker; ningún objeto de QGIS se toca fuera del hilo principal, salvo los proveedores
   de datos, que QGIS llama desde sus hilos de dibujo y que nunca usan la conexión directamente.

Reglas de la modalidad Conectada:

5. **Contención:**
   - el worker atiende las lecturas del mapa con prioridad sobre el trabajo en cola, sin interrumpir el
     que ya corre;
   - cada petición del mapa se divide en páginas acotadas, así que nunca ocupa el worker durante todo un
     dibujado y la memoria por petición queda limitada;
   - una petición abandonada por QGIS se cancela.
6. **Edición:**
   - solo tablas base con clave primaria entera de una columna (el FID);
   - el guardado lo aplica GeoDuck desde `beforeCommitChanges`, en **una** transacción;
   - control optimista por huella de fila: si una fila cambió desde que QGIS la leyó, no se escribe nada;
   - validación previa de las comprobaciones de QGIS y escrituras por lotes;
   - los métodos del proveedor solo informan ese veredicto, así que QGIS informa éxito solo si DuckDB
     confirmó;
   - con una transacción del usuario abierta, el guardado se rechaza.
7. **Ciclo de vida:**
   - tras DETACH o cierre de la sesión, las capas conectadas de esa base quedan «no disponibles», sin
     error ni bloqueo, y vuelven cuando la base se adjunta de nuevo con el mismo alias;
   - DETACH y cierre se bloquean mientras haya cambios sin guardar en una capa conectada de esa base.

## Consecuencias

- Pro: el usuario elige entre compatibilidad (Memoria), velocidad y poca RAM (Instantánea) o trabajo en
  vivo sin copia y edición en DuckDB (Conectada).
- Pro: las tres comparten lectura, normalización de tipos y geometría; no hay tres conversiones distintas.
- Contra: la modalidad Conectada rompe la frontera de ADR-0002 para sus capas. GeoDuck debe seguirlas,
  marcarlas no disponibles y reconectarlas.
- Contra: la Instantánea requiere GDAL ≥ 3.8 (`WriteArrow`). Sin él, la opción se desactiva con un
  motivo y la Memoria sigue disponible.
- Contra: dibujar todo en la Conectada cuesta unas 3 veces más que en la Instantánea (F-65), y los
  cambios sin confirmar del usuario son visibles en sus capas (F-62).
- `qgis_bridge` puede importar `osgeo` (GDAL), que QGIS distribuye: ADR-0010 actualizado.

## Verificación

AT-BRD-001..012 (`qa/test-strategy.md`), en QGIS 3.44 y 4.2 y con DuckDB 1.5.0, 1.5.6 y 2.0.0.
