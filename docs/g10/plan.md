# G10 · `v0.11.0a1` Rendimiento — plan

**Estado:** Propuesta (E0), pendiente de aprobación. **Requisitos:** GD-PERF-001..006 (detallan GD-BRD-003 y
GD-QA-001). **Contrato:** `spec/specs/performance-spec.md`; protocolo `spec/qa/benchmarks.md`.

**Gate:** AT-PERF-001..006 en la matriz de CI (QGIS 3.34, 3.40, 3.44, 4.2 × DuckDB 1.5.0, 2.0.0); línea base
publicada; estrés de 1 h sin cierres; guía manual en Windows con los números del equipo del propietario;
regresiones G0–G9. Tag y release `v0.11.0a1` solo los hace el propietario.

## 1. Entregas (un PR cada una)

| Entrega | Trabajo | Pruebas |
|---|---|---|
| **E0** | SPEC (performance-spec), requisitos GD-PERF, roadmap, este plan | `spec_sync --check` |
| **E0b** | Spike G10-A: cancelación por tipo de operación en DuckDB 1.5 y 2.0; bloqueos de la interfaz y RAM pico con la interfaz real; casos que no responden | Medidas en `docs/evidence/g10/spike/` |
| **E1** | Banco de medidas `tools/perf/` (T1–T7) y línea base; trabajo informativo de la CI | AT-PERF-001 |
| **E2** | Cancelación robusta: «Cancelar» en todo lo largo, puntos de control, sin restos | AT-PERF-002 |
| **E3** | Memoria: presupuesto por transferencia, aviso con alternativa, `temp_directory` de la sesión, «Diagnóstico» | AT-PERF-003 |
| **E4** | Interfaz sin bloqueos: lo pesado fuera del hilo de la interfaz, primera apertura de tabla ≤ 100 ms, F-129 | AT-PERF-004 |
| **E5** | Estrés de 1 h y datos rotos (T7) | AT-PERF-005 |
| **E6** | Aceptación: `docs/performance.md`, guía de Windows con números, versión `0.11.0a1` | AT-PERF-006; gate |

## 2. Preguntas para el propietario (E0)

1. **Cancelar:** ¿meta p95 ≤ 1 s desde el clic? (alternativas: 0,5 s más exigente, 2 s más holgada)
2. **Interfaz:** ¿bloqueos p95 ≤ 50 ms y máximo ≤ 200 ms durante transferencias?
3. **Memoria:** ¿presupuesto por transferencia = mitad de la RAM libre, con aviso y «Conectada»/«Exportar»? ¿y
   `temp_directory` de GeoDuck para que DuckDB use disco en vez de fallar?
4. **Equipo de referencia:** además de la CI, ¿medimos en tu Windows con la guía (una tabla de números al final)?

## 3. Avance

| Entrega | Estado | PR |
|---|---|---|
| E0 SPEC, requisitos, roadmap y plan | En revisión | — |
