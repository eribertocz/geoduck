# GeoDuck

> **Estado: Alpha (pre-release).** Ninguna versión de GeoDuck es estable. No existe fecha para v1.0.0.

GeoDuck es una extensión de escritorio para **QGIS 3 y QGIS 4**, escrita en Python, que lleva **DuckDB** a
QGIS: **SQL espacial y capas en los dos sentidos.**

- **Consultas SQL** en un editor moderno, con resultados que se recorren aunque tengan millones de filas.
- **De DuckDB a QGIS:** cada tabla o resultado se carga como **Copia** (los datos pasan a QGIS y ya no dependen
  de DuckDB) o como **Conectada** (QGIS lee directamente de DuckDB, sin copiar, y las ediciones se guardan en
  DuckDB).
- **De QGIS a DuckDB:** capas del proyecto y archivos (GeoPackage, Shapefile, Parquet, CSV…) con un clic o
  arrastrándolos.
- **Exportar** a los formatos habituales, siempre con DuckDB.

## Estado de la versión

| Versión | Alcance | Estado |
|---|---|---|
| `0.10.0a1` | Workspace profesional, editor SQL, QGIS ↔ DuckDB en los dos sentidos | Publicada (pre-release) |
| `0.11.0a1` — Rendimiento | Resultados bajo demanda, cancelar todo, memoria acotada, interfaz sin bloqueos | En desarrollo (G10) |

El alcance completo por fases está en [`spec/docs/roadmap.md`](spec/docs/roadmap.md); las versiones publicadas,
en [Releases](https://github.com/eribertocz/geoduck/releases).

## Dependencias de ejecución

GeoDuck usa el intérprete Python **de la instalación de QGIS**; no requiere ni impone un Python externo.

| Paquete | Requisito | Licencia |
|---|---|---|
| `duckdb` | `>= 1.5.0` (recomendada 1.5.6 en la rama 1.5; 2.x con soporte verificado, decisión D5) | MIT |
| `pyarrow` | En QGIS para Windows, la que incluye QGIS (verificado con 18.1.0); en otros casos, según [`compat/matrix.toml`](compat/matrix.toml) | Apache-2.0 |

Compatibilidad mínima: **QGIS 3.34** (decisión D8: primera serie con Python ≥ 3.10 en Windows, requisito de
DuckDB ≥ 1.5).

Las dependencias **no** se incluyen dentro del ZIP del complemento: el repositorio oficial de
complementos de QGIS no admite binarios. El método de instalación se decide en el spike G0-A
([`docs/certification/windows.md`](docs/certification/windows.md)).

## Compatibilidad

Compatibilidad declarada ≠ compatibilidad comprobada. Ninguna combinación está certificada todavía.
Consulte [`compat/matrix.toml`](compat/matrix.toml) y las notas de cada versión.

## Estructura del repositorio

| Ruta | Contenido |
|---|---|
| `geoduck/` | Paquete del complemento QGIS (lo que se distribuye en el ZIP) |
| `tests/` | `unit/`, `engine/` (DuckDB real), `qgis/` (PyQGIS real), `architecture/` |
| `spec/` | Paquete de especificación aprobado, **normativo**, sin modificar |
| `docs/adr-proposals/` | ADR propuestos por el implementador, pendientes de aprobación |
| `docs/evidence/` | Evidencia reproducible de spikes y gates |
| `docs/certification/` | Procedimientos de certificación (Windows, Spatial) |
| `compat/` | Matriz de compatibilidad versionada |
| `tools/` | Build del ZIP, verificador de entorno, scripts de soporte |

## Desarrollo

```bash
python -m pip install -e ".[dev]"        # herramientas de desarrollo (no para QGIS)
ruff check . && ruff format --check .
mypy
pytest tests/unit tests/architecture tests/engine
python tools/build_zip.py                  # genera dist/geoduck-<versión>.zip
```

Las pruebas `tests/qgis` requieren PyQGIS real (ver [`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Roles y contribución

- Propietario del producto: aprueba alcance, merges, tags y releases.
- Arquitectura y especificación: según `spec/`.
- Implementación: ramas y pull requests contra `main`; ningún merge sin aprobación del propietario.

Cada PR referencia los requisitos `GD-*` y su evidencia `AT-*` (ver la plantilla de PR).

## Licencia

GeoDuck se distribuye bajo **GNU General Public License v2.0 o posterior** (`GPL-2.0-or-later`).
Ver [`LICENSE`](LICENSE) y el análisis de dependencias en [`docs/licensing.md`](docs/licensing.md).
