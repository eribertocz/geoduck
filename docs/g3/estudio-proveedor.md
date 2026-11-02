# Estudio G3: proveedor DuckDB bajo demanda y edición conectada (para decisión)

**Estado:** para decisión del arquitecto y del propietario. Complementa
[`estudio-modalidades.md`](estudio-modalidades.md). **No modifica `spec/` ni el complemento**: los
prototipos están en `tools/bench/pyprovider_*.py` y la evidencia en `docs/evidence/g3/` (F-61..F-80).
Fecha: 2026-11-02.

## 1. Pregunta

¿Puede GeoDuck ofrecer capas DuckDB **bajo demanda**, como PostGIS, sin C++ y sin abrir conexiones propias
fuera de su sesión? ¿Y editarlas desde QGIS (altas, cambios y bajas de atributos y geometrías) sin perder
cambios ni informar guardados que DuckDB no hizo? Se compara con la instantánea recomendada
(GeoPackage en `/vsimem`).

## 2. Respuesta corta

- **Sí, es viable en PyQGIS, en QGIS 3.44 y 4.2, con el mismo código.** El prototipo:
  - es un `QgsVectorDataProvider` en Python;
  - traduce cada petición de QGIS a SQL;
  - la ejecuta como operación del `SessionWorker` real, así que la conexión nunca sale de su hilo (ADR-0006).
- **Lectura, ventaja y precio:**
  - **ventaja:** no copia nada (abre en 0,05–0,26 s con 5 M) y casi no usa RAM;
  - **precio:** construir cada entidad en Python. Dibujar todo cuesta 3× más que con GeoPackage, 4 s frente a 1,3–1,5 s con 1 M;
  - **la sesión pasa a ser compartida con el mapa:** una consulta larga del usuario congela las capas conectadas (117 s esperó el mapa a una consulta de 117 s).
- **Edición: viable y segura, pero solo con un «guardado previo» de GeoDuck.** Hay que aplicar el búfer de
  QGIS entero en **una** transacción antes de que QGIS llame al proveedor, con control optimista por
  huella de fila. Con los métodos estándar del proveedor no hay atomicidad posible: o se guarda a medias
  o QGIS pierde cambios en silencio (F-72).
- **Probado con 100, 1 000 y 10 000 entidades en QGIS 3.44 y 4.2:**
  - QGIS informa éxito **solo** si DuckDB confirmó;
  - ningún fallo (conflicto, error, cancelación, transacción abierta, DETACH) escribe nada ni pierde
    cambios del búfer;
  - los cambios concurrentes desde SQL se detectan en lugar de perderse;
  - con lotes Arrow, 10 000 cambios se guardan en ≈ 0,6 s (F-75..F-79).
- **Complejidad:**
  - proveedor de lectura de calidad alfa: ≈ 2 500–3 500 líneas más pruebas;
  - edición segura: ≈ 1 000–1 500 líneas más;
  - instantánea GeoPackage: ≈ 400–600 líneas.
- **Recomendación:**
  - **G3 entrega la instantánea** (GeoPackage en `/vsimem`, decisión 1 del estudio anterior);
  - **la modalidad «Conectada» se planifica como fase propia**, con proveedor PyQGIS de solo lectura
    primero y edición con guardado previo después, una vez aprobadas las decisiones de §8;
  - **dos modalidades quedan justificadas:** Instantánea para resultados SQL; Conectada para tablas base
    grandes y para editar en DuckDB.

## 3. Prototipo

| Pieza | Qué hace |
|---|---|
| `pyprovider_probe.py` | Proveedor «geoduck». Extensión: `st_intersects_extent` (núcleo de DuckDB ≥ 1.5) o `ST_Intersects` + RTree (`spatial`). Además: FID → `key IN (…)`, solo columnas pedidas, sin geometría si no se pide, `LIMIT` y comparaciones simples (`"campo" op literal`, `AND`) compiladas a SQL; el resto se evalúa en Python. Lectura `stream` (lector abierto en el worker, cola de 2 lotes) o `table` (el worker lee el resultado y queda libre) |
| `pyprovider_edit_probe.py` | Edición con los métodos del proveedor (`addFeatures`, `changeAttributeValues`, `changeGeometryValues`, `deleteFeatures`) y dos políticas: una transacción por método o una por guardado |
| `pyprovider_txn_probe.py` | **Guardado previo**: en `beforeCommitChanges`, GeoDuck lee el búfer de edición y lo aplica en una transacción: conflictos por `hash(fila)` → validación → escrituras por lotes → COMMIT. Los métodos del proveedor solo informan ese veredicto |

URI del prototipo: `session=<id>|table=<cat.esq.tabla>|geom=<col>|key=<pk>|fetch=table|pushdown=spatial|type=Point`.

## 4. Lectura bajo demanda frente a GeoPackage `/vsimem`

Puntos con id, texto y valor; base adjunta con RTree; 2 CPU. Valores de QGIS 3.44 / 4.2 en la misma celda.

| Medida | Proveedor (`table`, `spatial`) 1 M | GeoPackage 1 M | Proveedor 5 M | GeoPackage 5 M |
|---|---:|---:|---:|---:|
| Abrir (la instantánea incluye la copia y el índice) | 0,05 / 0,04 s | 2,3 / 2,8 s | 0,17 / 0,16 s | 13,3 / 15,5 s |
| 1 % del área | 0,32 / 0,32 s | 0,03 / 0,02 s | 1,3 / 1,4 s | 0,09 / 0,10 s |
| `"id" < 500` (compilado a SQL) | 0,012 s | 0,035–0,038 s | 0,012–0,014 s | 0,17–0,23 s |
| Filtro no compilable (`LIKE` + `AND`) | 21 / 19 s | — | 104 / 96 s | — |
| 100 FID | correctos, 0,04 s | — | correctos, 0,15 s | — |
| Dibujar con zoom al 1 % | 0,09 / 0,08 s | 0,02 s | 1,3 / 1,4 s | 0,13 s |
| Dibujar todo | 4,0 / 4,0 s | 1,5 / 1,3 s | 20 / 20–88 s ¹ | 7,5 / 7,4 s |
| RAM retenida | ≈ 0 (`stream`); resultado de la petición (`table`) | 340 MB + 137 MB `/vsimem` | 0,5–0,7 GB al dibujar todo (`table`) | 770 MB + 736 MB `/vsimem` |
| Espera de una consulta del usuario mientras se dibuja todo | 0,002 s (`table`) · 3,6–4,6 s (`stream`) | — | 0,7–1,1 s (`table`) · 19–21 s (`stream`) | — |

¹ En QGIS 4.2, el modo `table` con 5 M tardó 88 s en una ejecución: tiene que retener en RAM el
resultado completo de la petición (8 GB en la máquina). `stream` no retiene RAM, pero ocupa el worker
durante todo el dibujado.

## 5. Comportamiento con la sesión (QGIS 3.44 y 4.2, iguales)

| Caso | Resultado |
|---|---|
| Tabla de una base adjunta, vista, tabla `TEMP` y `:memory:` | Visibles: es la misma conexión de la sesión |
| Cambios sin confirmar del panel SQL | **Visibles** en el mapa; desaparecen tras ROLLBACK |
| Consulta larga del usuario | El dibujado espera en la cola del worker (117 s con una consulta de 117 s) |
| Cancelar el dibujado o cerrar un iterador a medias | El worker queda libre en ≤ 4 ms |
| DETACH de la base | La capa queda vacía con el error del motor; no se cuelga |
| Cierre de la sesión | La capa queda vacía («La sesión no acepta operaciones») |
| Reabrir el proyecto con la sesión viva | La capa vuelve |
| Reabrir el proyecto sin la sesión | Capa no disponible: hay que reconectar a una sesión; `:memory:` y `TEMP` no se pueden recuperar |

## 6. Edición conectada

### 6.1 Qué se puede editar (F-69, F-70)

Solo **tablas base** de una base no `READ_ONLY` con **clave primaria entera de una columna**, que es el
FID de QGIS; también las tablas `TEMP`.

- Quedan de solo lectura, con el motivo: vistas, consultas SQL, bases `READ_ONLY` y tablas sin clave primaria.
- `rowid` se mantuvo estable en las pruebas, pero DuckDB no lo garantiza, así que no se usa como FID.
- Las altas toman su id de la secuencia de la clave. Como `executemany` + `RETURNING` solo devuelve el
  último id (F-74), los ids se piden antes con `nextval`.
- DuckDB no guarda el subtipo de geometría: en una tabla vacía hay que declararlo (`type=Point`).

### 6.2 Por qué los métodos del proveedor no bastan (F-72)

QGIS guarda llamando a `changeGeometryValues` → `changeAttributeValues` → `deleteFeatures` →
`addFeatures`, y quita de su búfer lo que cada uno acepta.

| Política | Fallo en la última llamada |
|---|---|
| Una transacción por método | Lo anterior queda guardado; QGIS informa exactamente eso (guardado parcial) |
| Una transacción por guardado, confirmada en `leaveUpdateMode` | DuckDB revierte todo, pero QGIS ya quitó del búfer lo «aceptado»: **pérdida silenciosa** |

Y sin control de concurrencia, un cambio del panel SQL sobre la misma fila se pierde sin aviso
(«gana la última escritura», F-73).

### 6.3 Guardado previo atómico (F-75..F-80)

En `beforeCommitChanges` (existe en QGIS 3.34+ y 4.x), GeoDuck lee el búfer de edición y, en una sola
transacción del worker:

1. **Conflictos:** compara `hash(fila completa)` en DuckDB con la huella que el proveedor guardó cuando
   QGIS leyó esa fila. Si alguna cambió o desapareció, hace ROLLBACK, no escribe nada y lista las
   entidades en conflicto.
2. **Validación previa:** geometría compatible con la capa y prohibición de cambiar la clave primaria.
   Son las comprobaciones que QGIS haría después.
3. **Escrituras por lotes** y COMMIT. Cualquier error o cancelación → ROLLBACK.

Después, los métodos del proveedor solo informan el veredicto. Así **QGIS informa éxito solo si DuckDB
confirmó**, y si no, conserva el búfer entero para corregir y reintentar.

**Resultados** (`pyprovider_txn_*.json`). Cada guardado mezcla n cambios de dos atributos, n/2 de
geometría, n/4 bajas y n altas; tabla de 60 000 filas con RTree. Iguales en QGIS 3.44 y 4.2, con
n = 100, 1 000 y 10 000:

| Caso | QGIS informa | DuckDB | Búfer de QGIS | Recuperación |
|---|---|---|---|---|
| Guardado correcto (`row`, `many`, `arrow`) | éxito | todo aplicado; filas no tocadas intactas (comprobado fila a fila) | vacío | — |
| El panel SQL cambió una fila que QGIS editaba | **fallo: «Conflicto: k entidad(es)…»** | sin cambios; el cambio de SQL se conserva | entero | Releer la fila (sobrescribir a sabiendas) y reintentar: éxito e íntegro |
| El panel SQL cambió una fila que QGIS no toca | éxito | se conservan ambos cambios | vacío | — |
| Error de DuckDB en la última alta (NOT NULL) | fallo con el mensaje de DuckDB | sin cambios | entero | Corregir y reintentar: éxito |
| Cancelación durante el guardado (interrupt del worker) | fallo («Operación cancelada») en 0,11–0,35 s | sin cambios (ROLLBACK) | entero | Reintentar: éxito e íntegro |
| Geometría incompatible con la capa | fallo | sin cambios | entero | — |
| Transacción del usuario abierta | fallo con aviso | sin cambios | entero | Tras COMMIT/ROLLBACK del usuario: éxito |
| DETACH antes de guardar | fallo con el error del motor | — | entero | — |
| *Proveedor sin guardado previo (G3-C), cambio concurrente* | *éxito* | ***el cambio de SQL se pierde sin aviso*** | — | — |

**Escrituras por lotes** (tiempo del guardado; QGIS 3.44 / 4.2):

| n | Una sentencia por fila (`row`) | `executemany` (`many`) | Tablas Arrow + SQL por conjuntos (`arrow`) |
|---:|---:|---:|---:|
| 100 | 0,30 / 0,31 s | 0,29 / 0,28 s | 0,03 / 0,04 s |
| 1 000 | 2,9 / 2,8 s | 2,8 / 2,4 s | 0,07 / 0,06 s |
| 10 000 | 29,4 / 29,1 s | 26,2 / 25,6 s | **0,56 / 0,61 s** |

`executemany` apenas mejora: DuckDB lo ejecuta fila a fila. El modo Arrow registra tablas temporales y
aplica `UPDATE … FROM`, `INSERT … SELECT` y `DELETE … IN (SELECT …)`. Es ≈ 50× más rápido, sin perder
integridad, porque todo ocurre dentro de la misma transacción.

**Límites del prototipo que la versión definitiva debe resolver:**

- La huella solo protege las filas que QGIS **leyó** durante la edición. En el prototipo se guarda de
  todo lo leído en modo edición (≈ 16 B por fila).
- La recuperación de un conflicto es «releer y sobrescribir». Una interfaz definitiva ofrecería
  descartar, sobrescribir o comparar.
- El prototipo usa la conexión interna (`handle._con`) para `register` y `executemany`: hace falta una
  API de lotes en `ConnectionHandle`.
- Tras un guardado correcto hay que avisar al coordinador (época de datos), porque las previsualizaciones
  SQL quedan obsoletas.

## 7. Alternativas nativas

| Opción | Estado (F-50, F-56, F-57) |
|---|---|
| Proveedor DuckDB en QGIS | No existe en 3.44 ni en 4.2 |
| Driver ADBC de GDAL | No lista tablas con DuckDB 2.0, pierde el CRS, solo lectura y otra conexión que no ve la sesión |
| QDuckDB (Oslandia) | Proveedor de complemento, solo lectura, con su propio `duckdb`: conflicto de módulo con GeoDuck |
| `QgsSqlExpressionCompiler` | No está en PyQGIS: un proveedor Python compila sus propias expresiones |
| `QgsTransaction` para proveedores Python | No disponible; por eso el guardado previo |

## 8. Complejidad estimada (una persona, calidad alfa, QGIS 3.44 y 4.2)

| Bloque | Líneas aprox. | Notas |
|---|---:|---|
| Proveedor: URI, metadatos, tipos (§7), CRS, extensión, conteo, tipo de geometría declarado | 500–700 | La extensión necesita `spatial` o una pasada completa |
| Iterador: filtros, FID, columnas, transformación de CRS, `OrderBy`, `DistanceWithin`, `ExactIntersect`, simplificación | 500–700 | |
| Compilador de expresiones QGIS → SQL DuckDB (`LIKE`, `IN`, `IS NULL`, `OR`, `NOT`, funciones comunes) | 600–900 | Sin él, filtros de 20–100 s (F-66) |
| Integración con el worker: prioridad y equidad entre mapa y SQL, límite de RAM por petición, cancelación con `QgsFeedback` | 400–600 | Requiere decidir el modelo de conexión (§9) |
| Ciclo de vida: DETACH/cierre/reconexión, repintado tras SQL (época de datos), proyecto, `uniqueValues`/mín/máx, navegador | 500–700 | |
| Edición con guardado previo, conflictos, lotes Arrow, mensajes y recuperación | 1 000–1 500 | Necesita una API de lotes en `ConnectionHandle` (el prototipo usa `_con`) |
| Pruebas QGIS 3.44 / 4.2 + certificación Windows (#10) | 1 500–2 000 | |
| **Total Conectada (lectura + edición)** | **≈ 5 000–7 000** | Del orden de 8–12 semanas |
| *Instantánea GeoPackage `/vsimem`* | *400–600* | *1–2 semanas* |

## 9. Riesgos y decisiones abiertas

| Riesgo | Efecto | Opción |
|---|---|---|
| Worker único compartido por mapa y SQL | Una consulta larga congela las capas, y el modo `stream` bloquea el SQL mientras se dibuja | (a) cola con prioridad para lecturas cortas; (b) conexión de lectura secundaria (`cursor()`), que cambia ADR-0006 y no ve cambios sin confirmar ni `TEMP` |
| Python por entidad | Dibujar 5 M cuesta ≈ 20 s, frente a 7,5 s con GeoPackage | Simplificación y límites por escala; no es superable en Python |
| Cambios sin confirmar visibles en el mapa | El usuario ve datos que pueden revertirse | Indicador de «transacción abierta» en las capas conectadas |
| La capa depende de la sesión | DETACH o cierre la vacían; `:memory:` y `TEMP` no sobreviven al proyecto | Bloquear DETACH con capas conectadas o marcarlas no disponibles; reconectar sesiones de archivo |
| Huellas de filas leídas en edición | Memoria proporcional a lo leído mientras se edita (≈ 16 B por fila) | Guardar huellas solo de lo que QGIS pide por FID o en pantalla |
| Cambios por la SPEC | §1 prohíbe un proveedor propio en esta fase; §10 cambia | Decisión del arquitecto |

## 10. Decisiones que se piden

1. ¿Se confirma que **G3 entrega solo la instantánea** (GeoPackage en `/vsimem`) y que «Conectada» será
   una fase propia?
2. Para «Conectada»: ¿**proveedor PyQGIS propio** reutilizando el worker (este estudio), en lugar de ADBC
   o QDuckDB?
3. ¿Modelo de conexión: **worker único con prioridad** (ve toda la sesión) o **conexión de lectura
   secundaria** (cambia ADR-0006)?
4. ¿Edición solo mediante el **guardado previo atómico** con control optimista (§6.3), y solo para
   tablas base con clave primaria entera?
5. ¿Primera entrega de «Conectada» **de solo lectura**, con la edición en una entrega posterior?
