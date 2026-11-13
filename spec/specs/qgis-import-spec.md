# SPEC GD-IMP — Enviar capas de QGIS a DuckDB

**Estado:** Alpha · G8 · `v0.9.0a1` (decisión del propietario, 2026-11-05; ADR-0015) · **IDs:** GD-IMP-001..007

## 1. Meta
Cerrar el ciclo QGIS ↔ DuckDB: copiar una o varias capas vectoriales de QGIS (o solo su selección) a tablas
de una base DuckDB de la sesión, con su geometría y su SRC, para analizarlas con SQL. Es una **copia
puntual**: no hay sincronización ni vínculo vivo (la sincronización sigue fuera de alcance, product-spec §6).
La capa de QGIS nunca cambia.

## 2. Puntos de entrada (GD-IMP-001)
- Menú de una capa vectorial en el panel de capas de QGIS: GeoDuck › «Enviar a GeoDuck…» (#142; con varias
  capas seleccionadas, las envía todas).
- Workspace de GeoDuck: «+» de la barra lateral → «Importar capas de QGIS…».
- Con la interfaz de G9 (Workspace Pro): arrastrar capas del panel de capas a una base de la barra lateral
  y Ctrl+K → «Enviar capa de QGIS a DuckDB…».

Las capas ráster, de malla o de nube de puntos aparecen desactivadas con el motivo. Sin sesión lista, la
acción explica que hay que iniciar una.

## 3. Diálogo (GD-IMP-002; maqueta en `docs/g8/maqueta/`)
- **Destino:** una base de la sesión **en escritura** y un esquema (por defecto, la base en uso y `main`),
  o **«Tabla temporal (solo esta sesión)»** (`CREATE TEMP TABLE`; decisión del propietario, 2026-11-05).
  Las bases de solo lectura no se ofrecen.
- **Una fila por capa:** casilla, nombre, origen (proveedor), número de entidades, tipo de geometría y SRC;
  nombre de la tabla destino editable. El nombre propuesto sale del nombre de la capa en minúsculas, sin
  acentos ni espacios (`_`), sin chocar con otra fila.
- **Qué pasará**, por fila y en vivo: «Tabla nueva», «Ya existe», «No se puede» (con el motivo).
- **Si la tabla ya existe** (decisión del propietario: por defecto **no enviar**): «No enviar», «Reemplazar»,
  «Añadir filas» u «Otro nombre», elegido por cada tabla que choca. Nada se sobrescribe sin elegirlo.
- **Opciones:** «Solo seleccionadas» (visible si alguna capa tiene selección; indica cuántas); «Reproyectar
  a…» (QGIS/PROJ, como spatial-spec §4); «Vista en vez de copia» (solo §5.2). El filtro de cada capa
  (Capa → Filtrar…) **siempre** se respeta y se indica: se envía lo que la capa muestra.
- **Columnas:** desplegable por capa con la conversión de cada campo (§6) y sus avisos.
- **Resumen** antes de enviar: tablas que se crean, reemplazan o amplían, filas y camino (§5).
- **Capa grande** (decisión del propietario): si el camino general (§5.3) se estima en más de un minuto
  —entidades a enviar / 100 000 por segundo, cifra prudente del spike G8-A (F-114)—, el resumen lo avisa
  con la estimación. Nunca bloquea.
- «Abrir la tabla al terminar» (recordado). Ctrl+Intro envía; Esc cancela.

## 4. Garantías (GD-IMP-003)
- **Cada capa por separado** (desde G9, propietario 2026-11-06; antes «todo o nada»): cada capa en **su
  transacción** de DuckDB en la base destino; si una falla o se cancela, `ROLLBACK` de esa capa y no queda su
  tabla nueva, reemplazada ni ampliada; las que ya terminaron quedan («Deshacer» borra las nuevas).
  `import_batches` sigue siendo «todo o nada» para lo que recibe; la interfaz le pasa una capa cada vez
  (workspace-pro-spec §9).
- **Progreso y cancelación** por capa y en total; la interfaz de QGIS sigue respondiendo.
- **Conteo:** al terminar cada capa, filas en DuckDB = entidades leídas; si no, `ROLLBACK` de esa capa y error.
- **Sin pérdidas silenciosas:** un campo que no se puede convertir, una geometría ilegible o un SRC que no se
  puede expresar detienen el envío con su motivo, o se avisan antes de enviar si el diálogo ya lo sabe.
- La capa de QGIS, su selección y su filtro no cambian.
- Al terminar: aviso con «Abrir» (abre la tabla) y, solo si se creó una tabla nueva, «Deshacer» (`DROP` de
  esa tabla). Reemplazar o añadir no se pueden deshacer desde GeoDuck y el diálogo lo dice antes.
- Una base que es origen de capas Conectadas con cambios sin guardar sigue las protecciones de G3.

## 5. Caminos (GD-IMP-004), elegidos solos y mostrados en el resumen
1. **Capa Conectada de GeoDuck** de la misma sesión: `CREATE TABLE … AS SELECT` dentro de DuckDB a partir de la
   consulta de la capa (con su filtro y, si se pide, la selección como tabla Arrow de identificadores unida
   con `JOIN`: F-119), sin pasar las entidades por QGIS.
2. **Archivo que DuckDB lee directo** (Parquet/GeoParquet en G8): `read_parquet` en la base destino. Sin
   `spatial`, el SRC del GeoParquet no se lee (F-118): se fija con `ST_SetCRS` y el SRC de la capa de QGIS. Solo
   aquí existe «Vista en vez de copia»: `CREATE VIEW … AS SELECT * FROM read_parquet('…')`, que no copia
   datos y depende de que el archivo siga en su sitio (se avisa). Con selección o filtro, se copia.
3. **Cualquier otra capa vectorial** (GeoPackage, Shapefile, PostGIS, memoria, CSV…): una `QgsTask` lee las
   entidades desde `QgsVectorLayerFeatureSource`, arma lotes Arrow (atributos + geometría WKB) y el worker
   los inserta dentro de la transacción: el primer lote crea la tabla con `CREATE TABLE … AS SELECT` y los
   demás usan `INSERT … SELECT` (sin `spatial` no se puede declarar `GEOMETRY('EPSG:…')`: F-115).
   Medido: 1 millón de puntos en 5–7 s (F-114). Contrapresión con el mismo canal acotado que
   las cargas (qgis-bridge-spec §2).
4. **Capa que viene de un archivo que el GDAL de DuckDB lee** (G9, decisión del propietario, 2026-11-07):
   GeoPackage, Shapefile, FlatGeobuf, GeoJSON, KML, Geodatabase, Excel… (la lista de §10), sin filtro ni
   selección, sin «Reproyectar a…» y sin «Añadir filas»: `CREATE TABLE … AS SELECT * FROM ST_Read('ruta',
   layer = '…')` dentro de DuckDB, con el SRC de la capa (`ST_SetCRS`). Medido (2 núcleos, GeoPackage con
   EPSG:32719): 1 millón de puntos en 0,3 s contra 6,9 s por el camino 3 (**23×**); 200 000 polígonos en 0,3 s
   contra 2,4 s (**8×**). Necesita `spatial` cargada: si no lo está, el paso 1 lo dice («Con la extensión
   «spatial» de DuckDB, las capas que vienen de un archivo las copia DuckDB: hasta 20 veces más rápido… Sin
   ella, las copia QGIS como siempre») con «Instalar y acelerar» / «Cargar y acelerar». **Nunca bloquea:** sin
   ese clic, el camino 3. El resumen dice «leído directo por DuckDB». **El filtro de la capa** va como `WHERE`
   y se comprueba con las filas que muestra QGIS: si no coinciden o DuckDB no lo entiende, nada se escribe y
   esa capa se copia por el camino 3, sin error. **Trazabilidad** (paso 3 y «Exportar ▾»): origen (ícono por
   tipo) → QGIS (capas) → DuckDB; el puente turquesa «⚡ DuckDB» salta QGIS; el diagrama es también el avance.
   **También sin `spatial` (#140):** una capa que viene de un **Parquet/GeoParquet, Arrow, CSV o JSON** la lee
   DuckDB con su lector propio (`read_parquet`, `read_csv`, `read_json`, PyArrow para Arrow), sin `spatial` y
   con el filtro como `WHERE`. La geometría y el SRC salen de la capa de QGIS (sin `pyarrow.parquet`, que en
   algunos QGIS de Windows no carga: F-130). CSV y JSON solo sin geometría (QGIS la arma de columnas de texto
   que DuckDB no ve como geometría) y siempre con la comprobación de filas. Si la lectura directa falla o da
   otras filas, esa capa se copia por el camino 3 («DuckDB lee el archivo distinto que QGIS»). Una unidad
   montada (Google Drive, OneDrive) es una ruta más.

## 6. Columnas y tipos (GD-IMP-005)
| QGIS (`QMetaType`) | DuckDB |
|---|---|
| Int / UInt | `INTEGER` / `UINTEGER` |
| LongLong / ULongLong | `BIGINT` / `UBIGINT` |
| Double | `DOUBLE` |
| Bool | `BOOLEAN` |
| String | `VARCHAR` |
| Date / Time / DateTime | `DATE` / `TIME` / `TIMESTAMP` (con zona horaria: `TIMESTAMPTZ`) |
| ByteArray | `BLOB` |
| StringList / List de números | `VARCHAR[]` / `DOUBLE[]` o `BIGINT[]` |
| Map u otro | `JSON` como texto, con aviso |

- Nombres de campo tal cual, entre comillas. DuckDB no distingue mayúsculas: dos campos que solo difieren en
  ellas (`ID` e `id`) se renombran (`id_2`) con aviso.
- El identificador interno de QGIS (FID) no se copia salvo que sea un campo de la capa.
- **«Añadir filas»:** cada campo debe existir en la tabla con un tipo al que DuckDB convierta sin pérdida, y la
  geometría con el mismo SRC (o «Reproyectar a…» ese SRC). Si no, el diálogo lo marca «No se puede» y explica
  qué columna falla.

## 7. Geometría y SRC (GD-IMP-006; spike G8-A)
- La columna de geometría lleva el nombre que trae la capa (p. ej. `geom` o `geometry` en un GeoPackage,
  `shape` en una geodatabase); si no trae ninguno, `geom` (decisión del propietario, 2026-11-05). Tipo
  `GEOMETRY('<SRC>')`. Si choca con un campo, se renombra con aviso (§6).
- El WKB pasa por Arrow y se convierte con `ST_GeomFromWKB`; el SRC se fija con `ST_SetCRS(geom, '<authid>')`,
  que funciona **sin `spatial`** en DuckDB 1.5.0 y 2.0.0 y vuelve a QGIS al cargar la tabla (verificado
  2026-11-05). DuckDB ignora el SRC de los metadatos GeoArrow al importar: por eso se fija explícitamente.
- SRC sin código de autoridad (personalizado): se envía como **PROJJSON** (QGIS 4.x `toJsonString()`; 3.x
  GDAL `osr` desde su WKT2). WKT2 no sirve: DuckDB 1.5.0 lo pierde al leer (F-116). Si no se puede expresar,
  el diálogo ofrece «Reproyectar a…» o continuar **sin SRC** de forma explícita. Nunca se inventa (C4).
- Capa sin SRC: la tabla queda sin SRC, con aviso.
- **Base que no guarda SRC** (F-120): un archivo con formato `v1.0.0+` —el que crea DuckDB 1.5.x por defecto—
  no admite `GEOMETRY` con SRC. El diálogo lo detecta (`duckdb_databases().tags['storage_version']`) y lo
  dice; el usuario elige enviar **sin SRC** u otra base. Nada se escribe hasta que elige.
- Z/M y colecciones se conservan (WKB). Las geometrías inválidas se copian tal cual (no es una reparación;
  para eso, «Diagnosticar geometrías…»). Las `NULL` siguen `NULL`.
- Varias familias en la misma capa: se copian todas en la misma columna `GEOMETRY`.
- `spatial` no se necesita ni se carga (ADR-0011).

## 8. Fuera de alcance de G8
Sincronización o capas vinculadas; enviar estilos, uniones o campos virtuales calculados como expresión
(se envía su valor); capas ráster; GeoPackage/Shapefile leídos directo por DuckDB (necesitan extensiones:
ADR-0011; en G9 sí, con consentimiento: §10); editar la tabla desde el diálogo.

## 9. Sin regresión (GD-IMP-007)
Las cargas DuckDB → QGIS (G3–G4), el workspace, el SQL, los cuadernos y las protecciones de sesión siguen igual; un envío en curso bloquea `DETACH` y el cierre de la base destino igual que una operación propia.


## 10. Archivos → DuckDB (GD-IMP-008; G9, decisión del propietario, 2026-11-07)
Importar archivos de datos a tablas de DuckDB **siempre con el motor de DuckDB** (nunca con QGIS; el
rendimiento es la idea de GeoDuck). Maqueta aprobada: `docs/g9/maqueta/importar-exportar.png`.

- **Puntos de entrada:** «+» de la barra lateral › «Importar archivos…»; clic derecho en una base o un esquema
  › «Importar archivos aquí…»; Ctrl+K › «Importar archivos…»; **arrastrar** uno o varios archivos desde el
  escritorio, el Explorador de archivos o el Navegador de QGIS a GeoDuck (con el «pato al lago», §3 de
  workspace-pro-spec). Soltar uno o varios archivos **en el editor SQL** escribe el SQL que los lee, sin
  ejecutarlo (#146, punto 14; antes, un `CREATE TABLE` por archivo): `FROM 'ruta';` si DuckDB lo lee por su
  extensión (Parquet, CSV, JSON), con su función si no, o `FROM ST_Read('ruta');` para los de GDAL, uno por
  archivo, **en la línea donde se sueltan** y separados por una línea en blanco. Si hace falta `spatial` y no
  está cargada, la primera línea es `LOAD spatial;` (o `INSTALL spatial; LOAD spatial;`), visible: lo decide el
  usuario al ejecutar. Arrow y
  los no compatibles siguen a «Importar archivos». **Las capas de QGIS soltadas en el editor abren siempre
  el diálogo** (decisión del propietario, 2026-11-07).
- **Selector de archivos:** filtro «Todos los compatibles» y uno por formato, con ⚡ en los más rápidos.
- **Formatos y lector** (verificado con DuckDB 2.0.0):

  | Formato | Extensiones | Lector |
  |---|---|---|
  | ⚡ Parquet / GeoParquet | `.parquet` | `read_parquet` (incluido) |
  | ⚡ Arrow / Feather | `.arrow` `.feather` `.ipc` | PyArrow (`pyarrow.dataset`, por flujo) |
  | ⚡ CSV / TSV | `.csv` `.tsv` | `read_csv` (incluido) |
  | JSON / NDJSON | `.json` `.ndjson` `.jsonl` | `read_json` (incluido) |
  | ⚡ FlatGeobuf, GeoPackage, Shapefile (`.shp` o `.zip`), GeoJSON (`.geojson` `.geojsonl`), KML/KMZ, Geodatabase de ArcGIS (`.gdb`), OpenStreetMap (`.osm.pbf`, solo importar), Excel (`.xlsx`) | | `ST_Read` de `spatial` (GDAL de DuckDB) |

- **`spatial` con consentimiento (ADR-0011):** si hace falta y no está cargada, el paso 1 lo dice en una nota
  («… se leen con la extensión «spatial» de DuckDB. No está instalada: GeoDuck la instalará al pulsar
  «Instalar y continuar» (una sola vez, ~40 MB)»). Sin ese clic, GeoDuck no instala ni carga nada; los archivos
  que no la necesitan se pueden importar igual. No hay lector alternativo.
- **Paso 1 (Archivos):** una fila por capa u hoja (un GeoPackage o una Geodatabase muestran sus capas; un Excel,
  sus hojas), agrupadas en puntos, líneas, polígonos y tablas sin geometría, con el formato, el SRC y las
  filas (las de los metadatos; CSV y JSON muestran el tamaño del archivo, porque contarlas exige leerlos).
  Las que no se pueden leer, en gris con el motivo.
- **Pasos 2 y 3:** los de §3 y §4 (destino, «si ya existe», progreso, «Deshacer»), con el título
  «Archivos → DuckDB». Cada capa se copia con `CREATE TABLE … AS SELECT` en el motor, en su propia
  transacción, con el conteo de §4.
- **Solo formatos modernos, rápidos o muy usados** (decisión del propietario, 2026-11-07): cualquier otro
  archivo (p. ej. SpatiaLite) no entra al diálogo: un aviso claro dice cuáles, qué hacer y si los demás siguen. Si el GDAL de
  DuckDB lo lee (SpatiaLite, DXF, GML, GPX, MapInfo, ODS…): «Escribir consulta» (una pestaña con su
  `FROM ST_Read('ruta');`, sin ejecutar y lista para añadirle parámetros; propietario, 2026-11-13) y «Abrir en QGIS» (luego se añade la capa); si no son
  datos: «GeoDuck no puede leer: …», sin acciones. **Sin SpatiaLite ni SQLite** en la lista (decisión del propietario, 2026-11-07): GeoPackage es el formato
  moderno sobre SQLite; el GDAL de DuckDB no escribe SpatiaLite.
- **Geometría y SRC:** la que da el lector (`GEOMETRY('EPSG:…')`); un GeoParquet sin `spatial` toma el SRC
  de sus metadatos `geo` (F-118). Una base que no guarda el SRC (F-120) sigue la regla de §7.
