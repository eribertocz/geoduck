# ADR-0014 — Cuadernos en disco: archivo `.sql` explícito y copia de recuperación

**Estado:** Aceptado (propietario, 2026-11-03) · **Fase:** G7 · Notebook (`v0.8.0a1`)
**Relacionados:** security.md §4, sql-editor-spec §7 («G7 · Notebook»), ui-ux-spec §10, GD-SQL-008.

## Contexto
Hasta aquí los cuadernos vivían solo en memoria (GD-SQL-008, sin fase): al cerrar QGIS, o si se colgaba, se
perdía el SQL escrito. security.md §4 no permitía guardar SQL en disco sin una preferencia explícita, porque el
SQL puede llevar rutas o claves (`ATTACH`, `CREATE SECRET`). El propietario pidió poder guardar y abrir
cuadernos y no perder el trabajo si QGIS se cierra por un fallo.

## Decisión
- **Archivo `.sql` que elige el usuario** («Guardar cuaderno…», «Abrir cuaderno…», Ctrl+S y Ctrl+O). Formato
  abierto (`geoduck.domain.notebook_file`): cada celda empieza con `-- %% cell · database: <base>`; como son
  comentarios, el archivo se edita en cualquier editor y corre tal cual en DuckDB. Un `.sql` sin marcas se abre
  como una celda. Un cuaderno con archivo **se guarda solo** en él tras cada cambio.
- **Copia de recuperación**, **activada por defecto** y desactivable («⋯» de «Cuadernos»): tras cada cambio, el
  SQL y la base de cada celda de todos los cuadernos (nunca resultados) en la carpeta del perfil de QGIS
  (`geoduck/recuperacion/<sesión>/`). Cada QGIS abierto usa su propia carpeta con un `QLockFile`; al cerrar bien
  se borra. Si al abrir GeoDuck queda una carpeta cuyo candado está libre (su QGIS ya no existe), se ofrece
  «Recuperar» o «Descartar»; en los dos casos se borra.
- Toda escritura es atómica (temporal junto al destino y renombrado).
- Al iniciar QGIS se vuelven a abrir los cuadernos guardados que estaban abiertos: en `QgsSettings` solo sus
  rutas y la del activo (no su SQL); la ayuda de cada cuaderno dice dónde está guardado.

## Alternativas rechazadas
- **Guardar solos los cuadernos al cerrar QGIS, sin archivo elegido** (como la DuckDB UI): escribe SQL del
  usuario en disco de forma permanente sin que lo pida.
- **Formato propio (JSON):** no se abre ni corre fuera de GeoDuck.
- **Guardar dentro del proyecto `.qgz`:** mezcla el SQL con el proyecto y se comparte con él sin querer.

## Consecuencias
- security.md §4 cambia: el SQL se escribe en disco solo (a) en el archivo que el usuario eligió y (b) en la copia
  de recuperación de su perfil, que se borra al cerrar bien y se puede apagar. Si el SQL tiene una clave, queda en
  esos archivos: se avisa en la guía y en la ayuda de la opción.
- Una línea del SQL que empiece por `-- %% cell` partiría la celda al volver a abrir el archivo.
- Si el usuario edita el mismo archivo fuera de GeoDuck mientras está abierto, gana el último que guarda.
