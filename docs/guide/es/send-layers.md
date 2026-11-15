# Enviar capas de QGIS a GeoDuck

<span class="gd-time">3 minutos</span>

Lleva capas vectoriales del proyecto a una base, como tablas, para consultarlas con SQL.

## Cómo empezar

- **Arrastra** capas del panel de capas de QGIS sobre una base del explorador.
- En QGIS, clic derecho en las capas › **GeoDuck › Enviar a GeoDuck…**
- «+» › **Añadir capas de QGIS a GeoDuck…**

## El diálogo

1. **Destino:** la base y el esquema (o «Tabla temporal», solo para esta sesión).
2. **Nombres:** cada capa ya trae un nombre de tabla. Doble clic (o F2) para cambiarlo. Si ya existe, GeoDuck
   propone otro (`lecturas_2`), o puedes reemplazar o añadir filas.
3. **Enviar N capas.**

La línea de tiempo muestra cada capa. Las que terminan quedan aunque canceles las demás. Al final, **Deshacer**
borra las tablas nuevas.

!!! note
    Las capas ráster no se envían: aparecen en gris con el motivo.
