# Errores frecuentes

Cuando algo falla, GeoDuck muestra el mensaje del motor **tal cual** y, si lo reconoce, un título en español y
un botón para arreglarlo. Aquí, lo más común.

## No existe la tabla o la columna {#not-found}

> La tabla «predio» no existe · Sugerencia: predios.

- Revisa el nombre. Si el motor sugiere otro, pulsa **Cambiar a «…»**.
- ¿Está en otra base? Nómbrala completa: `otra_base.main.predios`, o hazla la base activa.
- Nombres con mayúsculas o espacios van entre comillas dobles: `"Nombre Cliente"`.

## Error de sintaxis {#syntax}

El motor no entiende el SQL. La tarjeta dice la línea y la palabra. Lo más común: una coma de más o de menos,
comillas sin cerrar, o una palabra reservada usada como nombre (ponla entre comillas dobles).

## Un valor no se puede convertir {#conversion}

> Could not convert string 'abc' to INTEGER

Hay filas con valores que no son del tipo pedido. **Usar TRY_CAST** devuelve `NULL` en esas filas en vez de
fallar.

## Archivos {#files}

- **No existe:** revisa la ruta; **Elegir archivo…** la cambia.
- **No es una base:** el archivo no es de DuckDB, o está dañado.
- **Está en uso:** otro programa lo tiene abierto en escritura. Ciérralo o abre la base en **Solo lectura**.

## Sin memoria {#memory}

La consulta necesitó más memoria de la permitida. **Subir memory_limit…** escribe `SET memory_limit` antes de
la sentencia. También ayuda filtrar antes de unir, o exportar por partes.

## Extensión espacial {#spatial}

> Scalar Function with name st_area does not exist… exists in the spatial extension

GeoDuck carga la extensión espacial al iniciar. Si no pudo (sin internet), el aviso tiene **Reintentar** e
**Instalar desde un archivo…**. **? › Diagnóstico del entorno** muestra la dirección exacta para descargarla.

## Restricciones {#constraint}

> Duplicate key "id: 7" violates primary key constraint

La fila rompe una regla de la tabla (clave repetida, valor nulo donde no se permite). Revisa los datos o la
regla.

## Transacciones {#transaction}

Tras un error dentro de una transacción (`BEGIN`), el motor no acepta más sentencias hasta `ROLLBACK`. GeoDuck
te lo dice en la barra de la consulta.

## La capa no está disponible {#layer-unavailable}

Una capa Conectada cuya base se cerró o no se encuentra. Clic derecho en la capa › **Abrir la base «…»**, o
abre la base desde GeoDuck: la capa vuelve sola.
