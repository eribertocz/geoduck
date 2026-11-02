# Evidencia G2 — pruebas breves de viabilidad

Linux, DuckDB 1.5.0, 1.5.6 y 2.0.0; QGIS 3.44.14 (Qt 5.15) y 4.2.3 (Qt 6.11). No es certificación Windows (#10).

## Spike G2-A · parser de DuckDB (`parser_probe.py`)

| ID | Hecho | Consecuencia |
|---|---|---|
| F-34 | `con.extract_statements(script)` separa bien comentarios, literales con `;`, `''`, `$$…$$`, `WITH … INSERT … RETURNING`, `BEGIN`, `SET`, macros, `ATTACH`/`DETACH`. Devuelve `type` (`StatementType`), `expected_result_type`, `named_parameters` y `query` | Se usa el parser oficial; nunca `split(';')` |
| F-35 | `query` es un tramo literal del script, pero los límites cambian: en 1.5.x incluye el comentario previo y no el `;`; en 2.0 incluye el `;` y el espacio posterior | Los rangos se calculan buscando cada `query` en orden en el texto original |
| F-36 | En 1.5.x, `PRAGMA version` se reescribe como `SELECT * FROM pragma_version();`: tipo `SELECT` y texto que no está en el script. En 2.0 conserva `PRAGMA` | Si un `query` no aparece literal, su rango es el hueco entre la sentencia anterior y la siguiente. La clasificación usa `type`, no la primera palabra |
| F-37 | `con.execute(statement)` acepta el objeto `Statement` en las tres versiones | Se ejecuta el objeto, sin volver a analizar texto |
| F-38 | Un error de sintaxis en cualquier sentencia hace fallar `extract_statements` para todo el script: no se ejecuta nada | Ninguna ejecución parcial por errores de sintaxis |
| F-39 | Las excepciones no traen la posición como atributo; el mensaje incluye `LINE n: <texto>` y una línea con `^` (en 2.0, `^^^^` bajo el token) | La ubicación del error se obtiene del mensaje cuando existe, sin prometerla siempre |

## Spike G0-B · editor SQL de QGIS (`editor_probe.py`, #11)

| ID | Hecho | Consecuencia |
|---|---|---|
| F-40 | `qgis.gui.QgsCodeEditorSQL` existe y funciona igual en QGIS 3.44 (Qt5) y 4.2 (Qt6): hereda de `QgsCodeEditor` → `QsciScintilla`, conserva el texto (también con ñ), da selección y cursor, números de línea, plegado, nombres de campos para autocompletar y marcas de aviso (`addWarning`, `clearWarnings`) | **Implementación única: `QgsCodeEditorSQL`**, sin editor web ni alternativa propia |
| F-41 | En `(línea, índice)`, el índice cuenta caracteres, aunque las posiciones absolutas internas (`positionFromLineIndex`) son bytes UTF-8 | GeoDuck traduce siempre con `(línea, índice)` y desplazamientos en caracteres, nunca con posiciones absolutas de QScintilla |

QGIS 3.34 tiene `QgsCodeEditorSQL` desde 3.0; se confirma en Windows dentro de #10.
