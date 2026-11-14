# SPEC GD-SQL — Editor SQL profesional y resultados

**Estado:** baseline Alpha · **IDs:** GD-SQL-001..007

## 1. Modelo UX
Un editor integrado en dock con pestañas de texto SQL, acciones **Ejecutar sentencia**, **Ejecutar selección**, **Ejecutar todo**, **Cancelar**, **Explicar**, resultados y historial (desde G7, en celdas: **Ejecutar celda**, **Ejecutar selección**, **Ejecutar celda y avanzar** y **Ejecutar todo**; ver «G7 · Notebook»). Nunca ejecuta SQL por presionar «Cargar en QGIS» sin que el usuario sepa cuál consulta se ejecutará.

El editor acepta el SQL disponible en DuckDB >=1.5 (DDL, DML, vistas, macros, transacciones, configuración, extensión Spatial, `ATTACH`, `DETACH`, consultas, `EXPLAIN`, `COPY`, `INSTALL`, `LOAD`) sujeto a permisos y funciones reales. No forzar el DSL «solo SELECT».

## 2. Parser y scripts
- Usar el parser oficial de DuckDB (`con.extract_statements`) para identificar sentencias. **No** separar con `str.split(';')`, porque hay literales, comentarios y bloques.
- Preservar texto, orden y posiciones del editor; si el parser no expone offsets, implementar mapeo verificado mediante pruebas, no heurística ingenua.
- Por defecto, ejecutar secuencialmente. Si falla una sentencia: detener el resto, presentar estado y la recuperación apropiada de transacción.
- Registrar por instrucción: `statement_id`, `run_id`, `type`, `status`, `duration_ms`, `message`, `preview_handle?`, `error_range?`, `catalog_epoch`.
- «Ejecutar selección» de múltiples sentencias respeta el orden y errores.

## 3. Tipos de salida
1. **Status:** DDL/administración o sentencia sin filas útiles; mostrar OK/error, duración y detalle seguro.
2. **Tabular read result:** `SELECT`, `WITH ... SELECT`, `VALUES`, lecturas que retornan filas; cada sentencia tiene pestaña independiente.
3. **Mutation with returned rows:** `INSERT/UPDATE/DELETE ... RETURNING` u otras salidas de escritura; ejecutar **una sola vez** y permitir inspeccionar preview; no repetir al pulsar cargar.
4. **Plan/diagnóstico:** `EXPLAIN`, avisos, tablas técnicas de resultado; visualizables, no capas automáticas.

Una sentencia no se clasifica solo por su primera palabra: `WITH` puede anteceder DML; el parser y el comportamiento del motor son la fuente de verdad.

## 4. Previsualización y paginación
- Vista previa: **20 filas fijas, sin selector** (en Workspace Pro, páginas de 100: workspace-pro-spec §5) (decisión del propietario, 2026-11-03; antes 200 por defecto con 50/200/500/1000); siempre visualmente etiquetada «Vista previa». «Cargar» y «Exportar» usan la consulta completa.
- Nunca materializar `fetchall()` en resultados sin límite conocido.
- Para lecturas reejecutables, usar una consulta acotada, respetando semántica SQL y su ordenación; si no hay `ORDER BY` no garantizar que la paginación sea estable.
- No calcular `COUNT(*)` completo automáticamente para todo SELECT. **Excepción (Workspace Pro, propietario,
  2026-11-06):** la pestaña de consulta muestra páginas de 100 filas y cuenta el total aparte, solo para una
  lectura reejecutable con más filas que la página (workspace-pro-spec §5).
- Cambiar de pestaña de resultados no debe mantener un reader DuckDB abierto.
- El registro conserva solo el fragmento mostrado y metadatos necesarios; no caché universal del resultado completo.
- No efectuar reejecuciones ocultas en consultas potencialmente volátiles/sensibles; indicar cuándo cambia el estado de datos.

## 5. Política de «Cargar resultado en QGIS»
- Solo se activa para resultados tabulares convertibles, seleccionados por el usuario.
- Ofrece las tres modalidades de qgis-bridge-spec §1: «Copia en memoria», «Copia rápida» (desactivada con motivo si GDAL < 3.8) y «Conectada». Un resultado SQL conectado es de solo lectura; editar exige cargar la tabla desde el explorador.
- Para `SELECT` reejecutable, volver a ejecutar **únicamente esa consulta de lectura** para obtener el conjunto completo mediante Arrow; comunicar que se basa en el estado actual y puede diferir de la preview.
- Si la query depende de tablas temporales eliminadas, base desadjuntada o una transacción ya cerrada, informar fallo en lugar de cargar otro resultado.
- Para consultas no deterministas o con funciones de efecto lateral, mostrar advertencia/solicitar confirmación explícita; la clasificación «SELECT» no es prueba absoluta de ausencia de efectos secundarios.
- **Nunca reejecutar** DDL/DML, el resto del script, un `RETURNING` ni los `ATTACH/DETACH` previos para obtener una capa.
- Los resultados de escritura con `RETURNING` no tienen carga del conjunto completo vía replay en V1; el usuario puede crear luego una consulta de lectura apropiada. Evitar falsa promesa de repetibilidad.
- Cada query genera 0/1/N capas según selección espacial. «Cargar todos» procesa explícitamente varios resultados y muestra estado por resultado, sin implicar transacción QGIS global entre resultados salvo que se implemente y pruebe.

## 6. Estado del SQL respecto de la sesión
- El catálogo activo (`USE`), tablas temporales, configuración, extensiones y transacciones pertenecen al worker de la sesión.
- Tras `ATTACH`/`DETACH`, `CREATE/DROP`, refrescar explorador y marcar las previews afectadas como posiblemente obsoletas; no borrarlas silenciosamente.
- Cuando cambia el SQL de origen de una pestaña, los resultados previos deben conservar `run_id` y mostrar claramente que ya no corresponden al texto actual.

## 7. Editor profesional por etapas
**P0:** resaltado, números de línea, ejecutar actual/selección/todo, stop, errores con ubicación cuando DuckDB la proporcione, pestañas resultados y registro de ejecuciones.

**P1:** autocompletado de catálogos/tablas/columnas/funciones `ST_*`, historial, múltiples pestañas de editor, búsqueda y reemplazo, snippets básicos, guardado explícito de SQL, `EXPLAIN ANALYZE`, accesos de teclado, formato SQL.

**P1 en G6 (`v0.7.0a1`, decisión del propietario 2026-11-02; GD-SQL-007):**
- **Autocompletado.** Sugiere bases, esquemas, tablas, vistas, columnas y funciones a partir del catálogo que da el worker (funciones con `duckdb_functions()`, verificado en E2 con DuckDB 1.5.0 y 2.0.0). Se abre al escribir tras un prefijo o un `.`, y con Ctrl+Espacio; no se abre dentro de comentarios ni de cadenas. Escape cierra; Intro o Tab aceptan solo con la lista abierta. Aceptar **solo inserta texto**: nunca ejecuta SQL. Los nombres que lo necesitan van entre comillas dobles, con las comillas internas duplicadas. Sin catálogo, el editor sigue funcionando sin sugerencias.
- **Pestañas de editor.** Varias pestañas en la misma sesión; cada una conserva su texto, cursor, selección y scroll, también al alternar ventana ↔ panel (AT-UX-004). Las ejecuciones actúan sobre la pestaña activa. Cerrar una pestaña con texto pide confirmación; con una ejecución en curso, no se cierra hasta que termine o se cancele. Las pestañas no se guardan entre reinicios de QGIS (GD-SQL-008).
- **Historial de la sesión.** Cada fila del registro (G5) conserva en memoria el SQL que ejecutó; «Abrir en el editor» lo copia a una pestaña nueva, **sin ejecutarlo**. No se escribe en disco (security.md §4); se pierde al cerrar la sesión.
- **«Explicar»** (retirado en G7 de la interfaz y del motor, decisión del propietario 2026-11-03: el plan se pide escribiendo `EXPLAIN …` en la celda; el texto que sigue describe G6). Ejecuta `EXPLAIN` de la sentencia actual (o de la selección, si es una sola sentencia) y muestra el plan en una pestaña de resultados. Nunca `EXPLAIN ANALYZE`. Con varias sentencias, se rechaza con un mensaje y no se ejecuta nada. Que `EXPLAIN` de una sentencia DML o DDL no la ejecuta se verifica en E3 con DuckDB 1.5.0 y 2.0.0; si no se confirma, «Explicar» se limita a consultas de lectura.

**P1 sin fase (GD-SQL-008):** formato SQL, historial guardado en disco, búsqueda y reemplazo, snippets, guardado explícito de SQL y `EXPLAIN ANALYZE`.

**P2 (evaluar):** diagnósticos en vivo, sugerencias sofisticadas y trazas de profiling; no son excusa para introducir editor web no justificado.

**G7 · Notebook (`v0.8.0a1`, decisiones del propietario 2026-11-03; GD-NB-001..008):** las pestañas de editor de
G6 pasan a ser **cuadernos**; cada cuaderno es una lista de **celdas**. Todo usa la sesión y el worker únicos.
- **Celda** = editor SQL (con el autocompletado de G6; el plan, escribiendo `EXPLAIN`) + base de la celda + su resultado. Puede tener
  varias sentencias: se ejecutan en orden, como un script (§2); el resultado que se muestra es el de la última que
  devuelve filas, y todas quedan en el registro.
- **Base de la celda.** Al ejecutar una celda, GeoDuck ejecuta `USE <base de la celda>` y después el SQL de la celda
  en **la misma operación del worker** (nada se intercala). Los nombres calificados (`otra_base.esquema.tabla`) son
  siempre válidos, y las tablas temporales se ven desde cualquier base. Verificado con DuckDB 1.5.0 y 2.0.0: `USE`
  se admite dentro de una transacción y `ROLLBACK` no lo deshace; una transacción solo puede escribir en **una**
  base (error de DuckDB, que se muestra tal cual). La base en uso de la sesión queda la de la última celda
  ejecutada. Una celda nueva (también la primera de un cuaderno nuevo) empieza en `memory`, la raíz de la sesión, y lo muestra en su selector desde que se crea; el usuario la cambia si quiere otra (decisión del propietario, 2026-11-03). «Duplicar celda» copia la base de la celda. Si el SQL de la celda contiene su propio `USE`, gana el del SQL y
  el selector de la celda lo refleja. Si la base de la celda se desadjunta, la celda lo indica y no se ejecuta hasta
  elegir otra. Cada resultado recuerda la base donde se ejecutó: «Cargar en QGIS» (las tres modalidades, también
  cada lectura de una capa Conectada) y «Exportar» repiten la consulta en esa base y después dejan la base en uso
  como estaba, en la misma operación del worker.
- **Ejecutar todo** recorre las celdas en orden (cada una con su `USE`) y se detiene en la primera que falla; las
  siguientes quedan sin ejecutar. Se cancela como un script.
- **Exportar (GD-NB-007).** «Exportar ▾» → CSV o Parquet exporta la **consulta completa**, no la vista previa:
  GeoDuck ejecuta `COPY (<consulta>) TO '<archivo>' (FORMAT csv, HEADER)` o `(FORMAT parquet)` en el worker, con la
  base de la celda, cancelable y con la sesión ocupada. Solo para una consulta de lectura (la misma regla que
  «Cargar en QGIS», GD-SQL-006: un DML nunca se repite); de una celda con varias sentencias se exporta la de su
  resultado. El archivo se elige con el diálogo del sistema, que pide confirmación si ya existe (DuckDB lo
  sobrescribe sin avisar; verificado en 1.5.0 y 2.0.0). Si se cancela o falla, no queda un archivo a medias.
  Verificado en 1.5.0 y 2.0.0: Parquet está incluido (sin instalar nada, ADR-0011); en CSV la geometría sale como
  WKT. Geometría en Parquet (decisión del propietario, 2026-11-03; spatial-spec §4): **sin SRC**, todo lector
  supone `OGC:CRS84` (lo dice GeoParquet), así que GeoDuck exporta con la opción por defecto (GeoParquet 1.0, la
  que más programas leen) y **avisa** que conviene fijarlo con `ST_SetCRS` en la consulta; **con SRC**
  (`GEOMETRY('EPSG:32719')`), la opción por defecto falla, así que exporta con `GEOPARQUET_VERSION 'V2'` y el SRC
  queda en el archivo (GDAL 3.13 lo lee como EPSG:32719). Nunca se inventa un SRC. El archivo se escribe primero
  como temporal oculto en la misma carpeta y se renombra al terminar.
  **G9 (decisión del propietario, 2026-11-07; maqueta `docs/g9/maqueta/importar-exportar.png`):** «Exportar ▾»
  (resultado, tabla y clic derecho) muestra ⚡ Parquet/GeoParquet, GeoPackage, CSV y ⚡ FlatGeobuf; «Más
  formatos ▸» trae ⚡ Arrow/Feather (PyArrow), JSON por líneas, Shapefile, GeoJSON, KML, Geodatabase de ArcGIS
  y Excel (la geometría como WKT). Cada opción dice en su ayuda qué pasará. **Siempre con el motor de DuckDB,
  nunca con QGIS**; sin SpatiaLite ni SQLite (GeoPackage los reemplaza; el GDAL de DuckDB no escribe
  SpatiaLite). Los formatos de GDAL usan `COPY … (FORMAT gdal, DRIVER …)` de `spatial`: si no está cargada,
  GeoDuck pide permiso («Instalar y exportar» / «Cargar y exportar», spatial-spec §10). Con un SRC en la
  geometría, DuckDB 2.0 exige fijar `geometry_always_xy`: si el usuario no lo fijó, GeoDuck lo pone en `true`
  (orden este-norte) **solo durante la exportación** y después lo deja sin fijar; si el usuario lo fijó, no se
  toca. **G10 (propietario, 2026-11-12):** si la consulta no tiene `ORDER BY`, `preserve_insertion_order` se
  apaga solo durante la exportación (cancelar baja de hasta 3,3 s a < 0,1 s; las filas pueden salir en otro
  orden, que SQL no garantiza sin `ORDER BY`) y se deja como estaba; con `ORDER BY`, el orden se respeta; si el
  usuario lo apagó, no se toca. Todo se escribe en una carpeta temporal junto al destino y se mueve al terminar (un Shapefile son
  varios archivos; una Geodatabase, una carpeta). **Shapefile (#141):** se escribe con su `.cpg` en UTF-8 (las
  tildes y la ñ se leen igual en cualquier programa) y, si algún nombre de campo pasa de 10 bytes, un aviso los
  lista: GDAL los acorta (dos largos pueden quedar «nombre_m_1»); para elegirlos, `AS` en la consulta o
  GeoPackage.
- **Cuadernos en disco (GD-NB-008, ADR-0014; decisión del propietario, 2026-11-03).** «Guardar cuaderno…» y
  «Abrir cuaderno…» (Ctrl+S, Ctrl+O) usan un archivo `.sql`: cada celda empieza con `-- %% cell · database: <base>`
  (también se leen `celda` y `base`); un `.sql` sin marcas se abre como una celda. Un cuaderno con archivo se guarda
  solo tras cada cambio. La **copia de recuperación** (activada por defecto, desactivable) guarda el SQL y la base
  de cada celda de todos los cuadernos en el perfil de QGIS y se borra al cerrar bien; si QGIS se cerró por un
  fallo, al abrir GeoDuck se ofrece recuperarla. Nunca se guardan resultados ni el historial. Los cuadernos
  guardados que estaban abiertos al cerrar QGIS se vuelven a abrir al iniciar, con el activo igual (en las opciones
  de QGIS solo se guardan sus rutas; uno que ya no existe se avisa y se omite). La ayuda de cada cuaderno (lista,
  selector y su nombre arriba) dice dónde está guardado; sin archivo, solo su nombre (propietario, 2026-11-03).
- Fuera de G7: estadísticas por columna de una tabla (histogramas, distintos), firma de funciones en el
  autocompletado.

## 8. Ejemplos de comportamiento esperado

```sql
CREATE TABLE productos AS SELECT 1 AS id, 'Medidor' AS nombre;
SELECT * FROM productos;
SELECT COUNT(*) AS n FROM productos;
```

Salida: tres registros de ejecución, dos pestañas de datos; se pueden cargar como tablas independientes de QGIS. No se reejecuta `CREATE` al cargar.

```sql
ATTACH 'comercial.duckdb' AS comercial (READ_ONLY);
SELECT * FROM comercial.main.ventas;
DETACH comercial;
```

Tras el `DETACH`, la vista previa existente sigue visible como preview limitada, pero la carga completa del `SELECT` anterior **ya no es válida** hasta volver a adjuntar la base explícitamente; no reconectar automáticamente.
