---
title: "GD-4 · Session Worker con propiedad exclusiva de la conexión"
labels: type/feature,area/engine,P0
milestone: v0.1.0a1
---
## Entregable
Hilo propietario, cola serial, guardia de resultado abierto (F-01), lectura completa solo si se agota el lector, cancelación cooperativa + interrupt() verificado (ADR-0006/0007).

## Requisitos
GD-SES-001, AT-SES-001

## Rama
`feat/GD-3-4-domain-engine`

## Criterios de aceptación
- [ ] AT-SES-001 en DuckDB 1.5.0, 1.5.6 y 2.0.0
- [ ] Regresión F-01 y 4 hilos × 200 operaciones sin fallo
