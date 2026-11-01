---
title: "GD-5 · Diagnóstico del entorno accionable"
labels: type/feature,area/infra,P0
milestone: v0.1.0a1
---
## Entregable
Python/ABI, QGIS/Qt, DuckDB (mín. 1.5.0), PyArrow con regla NumPy (F-03), spatial sin instalar, user site.

## Requisitos
GD-BOOT-002, AT-BOOT-002

## Rama
`feat/GD-5-diagnostics`

## Criterios de aceptación
- [ ] Sin pyarrow, NumPy incompatible y DuckDB < 1.5.0: mensaje accionable sin excepción
