# ADR-0005: compatibilidad progresiva certificada y Alpha prolongada

**Estado:** Aceptado sujeto a pruebas G0 · **Fecha:** 2026-11-01

## Contexto
El producto debe respetar QGIS 3 y 4, Windows al inicio, DuckDB >=1.5.0, Python compatible con QGIS, PyArrow y cambios Qt5→Qt6.

## Decisión
Código único para QGIS 3/4 mediante `qgis.PyQt` y adaptadores mínimos. Priorizar pruebas reales Windows QGIS 3.44 LTR y 4.2; versiones anteriores tras matrix de viabilidad del runtime. QGIS 2 excluido. Publicar con sufijos Alpha sin calendario de estable.

## Consecuencias
- No prometer todos los QGIS 3 antiguos: algunos usan Python inferior a 3.11, potencialmente incompatibles con alguna combinación DuckDB 1.5+/PyArrow; certificar cada entorno sin suponer compatibilidad.
- PyArrow y binarios deben verificarse en Python/ABI de QGIS.
- Plugin metadata no sustituye pruebas de instalación y ejecución.
- Posible necesidad de empaquetado específico por entorno Windows, sujeto a spike.

## Verificación
AT-COMP-001; CI/QGIS E2E por celda de matriz y notas de release precisas.
