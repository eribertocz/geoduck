# Prueba manual en Windows · G6 SQL Professional

> **Retirada en G9.** La interfaz de G6 (SQL profesional) se retiró en 0.10.0a1. La prueba manual vigente es
> [`workspace-pro.md`](workspace-pro.md). Se conserva como registro de lo probado en su momento.

Complementa la CI (Linux) para lo que solo se ve en Windows: teclado, ratón, idioma y empaquetado. Unos 15
minutos. Requisitos: Windows 10/11, QGIS 3.34+ (o 4.x), DuckDB y PyArrow como en
`docs/certification/workspace.md` §1. Instale el ZIP del PR (Complementos → Instalar a partir de ZIP).

Anote cada paso como **OK** o **Falla** (con captura) en `docs/evidence/g6/windows/<celda>/README.md`.

## 1. Preparación

1. Abra GeoDuck → «Iniciar sesión».
2. Pegue y ejecute (Ctrl+Mayús+Intro):

   ```sql
   CREATE TABLE zonas (id INTEGER NOT NULL, "Nombre oficial" VARCHAR, geom GEOMETRY);
   CREATE SCHEMA censo;
   CREATE TABLE censo.hogares (personas INTEGER);
   ```

## 2. Columnas en el explorador (AT-CAT-002)

| # | Haga | Debe pasar |
|---|---|---|
| 2a | Expanda la tabla «zonas» | «Cargando…» un instante; luego `id · INTEGER`, `Nombre oficial · VARCHAR`, `geom · GEOMETRY` (con icono de geometría) |
| 2b | Pase el ratón sobre `id` | Ayuda con el tipo y «Admite NULL: no» |
| 2c | Doble clic en `Nombre oficial` | En el editor aparece `"Nombre oficial"` (con comillas) |
| 2d | Arrastre `id` al editor | Aparece `id` donde suelta |
| 2e | Doble clic en la tabla «zonas» | Se abre «Cargar en QGIS» (como en G5); la tabla no se abre ni se cierra |
| 2f | Ejecute `ALTER TABLE zonas ADD COLUMN nueva BOOLEAN` | «zonas» sigue abierta y muestra `nueva · BOOLEAN` |

## 3. Autocompletado (AT-SQL-007)

| # | Haga | Debe pasar |
|---|---|---|
| 3a | Escriba `SELECT * FROM zo` | Lista con «zonas» y su icono; Intro → `zonas` |
| 3b | Escriba `SELECT z.` con `FROM zonas z` detrás | Solo las columnas de «zonas»; Tab inserta la elegida |
| 3c | Escriba `SELECT * FROM censo.` | «hogares» |
| 3d | Escape; luego Ctrl+Espacio | Se cierra; se vuelve a abrir |
| 3e | Escriba `-- zo` y `'zo` | No se abre nada |
| 3f | Con la lista cerrada, Intro | Línea nueva (nada se ejecuta) |

## 4. Pestañas, historial y «Explicar» (AT-SQL-008..010)

| # | Haga | Debe pasar |
|---|---|---|
| 4a | «+» (o Ctrl+T) | «Consulta 2», vacía y con el cursor |
| 4b | Escriba `SELECT 1` en «Consulta 2», ejecute; vuelva a «Consulta 1» | Cada pestaña conserva su texto |
| 4c | «Acoplar a QGIS» y «Abrir en ventana» | Pestañas, texto y cursor iguales |
| 4d | Cierre una pestaña con SQL (✕ o Ctrl+W) | Pregunta antes; «No» la deja abierta |
| 4e | Clic derecho en una fila del registro → «Abrir en el editor» | Pestaña nueva con ese SQL, sin ejecutarlo |
| 4f | Escriba `DELETE FROM zonas` y pulse «Explicar» | Pestaña de resultados con el plan; `SELECT count(*) FROM zonas` sigue igual |
| 4g | Seleccione dos sentencias y pulse «Explicar» | Aviso; no se ejecuta nada |
| 4h | Estreche el panel acoplado | «Explicar» queda como icono; ninguna acción desaparece |

## 5. Idioma (AT-I18N-001)

| # | Haga | Debe pasar |
|---|---|---|
| 5a | QGIS en español (Configuración → Opciones → General → Idioma), reinicie | GeoDuck en español, como en G5 |
| 5b | QGIS en inglés, reinicie | GeoDuck en inglés (botón «Run», pestaña «Query 1», mensajes de error en inglés) |
| 5c | Vuelva al idioma de siempre | QGIS sigue en su idioma: GeoDuck no lo cambia |

## 6. Resultado

Celda (Windows · QGIS · DuckDB) · fecha · pasos OK / Falla. Una falla abre una issue con la captura; no
bloquea el cierre de G6 salvo que lo decida el propietario.
