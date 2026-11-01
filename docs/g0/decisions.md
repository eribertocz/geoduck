# G0 — Registro de decisiones del propietario

| # | Decisión | Estado | Resolución / pendiente |
|---|---|---|---|
| D1 | Repositorio GitHub | **Parcialmente resuelta** | Resuelto: `eribertocz/geoduck`, público. Pendiente: crear el repositorio (con `main` inicializada, p. ej. con README) y autorizar el acceso de la app de GitHub de Claude. Mientras tanto, el trabajo vive en un repositorio local con ramas listas para empujar |
| D2 | Licencia | **Resuelta** | `GPL-2.0-or-later`. Implicaciones verificadas en `docs/licensing.md` (obligatorio «or later» por PyQt GPLv3 y PyArrow Apache-2.0; sin binarios en el ZIP) |
| D3 | Anclas QGIS de certificación (C1) | **Abierta** | Recomendación: 3.44.x LTR + 4.2.3; añadir 4.4.x como P0 cuando esté en la descarga |
| D4 | Equipo Windows 11 | **Resuelta (equipo)**; procedimiento entregado | Hay equipo. El procedimiento reproducible y los requisitos están en `docs/certification/windows.md`; pendiente su ejecución |
| D5 | DuckDB mínimo 1.5.0 vs recomendado 1.5.4+ (C8) | **Abierta** | Recomendación: mínimo 1.5.0, recomendado 1.5.4+. El código de G0 no depende de esta decisión |
| D6 | Merges | **Resuelta** | Exclusivos del propietario. El implementador crea ramas, commits y PR cuando tenga acceso autorizado; nunca fusiona a `main` |
| D7 | Red para `extensions.duckdb.org` en la sesión del implementador | **Abierta** | Alternativa: verificar `spatial` en el equipo Windows con `docs/certification/spatial.md` |

Además: **tags y releases requieren aprobación expresa del propietario** (decisión del 2026-11-01).

## Decisiones arquitectónicas del 2026-11-01 y su trazabilidad

| Decisión | Dónde se implementa / registra |
|---|---|
| Rutas seguras y verificables en DuckDB 1.5.x y 2.x | `geoduck/engine/compat.py`; matriz de CI 1.5.0 / 1.5.x / 2.0.x |
| Ninguna conexión usada por dos hilos | ADR-0006; `SessionWorker`, `ConnectionHandle`, `WrongThreadError` |
| Propiedad exclusiva, serialización, ciclo de vida de lectores | ADR-0006; `geoduck/engine/worker.py` |
| Cancelación desde otro hilo solo como excepción controlada | ADR-0007; `SessionWorker.cancel`, `interrupt_verified` |
| Detectar cargas incompletas; nunca capas parciales | ADR-0006 §5 (`ReadSummary.completed`); publicación atómica en G3 |
| GeoArrow para geometría y CRS | ADR-0008 (G3/G4) |
| PyArrow según la matriz real | ADR-0009; `compat/matrix.toml`; regla en `geoduck/infra/diagnostics.py` |
| Capas entregadas independientes | ADR-0002 (vigente); verificado en la evidencia G0 |
