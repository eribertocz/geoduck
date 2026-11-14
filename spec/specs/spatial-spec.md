# SPEC GD-SPA — Geometría, CRS y selección multi-geometría

**Estado:** Alpha · G4 Spatial Confidence (decisiones del propietario, 2026-11-02) · **IDs:** GD-SPA-001..004

## 1. Meta
Una tabla, vista o consulta puede contener cero, una o múltiples columnas geoespaciales. GeoDuck debe decidir con el usuario la(s) geometría(s) de cada capa, preservar los valores, asignar CRS solo cuando esté fundamentado y entregar capas nativas QGIS completas, en las tres modalidades de qgis-bridge-spec (Memoria, Instantánea y Conectada).

**Principio de G4:** ninguna pérdida silenciosa. Lo que no se puede representar se bloquea o se avisa con nombre de columna, motivo y número de filas afectadas.

## 2. Detección (GD-SPA-001)
1. Inspeccionar esquema tipado de relación/consulta y catálogos, buscando `GEOMETRY` y tipos espaciales DuckDB 1.5+/2.x compatibles, incluidos tipos especializados cuando se soporten.
2. **Columnas `BLOB` (WKB) y `VARCHAR` (WKT)** solo son geometría si el usuario lo indica en el diálogo de carga («Usar como geometría: WKB» o «WKT»). GeoDuck **no infiere** por nombre (`geom`, `wkt`…), por los primeros bytes ni por el contenido, y **no modifica el origen**: la conversión ocurre al leer. Su CRS es desconocido (§4): el usuario elige uno o continúa sin CRS. Un valor que no se puede leer como WKB/WKT es una geometría ilegible (§9).
3. En `GEOMETRY` genérico, el tipo de capa se deduce de los valores leídos (DuckDB no guarda el subtipo, F-71); en la modalidad Conectada, sin recorrer toda la fuente al abrir (§6).
4. Distinguir `NULL`, `EMPTY`, `POINT`/`MULTIPOINT`, `LINESTRING`/`MULTILINESTRING`, `POLYGON`/`MULTIPOLYGON`, `GEOMETRYCOLLECTION`, y las dimensiones Z, M y ZM.

## 3. Selección
| Situación | Acción |
|---|---|
| 0 geometrías | entregar tabla QGIS sin geometría; el diálogo ofrece marcar columnas `BLOB`/`VARCHAR` como geometría (§2.2) |
| 1 geometría con tipo + CRS inequívocos | seleccionarla automáticamente |
| 2+ geometrías | selector múltiple: el usuario marca una o varias columnas; **una capa por columna marcada** (§7) |
| CRS ausente/ambiguo | pedir elección explícita o marcar como desconocido, sin inventar EPSG (§4) |
| mezcla de familias | según la modalidad (§6); nunca truncar ni descartar geometrías en silencio |
| geometría ilegible (WKB/WKT de una columna marcada) | Memoria e Instantánea: la carga falla sin publicar nada e indica columna y fila; Conectada: la entidad se muestra sin geometría y se cuenta en el aviso de la capa (§9) |
| geometría `NULL` | feature con geometría vacía, conforme al contrato de campos |

Las columnas espaciales no elegidas para una capa no se pierden en DuckDB y **se excluyen de sus atributos**, con un aviso que las nombra; el usuario puede marcarlas para crear sus propias capas.

## 4. CRS en DuckDB 1.5+ (GD-SPA-003)
DuckDB 1.5+ permite tipos de geometría parametrizados con identificadores CRS, p.ej. `GEOMETRY('OGC:CRS84')`, y funciones `ST_CRS`, `ST_SetCRS`; el módulo `spatial` aporta transformaciones y catálogos CRS. Por ello GeoDuck **sí debe inspeccionar metadatos CRS cuando estén disponibles**. Una columna `GEOMETRY` sin CRS declarado no autoriza deducir EPSG:4326.

Orden de preferencia:
1. CRS explícitamente asociado al tipo de geometría/resultset (documentado y compatible).
2. Metadatos de origen confiables y trazables, si existen, y no contradicen el resultado SQL.
3. Selección explícita del usuario.
4. Mantener CRS desconocido con advertencia clara si el usuario decide continuar.

En G4 la única fuente del punto 1 es el tipo de la columna, que llega como PROJJSON en GeoArrow (§5); no hay una segunda declaración con la que pueda entrar en conflicto. Columnas `BLOB`/`VARCHAR` marcadas como geometría no traen CRS: puntos 3 y 4.

`ST_SetCRS` etiqueta un CRS; **no transforma** coordenadas. Una reproyección real requiere `ST_Transform` u operación equivalente y una decisión explícita del usuario. Nunca realizar una transformación oculta.

**Orden de ejes.** GeoDuck entrega a QGIS las coordenadas del WKB tal como las produce DuckDB, sin reordenarlas; QGIS interpreta x como este/longitud también en CRS geográficos como EPSG:4326. Con `spatial` cargada, GeoDuck fija `geometry_always_xy = true` al iniciar la sesión (#193; en DuckDB 2.0 no tiene valor por defecto y `ST_Transform` exige declararlo; en 2.1 pasará a `true`). Si el usuario lo cambia con su SQL, se respeta. Cuando `spatial` está cargada, GeoDuck muestra su valor efectivo en el diagnóstico y en los resultados espaciales cuando corresponda. Toda transformación iniciada por GeoDuck declara el orden de ejes en la propia llamada. Geometrías producidas en el orden de la autoridad (por ejemplo, latitud-longitud) se entregan tal cual y son responsabilidad del SQL del usuario. GeoDuck no intenta adivinar ejes invertidos a partir de los rangos de coordenadas.

**CRS ausente o desconocido.** Si DuckDB no declara CRS, o declara uno que QGIS no reconoce, GeoDuck no lo sustituye por otro (ni EPSG:4326 ni el CRS del proyecto), no publica la capa sin una decisión del usuario (puntos 3 y 4 anteriores), conserva el texto declarado en el mensaje y el registro, y nunca modifica las coordenadas. Elegir un CRS lo etiqueta; no transforma.

**Reproyección (decisión del propietario, 2026-11-02).** La reproyección es de QGIS/PROJ:
- **Memoria e Instantánea:** opción «Reproyectar a…» en el diálogo de carga, desactivada por defecto y solo disponible cuando la capa tiene CRS (declarado o elegido). GeoDuck transforma cada geometría con `QgsCoordinateTransform` (contexto de transformación del proyecto) al copiarla; la capa resultante lleva el CRS de destino y el mensaje de carga indica «reproyectada de A a B». Si una geometría no se puede transformar, la carga falla sin publicar nada e indica la fila. No usa `ST_Transform` ni necesita `spatial`.
- **Conectada:** no transforma; QGIS reproyecta al vuelo en el mapa, como con cualquier proveedor.
- El SQL del usuario puede usar `ST_Transform` (con `spatial` cargada por él): su resultado se entrega tal cual (AX-1c, AX-3).

## 5. Transporte WKB
Seleccionada una columna, leer la relación de lectura con `to_arrow_reader()`: DuckDB exporta cada columna `GEOMETRY` como `geoarrow.wkb`, con el CRS en PROJJSON en los metadatos del campo (ADR-0008). Esos metadatos son la fuente del tipo y del CRS (§4); no se impone `ST_AsWKB` (descarta el CRS) ni se añaden extensiones o paquetes adicionales. `ST_AsWKB` queda solo como alternativa explícita para tipos que DuckDB no exporte como GeoArrow. Convertir a `QgsGeometry.fromWkb` en main thread. Evitar serializar geometrías completas en WKT como camino principal por coste y precisión.

Columnas marcadas como geometría (§2.2): la consulta de lectura las convierte en DuckDB con funciones del núcleo, sin `spatial` (spike G4-A, DuckDB 1.5.0–2.0.0): `TRY(ST_GeomFromWKB(col))` para `BLOB` y `TRY(col::GEOMETRY)` para `VARCHAR`. A partir de ahí siguen el mismo camino que una columna `GEOMETRY` en las tres modalidades. Un valor no nulo cuya conversión da `NULL` es **ilegible** (§3, §9) y se detecta en la propia consulta.

La generación de la proyección SQL debe citar campos correctamente y preservar semántica de la consulta original; no modificar SQL de usuario en el editor. Se necesita test de tipos especializados y funciones concretas en DuckDB 2.0.

## 6. Geometrías mixtas y dimensiones (GD-SPA-004)
Una **familia** es punto, línea o polígono; `X` y `MultiX` son la misma familia. `GEOMETRYCOLLECTION` es una familia propia.

| Modalidad | Una sola familia | Varias familias |
|---|---|---|
| Memoria | capa `X` o `MultiX` (si alguna es múltiple) | opción del diálogo «Tipos mixtos: una capa por tipo», activada por defecto: una capa por familia (una vacía, p. ej. `POINT EMPTY`, queda en la suya), más una «sin geometría» si hay `NULL`; con una sola familia, las `NULL` quedan en su capa. Desactivada: la carga falla sin publicar nada y nombra los tipos encontrados |
| Instantánea | igual que Memoria | igual que Memoria (GDAL ya separa por tipo, G3) |
| Conectada | capa del tipo deducido | por defecto una capa `Unknown` con todas las filas (simbología por tipo no disponible, avisado). Opción «Separar por tipo»: una capa Conectada por familia, cada una con el filtro de su familia empujado a DuckDB; las filas `NULL` no entran en ninguna y se avisa su número |

- **Detección del tipo (Conectada):** al abrir, DuckDB lee solo la cabecera WKB de cada geometría (`DISTINCT` del código de tipo, sin pasar datos a Python: 0,1–0,2 s por millón de filas, F-93), como ya hacía G3. No se usa una muestra: un tipo que no apareciera en ella quedaría en una capa de otro tipo y QGIS no lo dibujaría (pérdida silenciosa). Una separación por tipo nunca pierde filas: cada familia presente tiene su capa y las `NULL` se avisan con su número.
- **Filtro de familia sin `spatial`:** se lee el código de tipo ISO de la cabecera de `ST_AsWKB` (núcleo de DuckDB 1.5+, siempre little-endian; spike G4-A: 100–180 ms por millón de filas).
- **Dimensiones Z/M:** se conservan. El tipo de la capa incluye toda dimensión presente en sus geometrías; las geometrías sin ella la reciben con valor `NaN`, con aviso. El proveedor `memory` acepta en silencio una geometría Z en una capa 2D y la perdería al exportar (spike G4-A, QGIS 3.34 y 4.2): por eso GeoDuck decide el tipo explícitamente y nunca deja una capa con dimensiones distintas de las de sus geometrías.
- **Edición:** en una capa de tipo fijo QGIS no admite geometrías de otra familia; en la capa `Unknown` cualquier familia es válida. No hay movimiento de entidades entre capas al editar.

## 7. Múltiples geometrías (GD-SPA-002)
Consulta ejemplo:
```sql
SELECT id, ST_Centroid(geom) AS centro, geom AS poligono
FROM zonas;
```
El panel detecta `centro` y `poligono` y permite marcar una o ambas. Por cada columna marcada GeoDuck crea una capa independiente, con su propio CRS y tipo y los mismos atributos no geométricos, en la modalidad elegida (Memoria, Instantánea o Conectada; decisión del propietario, 2026-11-02, que sustituye «las dos capas no mantienen conexión con la base»).

- **Nombres:** `<nombre> · <columna>` cuando se marca más de una; únicos en el proyecto.
- **Entrega atómica:** las capas se publican juntas al terminar; un error o una cancelación no publica ninguna.
- **Conectada:** cada capa es un proveedor `geoduck` con su `geom=<columna>`; la extensión, el filtro espacial y la edición usan solo su columna.

## 8. Pruebas geoespaciales obligatorias
- Point, Line, Polygon, Multi*, nulos/vacías, Z, M, ZM, `GEOMETRYCOLLECTION`, geometría inválida.
- Dos columnas geométricas con familias y CRS diferentes y selección de una y de ambas, en las tres modalidades.
- Columnas `BLOB` (WKB) y `VARCHAR` (WKT) marcadas como geometría, con valores ilegibles; sin marcar no son geometría.
- CRS tipado DuckDB 1.5+/2.x y CRS desconocido; CRS de distinto eje y reproyección explícita en Memoria e Instantánea.
- Filas con tipos mixtos en una columna: no se descartan silenciosamente.
- WKB con datos corruptos, `GEOMETRYCOLLECTION` y BLOB no geométrico.
- Consultas que generan geometría (`ST_Centroid`, `ST_Buffer`) sin columna espacial original.
- Orden de ejes y CRS. Punto de referencia `POINT(-68.15 -16.5)`; tolerancia 1e-9 en grados y 0,01 m en metros; cada prueba verifica coordenadas **y** CRS:

| ID | Caso | CRS esperado en QGIS | Coordenadas esperadas | Además |
|---|---|---|---|---|
| AX-1a | `GEOMETRY('OGC:CRS84')` | válido, `OGC:CRS84` | x = −68,15, y = −16,5 | QGIS → EPSG:32719 = `590716.04, 8175564.99` |
| AX-1b | `EPSG:4326` con `spatial` | válido, `EPSG:4326` | x = −68,15, y = −16,5 aunque `hasAxisInverted()` sea verdadero | QGIS → EPSG:32719 = `590716.04, 8175564.99` |
| AX-1c | `ST_Transform(GEOMETRY('EPSG:4326'), 'EPSG:32719', true)` | válido, `EPSG:32719` | `590716.04, 8175564.99` | igual a AX-1a/b transformado por QGIS. Con la forma de cuatro argumentos `ST_Transform(g, 'EPSG:4326', 'EPSG:32719', true)` DuckDB 2.0 no declara CRS en el resultado (F-99): la capa queda sin CRS asignado, con las mismas coordenadas |
| AX-2 | `geometry_always_xy` en `true`, `false` y sin fijar | — | — | valor mostrado en el diagnóstico y en un resultado con geometría = `duckdb_settings()`; GeoDuck no lo modifica |
| AX-3 | `ST_Transform` sin orden declarado, DuckDB 2.0, ajuste sin fijar | sin capa | — | error SQL del usuario; sin reintentos ni ajustes automáticos |
| AX-4a | sin CRS declarado | no válido; no se asigna ninguno | x = −68,15, y = −16,5 | no se publica sin decisión del usuario; advertencia visible |
| AX-4b | CRS desconocido para QGIS (`FOO:123`) | no válido; no se sustituye | x = −68,15, y = −16,5 | el mensaje muestra `FOO:123` |
| AX-4c | CRS desconocido y el usuario elige `EPSG:4326` | válido, `EPSG:4326` | x = −68,15, y = −16,5 | elegir etiqueta; no transforma |
| AX-5 | «Reproyectar a EPSG:32719» desde `OGC:CRS84`, Memoria e Instantánea | válido, `EPSG:32719` | `590716.04, 8175564.99` | el origen en DuckDB no cambia; el mensaje indica la reproyección |

### 8.1 Ida y vuelta QGIS → GeoDuck → QGIS (#141)
`tests/qgis/test_roundtrip.py` envía cada caso por el camino general y lo vuelve a cargar en las tres
modalidades, en toda la matriz de CI. Debe volver **idéntico**: el mismo SRC (UTM 19S, 20S y 21S, PSAD56
EPSG:24879, un SRC propio PROJ sin código y uno ESRI: nunca «el más parecido»), el mismo tipo de geometría con
Z y M, cada geometría (WKB; vacías y nulas como tales; una inválida tal cual, sin reparar), el orden lon/lat y
cada valor (entero de 64 bits mayor que 2^53, fecha, fecha y hora al milisegundo, hora, lógico, texto con tildes,
real). Excepciones documentadas: las **curvas** (CircularString, CompoundCurve…) vuelven en **segmentos
rectos**, porque DuckDB no tiene curvas, y el envío lo avisa («Las curvas se convierten en segmentos rectos»);
las **listas** vuelven como JSON de solo lectura; en la **Instantánea** la hora vuelve como texto ISO. Con
100 000 puntos, mismas filas y la misma suma de coordenadas.

## 9. Validez y reparación (GD-SPA-004; decisión del propietario, 2026-11-02)
**Estados distintos**, que se cuentan por separado: `NULL`, vacía, **ilegible** (WKB/WKT que no se puede leer, solo posible en columnas marcadas §2.2: DuckDB no admite `GEOMETRY` corrupta), **inválida** (legible pero topológicamente inválida según GEOS) y válida.

- **Diagnóstico bajo demanda:** menú contextual de una capa cargada por GeoDuck → «Diagnosticar geometrías…». Recorre la capa con QGIS/GEOS (`QgsGeometry.isGeosValid`, sin `spatial`) en una tarea cancelable, sin modificar la capa ni el origen. Informa total examinado, válidas, inválidas (con el motivo de GEOS de las primeras), vacías, `NULL` e ilegibles, y **selecciona en la capa** las entidades inválidas e ilegibles.
- **Reparación explícita:** desde el resultado del diagnóstico, «Reparar en una copia…» con confirmación. Crea una capa nueva en memoria `<capa> (reparada)` con `QgsGeometry.makeValid()`; la capa original y el origen en DuckDB no cambian. El mensaje informa cuántas geometrías cambiaron de tipo, de dimensión o de número de partes, y cuántas no se pudieron reparar (quedan sin geometría en la copia y se nombran). No se promete preservación geométrica exacta.
- **Cancelación o error:** no publica la copia ni deja recursos abiertos.

## 10. Extensión `spatial` (ADR-0011, security.md §2)
Ninguna función de G4 requiere `spatial`: CRS (GeoArrow/PROJJSON), filtro espacial (`ST_Intersects_Extent`), cabecera WKB (`ST_AsWKB`), reproyección (QGIS/PROJ), validez y reparación (QGIS/GEOS) y lectura WKB/WKT (QGIS) funcionan sin ella. Con `spatial` ya cargada, la extensión de una capa Conectada se calcula con `ST_Extent_Agg` (G3).

**`spatial` es parte de GeoDuck (#193, decisión del propietario, 2026-11-14).** GeoDuck es para análisis espacial y sin `spatial` DuckDB no lo tiene (sin ella solo trae `ST_GeomFromWKB`, `ST_AsText`, `ST_AsWKB`, `ST_CRS`, `ST_SetCRS`, `ST_Intersects_Extent` y, en 2.0, GeoJSON). Al iniciar cada sesión, GeoDuck ejecuta `LOAD spatial`; si no está instalada, antes `INSTALL spatial` (repositorio oficial firmado de DuckDB), sin preguntar. Con ella cargada fija `geometry_always_xy = true` (longitud, latitud; recomendado por DuckDB y valor por defecto en 2.1). **Sin internet o si falla**, GeoDuck funciona como sin ella y avisa en la barra de QGIS: «Se requiere la extensión spatial para el análisis espacial. No se pudo instalar.» + el mensaje de DuckDB, con «Reintentar» e «Instalar desde un archivo…» (una red sin salida a internet: `INSTALL '<archivo>'` + `LOAD spatial`; si el archivo no es el de esta versión de DuckDB y este sistema, el mensaje de DuckDB tal cual); en el siguiente inicio lo intenta otra vez. «Diagnóstico» da el enlace exacto del archivo (`https://extensions.duckdb.org/v<versión>/<sistema>/spatial.duckdb_extension.gz`) para descargarlo en otro equipo. «Archivos → GeoDuck», «Exportar ▾» a un formato de GDAL y la tarjeta «Cargar «spatial»» ya no piden permiso: si faltara, la instalan y cargan al usarlos (o muestran el mismo aviso). Ninguna otra extensión se instala ni se carga por cuenta de GeoDuck: `LOAD`/`INSTALL` de otras siguen siendo SQL del usuario.
