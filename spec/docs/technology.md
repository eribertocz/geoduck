# GeoDuck — Selección tecnológica y restricciones

**Fecha base:** 2026-11-01 · **Política:** elegir tecnologías de primera línea sin incluir dependencias por moda.

| Pieza | Elección | Motivo | Riesgo/prueba |
|---|---|---|---|
| Host GIS | QGIS 3/4 Desktop | Plugin nativo y capas administradas por QGIS | Qt5/Qt6 y bindings |
| Lenguaje plugin | Python de QGIS | API PyQGIS y mantenibilidad | QGIS controla el runtime |
| UI | PyQGIS + `qgis.PyQt`, widgets Qt | Integración y diseño nativo minimalista | diferencias Qt5/Qt6 |
| SQL editor | Preferir `QgsCodeEditorSQL` si el binding existe; fallback QScintilla/Qt | evitar editor web innecesario | spike Windows QGIS3/4 |
| Motor | DuckDB Python `>=1.5.0` certificado | SQL + relaciones + Spatial | versiones de almacenamiento y DLL |
| Spatial | extensión oficial DuckDB `spatial` | geometría y funciones `ST_*` | instalación/carga y permisos |
| Transporte | PyArrow RecordBatch | lotes, tipos columnares, transferencias acotadas | conversión a QVariant y RAM |
| Geometría | WKB → `QgsGeometry` | intercambio binario estándar | CRS separado y geometría mixta |
| Testing | pytest + pruebas reales QGIS | detección temprana | runners Windows QGIS instalados |
| Calidad | ruff, mypy orientativo, CI | consistencia | imports de PyQGIS en static checks |
| Benchmarks | harness reproducible | evidencia y regresiones | hardware fijo, métricas exactas |

## Política de versiones
- Windows x64 primero.
- Certificación inicial de referencia: QGIS 4.2.x actual y QGIS 3.44.x LTR, ambas instaladas, con PyQGIS real y dependencias reales.
- QGIS 4.0.x, otras 4.x y QGIS 3 anteriores: matriz gradual; ninguna garantía genérica de «todos QGIS 3».
- QGIS 2: fuera de soporte.
- DuckDB 1.5.0 es la versión mínima soportada. DuckDB 1.5.x y 2.x se certifican por matriz de CI; las versiones nuevas se incorporan tras validación. Usar APIs comunes verificadas, sin asumir que todas las APIs de 2.x existen en 1.5.
- La compatibilidad Python depende del wheel concreto de DuckDB 1.5.x/2.x y del runtime QGIS. Verificarla con instalación real por combinación; no imponer el requisito de Python de DuckDB 2.x a la rama 1.5.
- Elegir PyArrow que publique wheel compatible con el Python/ABI/arquitectura del QGIS de destino. No asumir que `pyarrow` funciona por tener instalado un Python separado.
- Usar rango compatible más lock/constraints por combinación certificada; evitar depender de «último» sin pruebas.

## Contrato de compatibilidad DuckDB (GD-COMP-DB-001)
- **Mínimo funcional: DuckDB Python 1.5.0** (inclusive). **Soporte objetivo: 1.5.x y versiones 2.x y superiores verificadas**; «superior» no equivale a certificación automática para versiones futuras.
- **Recomendada en la rama 1.5: DuckDB 1.5.6** (decisión D5, 2026-11-01). Por debajo de 1.5.4 el diagnóstico advierte de defectos conocidos de geometría.
- Exigir pruebas funcionales idénticas en 1.5.x y 2.x para SQL multisentencia, `ATTACH/DETACH`, `spatial`, relaciones lazy, `to_arrow_reader()`, tipos Arrow y entrega de capas PyQGIS.
- Las diferencias reales de APIs, semántica de conexión, lectores Arrow, transacciones, CRS y almacenamiento deben documentarse en una **matriz de capacidades por versión**. No introducir una rama de código especial sin una prueba reproducible.
- El runtime Python de QGIS, PyArrow y las ruedas nativas DuckDB determinan qué combinaciones se pueden certificar. La aplicación mostrará mensajes claros si la combinación no es soportada.
- La lectura/escritura de archivos DuckDB creados con otras versiones se probará separadamente: **compatibilidad de API Python no garantiza compatibilidad del formato de almacenamiento**.
- La transferencia a QGIS usa la misma interfaz lógica independientemente de la versión de DuckDB, con un adaptador mínimo solamente si hace falta.

## APIs DuckDB preferidas
- `duckdb.connect(database=":memory:")` explícito y sin conexiones globales.
- `con.execute(sql)` para DDL, DML, transacciones, ATTACH/DETACH y configuración.
- `con.sql(sql)`/`con.table(name)` para consultas y relaciones.
- `relation.to_arrow_reader(batch_size=...)` + `with` como transporte de lectura.
- `con.extract_statements()` para parseo de script, con una capa que conserve SQL original/posición si la API lo soporta.
- `duckdb_databases()`, `information_schema` para introspección.
- Nunca usar `con.execute(...).to_arrow_reader()` como vía «streaming» en DuckDB 2.0: ese camino copia filas y advierte.

## Decisión PyArrow
La versión de PyArrow se elige según la matriz real de QGIS, Python, NumPy y DuckDB; si QGIS incluye PyArrow, se usa esa y solo se instala `duckdb` (ADR-0009).

PyArrow **no es el backend de almacenamiento QGIS**; es el medio de transporte entre DuckDB y el convertidor PyQGIS. La copia final al proveedor `memory` está prevista. La prioridad es reducir picos de memoria, no anunciar zero-copy.

## Empaquetado
El complemento debe registrar un verificador de entorno que inspeccione Python, QGIS, Qt, architecture, `duckdb`, `pyarrow` y capacidad `spatial`. No ejecutar `pip install` silencioso dentro de QGIS; decidir el flujo de instalación Windows mediante un spike con instrucciones y paquete reproducible.

## Criterios para añadir librerías
Toda dependencia nueva requiere: necesidad no resuelta por QGIS/DuckDB, soporte a QGIS 3/4 en Windows, wheel/instalación viable, licencia compatible, mantenimiento razonable, plan de pruebas y evaluación de riesgo.
