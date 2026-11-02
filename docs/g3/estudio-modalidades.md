# Estudio G3: modalidades de carga en QGIS (para decisión)

**Estado:** para decisión del arquitecto y del propietario. **No modifica `spec/`** ni implementa nada del
complemento: solo hay scripts de medición en `tools/bench/` y evidencia en `docs/evidence/g3/`
(hallazgos F-42..F-60). Fecha: 2026-11-01.

## 1. Pregunta

Cómo debe GeoDuck llevar resultados de DuckDB a QGIS. Se comparan tres modalidades:

1. **Memoria QGIS**: transferencia completa con PyArrow a una capa `memory` (lo que hoy fija
   qgis-bridge-spec §1).
2. **GeoArrow + GDAL/QGIS**: DuckDB entrega lotes GeoArrow y GDAL los convierte en C++, en `/vsimem`
   (RAM) o en un archivo.
3. **Conectada a DuckDB**: un proveedor que consulte tablas, vistas o SQL bajo demanda, como PostGIS.

## 2. Respuesta corta

- **Dos modalidades a largo plazo, una ahora.** «Instantánea» se implementa en G3; «Conectada» se aplaza.
  Hoy no hay ninguna tecnología existente que la haga bien (§5.3) y construir un proveedor propio está
  fuera de la fase.
- **Instantánea, estrategia única predeterminada:**
  1. DuckDB normaliza los tipos con un `SELECT` envolvente generado según §7 (conversiones declarativas
     en C++, sin bucles Python por fila).
  2. El lector Arrow (GeoArrow, con CRS) va por lotes, con contrapresión y cancelación cooperativa.
  3. GDAL escribe esos lotes con `OGRLayer.WriteArrow` en un **GeoPackage en `/vsimem`**: GDAL hace la
     conversión de tipos, geometría y CRS.
  4. QGIS abre la capa con su proveedor OGR, privada hasta estar completa; luego se publica.
- **Alternativa, solo si GDAL < 3.8** (sin `WriteArrow`): la ruta propia a capa `memory`, con la misma
  normalización SQL, fechas desde enteros y tramos de 1 024 filas.
- **Requiere cambiar la SPEC** (§1, §5, §10 de qgis-bridge-spec), por eso se presenta para decisión
  (§7 de este estudio).

## 3. Entorno y método

Linux, 2 CPU, 8 GB. QGIS 3.44.14 (Qt 5.15) y 4.2.3 (Qt 6.11), ambos con GDAL 3.13.3. DuckDB 2.0.0 en QGIS;
motor también con 1.5.0 y 1.5.6. Cada escenario corre en un proceso nuevo. La integridad se comprueba
con una huella SHA-256 por fila (atributos + WKB) contra DuckDB. **No es Windows** (#10): las
conclusiones marcadas «por confirmar» dependen de esa certificación. Cómo reproducir:
[`docs/evidence/g3/README.md`](../evidence/g3/README.md).

## 4. Rutas medidas (1 M de filas: id, texto, DECIMAL, TIMESTAMP, booleano, punto con CRS)

| Ruta | QGIS | Total s | RAM retenida MB | Bloqueo máx. UI ms | Editable | Tras reabrir proyecto |
|---|---|---:|---:|---:|---|---|
| Memoria (propia, la mejor variante) | 3.44 / 4.2 | 10,1 / 8,7 | 454 / 548 | 70 / 71 | sí | no |
| GeoArrow → Arrow IPC `/vsimem` → OGR | 3.44 / 4.2 | 0,30 / 0,32 | 138 / 135 | 60 / 116 | **no** | no |
| GeoArrow → Arrow IPC en disco → OGR | 3.44 / 4.2 | 0,24 / 0,35 | 41 / 27 | 71 / 130 | **no** | sí |
| **GeoArrow → GeoPackage `/vsimem` (WriteArrow) → OGR** | 3.44 / 4.2 | **1,8 / 2,2** | **150 / 175** | **34 / 99** | **sí** | no |
| GeoArrow → GDAL → `materialize()` a memory | 3.44 / 4.2 | 3,4 / **45,5** | 558 / 655 | 3 180 / **45 308** | sí | no |
| DuckDB `COPY` → GeoParquet en disco → OGR | 3.44 / 4.2 | 0,36 / 0,41 | 122 / 77 | 20 / 76 | sí | sí |

En todas: integridad completa, la capa sobrevive a `DETACH`, al cierre de la conexión y al borrado del
`.duckdb`, y la cancelación a mitad no deja capas ni archivos (F-58, F-59). Dibujar la capa completa
cuesta lo mismo en todas (1,0–1,6 s con 1 M). Leer todos los atributos desde Python en QGIS 4.2 cuesta
≈ 10 s en memory y ≈ 55 s en OGR (F-49, por confirmar en Windows).

## 5. Matriz comparativa

| Criterio | 1. Memoria (propia) | 2. GeoArrow + GDAL (GeoPackage `/vsimem`) | 3. Conectada (mejor opción existente: ADBC de GDAL) |
|---|---|---|---|
| Viabilidad QGIS 3.34–4.x | Sí | Sí con GDAL ≥ 3.8 (`WriteArrow`); GeoPackage está en todo GDAL | Solo GDAL ≥ 3.11 con driver ADBC; QGIS no trae `libduckdb` |
| Viabilidad DuckDB 1.5+/2.x | Sí | Sí (GeoArrow y CRS desde 1.5) | Con 2.0 no lista tablas ni vistas; solo capas `SQL=` (F-56) |
| Windows | Sí (solo Python) | Por confirmar en #10: GDAL de OSGeo4W ≥ 3.8 | Requiere distribuir `libduckdb.dll` y la extensión `spatial`; una segunda copia de DuckDB en el proceso |
| Tiempo 1 M | 9–10 s | ≈ 2 s | Apertura 0,3 s; cada vista vuelve a consultar |
| RAM 1 M | 450–550 MB | 150–175 MB | Lo que pida cada vista |
| Escala a millones | Lineal en RAM; 5 M ≈ 2,5 GB (estimado) | Lineal en RAM, 3× menos; 5 M ≈ 0,8–0,9 GB (estimado) | Sí, sin materializar |
| Extensión visible, filtros, índices | Índice en memoria de QGIS | Índice espacial del GeoPackage (opcional) | Empuja extensión y atributos a DuckDB: 1 % del área en 0,8–0,9 s (1 M) y 3,1–3,7 s (5 M), más lento que GeoParquet en disco (0,16–0,35 s y ≈ 1 s) |
| Geometrías | WKB → `QgsGeometry` | GDAL; una geometría por capa | Solo con `spatial` cargada |
| CRS | GeoDuck debe traducirlo | GDAL lo lee de GeoArrow (`OGC:CRS84` exacto) | **Se pierde** en capas `SQL=` |
| Tipos (§7) | Reglas propias por tipo; fallan DECIMAL y fechas (F-43, F-45) | Fiel tras normalizar en SQL; sin ella, pérdidas silenciosas (F-47) | Las de GDAL (F-47) |
| Identificadores | FID nativo | FID de GeoPackage; el id del usuario queda como atributo (§8) | FID sintético de la consulta |
| Escritura / actualización | Edición en QGIS; no vuelve a DuckDB | Edición en QGIS; no vuelve a DuckDB | Solo lectura |
| Cancelación | Cooperativa por tramo | Cooperativa por lote; se borra `/vsimem` | Por consulta (GDAL) |
| Concurrencia con la sesión | Ninguna tras publicar | Ninguna tras publicar | Otra conexión al mismo archivo; no ve `:memory:`, `TEMP` ni cambios sin confirmar |
| ATTACH / DETACH / cierre | Independiente (F-59) | Independiente (F-59) | Depende del archivo; un `DETACH` no la afecta, borrar o bloquear el archivo sí |
| Reabrir proyecto QGIS | Se pierde (igual que hoy, §10) | Se pierde | Se reabre si el archivo existe |
| Encaje con la arquitectura | Es la SPEC actual | Cambia §1, §5 y §10; el worker sigue siendo dueño de DuckDB | Rompe ADR-0006 (otra conexión) y ADR-0009/0011 (otra copia de DuckDB) |
| Complejidad | Media-alta: tabla de tipos propia y troceo | Media: SQL de normalización + `WriteArrow` + ciclo de vida de `/vsimem` | Alta e inestable: dependencias nativas y fallos aguas arriba |
| Usa APIs existentes | Mínimo | Sí: `WriteArrow`, GeoPackage, proveedor OGR | Sí, pero hoy incompletas |

### 5.1 Por qué GeoPackage en `/vsimem` y no Arrow IPC

Arrow IPC es 6× más rápido (0,3 s), pero es **de solo lectura** y depende del driver Arrow, que solo
existe si GDAL se compiló con `libarrow`. Lo trae el instalador de Windows (OSGeo4W); el de macOS no lo
traía en 2023 y en Linux depende de la distribución. GeoPackage y `WriteArrow` son parte del núcleo de
GDAL ≥ 3.8, la capa es **editable** como la `memory` actual y conserva `OGC:CRS84` tal cual. Con 2 s por
millón de filas y 34–99 ms de bloqueo máximo, la diferencia con Arrow no justifica dos caminos.

### 5.2 Por qué no `materialize()` a memory

Daría una capa `memory` (SPEC actual) con la conversión de GDAL, pero en QGIS 4.2 cuesta 45 s por millón
de filas con un campo de fecha y bloquea la interfaz 45 s (F-49).

### 5.3 Por qué aplazar «Conectada»

- **ADBC de GDAL** es la opción correcta a largo plazo, porque no exige proveedor propio, pero hoy:
  - no lista tablas ni vistas con DuckDB 2.0;
  - pierde el CRS;
  - necesita `libduckdb` y la extensión `spatial` fuera de Python;
  - abre una conexión distinta, que no ve la sesión de GeoDuck.
- **QDuckDB** existe y funciona, pero:
  - es de solo lectura;
  - trae su propio `duckdb`, y dos complementos no pueden cargar versiones distintas en el mismo
    Python (ADR-0009/0011).
- **Proveedor propio:**
  - está prohibido en esta fase (§1);
  - en Python, QGIS lo llamaría desde hilos de dibujado, lo que choca con el dueño único de la
    conexión (ADR-0006);
  - recorrer entidades desde Python ya cuesta ≈ 40 µs por entidad en QGIS 4.2 (F-49).
- **Lo que «Conectada» resolvería** (no cargar todo en RAM y sobrevivir a la reapertura) lo da hoy una
  instantánea persistente en GeoParquet o GeoPackage en disco, que es la misma tubería con otro destino
  (F-55). Se propone como opción posterior, no en G3.

## 6. Riesgos

| Riesgo | Efecto | Mitigación |
|---|---|---|
| GDAL < 3.8 en alguna instalación de QGIS 3.34 (p. ej. Debian 12) | Sin `WriteArrow` | Alternativa memory (§2); diagnóstico muestra la versión de GDAL |
| Coste de fechas en QGIS 4.2 (F-43, F-49) | Leer o copiar capas con fechas es lento | Confirmar en Windows (#10); no afecta a la carga GDAL |
| `/vsimem` retiene RAM hasta liberarlo (F-51) | Fuga si la capa se quita y nadie libera | Liberar al recibir `layerWillBeRemoved`; es la única referencia que GeoDuck mantendría tras publicar |
| Normalización SQL incompleta | Pérdida silenciosa (F-47) | Tabla §7 convertida en pruebas por tipo, en 3.44 y 4.2 |
| Capas grandes en RAM | 5 M filas ≈ 0,8–0,9 GB en GeoPackage (estimado) | Advertencia por tamaño (§3 de la SPEC); opción posterior de destino en disco |
| Identificador mostrado del CRS | Arrow/Parquet lo muestran como `EPSG:4326` | Con GeoPackage se conserva `OGC:CRS84` |
| Windows sin certificar | Todo lo anterior medido en Linux | #10 antes de cerrar G3 |

## 7. Decisiones que se piden

1. ¿Se aprueba que la **instantánea** se entregue como **GeoPackage en `/vsimem`** creado por GDAL
   (`WriteArrow`) en lugar de una capa `memory`? Cambiaría qgis-bridge-spec:
   - §1: proveedor;
   - §5: la conversión la hace GDAL en el hilo del motor, sin objetos de QGIS;
   - §10: GeoDuck libera el archivo `/vsimem` cuando QGIS quita la capa.
2. ¿Se aprueba la **normalización de tipos en SQL** (DuckDB) como implementación de la §7, en lugar de
   reglas de conversión en Python?
3. ¿Se aprueba la **ruta memory como alternativa única** cuando GDAL < 3.8?
4. ¿Se aprueba **aplazar «Conectada»** y reevaluarla con ADBC de GDAL cuando liste tablas y conserve el
   CRS con DuckDB 2.x, sin proveedor propio?
5. ¿Se registra como idea posterior (no G3) la **instantánea persistente** en disco (GeoPackage o
   GeoParquet `V1`)?

Hasta que haya decisión: sin cambios en `spec/`, sin implementación de la modalidad conectada y el paso 2
de G3 en espera.
