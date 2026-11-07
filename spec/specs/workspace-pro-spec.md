# SPEC GD-WSP — Workspace Pro (interfaz nueva)

**Estado:** Propuesta · G9 · `v0.10.0a1` (decisiones del propietario, 2026-11-05 y 2026-11-06; ADR-0016) · **IDs:** GD-WSP-001..012

## 1. Meta y principios
Una interfaz **nueva desde cero**, de administrador de base de datos, moderna y minimalista (tipo TablePlus),
que reemplaza la de G5–G8. No se corrige ni se reaprovecha la actual: se construye aparte y la sustituye cuando
cubre todo (§12). El motor, la sesión, las cargas y el envío a DuckDB (G1–G8) no cambian: solo lo que el
usuario ve.

Principios (propietario, 2026-11-05):
- **Facilidad tremenda sin perder detalle.** Lo común en uno o dos clics, con valores por defecto correctos.
  El detalle no se pierde: está a un clic, visible cuando hace falta y escondido cuando no.
- **Menos es más.** Cada control se gana su sitio; las opciones aparecen solo cuando aplican.
- **Mensajes cortos, en lenguaje simple**, sin jerga técnica en lo común.
- **Nada que se pueda romper sin deshacerlo**; lo irreversible se dice antes.
- **Teclado para quien lo quiera** (Ctrl+K, atajos) y ratón para todo.
- **Capturas antes de construir** cada pantalla; el propietario las aprueba (E0b en adelante).
- **El balance entre opciones y claridad, en toda la interfaz** (propietario, 2026-11-06). Más opciones
  complican; quitarlas también falla. Para cada pantalla: lo común en un clic con el valor por defecto
  correcto; lo avanzado un paso atrás («Más opciones…»), nunca eliminado; solo se muestra lo que aplica en ese
  caso; cada opción dice en una línea qué pasará, y antes de una acción el usuario ve en una frase qué va a
  ocurrir. Así el usuario siempre sabe qué está haciendo.

## 2. Tecnología (GD-WSP-001; ADR-0016)
Qt Widgets de `qgis.PyQt`, en QGIS 3.34+ (Qt 5) y 4.x (Qt 6), con un **sistema de diseño propio** (§10). Sin
motor web (Qt WebEngine no viene en todas las instalaciones de QGIS, ADR-0016) y sin QML como base.
Componentes dibujados a mano donde Qt se ve anticuado (grilla, pestañas, barra lateral, chips, avisos, paleta).
Se mantienen el editor SQL de QGIS (`QgsCodeEditorSQL`), el lienzo del mapa y el arrastre del panel de capas.
Paquete nuevo `geoduck/ui/pro/` (capa `ui` de ADR-0010); la interfaz actual se retira en E6.

## 3. Disposición (GD-WSP-002; maqueta `docs/g8/maqueta/1-tabla`, `2-consulta`, `3-panel`)
- **Ventana propia** (por defecto) y **panel acoplado** a QGIS, con la misma sesión y las mismas pestañas
  (ADR-0013 se mantiene). «Acoplar a QGIS» / «Ventana» alterna sin perder nada.
- **Estado de DuckDB** (propietario, 2026-11-06: sin una barra más): en la ventana, arriba de la barra lateral
  («DuckDB 2.0.0» y «● Lista · en memoria», con «⋯»: Actualizar, **Cerrar DuckDB**); en el panel, en su
  cabecera. La fila de pestañas lleva «Buscar · Ctrl K» y «Acoplar a QGIS».
- **Iniciar y cerrar** (propietario, 2026-11-06): **«Iniciar DuckDB»** (botón grande en el centro cuando no
  está iniciado) y **«Cerrar DuckDB»** (menú «⋯»); la palabra «sesión» no aparece en la interfaz. Sin DuckDB
  iniciado, **todo está en gris** salvo «Iniciar DuckDB», «Abrir base…», «Crear base…», «Diagnóstico» y
  «Acerca de».
- **Barra lateral** (plegable, Ctrl+B): búsqueda; **★ Favoritos**; **Bases** (árbol: bases,
  esquemas, tablas, vistas, temporales, con su acceso); «+» (abrir o crear base, importar capas de QGIS); al pie,
  «Diagnóstico», «Acerca de» y la versión.
- **Área de pestañas:** pestañas de tabla y de consulta (§4, §5), con «+» (nueva consulta), cerrar (×,
  Ctrl+W), reordenar y recordar las abiertas.
- **Pie:** el último aviso (p. ej. «Capa «consumidores» añadida a QGIS desde DuckDB · Conectada · Ver en el mapa»).
- **Panel acoplado** (propietario, 2026-11-07, tras la prueba en Windows; antes no bajaba de 690 px): **modo
  compacto, mínimo 340 px** sin que nada se monte. Las mismas opciones que la ventana, con ícono y tooltip
  donde no cabe el texto: ▶ sin «Ejecutar», ■, la base sin «Se ejecuta en», «Exportar» y «Cargar en QGIS»
  como íconos, «Ver SQL» y el filtro como íconos, «Estructura» como ícono ⓘ arriba; el detalle de fila,
  cerrado. El **explorador** se abre **encima** del contenido con el botón de la barra lateral (Ctrl+B), sin
  repetir la sesión (está en la cabecera del panel), y se cierra al elegir algo, con Esc o con un clic fuera.
  Una ventana de menos de 640 px usa el mismo modo compacto.
- **Clic derecho en una o varias tablas** (Ctrl/Mayús + clic, como en el Explorador de Windows o QGIS) ›
  «Cargar en QGIS ▸» / «Cargar N tablas en QGIS ▸»: el mismo menú que al soltarlas en el mapa (§9); con una
  sola, también «Más opciones…».

## 4. Pestaña de tabla (GD-WSP-003)
Se abre con **doble clic** en una tabla o vista (barra lateral, ★ o Ctrl+K). Solo lectura en G9.
- **Datos:** grilla rápida por páginas (las filas se piden a DuckDB bajo demanda; nunca la tabla entera), con
  tipo bajo cada columna y número de fila.
  - **Orden:** clic en el encabezado (ascendente, descendente, sin orden); lo ejecuta DuckDB.
  - **Filtros en chips:** «+ Filtro» → columna, operador (=, ≠, >, <, contiene, empieza por, es nulo…) y valor;
    cada chip se quita con ×. Se combinan con Y. **«Ver SQL»** muestra la consulta equivalente y la abre en una
    pestaña de consulta.
  - **Buscar** en la tabla (texto en las columnas de texto).
  - **Paginación:** 100 filas por página, sin selector (propietario, 2026-11-05): «Filas 1–100 de 48 312», ‹ ›; el
    total se cuenta aparte, sin bloquear.
  - **Detalle de fila** (panel derecho, plegable): cada campo con su tipo y su valor completo; la geometría
    resumida (tipo, SRC, número de vértices); copiar valor.
- **Estructura:** columnas (nombre, tipo, nulos, clave), filas, tamaño aproximado y la sentencia `CREATE`.
- **Acciones:** «Cargar en QGIS ▾» (§7), «Ver en el mapa» tras cargar, «Exportar ▾» (CSV, Parquet), «Copiar»
  (Ctrl+C sobre la selección).

## 5. Pestaña de consulta (GD-WSP-004)
- Editor SQL de QGIS con resaltado, números de línea y el autocompletado de G6 (bases, tablas, columnas,
  funciones).
- **El archivo arriba, la ejecución abajo** (propietario, 2026-11-06): «⋯» junto a «+» en la fila de pestañas
  con «Abrir consulta…», «Guardar «nombre»» y «Guardar como…»; la barra de la consulta solo tiene lo de
  ejecutar: ▶ Ejecutar, Cancelar y **«Se ejecuta en [base ▾]»**.
- **Un solo «▶ Ejecutar»** (Ctrl+Intro; propietario, 2026-11-06, tras la prueba en Windows): corre la
  selección o, sin ella, **la sentencia marcada**. Una barra de acento a la izquierda del texto marca la
  sentencia que correrá y el botón lo dice («Ejecutar · línea 5», «Ejecutar selección»); se ejecuta
  exactamente lo marcado (se calcula en GeoDuck, igual con DuckDB 1.5 y 2.0; en una línea en blanco entre
  dos, la anterior). **«Ejecutar todo (N sentencias)»** un paso atrás: Ctrl+Mayús+Intro y el **clic derecho
  del editor** (arriba, sobre el menú de siempre); el tooltip del botón explica los dos atajos. Sin botón «Todo». **Cancelar**. La selección se ve con un azul
  claramente distinto del fondo, en claro y en oscuro.
- **Resultado** debajo (una pestaña por sentencia con tabla; sin pestañas si es una); **Mensajes** con el
  registro (OK, errores con línea y columna).
- **El resultado se maneja como la pestaña de tabla** (propietario, 2026-11-06, tras la prueba en Windows): el
  mismo pie abajo con «Filas 1–100 de 1 000 000 · 0,4 s», ‹ › de 100 filas, «Exportar ▾» y «Cargar en QGIS ▾»;
  y el mismo **detalle de fila** a la derecha, plegable. La primera página llega con la ejecución; las demás y
  el total repiten la lectura (`LIMIT`/`OFFSET`, `count(*)`) en el worker, sin bloquear. Sin `ORDER BY`, el
  orden entre páginas no está garantizado. Una escritura con filas (`… RETURNING`) nunca se repite: muestra su
  primera página, «Filas 1–100 de más de 100», sin ‹ ›.
- **Abrir y guardar** `.sql` (Ctrl+O, Ctrl+S) con autoguardado y copia de recuperación activada por defecto
  (ADR-0014, ahora por consulta; propietario, 2026-11-05). Un cuaderno de G7 se abre como **una consulta** (sus celdas, en orden; la base de cada celda,
  como comentario).

## 6. Ctrl+K (GD-WSP-005)
Paleta única para ir a cualquier sitio y hacer cualquier cosa sin el ratón: tablas y vistas de todas las bases,
consultas abiertas y recientes, y acciones (nueva consulta, adjuntar o crear base, enviar capas de QGIS,
cargar la tabla actual, diagnóstico, acoplar). Búsqueda tolerante (letras en orden, sin acentos ni mayúsculas),
con la base y el tipo de cada resultado. Intro abre; Esc cierra.

## 7. Cargar en QGIS (GD-WSP-006; decisión del propietario, 2026-11-05)
Dos opciones, en lenguaje simple:
- **«Copia»:** «Copia los datos a la memoria de QGIS; ya no depende de DuckDB» (propietario, 2026-11-07: sin
  «rápida», que hacía pensar en velocidad; lo que la define es que es una copia en memoria). Por dentro, la Copia rápida (GeoPackage en `/vsimem`, ADR-0012); la
  Copia en memoria solo como **respaldo automático** si GDAL no permite la rápida. El usuario nunca elige entre
  las dos.
- **Al guardar el proyecto** con alguna «Copia» (decisión del propietario, 2026-11-05, tras el spike E0b: ninguna
  copia sobrevive a reabrir el proyecto), GeoDuck lo avisa y ofrece en un clic **«Guardar las copias junto al
  proyecto»**: un GeoPackage al lado del `.qgz`, y cada capa pasa a leer ese archivo y sobrevive. Con «No, gracias»,
  al reabrir la capa se muestra «no disponible» con su motivo, nunca rota sin explicación.
- **«Conectada»:** «Lee directamente de DuckDB, sin copiar; lo que edites se guarda en DuckDB» (ADR-0012).
Reproyectar, separar por tipo y SRC siguen igual (spatial-spec), escondidos hasta que aplican.

## 8. Favoritos (GD-WSP-007)
- **Sin «Recientes» en la barra lateral** (propietario, 2026-11-06, tras la prueba en Windows): estorbaba y
  mostraba tablas que ya no se podían abrir. Lo abierto hace poco solo ordena Ctrl+K, que nunca muestra lo que
  ya no existe.
- **★ Favoritos:** el usuario marca tablas y consultas; aparecen arriba.
- Se recuerdan entre reinicios de QGIS (propietario, 2026-11-05). Se guardan solo **nombres** (base, esquema, objeto; ruta del `.sql`) en `QgsSettings`, nunca datos. Si un
  objeto ya no existe, se muestra atenuado con su motivo.

## 9. Capas de QGIS → DuckDB (GD-WSP-008; qgis-import-spec)
**Una sola ventana de tres pasos para las tres formas** (propietario, 2026-11-06, tras la prueba en Windows:
F-131; reemplaza el envío directo de E5). Ctrl+K y «+» → «Añadir capas de QGIS a DuckDB…»; en QGIS, clic
derecho sobre capas → «Añadir a DuckDB…». «Reproyectar a…» sigue siendo global para todas las capas.

| Cómo empieza | Paso 1 · Capas | Paso 2 · Dónde |
|---|---|---|
| Arrastrar capas a GeoDuck | Las arrastradas, marcadas | La base donde se soltaron (o la actual) |
| Clic derecho › «Añadir a DuckDB…» | Las seleccionadas en QGIS, marcadas | La base actual |
| «Añadir capas de QGIS a DuckDB…» | Todas las del proyecto; marcadas las seleccionadas en QGIS | La base actual |

1. **Capas:** agrupadas en Puntos, Líneas, Polígonos y Tablas sin geometría, con el icono de QGIS, entidades y
   SRC; las que no se pueden (ráster…), en gris con su motivo. Sin capas vectoriales, la ventana lo dice.
   «N capas elegidas» y «Siguiente ›».
2. **Dónde:** base y esquema, **siempre cambiables** (solo bases escribibles); «Qué pasará» con cada capa
   (siempre a la vista); «Más opciones» («Reproyectar a…», «Vista en vez de copia»); una frase de lo que
   ocurrirá. «‹ Atrás» y «Añadir N capas a DuckDB».
3. **Progreso:** una fila por capa (✓ añadida, ⟳ copiándose con su %, ○ en espera, ✕ cancelada o con error).
   «×» quita una capa en espera o detiene la que se copia; «Cancelar todo»; «Seguir en segundo plano». Al
   terminar: qué pasó con cada una, «Deshacer», «Abrir» y «Cerrar».

- **Cada capa se guarda por separado** (una transacción por capa; reemplaza «todo o nada» de G8, propietario
  2026-11-06): las que terminaron quedan aunque se cancelen o fallen otras; «Deshacer» borra las tablas
  nuevas. Las capas van una tras otra (DuckDB escribe de a una cosa).
- **En segundo plano:** el pie muestra «⟳ Añadiendo 2 de 4 a DuckDB · redes_bt 62 %»; un clic (o Ctrl+K ›
  «Ver progreso: capas de QGIS → DuckDB») vuelve al paso 3. Si se intenta añadir más mientras tanto, se
  muestra el paso 3 en curso: «Termina o cancela estas capas para añadir más». Al terminar con la ventana
  cerrada, un aviso «N capas de QGIS añadidas a DuckDB · prueba · Abrir · Deshacer · ×».
- **Dónde se suelta, claro:** la base bajo el cursor se resalta con un borde de acento y el pie dice
  «Suelta para enviar N capas a «db»»; en un espacio vacío o en la cabecera, la base actual.
- **Nombres:** «Añadir … a DuckDB» siempre termina en DuckDB (QGIS → DuckDB); «Cargar en QGIS» siempre termina
  en QGIS (DuckDB → QGIS). **GeoDuck** es el complemento; **DuckDB**, la base donde quedan los datos.
- **Avisos:** todos llevan «×» para cerrarlos sin hacer nada más (F-132).

**Arrastrar, en los dos sentidos** (propietario, 2026-11-06; E5).
- **DuckDB → QGIS:** soltar una o varias tablas o vistas en el mapa o en el panel de capas abre un **mini
  menú** «Copia» / «Conectada»: un clic carga todo lo soltado; Esc cancela. El SRC sale de la columna de
  geometría (`GEOMETRY('EPSG:4326')`); **solo si a alguna le falta**, una sola ventana pequeña pide uno para
  todas (desplegable para elegir por tabla).

## 10. Sistema de diseño (GD-WSP-009)
- **Tokens** en un solo lugar: colores, tipografía (la del sistema), tamaños, espacios, radios, sombras,
  duraciones. Tema **claro y oscuro** según el de QGIS. Los estilos se generan de los tokens y se aplican **solo
  a GeoDuck** (ADR-0011: nunca a QGIS).
- **Componentes:** botón (primario, secundario, peligro, fantasma), campo, desplegable, chip, pestaña, árbol,
  grilla, aviso, insignia, paleta, panel lateral.
- **Iconos** SVG propios, monocromos, que siguen el color del texto.
- **Movimiento** breve y medido (≤ 150 ms); nada que distraiga.
- Contraste AA en los dos temas.

## 11. Accesibilidad, idioma y estados (GD-WSP-010)
- Todo con teclado (Tab, flechas, atajos); foco visible; nombres accesibles y ayuda en cada acción.
- Inglés y español según el idioma de QGIS (catálogo `.ts`, como G6).
- Estados obligatorios en cada vista: DuckDB sin iniciar, cargando, vacío, error (con qué hacer), DuckDB
  ocupado.
- Pocos pasos y el espacio para lo que importa (propietario, 2026-11-06): una sola barra fina por pestaña,
  los avisos en el pie, nada que no se use.
- Panel estrecho: se compacta sin perder acciones.

## 12. Cambio y retiro (GD-WSP-011)
La interfaz nueva se construye en paralelo (E1–E5) y sustituye a la actual en E6, cuando cubre todas sus
funciones. Entonces se retiran el workspace de G5, el editor de G6 y los cuadernos de G7 (la lista de cuadernos,
las celdas y su selector). Los cuadernos guardados que estaban abiertos vuelven como consultas. Las
preferencias de presentación (ventana o panel, zona del panel, barra lateral) se conservan.

Al cambiar (E6, propietario 2026-11-06: «Tú decide»), lo que la interfaz anterior hacía y la nueva aún no:
- **Revertir una transacción abortada:** un aviso que no se va solo, «La transacción falló · Revertir», y
  Ctrl+K › «Revertir transacción». Sin él la sesión no se puede volver a usar salvo cerrándola.
- **Ver en el mapa:** el aviso de cada carga lleva «Ver en el mapa» (selecciona la capa y hace zoom; en la
  ventana, GeoDuck se minimiza).
- **Historial de ejecución:** Ctrl+K › «Historial de ejecución» abre una pestaña con cada sentencia (hora,
  estado, sentencia, duración, mensaje), «Todo / OK / Error» y «Limpiar»; doble clic la abre en una consulta
  nueva sin ejecutarla. Solo en memoria: no se guarda en disco ni entre reinicios.
- El aviso de carga conserva el origen, el acceso y los avisos (decisión del 2026-11-02).
- **Entorno incompleto** (sin DuckDB o PyArrow): la pantalla de inicio lo explica, «Iniciar» queda en gris y
  ofrece «Diagnóstico» (AT-BOOT-002).
- El menú de capa «Enviar a DuckDB…» hace lo mismo que soltar las capas (§9); «+» y Ctrl+K abren el diálogo
  para elegir.

Las opciones avanzadas de la ventana «Cargar en QGIS…» de G4 no se pierden (propietario, 2026-11-06): van en
«Cargar en QGIS ▾» › **«Más opciones…»** (E6b), la última línea, discreta, del menú. Abre una ventana corta:
Copia / Conectada; «Qué geometrías» solo si hay varias o una columna WKB/WKT («Usar «x» como geometría»);
«Reproyectar a…» solo en una Copia y «Separar por tipo de geometría» solo en una Conectada, cada una con una
línea que dice qué pasará; abajo, «Se cargarán N capas · Copia». El SRC que falte se pregunta después, una
vez (también el de una columna WKB/WKT). Las
columnas en el árbol del explorador se ven en «Estructura» de la pestaña de tabla (§4).

## 13. Rendimiento (GD-WSP-012)
Objetivos en la máquina de referencia (benchmarks.md), verificados en E3–E6:
- abrir una tabla de 1 millón de filas: primera página visible en menos de 0,5 s;
- desplazar, ordenar y filtrar sin congelar la interfaz (el trabajo va al worker);
- Ctrl+K con 1 000 objetos: resultados al teclear (< 50 ms por tecla);
- alternar ventana y panel en menos de 0,2 s.

## 14. Fuera de alcance de G9
Editar celdas en la grilla (después de G9); gráficos; diagramas entidad-relación; varias sesiones a la vez;
ejecutar en segundo plano varias consultas a la vez (el worker sigue siendo serial).

## 15. Sin regresión
La sesión, el SQL, las tres cargas (ahora con «Copia» unificada), el envío a DuckDB, el diagnóstico, la
convivencia (ADR-0011) y las protecciones de sesión siguen igual. Toda la suite G0–G8 pasa, con las pruebas de
interfaz reescritas para la interfaz nueva en E6.
