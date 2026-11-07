# Prueba manual en Windows · G9 Workspace Pro (con el envío de G8)

**Qué es.** Un recorrido guiado de lo que la CI (Linux, sin pantalla) no puede ver: la interfaz nueva en Windows
real, con su escala de pantalla, tema, monitores, rutas con acentos, el arrastre entre QGIS y GeoDuck y el
menú de capa de QGIS. Las funciones están probadas en la CI (`docs/g9/acceptance.md`). Incluye la prueba de
G8 (enviar capas a DuckDB), que quedó para G9 y ahora se hace con la interfaz nueva.
**Reemplaza** a `workspace.md` (G5), `sql-professional.md` (G6), `notebook.md` (G7) y a la parte de interfaz de
`send-to-duckdb.md` (G8): esa interfaz se retiró en G9. **No sustituye** a [`windows.md`](windows.md) (#10).
Duración aproximada: 45–60 minutos.

**Celda mínima:** Windows 10 u 11, QGIS 3.34.x LTR con DuckDB 2.0.0. Si hay tiempo, repetir 2, 4 y 7 en
QGIS 4.2 (Qt 6). **Referencia visual:** las capturas de `docs/evidence/g9/` (aprobadas).

Anote cada paso como **OK** o **Falla** (con captura) en `docs/evidence/g9/windows/<celda>/README.md`.

## 1. Preparación

1. DuckDB y PyArrow instalados como en [`windows.md`](windows.md) §1.
2. Instale el ZIP del commit que se prueba (Complementos → Instalar a partir de ZIP). Anote el commit.
3. **Actualizar desde 0.9.0a1 (AT-WSP-011):** si tenía 0.9.0a1 con un cuaderno guardado abierto y GeoDuck
   acoplado a la izquierda, **no borre nada** antes de instalar: el paso 2a lo comprueba. Si no, para empezar
   como en una instalación limpia, en la consola de Python de QGIS:
   `from qgis.core import QgsSettings; QgsSettings().remove("geoduck/pro")`
4. Cree una carpeta de prueba con acentos, por ejemplo `C:\geoduck-g9\pruebas ñá\`.
5. En QGIS cargue tres capas: un **GeoPackage** de polígonos en EPSG:32719 (unos cientos de entidades), un
   **Shapefile** de líneas y un **CSV** sin geometría.
6. Reinicie QGIS.

## 2. Abrir, actualizar e iniciar (AT-WSP-002, 010, 011)

| # | Haga | Debe pasar |
|---|---|---|
| 2a | (Solo si venía de 0.9.0a1) Pulse el botón de GeoDuck | Abre como **panel a la izquierda**, como lo tenía; el cuaderno que estaba abierto aparece como una **pestaña de consulta** con su SQL |
| 2b | Pulse el botón de GeoDuck (instalación limpia) | Se abre la **ventana propia**, encima de QGIS; todo en gris salvo «Iniciar DuckDB», «Abrir base…», «Crear base…», «Diagnóstico» y «Acerca de» |
| 2c | «Iniciar DuckDB» | Arriba de la barra lateral: «DuckDB · Lista» con su versión; la barra lateral y Ctrl+K se activan |
| 2d | «Nueva consulta»; escriba `SELECT 42 AS n;` y Ctrl+Intro | Resultado `42`, «1 fila · X ms» |
| 2e | «Acoplar a QGIS» (arriba a la derecha) | Panel con la **misma** consulta y su resultado; la sesión sigue «Lista» |
| 2f | En el panel, «Abrir en ventana» | Vuelve la ventana, con todo igual |
| 2g | Cierre la ventana con la X y vuelva a abrirla con el botón | La sesión sigue «Lista» y las pestañas siguen ahí |
| 2h | Deje GeoDuck como panel y reinicie QGIS | Abre como panel (el modo se recuerda); recientes y ★ vuelven |
| 2i | Ctrl+B | La barra lateral se pliega y se despliega; se recuerda al reiniciar |

## 3. Bases, tablas y consultas (AT-WSP-003, 004, 005, 006, 008)

| # | Haga | Debe pasar |
|---|---|---|
| 3a | «+» → «Crear base…» → `C:\geoduck-g9\pruebas ñá\prueba.duckdb` | Aparece «prueba» en «Bases» |
| 3b | En una consulta: `CREATE TABLE prueba.medidores AS SELECT range AS id, range * 1.5 AS kwh FROM range(1000000);` | Termina; la tabla aparece bajo «prueba» |
| 3c | Doble clic en `medidores` | La pestaña de tabla muestra la primera página **al instante**; «1–100 de 1 000 000» |
| 3d | Clic en la cabecera `kwh`; añada dos filtros (chips); busque; pase de página | Cada cosa responde sin congelar QGIS; «Ver SQL» abre la consulta equivalente |
| 3e | Elija una fila y abra el detalle; pase a «Estructura» | Valores completos; columnas, tipos, nulos y `CREATE` |
| 3f | Ctrl+K, escriba `medi` (sin acentos ni mayúsculas) e Intro | Abre la tabla; Esc cierra Ctrl+K |
| 3g | Marque la tabla con ★; reinicie QGIS | Vuelve en «★» y en «Recientes» |
| 3h | Guarde la consulta con Ctrl+S en la carpeta con acentos; ciérrela; Ctrl+O y ábrala | Vuelve con su texto |
| 3i | Escriba `BEGIN; CREATE TABLE u (x INTEGER PRIMARY KEY); INSERT INTO u VALUES (1), (1);` y ejecute | Aviso abajo a la derecha que **no se va solo**: «La transacción falló. «Revertir» descarta sus cambios…»; pulse «Revertir» y DuckDB vuelve a estar «Lista» |
| 3j | Ctrl+K › «Historial de ejecución» | Pestaña con cada sentencia (hora, ✓/✕, duración); «Error» filtra; doble clic abre una consulta nueva **sin ejecutarla** |

## 4. Cargar en QGIS (AT-WSP-007)

| # | Haga | Debe pasar |
|---|---|---|
| 4a | Cree una tabla con geometría: `CREATE TABLE prueba.pozos AS SELECT range AS id, ('POINT (' \|\| (-68 - range / 100) \|\| ' -16)')::GEOMETRY('OGC:CRS84') AS geom FROM range(500);` | Aparece en «prueba» |
| 4b | Ábrala → «Cargar en QGIS ▾» → «Copia» | La capa aparece en QGIS con su SRC y sin preguntas; aviso «Capa … cargada · Copia · 500 entidades · Origen … · Acceso …» con «Ver en el mapa» |
| 4c | «Ver en el mapa» | La capa queda elegida y el mapa hace zoom a ella; la ventana de GeoDuck se minimiza |
| 4d | «Cargar en QGIS ▾» → «Conectada» | Capa editable en DuckDB; edite un valor en QGIS y guárdelo: la pestaña de tabla lo muestra al recargar |
| 4e | «Cargar en QGIS ▾» → «Más opciones…» | Ventana corta: Copia / Conectada, «Reproyectar a…» solo en Copia, «Separar por tipo» solo en Conectada, cada una con su línea de ayuda y el resumen «Se cargará 1 capa · Copia». Con «Reproyectar a… EPSG:3857», la capa cae en su sitio |
| 4f | Guarde el proyecto (`.qgz`) en la carpeta con acentos | Aviso «1 capa es «Copia»…» → «Guardar las copias junto al proyecto»; se crea `<proyecto>_geoduck.gpkg` |
| 4g | Cierre y abra el proyecto | Las capas guardadas abren desde el GeoPackage; si eligió «No, gracias», un aviso dice cuáles quedaron vacías y por qué |
| 4h | Arrastre `pozos` (y otra tabla) desde la barra lateral **al mapa**; repita soltándolas en el **panel de capas** | Mini menú «2 tablas · ¿cómo cargarlas?» con Copia / Conectada donde soltó; Esc cancela sin cargar nada |

## 5. Enviar capas a DuckDB (G8 con la interfaz nueva; AT-WSP-009, AT-IMP-001..007)

| # | Haga | Debe pasar |
|---|---|---|
| 5a | Clic derecho sobre el GeoPackage en el panel de capas → «Enviar a DuckDB…» | Sin ventana: GeoDuck se muestra, una barra fina con «Cancelar» en el pie y, al terminar, «Capa «…» enviada a … · Abrir · Deshacer» |
| 5b | «Abrir» | La tabla, en una pestaña |
| 5c | Arrastre el Shapefile y el CSV desde el panel de capas **sobre «prueba»** en la barra lateral | La base se resalta con un borde y el pie dice «Suelta para enviar 2 capa(s) a «prueba»»; se envían a «prueba» sin ventana |
| 5d | Arrastre otra vez el GeoPackage sobre «prueba» | Ahora **sí** se abre la ventana (la tabla ya existe): «Ya existe: no se enviará»; elija «Reemplazar» o «Otro nombre» |
| 5e | Seleccione unas entidades en el mapa y arrastre la capa | Se abre la ventana con «Solo las entidades seleccionadas (N)» |
| 5f | «+» → «Enviar capas de QGIS a DuckDB…» | La ventana con todas las capas del proyecto; el ráster, en gris con su motivo; «Más opciones» pliega «Reproyectar a…» |
| 5g | Envíe una capa de 1 millón de entidades y pulse «Cancelar» en el pie a mitad | «Envío cancelado: no cambió nada en DuckDB.»; la tabla no existe |
| 5h | Tras un envío de una tabla nueva, «Deshacer» | «Deshecho: …»; la tabla desaparece de la barra lateral |
| 5i | Cierre DuckDB («Cerrar DuckDB») y repita 5a | El pie dice «Inicia DuckDB para enviar capas.» |
| 5j | Con DuckDB 1.5.x, envíe a una base **nueva** en archivo | La ventana se abre: esa base no guarda el SRC; «Enviar sin SRC» aparece y nada se envía hasta marcarlo (F-120) |

## 6. Pantalla, tema, monitores y teclado (AT-WSP-001, 010)

Windows: Configuración → Pantalla → Escala. Reinicie QGIS después de cada cambio.

| # | Haga | Debe pasar |
|---|---|---|
| 6a | Escala **125 %** y **150 %** | Textos nítidos; nada cortado ni superpuesto en la ventana, el panel, el editor, Ctrl+K y las ventanas pequeñas (abrir base, enviar, más opciones, SRC, guardar copias) |
| 6b | QGIS → Opciones → General → Tema: **Night Mapping**; reinicie | GeoDuck en su variante oscura (también el editor SQL); todo se lee. El resto de QGIS **no cambia** por GeoDuck (ADR-0011) |
| 6c | Vuelva al tema por defecto | GeoDuck vuelve a la variante clara |
| 6d | Panel muy estrecho (arrastre su borde) | Nada se corta; todas las acciones siguen a mano (cabecera del panel y Ctrl+K) |
| 6e | Con dos monitores: ventana en el segundo, cierre QGIS, desconecte ese monitor y abra QGIS | La ventana aparece completa en el monitor que queda |
| 6f | Solo teclado: Tab por la ventana; Ctrl+K, Ctrl+O, Ctrl+S, Ctrl+W, Ctrl+B, Ctrl+Intro | Todo se alcanza; los atajos solo actúan con el foco dentro de GeoDuck (Ctrl+Intro en la consola de Python de QGIS **no** ejecuta en GeoDuck) |

## 7. Idioma y entorno

| # | Haga | Debe pasar |
|---|---|---|
| 7a | QGIS en inglés, reinicie | «Start DuckDB», «Send to DuckDB…», «Load into QGIS», «More options…» |
| 7b | QGIS en español, reinicie | «Iniciar DuckDB», «Enviar a DuckDB…», «Cargar en QGIS», «Más opciones…» |
| 7c | (Opcional, en un QGIS sin DuckDB) Abra GeoDuck | «El entorno no está listo para GeoDuck» · «Falta: DuckDB…» con «Diagnóstico»; «Iniciar DuckDB» en gris |
| 7d | «Acerca de GeoDuck…» (menú Base de datos › GeoDuck) | Versión 0.10.0a1, licencia, enlaces y componentes; sin correos |

## 8. Resultado

Celda (Windows · QGIS · DuckDB) · fecha · commit · pasos OK / Falla, con el diagnóstico del entorno copiado y
capturas de la ventana y el panel. Una falla abre un hallazgo con ID nuevo y su captura; no se corrige en
silencio y no bloquea el cierre de G9 salvo que lo decida el propietario.
