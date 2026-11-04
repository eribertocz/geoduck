# SPEC GD-UX — Interfaz moderna, minimalista y profesional

**Estado:** baseline Alpha · **ID:** GD-UX-001

## 1. Filosofía
Una sola superficie coherente dentro de QGIS: **explorar, escribir, consultar y entregar**. UI nativa Qt, respetando tema claro/oscuro de QGIS, tipografía de sistema, espaciado generoso, controles discretos, íconos consistentes y estados visibles. No introducir landing pages, dashboards ni animaciones innecesarias.

## 2. Disposición del dock
```text
┌─ GeoDuck ────────────── [Sesión: memoria | Archivo RO/RW] [Estado] ──┐
│ Explorador de catálogos │ Editor SQL [tab 1] [tab 2]                 │
│   ▶ memory             │ [Ejecutar] [Actual] [Selección] [Todo]    │
│   ▼ comercial (RO)     │ SELECT ...                                 │
│     esquemas           │                                            │
│       tablas/vistas    ├────────────────────────────────────────────┤
│   + Adjuntar / Detach  │ Resultados [#1] [#2] [Ejecuciones]         │
│                       │ Preview paginado / error / plan            │
│                       │ [Cargar activo en QGIS] [Cargar elegidos]   │
└───────────────────────┴────────────────────────────────────────────┘
```

El explorador puede colapsarse; el área del editor y resultados tiene divisores ajustables. El dock es redimensionable, con estados vacíos informativos.

## 3. Interacciones definidas
- **Inicio:** tarjeta discreta «En memoria» / «Archivo DuckDB», selector de archivo, toggle «Solo lectura / Lectura y escritura», botón «Iniciar sesión». La UI se desbloquea al confirmar la sesión.
- **ATTACH:** icono `+` al lado de catálogos; diálogo path, alias, RO/RW; feedback al finalizar.
- **DETACH:** menú contextual «Desadjuntar» con confirmación si hay operaciones propias activas. No mostrar advertencia falsa de que se perderán capas QGIS ya entregadas. Si hay capas conectadas a esa base, avisar de que quedarán no disponibles hasta adjuntarla de nuevo.
- **Tabla/Vista:** doble clic o clic derecho «Cargar en QGIS…» con las tres modalidades y selector espacial si aplica. Toda tabla cargada como Conectada es editable; vistas y consultas, de solo lectura (qgis-bridge-spec §5.1).
- **Modalidad de carga:** un solo diálogo pequeño con tres opciones y una línea de ayuda cada una: «Copia en memoria — compatible, para resultados pequeños», «Copia rápida — rápida y con poca memoria», «Conectada a DuckDB — sin copiar, siempre al día». Recuerda la última elección. Las opciones no disponibles se muestran desactivadas con el motivo. Sin términos técnicos (`/vsimem`, GeoArrow, proveedor).
- **SQL:** botón principal «Ejecutar» opera sobre sentencia actual si no hay selección, o selección según preferencia explícita; comandos «Todo» y «Selección» inequívocos.
- **Resultados:** pestañas por sentencia con nombre legible y ID; cambiar pestaña selecciona solo ese resultado. `Cargar en QGIS` siempre etiqueta el resultado objetivo.
- **Múltiples geometrías:** selector pequeño con una casilla por columna, nombre/tipo/CRS; permitir una o varias (una capa por columna). No modal por cada consulta cuando no hay ambigüedad.
- **Opciones espaciales del diálogo de carga (G4, spatial-spec):** «Usar como geometría: WKB/WKT» para columnas `BLOB`/`VARCHAR` (nunca marcadas por defecto); «Tipos mixtos: una capa por tipo» (Memoria e Instantánea, activada) o «Separar por tipo» (Conectada, desactivada); «Reproyectar a…» (solo Memoria e Instantánea, desactivada, con CRS conocido).
- **Capa cargada por GeoDuck:** menú contextual «Diagnosticar geometrías…»; el resultado ofrece «Reparar en una copia…» (spatial-spec §9).
- **Sesión:** sin acción para `spatial`; `LOAD`/`INSTALL` los escribe el usuario en el editor (spatial-spec §10).
- **Progreso:** nombre operación, estado, filas procesadas, tiempo, cancelar; sin porcentaje inventado cuando no existe total.
- **Errores:** título comprensible, detalle expandible, acción de recuperación; conservar SQL para corregirlo.

## 4. Diseño visual
- Diseño monocromático por defecto con un acento derivado del tema QGIS; estados semanticamente accesibles (éxito/advertencia/error).
- Controles con alturas y espacios coherentes; evitar iconos sin texto o tooltip.
- Autocompletado contextual no intrusivo; errores de SQL resaltados sin cubrir código.
- Pestañas cerrables, atajos conocidos (Ctrl+Enter ejecutar actual, Ctrl+Shift+Enter ejecutar todo, Esc cancelar donde sea seguro), configurables. **F5 no se usa** (en QGIS refresca el mapa); los atajos actúan solo con el foco dentro de GeoDuck (decisión del propietario, 2026-11-02).
- UI responsive dentro del dock; no usar tamaños fijos que hagan inutilizable un panel estrecho.

## 5. Accesibilidad e internacionalización
- Teclado completo, foco visible, etiquetado accesible, contraste, tooltips y lectores de pantalla cuando Qt lo permita.
- Español inicial; internacionalización por catálogos de traducción con idioma inglés listo para incorporar. **Desde G6 (GD-I18N-001, issue #68):** los textos del código están en inglés y el español llega por el catálogo `i18n/geoduck_es.ts` (formato de Qt Linguist), según el idioma de QGIS. GeoDuck lo lee y traduce con un diccionario, sin `QTranslator` ni `.qm`: el hilo del motor también traduce mensajes y llamar a Qt desde él no es seguro, sin opción propia de GeoDuck ni cambio del idioma de QGIS. Sin traducción, se ve el texto en inglés, nunca un texto vacío. No se traducen el SQL, los nombres de objetos, los datos ni los mensajes de DuckDB. Se mantienen los términos de QGIS en cada idioma (SRC/CRS, entidades/features).
- Formatos numéricos locales en UI sin alterar sintaxis SQL ni precisión interna.

## 6. Estados obligatorios
`sin sesión`, `conectando`, `listo`, `ejecutando`, `preview disponible`, `resolución espacial`, `transfiriendo`, `cancelando`, `entrega exitosa`, `fallo recuperable`.

Para «entrega exitosa», no mostrar «capa lista» hasta que el proyecto QGIS haya registrado capas íntegras. Cuando se desadjunta una base, el explorador se actualiza; las capas entregadas no aparecen como «desconectadas» porque son independientes.

## 7. UX QA
Prueba de tareas guiadas con persona no programadora: adjuntar base, abrir tabla, cargar punto, desadjuntar y constatar que capa sigue visible. Prueba SQL avanzada: crear temporal, múltiples SELECT, alternar resultados, cargar sólo uno. Probar UI en Qt5 y Qt6 con distintos tamaños DPI.

## 8. Workspace UX (G5 · `v0.6.0a1`; ADR-0013; issue #49; decisiones del propietario, 2026-11-02)
Un solo workspace (`WorkspaceController` + `WorkspaceContent`: explorador, editor, resultados, registro y estado) con **dos presentaciones**: ventana propia (`QMainWindow`, **por defecto**) y panel acoplado (`QDockWidget`). El diagrama de §2 describe el panel; la maqueta aprobada en issue #49 es la referencia visual de ambas.

**Ventana propia.** Barra de sesión (estado, versión de DuckDB, «Acoplar a QGIS»); explorador lateral redimensionable, con «Iniciar sesión» / «Cerrar sesión» al pie; editor y resultados con divisor; registro inferior colapsable con filtros Todo/OK/Error; barra de estado (tarea, última carga con modalidad y origen, «Ver en el mapa», «Diagnóstico del entorno…», «Acerca de…», versión). Es **hija de la ventana principal de QGIS**: queda encima de QGIS, se minimiza con él y no tiene entrada propia en la barra de tareas. La **X la oculta**; el botón de GeoDuck de la barra de herramientas la vuelve a mostrar.

**Panel acoplado.** Barra de título propia («GeoDuck», «Abrir en ventana», X que oculta el panel) y estado de sesión; pestañas Explorador / SQL / Registro (con contador de errores); en SQL, editor y resultados en vertical con divisor; «Cargar en QGIS ▾» visible; mensaje de la última carga compacto con el detalle accesible. En un panel estrecho se compactan etiquetas, nunca se quitan acciones.

**Alternancia.** Es una operación de presentación: el contenido cambia de contenedor en el hilo GUI conservando su identidad y conexiones; nunca se repite SQL ni una carga, no se cancela nada y no hay `COMMIT`, `ROLLBACK` ni `DETACH`. Si el traslado falla, el shell de origen sigue operativo y se informa.

**Ubicación de las acciones existentes.**
- «+» del explorador: «Abrir existente…» y «Crear nueva…»; botón de actualizar el catálogo.
- Menú contextual de una base: «Desadjuntar» (con las protecciones de G3).
- Pie de «Bases de datos»: «Iniciar sesión» sin sesión activa y «Cerrar sesión» con ella (decisión del propietario, 2026-11-02). La ayuda «Doble clic o clic derecho → Cargar en QGIS…» va en cada tabla y vista del árbol.
- Barra de sesión: «Revertir transacción» solo con la transacción abortada.
- No hay acción «Activar spatial…» (decisión del propietario, 2026-11-02): el usuario escribe `INSTALL spatial; LOAD spatial;` en el editor, como en cualquier cliente de DuckDB (spatial-spec §10).
- Identidad visual: paleta corporativa, forma y tipografía de `docs/g5/maqueta/inventario.md` §0, aplicadas solo a los widgets de GeoDuck (ADR-0011).
- Capas de GeoDuck: «Diagnosticar geometrías…» en el menú de capa de QGIS (sin cambios).

**«Cargar en QGIS ▾».** El menú muestra las tres modalidades con su descripción y las no disponibles desactivadas con el motivo. Elegir una abre **el diálogo de G4 con esa modalidad marcada** (geometrías, SRC, «Reproyectar a…», tipos mixtos); nada cambia en G3/G4.

**«Ver en el mapa».** Trae QGIS al frente y selecciona la capa en el panel de capas. En la ventana propia, GeoDuck se minimiza para dejar ver el mapa (decisión del propietario, 2026-11-02); el botón de GeoDuck de la barra de herramientas la restaura. En el panel acoplado no se minimiza nada. Si la capa tiene extensión válida (no vacía, finita, transformable al SRC del proyecto con su contexto de transformación), hace zoom a ella. Si no la tiene (tabla sin geometría, sin geometrías, extensión desconocida o no transformable), no hace zoom y lo dice: «La capa no tiene extensión válida: se seleccionó sin hacer zoom». Si la capa ya no está en el proyecto, la acción se desactiva.

**Preferencias** (`QgsSettings`, prefijo `geoduck/workspace/`, con versión de esquema): modo, geometría de la ventana (corregida si su pantalla ya no existe), zona del panel, ancho del explorador y divisores por modo, pestaña activa, filtro del registro y límite de vista previa. Nunca filas, SQL guardado de otros procesos ni estado de DuckDB. Ajustes corruptos o antiguos → valores seguros.

**Cerrar.** Ocultar o cerrar la ventana o el panel no es «Cerrar sesión» (session-spec §2); descargar GeoDuck sigue el cierre seguro existente.


## 9. SQL Professional (G6 · `v0.7.0a1`; decisiones del propietario, 2026-11-02)

Todo vive en el mismo `WorkspaceContent` de G5 y se ve igual en la ventana propia y en el panel; no se crean ventanas, paneles ni conexiones nuevas.

- **Columnas en el explorador (GD-CAT-002).** Cada tabla y vista se puede expandir y muestra sus columnas como `nombre · TIPO`, con un icono propio para las de tipo `GEOMETRY` (por el tipo, nunca por el nombre). Ayuda: tipo exacto y «Admite NULL: sí/no». Se leen al expandir (session-spec `ListColumns`), con un nodo «Cargando…» mientras tanto. La búsqueda sigue filtrando por tablas y vistas, no por columnas. **Doble clic o arrastrar una columna** al editor inserta su nombre (entre comillas si hace falta) en la posición del cursor; el doble clic en una tabla o vista sigue siendo «Cargar en QGIS…» (§3).
- **Autocompletado.** Lista pequeña bajo el cursor, que no tapa la línea que se escribe; el tipo de cada sugerencia (columna, tabla, vista, esquema o base, función) con su icono de QGIS; las palabras clave, sin icono. Orden: columnas de los objetos de la sentencia, tablas, vistas, esquemas, bases, funciones y palabras clave. Sustituye al autocompletado de palabras de `QgsCodeEditorSQL`, para que no haya dos listas.
- **Pestañas de editor.** Encima del editor («Consulta 1», «Consulta 2»…), con «+» para una nueva y cierre en cada pestaña (también con el teclado); Ctrl+T nueva, Ctrl+W cerrar, solo con el foco en GeoDuck. En los editores de GeoDuck, Ctrl+T deja de intercambiar líneas (comando de QScintilla).
- **Historial.** «Abrir en el editor» en el menú contextual de cada fila del registro.
- **«Explicar»** (retirado en G7: se escribe `EXPLAIN` en la celda). Botón en la fila de «Ejecutar», con ayuda que explica que no ejecuta la sentencia; en una fila estrecha, solo su icono (no amplía el ancho mínimo de GeoDuck).
- **Idioma.** §5.

## 10. Notebook (G7 · `v0.8.0a1`; decisiones del propietario, 2026-11-03)

Referencia visual: la DuckDB UI (capturas del propietario, 2026-11-03), **sin incrustarla** (roadmap, decisión
2026-11-03). Maqueta en `docs/g7/maqueta/`. Todo en el mismo `WorkspaceContent` de G5, en ventana y en panel.

- **Columna izquierda (ventana):** «Cuadernos» (lista, «+» nuevo, renombrar, cerrar) encima de «Bases de datos» (el
  explorador de G5–G6, sin cambios). Es una barra lateral plegable, como la de la DuckDB UI: «◫» a la izquierda del
  nombre del cuaderno, o Ctrl+B, la oculta y la muestra; se recuerda (decisión del propietario, 2026-11-03). En el
  panel, los cuadernos van en el selector de la pestaña SQL.
- **Centro:** las celdas del cuaderno, una debajo de otra, con desplazamiento (capturas del propietario de la
  DuckDB UI, 2026-11-03). Cada celda:
  - **Margen izquierdo:** asa «⠿» para **arrastrar** la celda a otra posición (se mueven con ella su texto, su base y
    su resultado; no se ejecuta nada) y tres «˅» para **plegar** por separado la celda entera, el editor y el
    resultado. Encima de cada celda, «+» al pasar el ratón inserta una celda ahí.
  - **Cabecera:** botón ▶ (ejecuta la celda) con menú ▾ («Ejecutar celda», «Ejecutar selección», «Ejecutar celda
    y avanzar», cada uno con su atajo, como la DuckDB UI) y, a la derecha, el selector de base: un desplegable con
    el icono de base de datos, su nombre y «▾», con borde, para que no parezca un botón (propietario, 2026-11-03).
  - **Editor** (crece con su texto, desde una línea; con números de línea) y, debajo, el **resultado** con fondo propio y una línea encima:
    arriba «N filas en X ms» (con varias sentencias, «N filas · K sentencias en X ms», como la DuckDB UI) y sus botones;
    debajo la tabla, con grilla suave y la altura que pidan sus filas. Con un solo resultado no se muestra su pestaña (el rótulo ya lo
    dice); con varias sentencias, una pestaña por cada una. Una celda sin tabla (`CREATE`) muestra solo el rótulo, sin
    botones (decisión del propietario, 2026-11-03: opción A). Los botones: «Cargar ▾» (icono de capa y texto corto;
    la ayuda y el nombre accesible dicen «Cargar en QGIS») y «Exportar ▾» (CSV o Parquet, la consulta completa). Sin
    botón «Copiar»: Ctrl+C copia las celdas seleccionadas de la tabla, separadas por tabuladores (con toda la tabla
    seleccionada, también los nombres de las columnas). El rótulo «N filas en X ms ⓘ» tiene como ayuda el
    **resumen** del resultado (GD-NB-004): «N filas · M columnas» y cada columna con su tipo, sin consultas nuevas.
  - **Margen derecho:** «⛶ Vista de hoja» (Ctrl+E): la celda ocupa todo el centro, con el editor arriba y el
    resultado abajo separados por un divisor; otra vez ⛶ (o Escape) vuelve a la lista de celdas. Debajo, menú «⋯»,
    como la DuckDB UI: «Subir celda» (Ctrl+↑), «Bajar celda» (Ctrl+↓), separador, «Duplicar celda» y «Eliminar»
    (con confirmación si tiene SQL). Plegar queda en el margen izquierdo.
  - La celda activa tiene el borde de acento. Al final, «+ Añadir celda».
  - Teclado (además del ratón): Ctrl+↑/↓ sube o baja la celda activa.
- **Panel acoplado:** minimalista, solo lo esencial (decisión del propietario, 2026-11-03): en una fila, el selector
  del cuaderno, «▶ Ejecutar todo» y «Cancelar»; celdas con ▶, base, editor y resultado; «Exportar ▾» y «Cargar en
  QGIS ▾» al pie, para la celda activa.
- **Celda como tarjeta:** borde redondeado; la activa, con el borde de acento; el margen izquierdo (⠿ ˅) y el derecho
  (⛶ ⋯) quedan fuera de la tarjeta; la base, como desplegable (en rojo si se desadjuntó).
- **Sin columna derecha** (decisión del propietario, 2026-11-03): el resumen repetía la tabla; queda como ayuda ⓘ.
- **Registro** (ventana): plegado por defecto en una línea, «▸ Registro · Todo (N) · OK (N) · Error (N)»; «▸», o
  elegir un filtro, lo abre; se recuerda. En el panel va en su pestaña, siempre abierto.
- **Barra superior del cuaderno:** «◫», nombre del cuaderno, «▶ Ejecutar todo» (sin atajo) y «Cancelar»; sin
  selector de filas (vista previa fija de 20, sql-editor-spec §4). Sin «Sentencia», «Selección» ni «Explicar» (decisión del propietario, 2026-11-03): eso vive en el ▶
  de cada celda.
- **Atajos** (solo con el foco en GeoDuck, como la DuckDB UI): Ctrl+Intro ejecuta la celda activa; Ctrl+Mayús+Intro,
  solo su selección; Mayús+Intro ejecuta la celda y pasa a la siguiente (la crea si es la última); Alt+↑/↓ cambia de
  celda; Ctrl+↑/↓ la mueve; Ctrl+E vista de hoja.
- Rendimiento: un resultado se crea al terminar su celda y su altura está acotada (desplazamiento propio). Medido en
  E3 (QGIS 3.34 · Qt 5 y 4.2 · Qt 6): 100 celdas se crean en menos de 1 s (12 ms la siguiente), se ejecutan en
  4–5 s con 200 filas cada una y ocupan ~0,5 MB por resultado; el desplazamiento y el cambio de cuaderno son
  fluidos. Por eso todas las celdas conservan su tabla (no se liberan las que no se ven).
