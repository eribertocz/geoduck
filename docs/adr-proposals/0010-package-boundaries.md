# ADR-0010: estructura de paquetes y fronteras de importación verificadas

**Estado:** Propuesto · **Requiere:** aprobación del arquitecto
**Relacionado:** `spec/docs/architecture.md` §6 (estructura orientativa, simplificable «sin cambiar fronteras»)

## Contexto

La estructura orientativa usa un subpaquete `geoduck/duckdb/`. Dentro del paquete, ese nombre compite
con el paquete externo `duckdb` y dificulta leer qué importa cada módulo. Además, las fronteras entre
capas solo se mantienen si algo las comprueba automáticamente.

## Decisión

1. Paquetes: `domain/` (puro), `app/` (casos de uso), `engine/` (antes `duckdb/`), `qgis_bridge/`
   (antes `bridge/`, se crea en G3), `ui/`, `infra/`, y `plugin.py` como raíz de composición.
2. Reglas de importación:

| Paquete | Puede importar | No puede importar |
|---|---|---|
| `domain` | biblioteca estándar | todo lo demás |
| `app` | `domain`, biblioteca estándar | `duckdb`, `pyarrow`, `qgis`, `PyQt*`, `engine`, `ui`, `qgis_bridge` |
| `engine` | `domain`, `duckdb`, `pyarrow` | `qgis`, `PyQt*`, `app`, `ui`, `qgis_bridge` |
| `infra` | `domain`, biblioteca estándar; importación dinámica para diagnosticar | `app`, `ui`, `engine` |
| `ui` | `app`, `domain`, `infra`, `qgis`, `qgis.PyQt` | `duckdb`, `pyarrow`, `engine` |
| `plugin.py` | todo (raíz de composición) | — |

3. Un test de arquitectura sin dependencias externas (`tests/architecture`, análisis AST) hace cumplir
   la tabla en cada PR.

## Consecuencias

Las violaciones fallan en CI. Cambiar una regla exige modificar este ADR.
