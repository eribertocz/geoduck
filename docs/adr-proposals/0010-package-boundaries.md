# ADR-0010: estructura de paquetes y fronteras de importación verificadas

**Estado:** Propuesto — revisión 2 (2026-11-01) · **Requiere:** aprobación del arquitecto
**Relacionado:** `spec/docs/architecture.md` §2, §6 (la estructura orientativa admite simplificarse «sin
cambiar fronteras»); ADR-0006; ADR-0011

**Cambios respecto de la revisión 1:** la tabla refleja exactamente lo que hace cumplir el test. Se
explicitan el acceso al módulo raíz `geoduck` (solo `__version__`), las reglas previstas para
`qgis_bridge` (G3) y la regla complementaria de ADR-0011.

## Contexto

La estructura orientativa usa un subpaquete `geoduck/duckdb/`. Dentro del paquete, ese nombre se confunde
con el paquete externo `duckdb` y dificulta leer qué importa cada módulo. Además, las fronteras entre capas
solo se mantienen si algo las comprueba automáticamente en cada PR.

## Decisión

1. **Paquetes:** `domain/` (puro), `app/` (casos de uso), `engine/` (antes `duckdb/` en la estructura
   orientativa), `infra/`, `ui/`, `qgis_bridge/` (antes `bridge/`, se crea en G3) y `plugin.py` como raíz
   de composición. `__init__.py` solo expone `__version__` y `classFactory`, que importa `plugin`
   de forma diferida.
2. **Reglas de importación** («raíz» = el módulo `geoduck`, solo para `__version__`):

| Paquete | Puede importar | No puede importar |
|---|---|---|
| `domain` | biblioteca estándar, `domain` | todo lo demás |
| `app` | biblioteca estándar, `domain`, `app` | `duckdb`, `pyarrow`, `qgis`, `PyQt*`, `engine`, `infra`, `ui`, `qgis_bridge` |
| `engine` | biblioteca estándar, `domain`, `engine`, `duckdb`, `pyarrow` | `qgis`, `PyQt*`, `app`, `infra`, `ui`, `qgis_bridge` |
| `infra` | biblioteca estándar, raíz, `domain`, `infra`; importación **dinámica** de dependencias para diagnosticarlas | importación estática de `duckdb`/`pyarrow`/`qgis`; `app`, `engine`, `ui` |
| `ui` | biblioteca estándar, raíz, `domain`, `app`, `infra`, `ui`, `qgis` (incluido `qgis.PyQt`) | `duckdb`, `pyarrow`, `engine`, `qgis_bridge` |
| `qgis_bridge` (G3, propuesto) | biblioteca estándar, `domain`, `qgis_bridge`, `pyarrow`, `qgis` | `duckdb`, `engine`, `ui` |
| `plugin.py` | todo (raíz de composición); `engine` solo con importación diferida | — |

3. **Verificación automática.** Un test sin dependencias externas (`tests/architecture`, análisis AST de
   todas las importaciones, incluidas las diferidas dentro de funciones) hace cumplir la tabla en cada PR.
   El test incluye un caso que comprueba que la regla detecta una violación.
4. **Regla complementaria (ADR-0011).** Ningún módulo de `geoduck/` modifica rutas de importación,
   paquetes, variables de entorno ni otros complementos (`tests/architecture/test_no_foreign_mutation.py`).

## Consecuencias

- Pro: una frontera cruzada, como la UI usando DuckDB o el motor tocando QGIS, falla en CI.
- Pro: `domain`, `app` y `engine` se prueban sin QGIS.
- Contra: cambiar una regla exige modificar este ADR y el test a la vez.
- Al crear `qgis_bridge` en G3, su fila de la tabla se añade al test.

## Implementación y verificación vigentes

- `tests/architecture/test_import_boundaries.py`: una prueba por módulo, más
  `test_only_engine_imports_duckdb`, `test_engine_never_imports_qt_or_qgis`,
  `test_rules_detect_a_violation` y `test_every_package_is_covered`.
- `tests/architecture/test_no_foreign_mutation.py` (ADR-0011).
- Se ejecuta en el job «lint · tipos · arquitectura · unitarias» de CI.
