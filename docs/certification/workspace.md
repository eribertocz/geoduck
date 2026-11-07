# Prueba manual de G5 (Workspace UX) en Windows

> **Retirada en G9.** La interfaz de G5 (Workspace UX) se retiró en 0.10.0a1. La prueba manual vigente es
> [`workspace-pro.md`](workspace-pro.md). Se conserva como registro de lo probado en su momento.

**Qué es.** Un recorrido guiado de lo que la CI no puede ver: la ventana y el panel en Windows real, con
monitores, escala de pantalla (DPI) y tema. Las funciones están probadas en la CI (`docs/g5/acceptance.md`).
**No sustituye** a la certificación de [`windows.md`](windows.md) (#10). Duración aproximada: 30–40 minutos.

**Celda mínima:** QGIS 3.34.x LTR con DuckDB 2.0.0. Si hay tiempo, repetir 1–4 en QGIS 4.2.
**Referencia visual:** `docs/g5/maqueta/` (aprobada) y `docs/g5/capturas/` (lo que generó la CI).

## 1. Preparación

1. Instale el ZIP del commit que se prueba (Complementos → Instalar desde ZIP). Anote el commit.
2. Para empezar como en una instalación limpia, en la consola de Python de QGIS:
   `from qgis.core import QgsSettings; QgsSettings().remove("geoduck/workspace")`
3. Reinicie QGIS.

## 2. Ventana y panel (AT-UX-002, 003, 011)

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | Pulse el botón de GeoDuck de la barra de herramientas | Se abre la **ventana propia**, encima de QGIS, sin entrada propia en la barra de tareas de Windows |
| b | «Iniciar sesión» (pie de «Bases de datos»); escriba `SELECT 42 AS n;` y «▶ Ejecutar» | Resultado «… (1 fila)»; el punto de la barra de sesión, verde |
| c | Minimice QGIS y vuelva a abrirlo | La ventana de GeoDuck se minimiza y vuelve con QGIS |
| d | «Acoplar a QGIS» | Panel a la derecha con pestañas Explorador / SQL / Registro; el mismo SQL y el mismo resultado |
| e | «Abrir en ventana» (barra de título del panel) | Vuelve la ventana, con todo igual |
| f | Cierre la ventana con la X; pulse el botón de GeoDuck | La ventana vuelve; la sesión sigue «Lista» |
| g | Acople, cierre el panel con su X y vuelva a abrirlo con el botón | Igual que f |
| h | Deje GeoDuck como panel y reinicie QGIS; pulse el botón | Abre como panel (el modo se recuerda) |

## 3. Monitores y tamaño (AT-UX-010)

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | En la ventana, cambie su tamaño, ancho del explorador y alto del editor; reinicie QGIS | Se restauran |
| b | Con dos monitores: mueva la ventana al segundo, cierre QGIS, desconecte ese monitor y abra QGIS | La ventana aparece en el monitor que queda, completa y centrada (nunca fuera de pantalla) |
| c | Mueva el panel a la izquierda; reinicie QGIS en modo panel | El panel vuelve a la izquierda |

## 4. Escala de pantalla y tema (AT-UX-013, AT-UX-001)

Windows: Configuración → Pantalla → Escala. Reinicie QGIS después de cada cambio.

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| a | Escala **125 %** | Textos nítidos; nada cortado ni superpuesto en la ventana, el panel ni los diálogos «Cargar en QGIS», «Abrir base DuckDB» y «Acerca de» |
| b | Escala **150 %** | Igual que a |
| c | Panel muy estrecho (arrastre su borde) | Los atajos de los botones del editor desaparecen, pero todas las acciones siguen a la vista; nada se corta |
| d | QGIS → Configuración → Opciones → General → Tema de la interfaz: **Night Mapping**; reinicie | Se espera la variante oscura de GeoDuck (fondos oscuros, verde y azul más claros) y que todo se lea. **Por verificar:** GeoDuck elige la variante por la paleta de Qt; si el tema de QGIS no la cambia y GeoDuck queda claro, anótelo como hallazgo. El resto de QGIS no cambia por GeoDuck |
| e | Vuelva al tema por defecto | GeoDuck vuelve a la variante clara |
| f | Solo teclado: Tab por la ventana; Ctrl+Intro en el editor; Ctrl+Intro en la consola de Python de QGIS | Todas las acciones se alcanzan con Tab; Ctrl+Intro ejecuta en el editor y **no** hace nada en la consola de QGIS |

## 5. Comparación con la maqueta

Abra `docs/g5/maqueta/ventana.png` y `panel.png` junto a GeoDuck. Anote cualquier diferencia que no esté en
`docs/g5/maqueta/inventario.md` §5 (decisiones ya tomadas).

## 6. Evidencia

Cree `docs/evidence/g5/windows/<celda>/README.md` con el formato de la evidencia de G3: fecha, commit, el
diagnóstico del entorno copiado, una tabla con cada paso (2a … 4f) y «Correcto» o lo que pasó, y capturas de
la ventana y el panel. Si algo no coincide, un hallazgo con ID nuevo; no se corrige en silencio.
