# ADR-0003: API Relacional + Arrow por lotes como puente QGIS

**Estado:** Aceptado sujeto a spike técnico G3 · **Fecha:** 2026-11-01

## Contexto
El producto pide explotar DuckDB >=1.5 y aprovechar la ejecución lazy, sin copiar resultados completos a pandas para llevarlos a QGIS.

## Decisión
Para consultas de lectura: `con.sql(...)` y `relation.to_arrow_reader(batch_size=...)`. Los lotes se convierten a entidades de una capa QGIS de memoria; PyQGIS se manipula solo en hilo principal. Transferencia privada y commit al final.

## Tradeoffs
Pro: menor materialización intermedia, contratos de tipo Arrow, cancelación y progreso por lotes.

Contra: no es zero-copy; QGIS memory conserva entidades y puede agotar RAM. En DuckDB 1.5.x/2.x los readers abiertos ocupan su conexión. Complejidad de backpressure y worker/GUI.

## Verificación
AT-BRD-001..005, benchmarks de latencia/memoria y test de UI responsiva. El spike G3 puede ajustar batch sizes/worker strategy, no la propiedad de capa.
