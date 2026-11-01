# SPEC GD-SPA — Geometría, CRS y selección multi-geometría

**Estado:** baseline Alpha · **IDs:** GD-SPA-001..004

## 1. Meta
Una tabla, vista o consulta puede contener cero, una o múltiples columnas geoespaciales. GeoDuck debe decidir con el usuario la(s) geometría(s) de cada capa, preservar los valores, asignar CRS solo cuando esté fundamentado y entregar capas nativas QGIS completas.

## 2. Detección
1. Inspeccionar esquema tipado de relación/consulta y catálogos, buscando `GEOMETRY` y tipos espaciales DuckDB 1.5+/2.x compatibles, incluidos tipos especializados cuando se soporten.
2. Verificar funciones espaciales instaladas; para columnas BLOB/WKB o textos WKT exigir confirmación de origen/tipo, **no** inferir por nombre `geom` o por primeros bytes únicamente.
3. En `GEOMETRY` genérico, explorar tipos de valores con funciones espaciales cuando sea necesario para elegir la geometría del proveedor `memory`.
4. Distinguir `NULL`, `EMPTY`, `POINT`/`MULTIPOINT`, `LINESTRING`/`MULTILINESTRING`, `POLYGON`/`MULTIPOLYGON`, `GEOMETRYCOLLECTION`, subtipos con Z/M cuando PyQGIS lo permita.

## 3. Selección
| Situación | Acción |
|---|---|
| 0 geometrías | entregar tabla QGIS sin geometría |
| 1 geometría con tipo + CRS inequívocos | seleccionarla automáticamente |
| 2+ geometrías | selector: elegir una o «crear una capa por columna» |
| CRS ausente/ambiguo | pedir elección explícita o marcar como desconocido, sin inventar EPSG |
| mezcla de familias no compatible con layer tipo único | proponer dividir por familias o cancelar; nunca truncar geometría silenciosamente |
| geometría corrupta | reportar fallo de conversión; cancelar transferencia por defecto |
| geometría `NULL` | feature con geometría vacía, conforme al contrato de campos |

La columna espacial alternativa no se pierde en DuckDB. Para la capa concreta, por defecto se **excluye de los atributos** el resto de columnas espaciales, con opción explícita de incluirlas convertidas a texto WKT/WKB; el usuario puede crear una segunda capa para otra columna.

## 4. CRS en DuckDB 1.5+
DuckDB 1.5+ permite tipos de geometría parametrizados con identificadores CRS, p.ej. `GEOMETRY('OGC:CRS84')`, y funciones `ST_CRS`, `ST_SetCRS`; el módulo `spatial` aporta transformaciones y catálogos CRS. Por ello GeoDuck **sí debe inspeccionar metadatos CRS cuando estén disponibles**. Una columna `GEOMETRY` sin CRS declarado no autoriza deducir EPSG:4326.

Orden de preferencia:
1. CRS explícitamente asociado al tipo de geometría/resultset (documentado y compatible).
2. Metadatos de origen confiables y trazables, si existen, y no contradicen el resultado SQL.
3. Selección explícita del usuario.
4. Mantener CRS desconocido con advertencia clara si el usuario decide continuar.

`ST_SetCRS` etiqueta un CRS; **no transforma** coordenadas. Una reproyección real requiere `ST_Transform` u operación equivalente y decisión explícita. Verificar orden de ejes, particularmente `geometry_always_xy` de DuckDB 2.0, y contrastarlo con QGIS. Nunca realizar una transformación oculta.

## 5. Transporte WKB
Seleccionada una columna, generar una **relación de proyección explícita** que exponga la geometría como `ST_AsWKB(...)` de tipo binario, conservar otros atributos y un identificador estable de fila para la transferencia si resulta necesario. Convertir a `QgsGeometry.fromWkb` en main thread. Evitar serializar geometrías completas en WKT como camino principal por coste y precisión.

La generación de la proyección SQL debe citar campos correctamente y preservar semántica de la consulta original; no modificar SQL de usuario en el editor. Se necesita test de tipos especializados y funciones concretas en DuckDB 2.0.

## 6. Geometrías mixtas
Política V1: detectar incompatibilidades de familias geométricas antes de registrar capas. Si una columna contiene Point y Polygon mezclados, mostrar opciones **separar familias en capas** (solo cuando se implemente con garantías) o **cancelar con explicación**. No asignar tipo Polygon ignorando Points. El soporte opcional de `GeometryCollection` debe probarse en las ramas QGIS objetivo.

## 7. Múltiples geometrías
Consulta ejemplo:
```sql
SELECT id, ST_Centroid(geom) AS centro, geom AS poligono
FROM zonas;
```
El panel detecta `centro` y `poligono` y ofrece «Puntos», «Polígonos», «Ambos». Si el usuario elige ambos, GeoDuck crea dos capas independientes, verificadas, y las publica juntas al terminar. Las dos capas no mantienen conexión a DuckDB.

## 8. Pruebas geoespaciales obligatorias
- Point, Line, Polygon, Multi*, nulos/vacías, Z, geometría inválida.
- Dos columnas geométricas con familias diferentes y selección de ambas.
- CRS tipado DuckDB 1.5+/2.x y CRS desconocido; CRS de distinto eje y reproyección explícita.
- Filas con tipos mixtos en una columna: no se descartan silenciosamente.
- WKB con datos corruptos, `GEOMETRYCOLLECTION` y BLOB no geométrico.
- Consultas que generan geometría (`ST_Centroid`, `ST_Buffer`) sin columna espacial original.
