# Rendimiento

GeoDuck está hecho para tablas grandes. Algunas ideas para que vaya aún mejor.

- **Mira sin copiar.** Abrir una tabla o un resultado solo lee las filas visibles. No hace falta `LIMIT`.
- **Conectada para tablas grandes.** La capa lee solo lo que se ve en el mapa.
- **Índice espacial** en tablas de millones de geometrías: el mapa se dibuja más rápido al acercarte. Ver
  [Índice espacial](spatial-index.md).
- **Parquet** es el formato más rápido para guardar y volver a leer datos.
- **Filtra en SQL**, antes de cargar en QGIS: llega menos y antes.
- **Cancela sin miedo.** «Cancelar» detiene cargas, consultas y exportaciones sin dejar nada a medias.
- **Memoria.** Si una consulta muy grande no cabe en memoria, el motor usa un espacio temporal en disco. Si
  aun así falta, ver [Sin memoria](errors.md#memory).

## Números medidos {#measured}

Con **1 000 000 de filas** (puntos), QGIS 4.2 y el motor 2.0, en la CI (Linux, 4 núcleos). La mediana de
7 corridas; en su equipo los números serán otros.

| Operación | Mediana |
|---|---|
| Primera página de una consulta | 33 ms |
| Agregado (GROUP BY) | 6 ms |
| Cargar en QGIS · Conectada | 91 ms |
| Cargar en QGIS · Copia | 2 046 ms |
| Importar un Parquet | 50 ms |
| Enviar una capa de QGIS | 3 854 ms |
| Exportar a Parquet | 151 ms |
| Exportar a CSV | 287 ms |
| Cancelar una exportación | 40 ms |
