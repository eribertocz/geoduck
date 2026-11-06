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
- **Barra lateral** (plegable, Ctrl+B): búsqueda; **Recientes**; **★ Favoritos**; **Bases** (árbol: bases,
  esquemas, tablas, vistas, temporales, con su acceso); «+» (abrir o crear base, importar capas de QGIS); al pie,
  «Diagnóstico», «Acerca de» y la versión.
- **Área de pestañas:** pestañas de tabla y de consulta (§4, §5), con «+» (nueva consulta), cerrar (×,
  Ctrl+W), reordenar y recordar las abiertas.
- **Pie:** el último aviso (p. ej. «Capa «consumidores» cargada · Conectada · Ver en el mapa»).
- **Panel acoplado:** pestañas en una fila compacta, sin barra lateral (Ctrl+K y el menú de la pestaña la
  sustituyen); ninguna acción desaparece, se compacta.

## 4. Pestaña de tabla (GD-WSP-003)
Se abre con **doble clic** en una tabla o vista (barra lateral, Recientes, ★ o Ctrl+K). Solo lectura en G9.
- **Datos:** grilla rápida por páginas (las filas se piden a DuckDB bajo demanda; nunca la tabla entera), con
  tipo bajo cada columna y número de fila.
  - **Orden:** clic en el encabezado (ascendente, descendente, sin orden); lo ejecuta DuckDB.
  - **Filtros en chips:** «+ Filtro» → columna, operador (=, ≠, >, <, contiene, empieza por, es nulo…) y valor;
    cada chip se quita con ×. Se combinan con Y. **«Ver SQL»** muestra la consulta equivalente y la abre en una
    pestaña de consulta.
  - **Buscar** en la tabla (texto en las columnas de texto).
  - **Paginación:** 100 filas por página, sin selector (propietario, 2026-11-05): «1–100 de 48 312», ‹ ›; el
    total se cuenta aparte, sin bloquear.
  - **Detalle de fila** (panel derecho, plegable): cada campo con su tipo y su valor completo; la geometría
    resumida (tipo, SRC, número de vértices); copiar valor.
- **Estructura:** columnas (nombre, tipo, nulos, clave), filas, tamaño aproximado y la sentencia `CREATE`.
- **Acciones:** «Cargar en QGIS ▾» (§7), «Ver en el mapa» tras cargar, «Exportar ▾» (CSV, Parquet), «Copiar»
  (Ctrl+C sobre la selección).

## 5. Pestaña de consulta (GD-WSP-004)
- Editor SQL de QGIS con resaltado, números de línea y el autocompletado de G6 (bases, tablas, columnas,
  funciones). Base de la consulta en un desplegable.
- **Ejecutar** la sentencia bajo el cursor o la selección (Ctrl+Intro) y **Todo** (Ctrl+Mayús+Intro);
  **Cancelar**.
- **Resultado** debajo (una pestaña por sentencia con tabla; sin pestañas si es una), con «N filas · X ms»;
  **Mensajes** con el registro (OK, errores con línea y columna).
- «Exportar ▾» y «Cargar en QGIS ▾» del resultado.
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
- **«Copia»:** independiente de DuckDB. Por dentro, la Copia rápida (GeoPackage en `/vsimem`, ADR-0012); la
  Copia en memoria solo como **respaldo automático** si GDAL no permite la rápida. El usuario nunca elige entre
  las dos.
- **Al guardar el proyecto** con alguna «Copia» (decisión del propietario, 2026-11-05, tras el spike E0b: ninguna
  copia sobrevive a reabrir el proyecto), GeoDuck lo avisa y ofrece en un clic **«Guardar las copias junto al
  proyecto»**: un GeoPackage al lado del `.qgz`, y cada capa pasa a leer ese archivo y sobrevive. Con «No, gracias»,
  al reabrir la capa se muestra «no disponible» con su motivo, nunca rota sin explicación.
- **«Conectada»:** en vivo, editable en DuckDB (ADR-0012).
Reproyectar, separar por tipo y SRC siguen igual (spatial-spec), escondidos hasta que aplican.

## 8. Recientes y favoritos (GD-WSP-007)
- **Recientes:** las tablas y consultas abiertas hace poco (máximo 10), en esta y en sesiones anteriores.
- **★ Favoritos:** el usuario marca tablas y consultas; aparecen arriba.
- Se recuerdan entre reinicios de QGIS (propietario, 2026-11-05). Se guardan solo **nombres** (base, esquema, objeto; ruta del `.sql`) en `QgsSettings`, nunca datos. Si un
  objeto ya no existe, se muestra atenuado con su motivo.

## 9. Enviar a DuckDB (GD-WSP-008; qgis-import-spec)
El diálogo de G8 rehecho con el sistema de diseño, mismo comportamiento. Ctrl+K → «Enviar capa de QGIS a
DuckDB…». «Reproyectar a…» sigue siendo global para todo el envío (decisión, 2026-11-05).

**Arrastrar, en los dos sentidos** (propietario, 2026-11-06; E5). Lo mínimo: se pregunta solo lo que falta.
- **QGIS → DuckDB:** soltar una o varias capas del panel de capas en una base de la barra lateral (en el panel
  acoplado, en cualquier parte: la base actual). Cada tabla guarda el SRC de su capa. Simplificaciones
  (propietario, 2026-11-06: «Tú decide»):
  1. **Sin diálogo si no hay nada que decidir:** si todas serán tablas nuevas, sin selección y con SRC, se
     envían directamente y el pie avisa «N capas enviadas a db · Abrir · Deshacer». El diálogo (con la base y
     las capas elegidas) solo se abre si hay algo que decidir: una tabla que ya existe, una capa que no se
     puede, una selección o el SRC.
  2. **Diálogo más limpio:** sin la columna «Qué pasará» si todo es una tabla nueva; «Reproyectar a…» y «Vista
     en vez de copia», plegados bajo «Más opciones».
  3. **Dónde se suelta, claro:** la base bajo el cursor se resalta con un borde de acento y el pie dice
     «Suelta para enviar N capas a «db»»; en un espacio vacío o en la cabecera, la base actual.
  4. **Progreso en el pie:** una barra fina y «Cancelar»; sin otra ventana.
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

Se retiran con la ventana «Cargar en QGIS…» de G4 sus opciones avanzadas: «Reproyectar a…» al cargar, usar
una columna WKB o de texto como geometría y «Separar por tipo» en una Conectada (cargar en un clic, §7). Las
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
