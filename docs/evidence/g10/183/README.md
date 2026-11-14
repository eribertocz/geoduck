# #183 · Estado «no disponible» nativo de QGIS (spike)

**Fecha:** 2026-11-14. **Versiones:** QGIS 3.34.6, 3.40.3, 3.44.14 y 4.2.3 (CI, `workflow_dispatch` sobre la
rama `g10/183-spike`) y 3.34 / 3.42 locales.

## Qué se midió

Un proveedor de Python mínimo cuya validez depende de una bandera; `QgsVectorLayer.setDataSource` con la
misma URI vuelve a crear el proveedor.

| Comprobación | Resultado en las 4 versiones |
|---|---|
| Proveedor inválido → la capa queda inválida | ✓ |
| Sigue en el proyecto y en el árbol, con su nombre, estilo y SRC | ✓ |
| No devuelve entidades | ✓ |
| Proveedor válido otra vez → la capa vuelve, con sus entidades y su estilo | ✓ |
| Proyecto guardado y reabierto con el proveedor inválido: la capa se conserva inválida y con estilo | ✓ |
| Después, `setDataSource` la vuelve válida | ✓ |

## Límites de QGIS (aceptados por el propietario, 2026-11-14)

1. El ⚠ del panel de capas (`QgsLayerTreeViewBadLayerIndicatorProvider`) tiene texto fijo y su clic abre
   «Cambiar fuente de datos». El texto de GeoDuck va en la barra de mensajes y en el clic derecho
   «Abrir la base «…»».
2. Al abrir un proyecto con capas inválidas, QGIS muestra «Gestionar capas no disponibles». GeoDuck abre las
   bases mientras QGIS lee el proyecto (desde el proveedor), así las capas llegan válidas; la ventana de QGIS
   solo aparece si falta un archivo.
