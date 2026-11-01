# ADR-0009: selección de PyArrow a partir de la matriz real QGIS/Python/NumPy/DuckDB

**Estado:** Propuesto — recoge la decisión arquitectónica del 2026-11-01 · **Requiere:** aprobación del arquitecto
**Relacionado:** ADR-0005; `spec/docs/technology.md` (Decisión PyArrow)

## Contexto

F-03: PyArrow 26.0.0 no importa si el Python de QGIS tiene NumPy 1.x (QGIS 3.34 en Ubuntu trae 1.26.4;
QGIS 3.44 en Windows ha incluido 1.26.4 según el issue #63733). PyArrow 25.0.1 sí funciona. Los wheels
disponibles también dependen de la versión de Python (p. ej. PyArrow 26 no publica wheel para 3.10).

## Decisión

1. La versión de PyArrow **no** se fija globalmente: se elige por celda de la matriz
   (`compat/matrix.toml`) según QGIS, Python, NumPy embebida y DuckDB, y se fija en
   `constraints/<celda>.txt`.
2. Regla de compatibilidad verificada que el diagnóstico aplica en tiempo de ejecución:
   *PyArrow ≥ 26 requiere NumPy ≥ 2 cuando NumPy está presente*. Las reglas nuevas solo se añaden
   con evidencia reproducible.
3. Ningún rango se amplía a una versión nueva de PyArrow sin pasar la matriz.
4. GeoDuck no instala ni actualiza NumPy: es del entorno QGIS.

## Verificación

Test unitario de la regla en `infra/diagnostics`; job de CI con NumPy 1.26 (QGIS 3.34 apt) y NumPy 2.x
(conda-forge); certificación Windows por celda.
