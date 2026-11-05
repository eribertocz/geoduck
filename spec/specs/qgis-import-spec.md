# SPEC GD-IMP — Enviar capas de QGIS a DuckDB

**Estado:** Alpha · G8 · `v0.9.0a1` (decisión del propietario, 2026-11-05; ADR-0015) · **IDs:** GD-IMP-001..007

## 1. Meta
Cerrar el ciclo QGIS ↔ DuckDB: copiar una o varias capas vectoriales de QGIS (o solo su selección) a tablas
de una base DuckDB de la sesión, con su geometría y su SRC, para analizarlas con SQL. Es una **copia
puntual**: no hay sincronización ni vínculo vivo (la sincronización sigue fuera de alcance, product-spec §6).
La capa de QGIS nunca cambia.

## 2. Puntos de entrada (GD-IMP-001)
- Menú de una capa vectorial en el panel de capas de QGIS: «Enviar a DuckDB…» (con varias capas
  seleccionadas, las envía todas).
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
- **Todo o nada:** todas las capas del envío en **una transacción** de DuckDB en la base destino; si una
  falla o se cancela, `ROLLBACK` y no queda ninguna tabla nueva, reemplazada ni ampliada.
- **Progreso y cancelación** por capa y en total; la interfaz de QGIS sigue respondiendo.
- **Conteo:** al terminar, filas en DuckDB = entidades leídas de cada capa; si no, `ROLLBACK` y error.
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
ADR-0011); editar la tabla desde el diálogo.

## 9. Sin regresión (GD-IMP-007)
Las cargas DuckDB → QGIS (G3–G4), el workspace, el SQL, los cuadernos y las protecciones de sesión siguen igual; un envío en curso bloquea `DETACH` y el cierre de la base destino igual que una operación propia.
