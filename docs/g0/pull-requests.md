# G0 — Ramas y pull requests preparados

Las ramas están apiladas: cada PR toma como base la rama anterior. El propietario fusiona en orden.
El implementador no fusiona a `main`, no crea tags ni releases.

| # | Rama | Base del PR | Issues | Evidencia principal |
|---|---|---|---|---|
| 1 | `chore/GD-1-bootstrap` | `main` | GD-1 | `spec/` idéntico al ZIP aprobado; LICENSE y `docs/licensing.md` |
| 2 | `docs/GD-2-adr-g0-evidence` | 1 | GD-2 | `docs/adr-proposals/`, `docs/evidence/g0/`, `docs/g0/` |
| 3 | `feat/GD-3-4-domain-engine` | 2 | GD-3, GD-4 | `tests/unit`, `tests/engine` en DuckDB 1.5.0/1.5.6/2.0.0 |
| 4 | `feat/GD-5-diagnostics` | 3 | GD-5 | `tests/unit/test_diagnostics.py`, `compat/matrix.toml` |
| 5 | `feat/GD-6-7-plugin-shell` | 4 | GD-6, GD-7 | `tests/qgis` en QGIS 3.44.14/Qt5 y 4.2.3/Qt6; capturas `docs/evidence/g0/ui/` |
| 6 | `ci/GD-8-9-architecture-ci` | 5 | GD-8, GD-9 | `tests/architecture`; `.github/workflows/ci.yml`; ZIP reproducible |
| 7 | `docs/GD-10-11-windows-spatial-certification` | 6 | GD-10, GD-11 (procedimiento) | `docs/certification/`, `tools/verify_env.py`, `tools/windows/` |

GD-10, GD-11 (ejecución en Windows) y GD-12 (release) siguen abiertos hasta tener la evidencia de
Windows y la aprobación del propietario.

## Pasos cuando exista acceso autorizado

1. El propietario crea `eribertocz/geoduck` (público) con `main` inicializada (p. ej. con un README) y
   autoriza a la app de GitHub de Claude.
2. El implementador rebasa la pila sobre el `main` remoto, empuja las 7 ramas y ejecuta
   `tools/github/bootstrap.sh` (etiquetas, milestones `v0.1.0a1`…`v0.9.0a1`, issues GD-1…GD-12), primero
   con `DRY_RUN=1`.
3. Abre los 7 PR con la plantilla, enlazando issues y evidencia.
