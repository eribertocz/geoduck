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

`ST_SetCRS` etiqueta un CRS; **no transforma** coordenadas. Una reproyección real requiere `ST_Transform` u operación equivalente y una decisión explícita del usuario. Nunca realizar una transformación oculta.

**Orden de ejes.** GeoDuck entrega a QGIS las coordenadas del WKB tal como las produce DuckDB, sin reordenarlas; QGIS interpreta x como este/longitud también en CRS geográficos como EPSG:4326. GeoDuck no fija el ajuste `geometry_always_xy` de la extensión `spatial` (en DuckDB 2.0 no tiene valor por defecto y `ST_Transform` exige declararlo; en 2.1 pasará a `true`). Cuando `spatial` está cargada, GeoDuck muestra su valor efectivo en el diagnóstico y en los resultados espaciales cuando corresponda. Toda transformación iniciada por GeoDuck declara el orden de ejes en la propia llamada. Geometrías producidas en el orden de la autoridad (por ejemplo, latitud-longitud) se entregan tal cual y son responsabilidad del SQL del usuario. GeoDuck no intenta adivinar ejes invertidos a partir de los rangos de coordenadas.

**CRS ausente o desconocido.** Si DuckDB no declara CRS, o declara uno que QGIS no reconoce, GeoDuck no lo sustituye por otro (ni EPSG:4326 ni el CRS del proyecto), no publica la capa sin una decisión del usuario (puntos 3 y 4 anteriores), conserva el texto declarado en el mensaje y el registro, y nunca modifica las coordenadas. Elegir un CRS lo etiqueta; no transforma.

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
- Orden de ejes y CRS. Punto de referencia `POINT(-68.15 -16.5)`; tolerancia 1e-9 en grados y 0,01 m en metros; cada prueba verifica coordenadas **y** CRS:

| ID | Caso | CRS esperado en QGIS | Coordenadas esperadas | Además |
|---|---|---|---|---|
| AX-1a | `GEOMETRY('OGC:CRS84')` | válido, `OGC:CRS84` | x = −68,15, y = −16,5 | QGIS → EPSG:32719 = `590716.04, 8175564.99` |
| AX-1b | `EPSG:4326` con `spatial` | válido, `EPSG:4326` | x = −68,15, y = −16,5 aunque `hasAxisInverted()` sea verdadero | QGIS → EPSG:32719 = `590716.04, 8175564.99` |
| AX-1c | `ST_Transform(…, 'EPSG:4326', 'EPSG:32719', true)` | válido, `EPSG:32719` | `590716.04, 8175564.99` | igual a AX-1a/b transformado por QGIS |
| AX-2 | `geometry_always_xy` en `true`, `false` y sin fijar | — | — | valor mostrado en el diagnóstico y en un resultado con geometría = `duckdb_settings()`; GeoDuck no lo modifica |
| AX-3 | `ST_Transform` sin orden declarado, DuckDB 2.0, ajuste sin fijar | sin capa | — | error SQL del usuario; sin reintentos ni ajustes automáticos |
| AX-4a | sin CRS declarado | no válido; no se asigna ninguno | x = −68,15, y = −16,5 | no se publica sin decisión del usuario; advertencia visible |
| AX-4b | CRS desconocido para QGIS (`FOO:123`) | no válido; no se sustituye | x = −68,15, y = −16,5 | el mensaje muestra `FOO:123` |
| AX-4c | CRS desconocido y el usuario elige `EPSG:4326` | válido, `EPSG:4326` | x = −68,15, y = −16,5 | elegir etiqueta; no transforma |
