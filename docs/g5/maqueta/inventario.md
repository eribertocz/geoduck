# Inventario de la maqueta de G5 — componente por componente

**Estado:** aprobado por el propietario (2026-11-02) e implementado en la entrega de pulido visual (E4b), con
las decisiones de la §5, tomadas durante su revisión.
**Referencia:** `ventana.png` y `panel.png` (este directorio), `README.md` (diferencias ya decididas) y
ui-ux-spec §8. **Comparado con:** `main` + PR #81 (G5 E1–E4).

Cada fila dice **dónde** va el componente, **qué texto** lleva, **cómo se comporta** y **qué hay hoy**. Las
filas marcadas **Cambia** son el trabajo de la entrega de pulido. Las marcadas **Pregunta** necesitan una
decisión del propietario (§4).

Los colores y medidas de cada componente son los de la §0.

## 0. Identidad visual de GeoDuck (paleta corporativa)

**Decisión del propietario (2026-11-02):** aspecto y colores casi idénticos a la maqueta, con una paleta
corporativa moderna y profesional. Los valores del tema claro se **midieron en los píxeles** de `ventana.png` y
`panel.png` (colores más frecuentes de cada componente), no se estimaron. La variante oscura mantiene los
mismos tonos con el contraste adecuado para el tema oscuro de QGIS.

### 0.1 Colores

| Rol | Uso | Claro (maqueta) | Oscuro |
|---|---|---|---|
| **Verde GeoDuck** (primario) | «▶ Ejecutar», «Iniciar sesión», punto «Lista», «OK», filtro elegido | `#2D7A3E` | `#3FA45B` |
| **Azul QGIS** (acción hacia QGIS) | «Cargar en QGIS ▾», enlaces («Ver en el mapa», «Diagnóstico…») | `#1F5FA8` | `#4C8DDB` |
| Rojo error | Pestaña «Error · sentencia n», «Error», mensajes de error, «Revertir transacción» | `#B42318` | `#F06A5F` |
| Ámbar ocupado | Punto de sesión ejecutando o conectando | `#9A6700` | `#D4A72C` |
| Texto | Texto principal, nombres en negrita | `#1F2328` | `#E6EDF3` |
| Texto secundario | Detalles en gris, descripciones, atajos, versión | `#57606A` | `#9198A1` |
| Fondo de la ventana | Separación entre tarjetas | `#EEF0F2` | `#0D1117` |
| Tarjeta | Fondo de explorador, editor, resultados, registro | `#FFFFFF` | `#161B22` |
| Cabecera de tabla | Fila de cabeceras de resultados | `#F6F7F8` | `#1C2128` |
| Borde | Tarjetas, botones con borde, buscador | `#D0D4D9` | `#30363D` |
| Borde suave | Líneas entre filas, separadores | `#E3E6E9` | `#262C34` |
| Selección | Objeto elegido del árbol, entrada resaltada del menú | `#E3EDF8` | `#1F3550` |
| Filtro elegido | Fondo del botón de filtro activo del registro | `#EEF4FB` | `#18283B` |
| Éxito suave | Recuadro de la última carga en el panel (fondo / borde) | `#EEF6F0` / `#B7DCC0` | `#14261A` / `#2E5A3A` |
| Error suave | Recuadro de un error en el panel (fondo / borde) | `#FBF4F3` / `#E7B8B5` | `#2A1715` / `#6B2C27` |
| SQL: palabras clave | `SELECT`, `FROM`, `WHERE` en el editor | `#8250DF` | `#B392F0` |

GeoDuck usa la variante oscura cuando el tema de QGIS es oscuro (se detecta por la luminosidad del fondo de la
paleta de QGIS). Contraste mínimo de texto: 4,5:1 (WCAG AA) en ambas variantes.

### 0.2 Forma y tipografía

| Elemento | Valor (px lógicos) |
|---|---|
| Tipografía | La del sistema (Segoe UI en Windows): sin fuentes propias. Editor: monoespaciada de QGIS |
| Tamaños | Texto 13; títulos de tarjeta 14 negrita; detalles 12 |
| Tarjetas | Radio 8, borde 1, margen interior 12, separación entre tarjetas 12 |
| Botones | Alto 30, radio 6, margen horizontal 12; principal relleno de color con texto blanco; secundario blanco con borde |
| Filtros del registro | Píldora: alto 26, radio 13 |
| Iconos | Del tema de QGIS (mismo trazo que el resto de QGIS) |

### 0.3 Cómo se aplica (sin tocar QGIS, ADR-0011)

- Una hoja de estilo **solo para los widgets de GeoDuck** (por nombre de objeto), nunca `qApp.setStyleSheet` ni
  la configuración de QGIS. El resto de QGIS no cambia de aspecto.
- Los colores del editor SQL se fijan **en el analizador de sintaxis del editor de GeoDuck**
  (`lexer().setColor(...)`), no en el esquema de colores global de QGIS. Comprobado en QGIS 3.34 y 4.2: otro
  editor de QGIS conserva sus colores.
- La paleta vive en un único módulo (`geoduck/ui/theme.py`) con las dos variantes.

## 1. Ventana propia (`ventana.png`)

### 1.1 Título de la ventana

| # | Componente | Dónde | Texto / aspecto | Hoy | |
|---|---|---|---|---|---|
| V1 | Título | Barra de título de Windows | Icono de GeoDuck + «GeoDuck» («— ventana» es la etiqueta de la maqueta, no del título) | «GeoDuck», sin icono | Cambia: añadir icono |

### 1.2 Barra de sesión (una sola fila, a todo el ancho, con línea inferior; sin recuadro)

| # | Componente | Dónde | Texto / aspecto | Hoy | |
|---|---|---|---|---|---|
| V2 | Punto de estado | Izquierda | ● verde con «Lista»; ámbar ocupada; rojo con fallo; gris sin sesión | No existe | Cambia |
| V3 | Título | Tras el punto | «Sesión DuckDB» en negrita | Igual, dentro de un recuadro | Cambia: sin recuadro |
| V4 | Detalle | Tras el título | Gris: «Lista · DuckDB 2.0.0 · en memoria» (estado · versión · «en memoria» o nombre del archivo raíz) | «Lista» y «DuckDB 2.0.0 · cancelación inmediata disponible» por separado | Cambia: una sola línea; la cancelación pasa a la ayuda |
| V5 | «Acoplar a QGIS» | Derecha, antes de «Cerrar sesión» | Botón con borde, icono de panel + texto | En una fila aparte, encima de la barra | Cambia: en esta fila |
| V6 | «Cerrar sesión» | Extremo derecho | Botón con borde | Igual | — |
| V7 | «Iniciar sesión» | En lugar de «Cerrar sesión», sin sesión | Botón principal (verde) | Existe, a la izquierda de «Cerrar sesión» | Cambia: mismo sitio que «Cerrar sesión» |
| V8 | «Revertir transacción» | Antes de «Cerrar sesión», solo con la transacción abortada | Botón con borde, texto en rojo | Existe | Cambia: estilo |
| V9 | Menú «⋯» | — | Se quita, junto con «Activar spatial…» (R2) | Existía, al final | Quitado |

### 1.3 Explorador (columna izquierda, tarjeta con bordes redondeados)

| # | Componente | Dónde | Texto / aspecto | Hoy | |
|---|---|---|---|---|---|
| V10 | Título | Arriba a la izquierda de la tarjeta | «Bases de datos» en negrita | Igual | — |
| V11 | «+» | Arriba a la derecha | Botón cuadrado con borde «+» → Abrir existente… / Crear nueva… | Icono verde de QGIS con flecha de menú | Cambia: botón cuadrado «+» sin flecha |
| V12 | Actualizar | A la derecha de «+» | Botón cuadrado con flecha circular | Icono de QGIS | Cambia: mismo estilo que «+» |
| V13 | Buscador | Bajo el título, a todo el ancho | Lupa a la izquierda + «Buscar bases, esquemas y tablas…» | Sin lupa | Cambia: lupa |
| V14 | Base | Árbol, nivel 1 | Nombre en **negrita** + « · raíz, en uso» / « · lectura y escritura» / « · solo lectura» en gris | Todo en el mismo estilo | Cambia: negrita + gris |
| V15 | Esquema | Nivel 2 | «main» | Igual | — |
| V16 | Grupos | Nivel 3 | «Tablas (n)», «Vistas (n)», «Tablas temporales (n)» | Igual | — |
| V17 | Objetos | Nivel 4 | Nombre; selección con fondo azul claro | Igual (selección del tema) | — |
| V18 | Desplegado inicial | — | Bases y «Tablas (n)» abiertos; «Vistas (n)» y «Tablas temporales (n)» cerrados | Todo abierto | Cambia |
| V19 | Ayuda al pie | Abajo de la tarjeta, separada por una línea | Gris: «Doble clic o clic derecho → Cargar en QGIS…» | Igual, sin línea | Cambia: línea |
| V20 | Menú de la base | Clic derecho sobre una base | «Desadjuntar» | Igual | — |

### 1.4 Editor (tarjeta arriba a la derecha)

| # | Componente | Dónde | Texto / aspecto | Hoy | |
|---|---|---|---|---|---|
| V21 | «Ejecutar» | Primero a la izquierda | Botón principal verde «▶ Ejecutar» + atajo en gris **«Ctrl+Mayús+Intro»** (sin F5, README) | Botón plano «Todo» | Cambia |
| V22 | «Sentencia» | Segundo | Botón con borde «Sentencia» + atajo en gris «Ctrl+Intro» | Botón plano | Cambia |
| V23 | «Selección» | Tercero | Botón con borde | Botón plano | Cambia |
| V24 | «Cancelar» | Cuarto | Botón con borde; gris si no hay nada que cancelar | Botón plano, tras un separador | Cambia |
| V25 | Filas | Derecha | «Filas» + desplegable «200» | Igual | — |
| V26 | Editor | Bajo los botones | Números de línea, resaltado SQL; **sin** título «Editor» | Con título «Editor» | Cambia: quitar el título |

### 1.5 Resultados (tarjeta en el centro a la derecha)

| # | Componente | Dónde | Texto / aspecto | Hoy | |
|---|---|---|---|---|---|
| V27 | Pestaña de resultado | Fila de pestañas, a la izquierda | Nombre en negrita + gris «(200 filas · hay más)» / «(12 filas)»; la activa, subrayada | «2 · Resultado» | Cambia |
| V28 | Pestaña de error | En la misma fila, en su orden | Rojo «Error · sentencia 3»; al abrirla, el mensaje completo y «Ir a la sentencia» | No existe (el error solo va al registro y al editor) | Cambia |
| V29 | «Cargar en QGIS ▾» | Derecha de la fila de pestañas; uno solo, para la pestaña activa | Botón principal azul, icono de capas | Un botón pequeño dentro de cada resultado | Cambia |
| V30 | Menú de modalidades | Bajo «Cargar en QGIS ▾» | Tres entradas en dos líneas: **nombre** + descripción gris. «Copia en memoria — Capa temporal de QGIS. Para resultados pequeños o medianos.» · «Copia rápida — GeoPackage en memoria. Ideal para resultados grandes.» · «Conectada — Lee DuckDB bajo demanda. Editable si viene de una tabla.» No disponible: gris + motivo | Una línea por entrada, textos de G3 | Cambia: dos líneas y textos de la maqueta |
| V31 | Cabeceras | Fila de cabecera | «# Consumidor», «Aa RazonSocial» (marca gris + nombre en negrita) | «# Consumidor» todo igual | Cambia: marca gris, nombre en negrita |
| V32 | Número de fila | Primera columna | 1, 2, 3… en gris, sin fondo | Cabecera vertical de Qt | Cambia: estilo |
| V33 | Geometría | Columna de geometría | «POINT · 21 B» (tipo · tamaño en bytes) | Igual (`describe_wkb`, desde G3) | — |
| V34 | Números | Columnas numéricas | Alineados a la derecha | Igual | — |
| V35 | «Vista previa» | — | **No aparece en la maqueta** | «Vista previa · n filas · hay más» encima de la tabla (exigido por sql-editor-spec §1) | **Pregunta P1** |
| V36 | «Posiblemente obsoleta» | — | **No aparece en la maqueta** | Etiqueta en cursiva (sql-editor-spec §5) | **Pregunta P1** |

### 1.6 Registro (tarjeta abajo a la derecha)

| # | Componente | Dónde | Texto / aspecto | Hoy | |
|---|---|---|---|---|---|
| V37 | Título y filtros | Fila superior | «Registro» en negrita + botones redondeados «Todo (3)» (elegido: borde verde), «OK (2)», «Error (1)» | Botones planos a la derecha | Cambia |
| V38 | Filas | Lista sin cabecera | Hora «10:24:11» · nombre · estado («OK» verde / «Error» rojo) · duración · mensaje (en rojo si es error) | Tabla con cabecera «Ejec.», «#», «Resultado», «Estado», «Duración», «Mensaje»; errores en negrita | Cambia; **Pregunta P2** (columnas «Ejec.» y «#») |
| V39 | Plegar | — | La zona se puede reducir con el divisor | Igual | — |

### 1.7 Barra de estado (una sola línea al pie, a todo el ancho)

| # | Componente | Dónde | Texto / aspecto | Hoy | |
|---|---|---|---|---|---|
| V40 | Última carga | Izquierda | «Capa «consumidores» cargada · Conectada · 1 141 829 entidades · Origen: … · Acceso: …» en una línea; si no cabe, se recorta y el texto completo va en la ayuda | Mensaje de varias líneas encima del pie | Cambia; **Pregunta P3** (avisos y errores largos) |
| V41 | «Ver en el mapa» | Tras la última carga | Enlace subrayado | Botón plano en el pie | Cambia |
| V42 | «Diagnóstico del entorno…» | Derecha | Enlace subrayado | Botón plano | Cambia |
| V43 | «Acerca de…» | Derecha | Enlace subrayado | Botón plano | Cambia |
| V44 | Versión | Extremo derecho | Gris «v0.x.y · Alpha» | Igual | — |

## 2. Panel acoplado (`panel.png`)

| # | Componente | Dónde | Texto / aspecto | Hoy | |
|---|---|---|---|---|---|
| P1 | Título del panel | Barra de título del panel | «GeoDuck» a la izquierda; «Abrir en ventana» (icono de ventana externa) a la derecha, **en la misma barra** | «Abrir en ventana» en una fila aparte, bajo el título | Cambia; **Pregunta P4** (botones flotar/cerrar) |
| P2 | Sesión | Fila bajo el título | ● + «Sesión» negrita + gris «Lista · DuckDB 2.0.0»; a la derecha, enlace «Cerrar» | Recuadro con «Sesión», «Lista», motor y botón «Cerrar» | Cambia |
| P3 | «⋯» / Iniciar / Revertir | Misma fila, a la derecha | Como V7–V9, en forma compacta | Existen | Cambia: estilo |
| P4 | Pestañas | Bajo la sesión | «Explorador», «SQL», «Registro (1)» con el número en rojo; la activa, subrayada | Pestañas del tema; número sin color | Cambia |
| P5 | Botones del editor | Pestaña SQL, arriba | «▶ Ejecutar» verde, «Sentencia», «Selección»; desplegable «200» a la derecha (sin «Filas») | Botones planos con icono | Cambia; **«Cancelar» se mantiene** (la maqueta no lo muestra, pero §8 prohíbe quitar acciones) |
| P6 | Editor | Bajo los botones | Igual que V26 | — | Cambia |
| P7 | Pestañas de resultado | Bajo el editor | Compactas: «Consumidores 200+», «Error · 3» | Como en la ventana | Cambia |
| P8 | Tabla | Bajo las pestañas | Igual que V31–V34 (cabecera en dos líneas si no cabe) | — | Cambia |
| P9 | «Cargar en QGIS ▾» | Abajo, **a todo el ancho** | Botón principal azul | Botón pequeño en cada resultado | Cambia |
| P10 | Última carga | Bajo «Cargar en QGIS ▾» | Recuadro verde suave: 1.ª línea en negrita «Capa … cargada · Conectada · n entidades»; 2.ª «Origen: … · Acceso: …» | Mensaje sin recuadro | Cambia (errores: recuadro rojo suave) |
| P11 | Pie | Abajo | Enlaces «Diagnóstico…», «Acerca de…»; versión a la derecha | Botones planos («Mapa», «Diagnóstico…», «Acerca de…») | Cambia; **Pregunta P5** («Ver en el mapa» en el panel) |

## 3. Lo que no cambia

Comportamiento de E1–E4 (alternancia, preferencias, búsqueda, filtros, «Ver en el mapa», minimizar),
atajos, accesibilidad (nombres accesibles y ayudas con el texto completo), panel estrecho (etiquetas cortas,
ninguna acción quitada) y todo lo de G0–G4. Los datos de la maqueta son de ejemplo.

## 4. Preguntas para el propietario

| | Pregunta | Propuesta |
|---|---|---|
| P1 | sql-editor-spec exige que cada resultado esté «siempre visualmente etiquetado Vista previa» y que se marque «Posiblemente obsoleta». La maqueta no lo muestra | Mantener una línea pequeña y gris bajo las pestañas: «Vista previa · 200 filas · hay más» y, si aplica, «Posiblemente obsoleta» en cursiva. Ocupa una línea |
| P2 | El registro de la maqueta no tiene «Ejec.» (número de ejecución) ni «#» (número de sentencia) | Quitar las columnas; el número de sentencia va en el nombre si no hay título («Sentencia 3», como en la maqueta). La ejecución, en la ayuda de la fila |
| P3 | Una carga con avisos (p. ej. «Sin SRC asignado») o un error largo no cabe en una línea | En la ventana: una línea recortada, con el texto completo en la ayuda; los avisos y errores también van al registro. En el panel: el recuadro (P10) muestra todo |
| P4 | Poner «Abrir en ventana» en la barra de título del panel obliga a dibujar esa barra; los botones flotar/cerrar de QGIS se pierden | Dibujar la barra con «GeoDuck», «Abrir en ventana» y una X que oculta el panel (sin flotar) |
| P5 | La maqueta del panel no muestra «Ver en el mapa» (en el panel el mapa ya está a la vista) | Mantenerlo como enlace en el pie del panel, junto a «Diagnóstico…» |

## 5. Decisiones del propietario durante la revisión (2026-11-02)

| | Decisión | Afecta a |
|---|---|---|
| R1 | Aprobadas las propuestas P1–P5; libertad para quitar lo que sobra y añadir lo que falta («menos es más») | Todo |
| R2 | **Sin «Activar spatial…»**: el usuario escribe `INSTALL spatial; LOAD spatial;` en el editor. Se quita el menú «⋯» | V9, P3; spatial-spec §10; ui-ux-spec §8 |
| R3 | **«Iniciar sesión» / «Cerrar sesión» al pie de «Bases de datos»** (ventana y panel); el texto se mantiene «Cerrar sesión» | V6, V7, P2 |
| R4 | «Doble clic o clic derecho → Cargar en QGIS…» pasa a la **ayuda de cada tabla y vista** del árbol | V19 |
| R5 | Diálogo «Abrir / Crear base DuckDB»: casilla **«Solo lectura»** marcada por defecto, con una línea que explica la diferencia (DuckDB 2.0: un solo proceso escribe; varios pueden leer); etiqueta **«Alias»** con el alias por defecto a la vista; «Crear» sin fila de acceso; avisos de archivo inexistente o existente antes de aceptar | Diálogo de G1 |

### Otras decisiones de diseño (E4b)

- «Cargar en QGIS ▾»: el clic abre el diálogo de G4 con la última modalidad; la flecha, el menú en dos
  líneas. Uno solo, para la pestaña activa.
- Pestaña de error «Error · sentencia n» con el mensaje completo y «Ir a la sentencia».
- La línea bajo las pestañas dice solo «Vista previa» (y, si aplica, «Posiblemente obsoleta»): el número de
  filas ya está en la pestaña.
- En el registro, la hora y la ejecución/sentencia quedan en la ayuda de la hora (P2).
- **Hallazgo corregido:** cargar en QGIS una sentencia terminada en `;` (o seguida de un comentario) daba
  «Parser Error» desde G3. `load_sql` quita del final el `;` y las líneas de comentario antes de envolverla.
