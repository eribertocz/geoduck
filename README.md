# GeoDuck

> **Estado: Alpha (pre-release).** Ninguna versión de GeoDuck es estable. No existe fecha para v1.0.0.

GeoDuck es una extensión de escritorio para **QGIS 3 y QGIS 4**, escrita en Python, que integra
una sesión **DuckDB** de primera clase dentro de QGIS y entrega resultados como **capas nativas de
memoria de QGIS**.

> **DuckDB procesa → GeoDuck transfiere → QGIS administra.**

Una vez entregada, la capa pertenece a QGIS: no mantiene vínculo con GeoDuck ni con DuckDB.

## Estado de la versión objetivo

| Versión | Alcance | Estado |
|---|---|---|
| `0.1.0a1` — Alpha Foundation | Panel en QGIS 3/4, diagnóstico del entorno, sesión DuckDB `:memory:` | En desarrollo; gate G0 abierto |

El alcance completo por fases está en [`spec/docs/roadmap.md`](spec/docs/roadmap.md).

## Dependencias de ejecución

GeoDuck usa el intérprete Python **de la instalación de QGIS**; no requiere ni impone un Python externo.

| Paquete | Requisito | Licencia |
|---|---|---|
| `duckdb` | `>= 1.5.0` (recomendado `>= 1.5.4`), ramas 1.5.x y 2.x verificadas por matriz | MIT |
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
