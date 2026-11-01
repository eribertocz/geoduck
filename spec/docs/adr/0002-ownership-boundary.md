# ADR-0002: QGIS es propietario de capas entregadas

**Estado:** Aceptado para Alpha · **Fecha:** 2026-11-01

## Contexto
El producto debe cargar tablas y consultas DuckDB en QGIS y permitir `DETACH` sin retirar o romper capas previamente cargadas.

## Decisión
La salida es una copia completa en `QgsVectorLayer(provider="memory")` independiente del origen. Tras registrar la capa en el proyecto QGIS, GeoDuck deja de administrarla, refrescarla o vincularla a DuckDB.

## Consecuencias
Pro: modelo mental sencillo; `DETACH` y cierre de GeoDuck no afectan capas; UI más pequeña.

Contra: uso RAM, sin actualización automática, riesgo inherente de datos temporales si QGIS se cierra sin guardar. La UI puede recordar al usuario que QGIS administra el guardado, sin asumirlo.

## Alternativa descartada
Proveedor dinámico DuckDB de QGIS. Puede evaluarse en una fase futura, pero cambiaría la frontera de responsabilidades y exige nuevo ADR.

## Verificación
AT-BRD-005 y AT-SES-004.
