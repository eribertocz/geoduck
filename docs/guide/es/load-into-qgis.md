# Cargar en QGIS

<span class="gd-time">3 minutos</span>

## La forma rápida

Arrastra una o varias tablas del explorador al mapa (o al panel de capas) y elige **Copia** o **Conectada**.
También: clic derecho › **Cargar en QGIS ▸**, o el icono de la barra «Resultado» de una consulta.

Ver [Copia y Conectada](concepts.md#copia-y-conectada) para elegir.

## Con opciones

Clic derecho › Cargar en QGIS › **Más opciones…**: el nombre de la capa, el modo y qué columnas de geometría
cargar (una capa por columna).

## Sistema de referencia

GeoDuck toma el SRC de la columna de geometría (`GEOMETRY('EPSG:4326')`). Si falta, te pide uno, una sola vez
para todas las tablas.

## Al guardar el proyecto

- **Copia:** GeoDuck ofrece **Guardar las copias junto al proyecto** (un GeoPackage al lado del `.qgz`). Si no,
  al reabrir el proyecto la capa sale «no disponible» con su motivo.
- **Conectada a una base de archivo:** vuelve sola al abrir el proyecto.
- **Conectada a una base en memoria:** GeoDuck avisa que no podrá reabrirla y ofrece **Guardar la base como
  archivo**.
