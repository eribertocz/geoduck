# Conceptos

<span class="gd-time">4 minutos</span>

## Sesión

Mientras GeoDuck está iniciado hay una **sesión**: un motor de base de datos analítico (DuckDB) que corre
dentro de QGIS. El punto del logo dice cómo está: verde **activa**, ámbar **ocupada**, rojo **con error**; sin
punto, **detenida**. «Cerrar sesión» está en el menú del logo.

## Base y esquema

- Una **base** es un archivo `.duckdb` o una base **en memoria** (se pierde al cerrar la sesión). Puedes tener
  varias abiertas a la vez.
- La **base activa** (franja turquesa y etiqueta «activa» en el explorador) es donde se ejecutan las consultas
  y donde va lo nuevo. Otra base se nombra completa en el SQL: `otra_base.main.tabla`.
- Un **esquema** agrupa tablas dentro de una base. El de siempre es `main`.

## Copia y Conectada

Al cargar una tabla en QGIS eliges cómo:

| | Copia | Conectada |
|---|---|---|
| Qué hace | Copia los datos a QGIS | Lee directo de la base, sin copiar |
| Depende de la base | No | Sí: si la base se cierra, la capa queda «no disponible» |
| Editar | Edita la copia | Lo que edites se guarda en la base |
| Mejor para | Tablas medianas, trabajo sin la base | Tablas grandes, datos que cambian |

Al guardar un proyecto con capas **Copia**, GeoDuck ofrece guardarlas en un GeoPackage junto al proyecto, para
que vuelvan al reabrirlo. Una capa **Conectada** a una base de archivo vuelve sola: al abrir el proyecto,
GeoDuck se inicia y abre la base.

## Camino directo

Cuando llevas capas o archivos a GeoDuck, siempre que puede los lee el motor directamente (⚡ «leída
directamente por GeoDuck»), sin pasar por QGIS. Es más rápido. Si no se puede (un formato que solo QGIS lee,
un filtro de QGIS), se lee con QGIS y la línea de tiempo dice por qué.

## Trazabilidad

Cada envío, importación, exportación o carga muestra una **línea de tiempo**: de dónde viene, cómo se lee,
cuántas filas, a dónde va y cuánto tardó cada paso. Si algo falla, el paso se pone rojo con su error. Al
terminar, **Deshacer** borra lo que se creó.
