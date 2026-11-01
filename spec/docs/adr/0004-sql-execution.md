# ADR-0004: editor con SQL DuckDB completo y resultados por sentencia

**Estado:** Aceptado para Alpha · **Fecha:** 2026-11-01

## Contexto
El usuario exige cualquier sentencia soportada por DuckDB, scripts mixtos (`CREATE`, `ATTACH`, `SELECT`) y selección explícita de qué resultado cargar en QGIS.

## Decisión
DuckDB parsea y ejecuta scripts secuencialmente, un estado por sentencia y una pestaña por resultado. Las lecturas usan API relacional cuando es útil; DDL/DML y administración, Connection API. Cargar a QGIS es acción separada.

## Consecuencias
- No elegir arbitrariamente primer/último SELECT.
- No ejecutar de nuevo DDL/DML ni `RETURNING` para generar capas.
- Para SELECT replayable, reejecutar sólo la consulta con aviso de estado actual. Si el origen ya no existe, error claro.
- Las previas no equivalen a datasets completos ni snapshots inmutables.
- Advertencia que SELECT puede contener funciones de efectos secundarios o depender de orden mutable.

## Verificación
AT-SQL-001..007 y test adversarial `INSERT RETURNING`.
