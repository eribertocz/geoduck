# Extensión DuckDB `spatial` y prueba manual de G4 en Windows

**Estado:** §1–6 (instalación de `spatial`, G0): no verificada por ejecución en la sesión del implementador
(sin red hacia `extensions.duckdb.org`, decisión D7); se ejecuta en el equipo Windows de certificación.
§7 (prueba funcional de G4 Spatial Confidence): guía para el propietario, pendiente de ejecutar.

## 1. Qué es y qué necesita GeoDuck

- Extensión oficial y **firmada** de DuckDB (licencia MIT; enlaza GEOS LGPL-2.1, PROJ y GDAL MIT).
  GeoDuck **no** la redistribuye.
- En DuckDB ≥ 1.5 el tipo `GEOMETRY`, `ST_AsWKB`, `ST_CRS`, `ST_SetCRS` y el CRS `OGC:CRS84` funcionan
  **sin** spatial (verificado, evidencia F-05/F-10). Los CRS `EPSG:*` en el tipo, `ST_Transform`,
  `geometry_always_xy` y la mayoría de funciones `ST_*` requieren spatial (verificado: sin spatial,
  `GEOMETRY('EPSG:4326')` falla con «unrecognized coordinate system»).
- G0 no depende de spatial. G4 tampoco: ninguna función de GeoDuck la necesita (spatial-spec §10); solo la
  usa el SQL del usuario (`LOAD spatial;`; pruebas AX-1b, AX-1c, AX-2 y AX-3).

## 2. Dónde se instala

DuckDB guarda cada extensión por versión de DuckDB y plataforma:
`%USERPROFILE%\.duckdb\extensions\v<versión DuckDB>\windows_amd64\spatial.duckdb_extension`.
Consecuencia: **cambiar de DuckDB (p. ej. 1.5.6 → 2.0.0) exige reinstalar spatial** para la nueva
versión. El diagnóstico de GeoDuck informa el directorio efectivo (`extension_directory`).

## 3. Métodos de instalación

| Método | Cómo | Cuándo |
|---|---|---|
| S1 en línea, explícito | `INSTALL spatial; LOAD spatial;` desde el repositorio oficial. En certificación: `verify_env.py --install-spatial` | Equipos con salida a `extensions.duckdb.org` |
| S2 sin conexión | Descargar `https://extensions.duckdb.org/v<versión>/windows_amd64/spatial.duckdb_extension.gz` en otro equipo, copiarlo y ejecutar `INSTALL '<ruta>\spatial.duckdb_extension.gz'; LOAD spatial;` | Redes corporativas sin salida |
| S3 directorio propio | `SET extension_directory = '<carpeta de GeoDuck>'` antes de instalar | Solo si el propietario lo aprueba por ADR (aislamiento por perfil) |

En los tres, la **firma se verifica**: GeoDuck nunca activa `allow_unsigned_extensions`, nunca hace
`INSTALL`/`LOAD` silencioso desde un origen remoto y deja que la UI (G4) pida consentimiento explícito
(spec/docs/security.md §2, GD-SEC-001).

## 4. Verificación (en cada celda de certificación)

Ejecute con el Python de QGIS de la celda:

```powershell
<lanzador python-qgis*.bat> C:\geoduck\tools\verify_env.py --out C:\geoduck-cert\<celda>-spatial --only Spatial diagnostico --install-spatial
```

La comprobación «Spatial: instalación, carga, EPSG y orden de ejes» registra:

| Dato | Qué confirma |
|---|---|
| `version` | Versión de spatial cargada para esa versión de DuckDB |
| `epsg_type` | `GEOMETRY('EPSG:4326')` se reconoce con spatial cargada |
| `transform` | `ST_Transform` de La Paz (−68,15; −16,5) de EPSG:4326 a EPSG:32719. Compare con QGIS (contradicción C4 y orden de ejes) |
| `geometry_always_xy` | Si el ajuste existe y su valor por defecto en 1.5.x y 2.x |
| `geoarrow_crs_epsg_32719` | La exportación GeoArrow incluye el CRS EPSG en sus metadatos (ADR-0008) |

Repita con DuckDB 1.5.0, 1.5.6 y 2.0.0. Cada versión instala su propio binario de spatial.

**Contraste del orden de ejes.** En QGIS, `EPSG:4326` tiene `hasAxisInverted() == True` y
`OGC:CRS84` no (verificado en QGIS 3.34, 3.44 y 4.2). Si `transform` devuelve las coordenadas
intercambiadas respecto de lo que QGIS espera, se documenta como hallazgo para G4. No se corrige en
silencio.

## 5. Desinstalación

Borre `spatial.duckdb_extension` de la carpeta indicada en el diagnóstico (o toda la carpeta
`v<versión>\windows_amd64`). DuckDB no mantiene otro registro.

## 6. Resultado esperado para cerrar G0

- Spatial carga en Windows para al menos una versión de DuckDB por cada QGIS ancla, **o**
- la limitación queda documentada y el propietario la acepta explícitamente (criterio del gate G0).

## 7. Prueba manual de G4 (Spatial Confidence) en Windows

**Qué es.** Un recorrido guiado de AT-SPA-001..004 con la interfaz real, en Windows. Repite a mano lo que la CI
comprueba en Linux (`docs/g4/acceptance.md`). **No sustituye** a la certificación de
[`windows.md`](windows.md) (#10). Duración aproximada: 45 minutos.

**Celda mínima:** QGIS 3.34.x LTR con DuckDB 2.0.0 (la de la evidencia de G3). Si hay tiempo, repetir en QGIS
4.2 o con DuckDB 1.5.x. Solo los pasos 7.5 b–c necesitan `spatial`; todo lo demás funciona sin ella.

### 7.1 Preparación

1. Descargue el ZIP del complemento del PR o del commit que se prueba (CI → artefacto «ZIP del complemento»)
   y anote el commit.
2. QGIS → Complementos → Instalar desde ZIP. Abra el panel GeoDuck.
3. «Diagnóstico del entorno…» → «Copiar». Pegue el texto en la evidencia (§7.8). Debe decir «utilizable».
4. Cree un proyecto nuevo y vacío. Inicie una sesión en memoria.
5. Pegue en el editor SQL este script y ejecútelo entero. Crea los datos de prueba; no necesita `spatial`:

```sql
-- Dos geometrías: una con SRC declarado (centro) y otra sin SRC (poligono)
CREATE TABLE zonas AS SELECT range::INTEGER AS id, 'z' || range AS nombre,
  ('POINT(' || range || ' ' || range || ')')::GEOMETRY('OGC:CRS84') AS centro,
  ('POLYGON((' || range || ' 0,' || (range + 1) || ' 0,' || (range + 1) || ' 1,' || range || ' 0))')::GEOMETRY AS poligono
FROM range(300);

-- Geometrías guardadas como WKB (BLOB) y WKT (VARCHAR); la fila 4 es ilegible en ambas
CREATE TABLE crudas (id INTEGER PRIMARY KEY, wkb BLOB, wkt VARCHAR, etiqueta VARCHAR);
INSERT INTO crudas VALUES
  (1, from_hex('0101000000000000000000F03F0000000000000040'), 'POINT (1 2)', 'a'),
  (2, from_hex('000000000140080000000000004010000000000000'), 'POINT (3 4)', 'b'),
  (3, NULL, NULL, 'c');
CREATE TABLE crudas_mal AS SELECT * FROM crudas;
INSERT INTO crudas_mal VALUES (4, from_hex('0101'), 'no es WKT', 'd');

-- Tipos mixtos: puntos, líneas y polígonos; cada 10 filas una NULL; la fila 7 vacía
CREATE TABLE mixta AS SELECT range::INTEGER AS id, CASE
  WHEN range % 10 = 9 THEN NULL
  WHEN range = 7 THEN 'POINT EMPTY'::GEOMETRY
  WHEN range % 3 = 0 THEN ('POINT(' || range || ' 0)')::GEOMETRY
  WHEN range % 3 = 1 THEN ('LINESTRING(' || range || ' 0, ' || range || ' 1)')::GEOMETRY
  ELSE ('POLYGON((' || range || ' 0,' || (range + 1) || ' 0,' || range || ' 1,' || range || ' 0))')::GEOMETRY
END AS g FROM range(3000);

-- Un tipo que solo aparece en la última fila (F-93)
CREATE TABLE tardia AS SELECT range::INTEGER AS id, CASE WHEN range = 19999
  THEN 'POLYGON((0 0, 1 0, 0 1, 0 0))'::GEOMETRY
  ELSE ('POINT(' || range || ' 0)')::GEOMETRY END AS g FROM range(20000);

-- Validez: 1 válida, 2 inválidas (pajarita, anillo degenerado), 1 vacía, 1 NULL
CREATE TABLE geoms (id INTEGER PRIMARY KEY, g GEOMETRY);
INSERT INTO geoms VALUES
  (1, 'POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))'), (2, 'POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))'),
  (3, 'POLYGON((0 0, 1 0, 0 0))'), (4, 'POLYGON EMPTY'), (5, NULL);
```

**Cómo cargar.** «Copia en memoria» y «Copia rápida» son las copias; «Conectada a DuckDB» no copia. Para que una
Conectada sea editable, cargue la **tabla** desde el explorador (clic derecho → «Cargar en QGIS…» o doble clic),
no un `SELECT` (las consultas son de solo lectura, G3). Para las copias puede ejecutar
`SELECT * FROM <tabla>` y pulsar «Cargar en QGIS». Entre un paso y otro puede borrar las capas del proyecto.

### 7.2 AT-SPA-001 — 0, 1 y 2 geometrías; WKB y WKT

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | `SELECT 1 AS id, 'x' AS t` → «Cargar en QGIS», Copia en memoria | Tabla sin geometría (sin icono de mapa), 1 fila |
| b | `SELECT id, centro FROM zonas` → «Cargar en QGIS» | `centro` marcada sola; capa de puntos con SRC `OGC:CRS84`, 300 entidades |
| c | `SELECT * FROM zonas` → «Cargar en QGIS» | El diálogo muestra «Geometrías» con `centro` y `poligono`; solo una marcada; no deja aceptar si desmarca las dos |
| d | `SELECT * FROM crudas` → «Cargar en QGIS», sin tocar «Usar como geometría» | Tabla **sin** geometría; `wkb` y `wkt` aparecen como campos |
| e | Igual, pero «Usar como geometría» = `wkb (WKB)`, SRC `EPSG:4326`. Repetir con `wkt (WKT)`. Hacerlo en las tres modalidades | Capa de puntos de 3 entidades: (1 2), (3 4) y una sin geometría. Herramienta Identificar sobre el punto (3 4) confirma que el WKB big-endian se lee bien |
| f | Después de e, ejecute `SELECT id, hex(wkb), wkt FROM crudas ORDER BY id` | Igual que antes de cargar: el origen no cambió |

### 7.3 AT-SPA-002 — centroide y polígono, una y ambas capas

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | `SELECT * FROM zonas` → marcar `centro` **y** `poligono`; para `poligono` elegir SRC `EPSG:32719`. Copia en memoria | Dos capas: «… · centro» (puntos, `OGC:CRS84`) y «… · poligono» (polígonos, `EPSG:32719`), 300 entidades cada una. Abrir la tabla de atributos: ninguna tiene la columna de la otra geometría. El mensaje nombra las dos capas |
| b | Repetir a con Copia rápida | Igual que a |
| c | Explorador → tabla `zonas` → «Cargar en QGIS…», marcar ambas, Conectada | Dos capas Conectadas. Zoom a la capa de cada una: cada una usa su propia geometría. Ambas editables |
| d | Solo `poligono` marcada | Una sola capa; aviso que nombra `centro` como omitida |
| e | Cancelar a mitad: `SELECT range AS id, ('POINT(' \|\| range \|\| ' 0)')::GEOMETRY AS a, ('POINT(0 ' \|\| range \|\| ')')::GEOMETRY AS b FROM range(3000000)` → marcar `a` y `b`, Copia en memoria; pulse «Cancelar» (barra del editor SQL) mientras carga | No se añade ninguna capa al proyecto; la sesión vuelve a estar lista |

### 7.4 AT-SPA-003 — SRC sin `spatial`

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | `SELECT 'POINT(-68.15 -16.5)'::GEOMETRY('OGC:CRS84') AS g` → Copia en memoria | SRC `OGC:CRS84`. Identificar: x = −68,15, y = −16,5 |
| b | `SELECT 'POINT(-68.15 -16.5)'::GEOMETRY AS g` → «Cargar en QGIS» | El diálogo avisa «Los datos no declaran SRC» y pide uno. Continúe sin SRC: la capa queda sin SRC (QGIS no asigna EPSG:4326 por su cuenta) y coordenadas sin cambio |
| c | Igual que b, eligiendo `EPSG:4326` | SRC `EPSG:4326`; coordenadas sin cambio (elegir etiqueta, no transforma) |
| d | `SELECT 'POINT(-68.15 -16.5)'::GEOMETRY('FOO:123') AS g` → «Cargar en QGIS» | El diálogo dice que QGIS no reconoce `FOO:123` y pregunta. Nunca aparece otro SRC en su lugar |
| e | a con «Reproyectar a…» = `EPSG:32719`, en Copia en memoria y en Copia rápida | SRC `EPSG:32719`; Identificar: x ≈ 590716,04, y ≈ 8175564,99. El mensaje dice «Reproyectada de … a EPSG:32719» |
| f | En el diálogo, elija Conectada | «Reproyectar a…» no está disponible (la Conectada la reproyecta QGIS al vuelo) |

### 7.5 AT-SPA-003 — `spatial` con el SQL del usuario (ADR-0011)

En G5 se retiró la acción «Activar spatial…» (decisión del propietario, 2026-11-02): `spatial` se carga con SQL.

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | En una sesión nueva, sin escribir nada sobre spatial, use GeoDuck (pasos 7.2–7.4) | GeoDuck nunca carga ni instala `spatial` por su cuenta |
| b | En el editor: `INSTALL spatial; LOAD spatial;` | `spatial` cargada en esta sesión. «Diagnóstico del entorno…» la muestra cargada, con `geometry_always_xy` y su valor; GeoDuck no lo cambió |
| c | `SELECT ST_Transform('POINT(-68.15 -16.5)'::GEOMETRY('EPSG:4326'), 'EPSG:32719', true) AS g` → Copia en memoria | SRC `EPSG:32719`, x ≈ 590716,04, y ≈ 8175564,99 (igual que 7.4 e) |
| d | Cierre la sesión y abra otra | `spatial` ya no está cargada: `LOAD` valía solo para la sesión anterior |

### 7.6 AT-SPA-004 — ilegibles, tipos mixtos y dimensiones

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | `SELECT * FROM crudas_mal ORDER BY id`, «Usar como geometría» = `wkb (WKB)`, Copia en memoria | La carga falla: «Geometría ilegible en la columna «wkb» (WKB), fila 4». No se añade ninguna capa |
| b | Explorador → `crudas_mal` → Conectada con `wkb (WKB)` | Capa de 4 entidades; aviso «1 geometrías ilegibles en «wkb» (WKB): se muestran sin geometría» |
| c | `SELECT * FROM mixta` → Copia en memoria (opción «Tipos mixtos: una capa por tipo» activada) | Capas de puntos, líneas, polígonos y «sin geometría»; la suma de entidades es 3000 |
| d | Igual que c, desactivando «Tipos mixtos: una capa por tipo» | La carga falla y nombra los tipos encontrados; no se añade ninguna capa |
| e | Explorador → `mixta` → Conectada sin «Separar por tipo» | Una capa con todas las filas (3000) y aviso de tipos mixtos sin simbología por tipo |
| f | Explorador → `mixta` → Conectada con «Separar por tipo» | Tres capas («— Point», «— LineString», «— Polygon»); suma 2700; aviso de 300 filas sin geometría |
| g | Explorador → `tardia` → Conectada con «Separar por tipo» | Dos capas: «— Point» con 19 999 y «— Polygon» con 1 (el de la última fila no se pierde) |
| h | `SELECT 1 AS id, 'POINT(1 2)'::GEOMETRY AS g UNION ALL SELECT 2, 'POINT Z(3 4 5)'::GEOMETRY` → Copia en memoria | Capa `PointZ` (Propiedades → Información); la fila 1 tiene z = NaN y hay aviso «Z añadida con valor NaN a 1 geometrías sin Z» |
| i | `SELECT 'GEOMETRYCOLLECTION(POINT(1 1), LINESTRING(0 0, 1 1))'::GEOMETRY AS g` y `SELECT 'POINT ZM(1 2 3 4)'::GEOMETRY AS g` → Copia en memoria | Se cargan tal cual (colección; `PointZM`) |

### 7.7 AT-SPA-004 — diagnóstico y reparación

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | `SELECT * FROM geoms` → Copia en memoria. Panel Capas → clic derecho en la capa → «Diagnosticar geometrías…» | Examinadas 5: válidas 1, inválidas 2 (con motivo, p. ej. «Self-intersection»), vacías 1, NULL 1, ilegibles 0. Quedan seleccionadas las filas 2 y 3 |
| b | Repetir a con la capa Conectada de `geoms` (desde el explorador) | Mismos contadores; `SELECT * FROM geoms` no cambia |
| c | En el resultado, «Reparar en una copia…» → **No** | No se crea nada |
| d | «Reparar en una copia…» → **Sí** | Capas nuevas «geoms (reparada) — …»; el mensaje dice cuántas cambiaron de tipo (2) y que la original no cambia. La capa original sigue igual |
| e | Diagnosticar la Conectada de `crudas_mal` con `wkb` (paso 7.6 b) | Ilegibles 1, separadas de las NULL |

### 7.8 Evidencia

Cree `docs/evidence/g4/windows/<celda>/README.md` (por ejemplo `win11-qgis-3.34.15`) con el formato de
`docs/evidence/g3/windows/win11-qgis-3.34.15/README.md`:

- fecha, quién, commit y versión del ZIP;
- el diagnóstico del entorno copiado del panel (paso 7.1.3, y otra vez tras 7.5 b);
- una tabla con cada paso (7.2 a … 7.7 e) y «Correcto» o lo que pasó;
- hallazgos con ID nuevo (F-1xx) si algo no coincide. No se corrigen en silencio: cada uno va a un PR.
