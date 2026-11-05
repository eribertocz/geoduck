# GeoDuck — Estrategia de pruebas y CI

**Estado:** baseline QA · **Política:** un feature sin test de aceptación no se considera completo.

## 1. Pirámide de pruebas
- **Unitarias** (rápidas, cada PR): parseo y planificación SQL, estados de sesión, quoting de rutas/alias, clasificación de resultados, mapeo de campos, CRS y políticas de retry/safe replay. Dobles para interfaces QGIS; no suplantan integración.
- **DuckDB real** (cada PR): `:memory:`, `ATTACH/DETACH`, scripts, `CREATE`, temporales, `SELECT`, DML y reader Arrow en v1.5.x y v2.x; no mocks del motor para aceptación.
- **PyQGIS real** (PR/release en runners Windows provisionados): creación de memory layer, campos, WKB, mezcla geométrica, entrega múltiple y descarte en cancelación.
- **E2E QGIS GUI** (gates/release): abrir dock, escribir SQL, cargar capa y comprobar que persiste tras `DETACH`; UI QGIS3 y QGIS4.
- **Seguridad, resiliencia y compatibilidad**: extensiones, bloqueos, interrupción, OOM simulado, errores tipo/CRS, instalación limpia.
- **Performance**: harness determinista con inventario hardware y datos generados repetibles.

## 2. CI por niveles
**PR requerido:** formato/lint, tests unitarios, tests DuckDB, build del plugin, validación metadata/documentación, verificación de dependencias y licencia, detección de APIs obsoletas.

**Integración de QGIS:** matrix Windows x64 QGIS 3.44 LTR y 4.2 latest, cada combinación en un entorno certificado. Si los runners GitHub estándar no tienen QGIS real, usar runners dedicados/VM provisionadas, y **reportar no ejecutado**, no declarar éxito verde ficticio.

**Release Alpha:** toda la matriz P0 real + E2E + benchmarks respecto baseline y auditoría de seguridad.

## 3. Casos de aceptación prioritarios
| ID | Escenario | Resultado esperado |
|---|---|---|
| AT-BOOT-001 | Abrir dock en QGIS 3/4 | sin errores de import/UI |
| AT-BOOT-002 | falta `pyarrow` | diagnóstico accionable, sin crash |
| AT-SES-001 | sesión :memory: | tablas temporales y SQL funcional |
| AT-SES-002 | archivo RO/RW | modos respetados, archivo no corrupto |
| AT-SES-003 | ATTACH por SQL y DETACH UI (y viceversa) | catálogo/UI iguales |
| AT-SES-004 | cargar capa → DETACH → inspeccionar capa | capa intacta; archivo liberado por GeoDuck |
| AT-SES-005 | BEGIN → INSERT → fallo → rollback | semántica DuckDB 1.5.x/2.x respetada |
| AT-CAT-001 | múltiples catálogos/esquemas y vistas | explorador completo y refrescado |
| AT-CAT-002 | expandir tabla y vista en varias bases y esquemas, nombres con espacios y comillas; DDL, ATTACH/DETACH e invalidación mientras se cargan | columnas y tipos exactos, geometría por tipo, nulos; una sola lectura al expandir, sin filas; doble clic y arrastre insertan el nombre citado; nada obsoleto tras invalidar |
| AT-SQL-001 | CREATE/INSERT/COPY/EXPLAIN/SELECT | ejecución según DuckDB |
| AT-SQL-002 | script 2 SELECT + CREATE | estados ordenados, 2 resultados |
| AT-SQL-003 | pestañas de distintos resultados | cada preview corresponde al SQL correcto |
| AT-SQL-004 | ejecutar selección/actual/todo (G7: celda, selección o todo el cuaderno) | solo lo elegido se ejecuta |
| AT-SQL-005 | SELECT un millón | preview acotada, no fetchall |
| AT-SQL-006 | DML RETURNING → cargar | no repetir DML; carga completa no disponible por replay |
| AT-SQL-007 | autocompletado en catálogos adjuntos, tras DDL y ATTACH/DETACH, dentro de comentarios y cadenas | contexto correcto; nombres citados; aceptar nunca ejecuta SQL; sin sugerencias obsoletas; Escape/Intro/Tab como en sql-editor-spec §7 |
| AT-SQL-008 | varias pestañas de editor, ejecutar en cada una, alternar ventana ↔ panel, cerrar con texto y con ejecución en curso | cada pestaña conserva su estado; se ejecuta solo la activa; confirmación al cerrar; sin sesiones nuevas |
| AT-SQL-009 | «Abrir en el editor» desde el registro, con SQL de varias sentencias | el SQL vuelve exacto a una pestaña nueva sin ejecutarse; nada escrito en disco |
| AT-SQL-010 | `EXPLAIN` escrito en la celda sobre SELECT y DML (G7 retira «Explicar» de la interfaz y del motor) | plan en una pestaña de resultados; la tabla no cambia |
| AT-BRD-001 | SELECT sin geometría → QGIS | tabla memory íntegra |
| AT-BRD-002 | lector Arrow multi-lote | conteos/valores coinciden |
| AT-BRD-003 | cancelar carga prolongada | GUI responde, lector cerrado |
| AT-BRD-004 | fallo fila 30 001 | ninguna capa parcial publicada |
| AT-BRD-005 | capa entregada (Memoria/Instantánea) → DETACH, cerrar GeoDuck | QGIS controla capa y atributos |
| AT-BRD-006 | Instantánea 1 M filas; quitar la capa | íntegra fila a fila, CRS, editable; `/vsimem` liberado al quitarla |
| AT-BRD-007 | un tipo de cada fila de §7 en las tres modalidades | valor conservado, o texto/rechazo con aviso; nunca pérdida silenciosa |
| AT-BRD-008 | Conectada sobre tabla, vista y SQL; extensión, expresión, FID | filas y FID correctos; SQL con filtros empujados |
| AT-BRD-009 | dibujar mientras corre SQL largo; SQL mientras se dibuja | ni la UI ni la sesión se bloquean más de una página; cancelación libera el worker |
| AT-BRD-010 | editar 100/1 000/10 000 entidades; conflicto SQL; error; cancelación; transacción abierta | éxito ⇔ COMMIT; fallo ⇒ DuckDB intacto y búfer conservado |
| AT-BRD-011 | capa conectada → DETACH → ATTACH; cerrar; reabrir proyecto | no disponible sin errores; vuelve con el mismo alias; cambios sin guardar bloquean DETACH/cierre |
| AT-BRD-012 | cargar con cada modalidad desde la UI | elección clara, progreso, cancelación, nombre de capa |
| AT-SPA-001 | 0/1/2 campos GEOMETRY; columnas `BLOB` (WKB) y `VARCHAR` (WKT) marcadas y sin marcar | decisión adecuada, no geometría arbitraria; sin marcar nunca son geometría; el origen no cambia |
| AT-SPA-002 | centroide + polígono → una y ambas capas, en las tres modalidades; error y cancelación a mitad | una capa por columna marcada, completa, con su CRS y tipo; Conectada filtra por su columna; error/cancelación no publica ninguna |
| AT-SPA-003 | GEOMETRY con CRS y sin CRS; AX-1..AX-5 (spatial-spec §8); «Reproyectar a…» en copias | conservar/preguntar, nunca CRS inventado; asignar no mueve coordenadas, reproyectar sí (tolerancias de §8); `geometry_always_xy` visible y nunca modificado |
| AT-SPA-004 | geometría corrupta (WKB/WKT ilegible) o mixta; colecciones, Z, M, ZM, NULL, vacías; inválidas | error o separación explícita, no pérdidas; Conectada `Unknown` o separada sin duplicados, con el tipo leído de las cabeceras WKB en DuckDB; diagnóstico cuenta NULL/vacía/ilegible/inválida, selecciona y no modifica; reparación solo en copia, con cambios informados |
| AT-UX-001 | pruebas teclado/tema/dock/Qt | acciones visibles y accesibles |
| AT-UX-002 | instalación limpia; reiniciar tras elegir un modo | abre en ventana propia; el modo elegido se recuerda |
| AT-UX-003 | alternar ida y vuelta | misma sesión, mismo worker y mismo contenido (identidad comprobada) |
| AT-UX-004 | alternar con editor modificado y resultados abiertos | texto, cursor, selección, scroll, resultados y pestañas intactos |
| AT-UX-005 | alternar durante SQL, carga o cancelación | la tarea sigue y entrega exactamente un resultado |
| AT-UX-006 | explorador con varias bases, vistas y temporales; búsqueda | filtra y agrupa sin leer filas; acceso por base correcto |
| AT-UX-007 | resultados con tipos, `NULL`, cadena vacía y límite | tipo por columna, `NULL` ≠ "", «hay más» correcto |
| AT-UX-008 | Memoria, Copia rápida y Conectada desde ambos modos; «Ver en el mapa» con y sin extensión válida | una capa por carga, sin duplicados; el menú abre el diálogo de G4 con el modo marcado |
| AT-UX-009 | registro Todo/OK/Error | filtra sin borrar; mensaje completo accesible |
| AT-UX-010 | restaurar modo, ventana, dock y divisores; pantalla ausente | se restauran; nunca queda fuera de pantalla; ajustes corruptos → valores seguros |
| AT-UX-011 | cerrar u ocultar la ventana o el panel | sin cierre de sesión, DETACH, ROLLBACK ni capas invalidadas |
| AT-UX-012 | 20 alternancias seguidas | sin señales dobles, widgets huérfanos ni sesiones extra |
| AT-UX-013 | teclado, panel estrecho, DPI y tema | todas las acciones alcanzables; atajos solo dentro de GeoDuck |
| AT-UX-014 | fallo inyectado durante el traslado | el shell anterior sigue operativo; nada se repite |
| AT-UX-015 | regresión G0–G4 | todas pasan; otras herramientas de QGIS sin cambios |
| AT-I18N-001 | QGIS en inglés y en español; paquete ZIP | textos en el idioma de QGIS; traducción completa de la interfaz; sin texto vacío; idioma de QGIS sin cambios; SQL y datos sin traducir; el ZIP incluye la traducción |
| AT-NB-001 | añadir (al final y entre celdas), arrastrar, subir/bajar con el teclado, duplicar, borrar; plegar celda, editor y resultado por separado; vista de hoja (Ctrl+E) y vuelta; varios cuadernos | orden y contenido conservados (texto, base y resultado viajan con la celda; nada se ejecuta); borrar una celda con SQL pide confirmación |
| AT-NB-002 | «Ejecutar todo» con una celda que falla | celdas en orden; se detiene en la que falla; las siguientes no se ejecutan |
| AT-NB-003 | dos celdas con bases distintas, ejecutadas en cualquier orden | cada una lee su base; la base en uso queda la de la última ejecutada |
| AT-NB-004 | `SELECT * FROM otra.tabla` con otra base en la celda (y al revés: celda en `db` que lee `memory.t`); `LOAD spatial; SELECT …` en una celda (resultado de la última, «2 sentencias»); `USE` escrito en la celda; base de la celda desadjuntada | nombres calificados funcionan; el selector sigue al `USE`; la celda sin base no se ejecuta y lo dice |
| AT-NB-005 | resultado y «Cargar en QGIS ▾» en cada celda (tres modalidades, geometría) | la capa sale del SQL de esa celda; nada se repite (GD-SQL-006) |
| AT-NB-006 | resumen del resultado seleccionado | filas, columnas y tipos correctos; ninguna consulta nueva |
| AT-NB-007 | lista de cuadernos | cambiar de cuaderno conserva su estado; sin archivo ni copia, nada en disco |
| AT-NB-008 | autocompletado, atajos (Ctrl+Intro celda, Ctrl+Mayús+Intro selección, Mayús+Intro celda y avanzar) e historial dentro de una celda | como en G6, en la celda activa |
| AT-NB-009 | alternar ventana ↔ panel con varias celdas, resultados y una ejecución en curso | mismo estado, un solo resultado (AT-UX-004/005) |
| AT-NB-010 | teclado, panel estrecho, Qt 5 y Qt 6, inglés y español | todas las acciones accesibles; textos traducidos |
| AT-NB-011 | exportar a CSV y Parquet una consulta de 1 millón de filas con geometría; archivo existente; cancelar; celda con DML o con `load spatial; select …` | el archivo tiene todas las filas, no las de la vista previa; nada se sobrescribe sin confirmar; cancelar no deja archivo a medias; DML no se exporta (no se repite) y de la celda se exporta solo la consulta de lectura |
| AT-NB-012 | guardar y abrir un cuaderno `.sql`; un `.sql` cualquiera; cambiar un cuaderno guardado; reiniciar QGIS con cuadernos guardados abiertos; cerrar bien; QGIS que se cierra por un fallo; copia apagada | marcas y bases de vuelta; una celda; el archivo se actualiza solo; vuelven los guardados (solo sus rutas en las opciones) con el activo y la ruta en su ayuda; la copia se borra; se ofrece recuperar y se recupera; apagada, nada se escribe |
| AT-IMP-001 | menú de capa con una y varias capas; workspace «+»; capa ráster; sin sesión | envía las vectoriales; ráster desactivada con motivo; sin sesión, explica qué hacer |
| AT-IMP-002 | tabla que no existe, que existe y nombre repetido entre filas | «Tabla nueva» / «Ya existe» / aviso; por defecto no se envía la que existe; reemplazar, añadir y otro nombre hacen lo indicado |
| AT-IMP-003 | solo seleccionadas; capa con filtro; reproyectar; vista sobre Parquet | se envía lo seleccionado y filtrado; coordenadas transformadas (tolerancias de spatial-spec §8); la vista no copia datos |
| AT-IMP-004 | fallo en la segunda capa; cancelar a mitad; conteo distinto forzado | ninguna tabla creada, reemplazada ni ampliada; la UI responde; la capa de QGIS igual |
| AT-IMP-005 | capa Conectada, Parquet, GeoPackage, Shapefile, memoria y CSV | camino esperado en el resumen; mismas filas y valores que en QGIS |
| AT-IMP-006 | todos los tipos de §6; `ID` e `id`; añadir con columnas incompatibles | tipos de la tabla; renombrado con aviso; «No se puede» con la columna que falla |
| AT-IMP-007 | EPSG:4326, EPSG:32719, SRC personalizado, sin SRC; Z/M, colección, `NULL`, inválida | `GEOMETRY('<SRC>')` que vuelve a QGIS con el mismo SRC y coordenadas; personalizado: aviso y decisión; sin `spatial` cargada |
| AT-IMP-008 | regresión G0–G7 | todas pasan |
| AT-SEC-001 | extensiones externas y RO | restricciones y advertencias funcionan |
| AT-CFG-001 | reiniciar plugin | configuración sí, datos/capas no persistidos por GeoDuck |
| AT-COMP-001 | matriz QGIS/Python/Qt/PyArrow | reportes reproducibles por celda |
| AT-QA-001 | CI y perf baseline | informes vinculados a commit |

## 4. Tests adversariales obligatorios
- Alias con espacios/comillas y ruta Windows con acentos/Unicode.
- SQL con `;` dentro de strings, comentarios y macros.
- Reader Arrow abierto + tentativa de `DETACH`: no provocar `ResourceInUseException` sin manejo.
- SQL que referencia vista creada en `:memory:`; consultas posteriores usan mismo estado de sesión.
- SELECT antiguo tras `DROP` o `DETACH`: falla claramente, **sin** reconectar silenciosamente.
- `SELECT` volátil: no prometer coincidencia preview y carga completa.
- Queries sin `ORDER BY`: paginación no garantiza orden estable.
- `INSERT RETURNING`: no duplicar escrituras al hacer preview/cargar.
- CRS tipado vs CRS desconocido; EPSG confundible y ejes XY.
- `DECIMAL` de alta precisión y enteros grandes: sin corrupción silenciosa.
- Cancelación a mitad de 2 capas simultáneas: ninguna publicada.
- Reabrir archivo RW desde un proceso independiente tras `DETACH` exitoso.
- Ejecutar sin QGIS UI (headless) donde aplica; GUI real donde el caso lo exige.

## 5. Pruebas de compatibilidad
A cada plataforma/versión declarar: `certificado`, `conocido con limitaciones`, `no probado` o `incompatible`. Ninguna combinación sin prueba figura como certificada. Test de ejecución con `sys.executable` de QGIS, no un venv independiente.

## 6. Política de merges/releases
- Bloqueantes: 100% tests P0 de integridad/sesión, sin crash reproducible, sin corrupción de datos/capas, sin bypass de RO, sin incompatibilidad silenciosa.
- Lint/tests básicos verdes son necesarios pero **insuficientes** para gates de integración.
- Cada PR debe adjuntar test ID, evidencia y release target. Regresiones verificadas bloquean release. Los benchmarks no justifican reducir corrección.

## Matriz obligatoria de regresión DuckDB
- Ejecutar pruebas con **1.5.x y 2.x** (comenzando con 1.5.0 y 2.0.0 si sus wheels son compatibles con el runtime).
- Verificar por cada versión DuckDB + Spatial + PyArrow: SELECT lazy, lector por lotes, SQL mixto, ATTACH/DETACH, geometría y CRS, cancelación, archivo persistente y casos de error.
- Mantener artefactos de resultado y versión exacta; no declarar soporte para una combinación no probada.
