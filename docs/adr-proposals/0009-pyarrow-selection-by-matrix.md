# ADR-0009: PyArrow según la matriz real de QGIS, Python, NumPy y DuckDB

**Estado:** Principios aprobados (dictamen del 2026-11-01) — **pendiente la validación literal de este texto** · revisión 2
**Recoge:** decisión arquitectónica del 2026-11-01 («la versión de PyArrow debe elegirse a partir de la
matriz real de QGIS, Python, NumPy y DuckDB»)
**Relacionado:** ADR-0005, ADR-0011; `spec/docs/technology.md` (Decisión PyArrow, Empaquetado);
`spec/docs/compatibility-distribution.md`

**Cambios respecto de la revisión 1:** incorpora la evidencia de Windows (F-13, F-15). La regla
principal pasa a ser usar la PyArrow que incluye QGIS cuando existe. Antes, la revisión 1 fijaba una
versión por celda.

## Contexto

- **F-03** (Linux): PyArrow 26.0.0 no importa si NumPy es 1.x («requires NumPy 2.0»); PyArrow 21.0.0 a
  25.0.1 sí funcionan con NumPy 1.26.4.
- **F-13** (Windows, QGIS 3.34.15): QGIS incluye su propia **PyArrow 18.1.0**. Una PyArrow distinta en el
  *site* de usuario (25.0.1) falla con `ImportError: DLL load failed … No se encontró el proceso
  especificado`. La causa probable es que la DLL de Arrow de QGIS ya está cargada en el proceso con otra
  versión.
- **F-15** (Windows): `pip install … --upgrade` sin `--no-deps` instaló NumPy 2.5.4 por encima de la
  NumPy 1.26.4 de QGIS y rompió la compatibilidad declarada de scipy.
- Verificado (Linux, CI): GeoDuck funciona con DuckDB 1.5.0 y 2.0.0 + PyArrow 18.1.0 + NumPy 1.26.4.
  Es compatibilidad de APIs, no certificación Windows.
- Disponibilidad de wheels (`pip download`): PyArrow 26 no publica wheel para Python 3.10; DuckDB 2.0
  exige Python ≥ 3.11.

## Decisión

1. **Si QGIS incluye PyArrow, se usa esa.** GeoDuck y sus instrucciones de instalación solo instalan
   `duckdb`. Nunca instalan otra PyArrow en una instalación de QGIS que ya la trae (F-13).
2. **Si QGIS no incluye PyArrow**, la versión se elige por celda de `compat/matrix.toml` según Python y
   NumPy de esa instalación, y se fija en `constraints/<celda>.txt`.
3. **NumPy es del entorno QGIS.** Nunca se instala ni se actualiza; toda instalación usa `--no-deps` (F-15).
4. **Reglas verificadas que el diagnóstico aplica en tiempo de ejecución:**
   - PyArrow ≥ 26 requiere NumPy ≥ 2 cuando NumPy está presente (F-03);
   - un `DLL load failed` al importar PyArrow indica un choque con la PyArrow de QGIS y se explica así (F-13);
   - NumPy o PyArrow cargadas desde el *site* de usuario se advierten (QGIS #63733, F-13, F-15).
   Solo se añaden reglas nuevas con evidencia reproducible.
5. **Piso declarado:** `pyarrow >= 18` (18.1.0 es la mínima verificada). Ningún rango se amplía sin pasar
   la matriz.
6. **Distinción obligatoria.** Los jobs de CI en Ubuntu que reproducen las versiones de una celda
   demuestran compatibilidad de APIs, **no** certificación Windows.

## Consecuencias

- Pro: no se mezclan DLL nativas con las de QGIS, la causa de los fallos observados.
- Pro: menos que instalar para el usuario (solo `duckdb`).
- Contra: GeoDuck depende de la PyArrow que elija QGIS; si una versión futura de QGIS trae una PyArrow
  incompatible, se detecta en la matriz y en el diagnóstico, no se corrige instalando otra.
- Dependencias: ADR-0011, porque no se modifican dependencias de otros complementos; la decisión del
  método de instalación (spike G0-A, pendiente).

## Implementación y verificación vigentes

- `geoduck/infra/diagnostics.py`: `_check_pyarrow`, el mensaje de `DLL load failed` y `_check_user_site`.
- `tests/unit/test_diagnostics.py`: PyArrow 26 + NumPy 1 → FAIL; PyArrow 26 + NumPy 2 → OK; error real de
  Windows `DLL load failed` → FAIL con acción; NumPy en el *site* de usuario → WARN; combinación real de
  QGIS 3.34.15 → utilizable.
- CI (`.github/workflows/ci.yml`): motor con PyArrow 25.0.1 y con PyArrow 18.1.0 + NumPy 1.26.4.
- `compat/matrix.toml`, `constraints/win-qgis-3.34-py312.txt` (solo `duckdb`).
- Evidencia: `docs/evidence/g0/windows/win11-qgis-3.34.15/`.
