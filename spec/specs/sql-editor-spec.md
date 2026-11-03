# SPEC GD-SQL — Editor SQL profesional y resultados

**Estado:** baseline Alpha · **IDs:** GD-SQL-001..007

## 1. Modelo UX
Un editor integrado en dock con pestañas de texto SQL, acciones **Ejecutar sentencia**, **Ejecutar selección**, **Ejecutar todo**, **Cancelar**, **Explicar**, resultados y historial. Nunca ejecuta SQL por presionar «Cargar en QGIS» sin que el usuario sepa cuál consulta se ejecutará.

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
- Vista previa por defecto: 200 filas; opción 50/200/500/1000; siempre visualmente etiquetada «Vista previa».
- Nunca materializar `fetchall()` en resultados sin límite conocido.
- Para lecturas reejecutables, usar una consulta acotada, respetando semántica SQL y su ordenación; si no hay `ORDER BY` no garantizar que la paginación sea estable.
- No calcular `COUNT(*)` completo automáticamente para todo SELECT.
- Cambiar de pestaña de resultados no debe mantener un reader DuckDB abierto.
- El registro conserva solo el fragmento mostrado y metadatos necesarios; no caché universal del resultado completo.
- No efectuar reejecuciones ocultas en consultas potencialmente volátiles/sensibles; indicar cuándo cambia el estado de datos.

## 5. Política de «Cargar resultado en QGIS»
- Solo se activa para resultados tabulares convertibles, seleccionados por el usuario.
- Ofrece las tres modalidades de qgis-bridge-spec §1: «Copia en memoria», «Copia rápida» (desactivada con motivo si GDAL < 3.8) y «Conectada a DuckDB». Un resultado SQL conectado es de solo lectura; editar exige cargar la tabla desde el explorador.
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
- **«Explicar».** Ejecuta `EXPLAIN` de la sentencia actual (o de la selección, si es una sola sentencia) y muestra el plan en una pestaña de resultados. Nunca `EXPLAIN ANALYZE`. Con varias sentencias, se rechaza con un mensaje y no se ejecuta nada. Que `EXPLAIN` de una sentencia DML o DDL no la ejecuta se verifica en E3 con DuckDB 1.5.0 y 2.0.0; si no se confirma, «Explicar» se limita a consultas de lectura.

**P1 sin fase (GD-SQL-008):** formato SQL, historial guardado en disco, búsqueda y reemplazo, snippets, guardado explícito de SQL y `EXPLAIN ANALYZE`.

**P2 (evaluar):** diagnósticos en vivo, sugerencias sofisticadas y trazas de profiling; no son excusa para introducir editor web no justificado.

**G7 · Notebook (`v0.8.0a1`, decisiones del propietario 2026-11-03; GD-NB-001..006):** las pestañas de editor de
G6 pasan a ser **cuadernos**; cada cuaderno es una lista de **celdas**. Todo usa la sesión y el worker únicos.
- **Celda** = editor SQL (con el autocompletado y «Explicar» de G6) + base de la celda + su resultado. Puede tener
  varias sentencias: se ejecutan en orden, como un script (§2); el resultado que se muestra es el de la última que
  devuelve filas, y todas quedan en el registro.
- **Base de la celda.** Al ejecutar una celda, GeoDuck ejecuta `USE <base de la celda>` y después el SQL de la celda
  en **la misma operación del worker** (nada se intercala). Los nombres calificados (`otra_base.esquema.tabla`) son
  siempre válidos, y las tablas temporales se ven desde cualquier base. Verificado con DuckDB 1.5.0 y 2.0.0: `USE`
  se admite dentro de una transacción y `ROLLBACK` no lo deshace; una transacción solo puede escribir en **una**
  base (error de DuckDB, que se muestra tal cual). La base en uso de la sesión queda la de la última celda
  ejecutada. Una celda nueva toma la base en uso. Si el SQL de la celda contiene su propio `USE`, gana el del SQL y
  el selector de la celda lo refleja. Si la base de la celda se desadjunta, la celda lo indica y no se ejecuta hasta
  elegir otra.
- **Ejecutar todo** recorre las celdas en orden (cada una con su `USE`) y se detiene en la primera que falla; las
  siguientes quedan sin ejecutar. Se cancela como un script.
- **Exportar (GD-NB-007).** «Exportar ▾» → CSV o Parquet exporta la **consulta completa**, no la vista previa:
  GeoDuck ejecuta `COPY (<consulta>) TO '<archivo>' (FORMAT csv, HEADER)` o `(FORMAT parquet)` en el worker, con la
  base de la celda, cancelable y con la sesión ocupada. Solo para una consulta de lectura (la misma regla que
  «Cargar en QGIS», GD-SQL-006: un DML nunca se repite); de una celda con varias sentencias se exporta la de su
  resultado. El archivo se elige con el diálogo del sistema, que pide confirmación si ya existe (DuckDB lo
  sobrescribe sin avisar; verificado en 1.5.0 y 2.0.0). Si se cancela o falla, no queda un archivo a medias.
  Verificado en 1.5.0 y 2.0.0: Parquet está incluido (sin instalar nada, ADR-0011); en CSV la geometría sale como
  WKT; en Parquet sale como geometría, pero al volver a leerla DuckDB le asigna `OGC:CRS84` aunque no tenga SRC
  (por verificar en E3: avisar, o declarar el SRC conocido, sin inventarlo; spatial-spec §4).
- Los cuadernos viven en memoria mientras dure el workspace; guardarlos en disco es GD-SQL-008 (sin fase).
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
