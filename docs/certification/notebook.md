# Prueba manual en Windows · G7 Notebook

Complementa la CI (Linux) para lo que solo se ve en Windows: ratón (arrastrar), teclado, diálogos del sistema,
idioma y aspecto. Unos 20 minutos. Requisitos: Windows 10/11, QGIS 3.34+ (o 4.x), DuckDB y PyArrow como en
`docs/certification/workspace.md` §1. Instale el ZIP del PR (Complementos → Instalar a partir de ZIP).

Anote cada paso como **OK** o **Falla** (con captura) en `docs/evidence/g7/windows/<celda>/README.md`.

## 1. Preparación

1. Abra GeoDuck → «Iniciar sesión». Cree una carpeta de prueba, por ejemplo `C:\geoduck-g7\`.
2. En la primera celda, pegue y ejecute con **Ctrl+Intro**:

   ```sql
   ATTACH 'C:\geoduck-g7\otra.duckdb' AS otra;
   CREATE TABLE otra.consumidores AS
     SELECT range AS id, 'zona ' || (range % 3) AS zona,
            ('POINT(' || (range % 50) || ' ' || (range % 7) || ')')::GEOMETRY AS geom
     FROM range(100000);
   CREATE TABLE memory.tarifas AS SELECT 'zona 0' AS zona, 1.5 AS precio;
   ```

## 2. Celdas y base de cada celda (AT-NB-003, 004, 005)

| # | Haga | Debe pasar |
|---|---|---|
| 2a | «+ Añadir celda»; en su selector de base elija `otra`; escriba `SELECT * FROM consumidores` y pulse **Ctrl+Intro** | Tabla debajo con «20+ filas · X ms ⓘ» (20 filas de vista previa); números de línea en el editor; sin pestaña (un solo resultado) |
| 2b | Añada otra celda en `memory` con `SELECT c.zona, t.precio FROM otra.consumidores c JOIN tarifas t USING (zona) LIMIT 5` | Funciona: se lee otra base por su nombre |
| 2c | Vuelva a la celda 2a y pulse «Cargar ▾» → «Copia en memoria» | Capa de 100 000 puntos en QGIS, aunque la última celda ejecutada sea `memory` |
| 2d | Repita 2c con «Conectada a DuckDB» y mueva el mapa | La capa se dibuja; ejecutar otra celda no la rompe |
| 2e | En una celda escriba `USE otra; SELECT count(*) FROM consumidores` y ejecútela | El selector de esa celda pasa a `otra` |
| 2f | Ejecute `DETACH otra` en otra celda | Las celdas en `otra` muestran «otra (no adjunta)» en rojo; ejecutarlas avisa y no hace nada |

## 3. Atajos (AT-NB-008)

| # | Haga | Debe pasar |
|---|---|---|
| 3a | En una celda con `SELECT 1 AS a; SELECT 2 AS b`, **Ctrl+Intro** | Las dos sentencias; dos pestañas («A», «B») |
| 3b | Seleccione solo `SELECT 2 AS b` y pulse **Ctrl+Mayús+Intro** | Solo esa sentencia |
| 3c | **Mayús+Intro** en la última celda | La ejecuta y crea una celda nueva con el cursor |
| 3d | **Alt+↑ / Alt+↓** | El foco pasa a la celda de arriba / de abajo |
| 3e | **Ctrl+↑ / Ctrl+↓** | La celda activa sube / baja (el texto no se desplaza) |
| 3f | **Ctrl+E** | Vista de hoja: solo esa celda; otra vez Ctrl+E vuelve a la lista |
| 3g | Escriba `SELECT * FROM otr` | El autocompletado sugiere `otra` (como en G6) |
| 3h | Fuera de GeoDuck (en el mapa de QGIS), Ctrl+Intro y Ctrl+E | Nada de GeoDuck se ejecuta |

## 4. Ratón: arrastrar, plegar, menú (AT-NB-001)

| # | Haga | Debe pasar |
|---|---|---|
| 4a | Arrastre una celda por su asa «⠿» encima de otra | Cambia de sitio con su texto, su base y su resultado; nada se ejecuta |
| 4b | Use los tres «˅» del margen | Pliega la celda entera, solo el editor y solo el resultado |
| 4c | Menú «⋯» → «Subir celda», «Bajar celda», «Duplicar celda» | Hace lo que dice; el menú muestra Ctrl+↑ y Ctrl+↓ |
| 4d | «⋯» → «Eliminar» en una celda con SQL | Pregunta antes; «No» la deja |
| 4e | El «+» encima de una celda | Inserta una celda vacía ahí |

## 5. Exportar (AT-NB-011)

| # | Haga | Debe pasar |
|---|---|---|
| 5a | En la celda de 2a: «Exportar ▾» → «CSV…», guarde `C:\geoduck-g7\consumidores.csv` | Mensaje «Exportadas 100000 filas»; el archivo tiene 100 001 líneas (con la cabecera) y la geometría en WKT |
| 5b | Repita y elija el mismo archivo | Windows pregunta si quiere reemplazarlo; «No» no cambia nada |
| 5c | «Exportar ▾» → «Parquet…» | Aviso de que la geometría no tiene SRC (se supondrá OGC:CRS84). Arrastre el `.parquet` a QGIS: se abre |
| 5d | Celda con `SELECT id, ST_SetCRS(geom, 'EPSG:32719') AS geom FROM otra.consumidores`; exporte a Parquet | Sin aviso; al abrirlo en QGIS (si su GDAL lo admite) el SRC es EPSG:32719 |
| 5e | Exporte `SELECT a.range * b.range FROM range(30000) a, range(30000) b` a Parquet y pulse «Cancelar» enseguida | «Exportación cancelada»; en la carpeta no queda ningún archivo nuevo ni oculto |
| 5f | Celda con `INSERT INTO memory.tarifas VALUES ('zona 1', 2) RETURNING *` | Se ve la fila devuelta, pero «Exportar» y «Cargar» están desactivados (una escritura no se repite) |

## 6. Cuadernos, resumen y panel (AT-NB-006, 007, 009, 010)

| # | Haga | Debe pasar |
|---|---|---|
| 6a | «Cuadernos» → «+»; doble clic en su nombre y escriba «Cobranza» | Cuaderno nuevo y renombrado; cambiar entre cuadernos conserva sus celdas |
| 6b | Seleccione un cuaderno con SQL y pulse Supr | Pregunta antes de cerrarlo |
| 6c | Pase el ratón sobre «20+ filas · X ms ⓘ» | Ayuda con «20+ filas · 3 columnas» y cada columna con su tipo (no hay columna derecha) |
| 6d | Ejecute una celda larga y, mientras corre, «Acoplar a QGIS» y «Abrir en ventana» | Mismas celdas y resultados; la ejecución sigue y se puede cancelar |
| 6e | En el panel acoplado, estréchelo al mínimo | Selector del cuaderno y «Ejecutar todo» arriba; «Exportar» y «Cargar en QGIS» al pie (de la celda activa); ninguna acción desaparece; «3 filas · X ms ⓘ» muestra el resumen al pasar el ratón |
| 6f | Recorra el panel con Tab | Cada botón recibe el foco y tiene ayuda |
| 6g | Ventana: «◫» (o Ctrl+B) | Se oculta y se muestra la barra «Cuadernos + Bases de datos»; se recuerda al reiniciar |
| 6i | Ventana: «▸ Registro · Todo (N) · …» abajo | Plegado por defecto en una línea; «▸» lo abre; se recuerda al reiniciar |
| 6j | En una tabla de resultado, seleccione unas celdas y pulse Ctrl+C; pegue en Excel | Se pegan esas celdas en columnas; con Ctrl+A antes, también los nombres |
| 6k | El selector de base de una celda | Se ve como desplegable (icono de base, nombre y «▾»), no como botón |
| 6l | Pie de la ventana: «Ver en el mapa» | Con icono de mapa |
| 6h | «⋯» de «Cuadernos» → «Guardar cuaderno» (o Ctrl+S); elija `C:\geoduck-g7\ventas` | Se crea `ventas.sql`; el cuaderno pasa a llamarse «ventas». Ábralo en el Bloc de notas: una marca `-- %% cell · database: …` por celda |
| 6m | Cambie el SQL de una celda de «ventas» y espere 2 s; vuelva a abrir `ventas.sql` en el Bloc de notas | El cambio ya está (se guarda solo) |
| 6n | Cierre «ventas»; «⋯» → «Abrir cuaderno…» (o Ctrl+O) → `ventas.sql` | Vuelven sus celdas, con su base |
| 6o | Abra un `.sql` cualquiera (sin marcas) | Se abre como una sola celda |
| 6p | Escriba SQL en un cuaderno sin guardar; cierre QGIS a la fuerza (Administrador de tareas → Finalizar tarea); abra QGIS y GeoDuck | Aviso «GeoDuck no se cerró bien. ¿Recuperar su cuaderno?»; «Recuperar» devuelve el SQL |
| 6q | Cierre QGIS normalmente y vuelva a abrirlo | No hay aviso: la copia se borró |
| 6r | «⋯» → desmarque «Copia de recuperación…» | Se borra la carpeta `geoduck\recuperacion\…` del perfil de QGIS y no se vuelve a escribir |
| 6s | En una celda con base `db`, pulse «+ Añadir celda» | La celda nueva muestra ya `memory` en su selector (sin ejecutarla); «⋯» → «Duplicar celda» conserva `db` |

## 7. Idioma y aspecto

| # | Haga | Debe pasar |
|---|---|---|
| 7a | QGIS en inglés, reinicie | «Run all», «Notebooks», «Add cell», «Load», «Export» |
| 7b | QGIS en español, reinicie | «Ejecutar todo», «Cuadernos», «Añadir celda», «Cargar», «Exportar» |
| 7c | Tema oscuro de QGIS (Configuración → Opciones → General → Tema «Night Mapping») | Celdas, borde de la activa, etiqueta de la base y resultado legibles |
| 7d | Compare con `docs/g7/maqueta/maqueta.png` | Misma disposición: cuadernos y bases a la izquierda, celdas al centro, resumen a la derecha |

## 8. Resultado

Celda (Windows · QGIS · DuckDB) · fecha · pasos OK / Falla. Una falla abre una issue con la captura; no
bloquea el cierre de G7 salvo que lo decida el propietario.
