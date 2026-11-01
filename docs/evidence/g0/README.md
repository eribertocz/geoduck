# Evidencia G0 — auditoría técnica de viabilidad (2026-11-01)

Esta carpeta conserva, sin editar, los scripts y salidas de la auditoría G0. Sirve para reproducir
cada afirmación del informe y para detectar regresiones cuando cambien las versiones.

## Alcance y límites

- **Plataforma:** contenedor Linux x86_64, Ubuntu 24.04. **No es Windows.** Estos resultados prueban
  comportamiento de APIs y de PyQGIS; no prueban la instalación en Windows (gate G0-A pendiente).
- **Sin red hacia `extensions.duckdb.org`:** la extensión `spatial` no se pudo instalar ni verificar.
- **Rendimiento:** las cifras de tiempo son indicativas (hardware compartido, sin repeticiones). No son
  benchmarks según `spec/qa/benchmarks.md`.

## Combinaciones ejecutadas

| Host | Qt | Python | NumPy | DuckDB | PyArrow | Origen |
|---|---|---|---|---|---|---|
| sin QGIS | — | 3.12.3 | — | 1.5.0, 1.5.1–1.5.5 (bisección), 1.5.6, 2.0.0 | 26.0.0 | PyPI |
| QGIS 3.34.4 | 5.15.13 | 3.12.3 | 1.26.4 | 1.5.0, 2.0.0 | 25.0.1 | apt (Ubuntu) |
| QGIS 3.44.14 | 5.15.15 | 3.12.16 | 2.5.4 | 1.5.0, 2.0.0 | 25.0.1 | conda-forge |
| QGIS 4.2.3 | 6.11.2 | 3.14.10 | 2.5.4 | 1.5.0, 2.0.0 | 25.0.1 | conda-forge |

Disponibilidad de wheels Windows comprobada con
`pip download --no-deps --only-binary=:all: --platform win_amd64 --python-version X.Y`.

## Fallos y diferencias detectados

| ID | Hallazgo | Versiones | Evidencia |
|---|---|---|---|
| F-01 | Con un lector Arrow abierto, otra sentencia en la misma conexión se **acepta** y el lector termina con 1 000 de 100 000 filas **sin error** | 1.5.0, 1.5.6 (2.0.0 rechaza con `ResourceInUseException`) | `scripts/repro_reader_truncation.py`, `results/F-01_reader_truncation.txt` |
| F-02 | Uso simultáneo de una conexión desde dos hilos: segfault (-11), abort (134), bloqueo (timeout) o éxito, de forma no determinista | 1.5.0 (1.5.6 sin fallo observado; 2.0.0 `ResourceInUseException`) | `scripts/repro_concurrent_segfault.py`, `results/F-02_concurrent_use.txt` |
| F-03 | PyArrow 26.0.0 no importa con NumPy 1.26.4 («requires NumPy 2.0 or newer»); 25.0.1 a 21.0.0 sí | PyArrow 26 | `scripts/repro_pyarrow_numpy.sh` |
| F-04 | `rel.to_arrow_table()` de `GEOMETRY` → `InternalException`; `to_arrow_reader()` funciona | 1.5.0–1.5.3 (corregido en 1.5.4) | `scripts/geo_min.py`, `results/F-04_geometry_arrow_bisect.txt` |
| F-05 | `fetchall()` de `GEOMETRY` y el cast `'…'::GEOMETRY` no soportados | 1.5.0 | `scripts/geo_core.py`, `scripts/geo_min.py` |
| F-06 | `ATTACH ? AS x` con parámetro: error de parser | 1.5.x (2.0.0 sí lo admite) | `results/session_*.json` (`C.attach_param_path`) |
| F-07 | `COMMIT` tras un error dentro de `BEGIN` se acepta sin error pero revierte toda la transacción | 1.5.0, 1.5.6, 2.0.0 | `results/session_*.json` (`H.failed_stmt_in_tx`) |
| F-08 | `con.sql()` de DDL devuelve `None` (1.5.x) o una relación (2.0.0); las relaciones se re-ejecutan en cada lectura | todas | `results/session_*.json` (`J.*`) |
| F-09 | `interrupt()` desde otro hilo detiene `execute` y lectores (latencia observada 1,5–180 ms en todas las versiones 1.5.0–1.5.6 y 2.0.0); dentro de un lector llega como `OSError`; la conexión sigue usable | 1.5.0–1.5.6, 2.0.0 | `results/session_*.json` (`G.*`), `results/F-09_interrupt_all_versions.txt` |
| F-10 | La relación exporta `GEOMETRY` como `geoarrow.wkb` con CRS PROJJSON en los metadatos del campo; `ST_AsWKB` produce `binary` **sin** metadatos | 1.5.0+ (vía lector) | `scripts/geo_arrow.py`, `scripts/geo_min.py` |
| F-11 | `QgsField(nombre, QMetaType.Type)` no existe en QGIS 3.34; NULL llega como `QVariant` NULL en QGIS 3 y como `None` en QGIS 4.2 | QGIS 3.34 / 4.2 | `results/qgis_*.json` |
| F-12 | DuckDB 1.5.0 no abre archivos escritos por 2.0.0 en formato por defecto; sí con `STORAGE_VERSION 'v1.5.0'` | 2.0.0 → 1.5.0 | ver informe G0, §2 |

## Resultados positivos (resumen)

- Flujo DuckDB → `to_arrow_reader` → `QgsVectorLayer(memory)`: 100 000 puntos con
  `rows_read == rows_added == featureCount` en las 6 combinaciones QGIS × DuckDB (`results/qgis_*.json`).
- CRS `OGC:CRS84` reconstruido con `QgsCoordinateReferenceSystem.createFromUserInput(<PROJJSON>)`.
- Fallo simulado en la fila 30 001: ninguna capa publicada.
- Capa entregada intacta tras `con.close()`.
- Tras `DETACH`, un proceso externo abre el archivo en RW (Linux).

## Cómo reproducir

```bash
python3.12 -m venv .v && .v/bin/pip install "duckdb==2.0.0" "pyarrow==26.0.0"
.v/bin/python -I scripts/spike_session.py   # escribe out/session_<versión>.json
.v/bin/python -I scripts/repro_reader_truncation.py
# PyQGIS: dentro de un entorno con QGIS (p. ej. conda-forge "qgis=3.44.14")
QT_QPA_PLATFORM=offscreen python scripts/spike_qgis.py
```

Los scripts escriben en `out/` relativo al directorio actual. `spike_session.py` acepta
`GD_SKIP_MT=1` para omitir la prueba que hace caer DuckDB 1.5.0 (F-02).
