# Prueba manual en Windows · G8 Enviar capas de QGIS a DuckDB

> **G9:** la interfaz de este envío (barra de mensajes de QGIS, «Importar capas de QGIS…») cambió en 0.10.0a1.
> La prueba vigente, con la interfaz nueva, está en [`workspace-pro.md`](workspace-pro.md) §5.

Complementa la CI (Linux) para lo que solo se ve en Windows: el menú de capa de QGIS, la barra de mensajes,
el diálogo, archivos con rutas de Windows, idioma y aspecto. Unos 20 minutos. Requisitos: Windows 10/11,
QGIS 3.34+ (o 4.x), DuckDB y PyArrow como en `docs/certification/workspace.md` §1. Instale el ZIP del PR
(Complementos → Instalar a partir de ZIP).

Anote cada paso como **OK** o **Falla** (con captura) en `docs/evidence/g8/windows/<celda>/README.md`.

## 1. Preparación

1. Cree una carpeta de prueba con acentos, por ejemplo `C:\geoduck-g8\pruebas ñá\`.
2. En QGIS, cargue tres capas:
   - un **GeoPackage** con polígonos en un SRC proyectado (por ejemplo EPSG:32719) y unos cientos de entidades;
   - un **Shapefile** de líneas;
   - un **CSV** sin geometría (Capa → Añadir capa → Texto delimitado).
3. Abra GeoDuck → «Iniciar sesión».

## 2. Puntos de entrada (AT-IMP-001)

| # | Haga | Debe pasar |
|---|---|---|
| 2a | Clic derecho sobre la capa GeoPackage en el panel de capas | Aparece «Enviar a DuckDB…» |
| 2b | Seleccione las tres capas (Ctrl+clic) → clic derecho → «Enviar a DuckDB…» | El diálogo muestra las tres, marcadas, cada una con origen, entidades, geometría y SRC |
| 2c | Cancele. En GeoDuck, «+» de «Bases de datos» → «Importar capas de QGIS…» | Mismo diálogo con todas las capas del proyecto; marcadas solo las elegidas en el panel |
| 2d | Añada una capa ráster al proyecto y repita 2c | El ráster aparece gris, con «solo se pueden enviar capas vectoriales» |
| 2e | Cierre la sesión de GeoDuck y repita 2a | La barra de QGIS dice «Inicia una sesión de GeoDuck para enviar capas a DuckDB.» |

## 3. Diálogo y envío (AT-IMP-002, 003)

| # | Haga | Debe pasar |
|---|---|---|
| 3a | Inicie la sesión. Envíe la capa GeoPackage con los valores por defecto (solo «Enviar», o Ctrl+Intro) | Progreso con «Cancelar» en la barra de QGIS; al terminar, «Enviado a DuckDB: … · N filas» con «Abrir» y «Deshacer» |
| 3b | Pulse «Abrir» | GeoDuck se muestra con la tabla seleccionada en el explorador |
| 3c | Vuelva a enviar la misma capa | «Ya existe: no se enviará» y «Enviar» desactivado. Elija «Reemplazar» y envíe: el resumen dice que no se puede deshacer |
| 3d | Envíe de nuevo y elija «Añadir filas» | La tabla tiene el doble de filas |
| 3e | Elija «Otro nombre» | El nombre pasa a `…_2` con el foco para editarlo |
| 3f | Seleccione unas entidades de la capa en el mapa y envíela con «Solo las entidades seleccionadas (N)» | Solo esas filas |
| 3g | Capa → Filtrar… (por ejemplo, la mitad) y envíela | La fila dice «con filtro»; llegan solo las filtradas |
| 3h | Envíe con «Reproyectar a…» → EPSG:4326 | El resumen dice «Reproyectado a EPSG:4326 con QGIS/PROJ»; cargue la tabla en QGIS: cae en su sitio sobre la capa original |
| 3i | Envíe la capa CSV a «Tabla temporal (solo esta sesión)» | Aparece en «Temporales» del explorador |
| 3j | Tras un envío de una tabla nueva, pulse «Deshacer» | «Deshecho: …»; la tabla desaparece del explorador |

## 4. Bases en archivo y SRC (AT-IMP-007)

| # | Haga | Debe pasar |
|---|---|---|
| 4a | «+» → «Crear nueva…» → `C:\geoduck-g8\pruebas ñá\destino.duckdb`; envíe el GeoPackage a esa base | La tabla está en `destino`; cierre y abra QGIS, adjunte el archivo y cargue la tabla: mismo SRC |
| 4b | Con DuckDB 1.5.x, adjunte un archivo creado por DuckDB 1.5 sin `STORAGE_VERSION` y elíjalo como destino | «Esta base usa un formato de archivo antiguo…»; «Enviar sin SRC» aparece; nada se envía hasta marcarlo |
| 4c | Una capa con SRC personalizado (Proyecto → Propiedades → SRC → Personalizado) | Aviso «SRC personalizado: se guarda con su definición completa (PROJJSON)»; vuelve a QGIS con el mismo SRC |

## 5. Grandes, cancelar y GeoParquet

| # | Haga | Debe pasar |
|---|---|---|
| 5a | Envíe una capa de 1 millón de entidades o más | Resumen con «Capas grandes: puede tardar unos N minutos» si se estima más de un minuto; QGIS sigue respondiendo mientras envía |
| 5b | Repita 5a y pulse «Cancelar» a mitad | «Envío cancelado: no cambió nada en DuckDB.»; la tabla no existe |
| 5c | Con QGIS 3.44+ (GDAL con Parquet), cargue un GeoParquet y envíelo con «Vista en vez de copia» | «Vista nueva»; el explorador la muestra en «Vistas»; cargue después otra tabla de DuckDB a QGIS: funciona y conserva su SRC (F-121) |

## 6. Idioma y aspecto

| # | Haga | Debe pasar |
|---|---|---|
| 6a | QGIS en inglés, reinicie | «Send to DuckDB…», «Import QGIS layers…», «Do not send», «Send» |
| 6b | QGIS en español, reinicie | «Enviar a DuckDB…», «Importar capas de QGIS…», «No enviar», «Enviar» |
| 6c | Tema oscuro de QGIS | Diálogo legible: el detalle de cada capa en gris, los «No se puede» en rojo |
| 6d | Recorra el diálogo con Tab y marque/desmarque una capa con Espacio | Cada control recibe el foco; Esc cancela; Ctrl+Intro envía |
| 6e | Compare con `docs/evidence/g8/ui/` | Misma disposición |

## 7. Resultado

Celda (Windows · QGIS · DuckDB) · fecha · pasos OK / Falla. Una falla abre una issue con la captura; no
bloquea el cierre de G8 salvo que lo decida el propietario.
