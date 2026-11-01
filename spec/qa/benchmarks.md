# GeoDuck — Protocolo de benchmarks y perfiles

**Estado:** plan experimental; **no contiene resultados medidos**.

## 1. Propósito
Medir DuckDB SQL, Arrow, conversión a entidades QGIS, memoria, responsividad, cancelar y `DETACH`. No publicar afirmaciones de desempeño antes de ejecutarlas en condiciones reproducibles.

## 2. Equipo y entorno registrados
OS exacto; CPU núcleos/frecuencia; RAM; SSD; QGIS versión y Qt; Python `sys.version`/ABI; DuckDB; PyArrow; GeoDuck commit; tamaños de batch; `threads`, `memory_limit`, temperatura/carga; estado caché caliente/fría.

## 3. Generadores reproducibles
- T1: 100k filas tabulares simples (INT/DOUBLE/VARCHAR/NULL).
- T2: 1M filas con 10 columnas (fechas, DECIMAL, strings, NULL).
- T3: 100k / 1M puntos WKB, CRS declarado.
- T4: 100k polígonos (varios vértices); registrar tamaño total en bytes.
- T5: 2 geometrías por fila (POINT + POLYGON), 100k.
- T6: 1M+ filas agregadas por SQL a ~1k resultados (medir pushdown y puente).
- T7: datos inválidos en posición parametrizable para atomicidad.

Scripts deterministas con semilla fija, verificaciones de checksums/filas y dataset checksum en cada corrida. Datos de prueba artificiales: no usar datos sensibles.

## 4. Métricas
1. **Latencia de preparación** de relación y esquema.
2. **Tiempo de primera preview** (200 filas).
3. **Tiempo total de carga QGIS**, subdividido DuckDB query, Arrow, convertir y `addFeatures`/commit.
4. Throughput filas/s y MB/s en las fases medibles.
5. RAM pico QGIS, memoria worker y backlog Arrow.
6. Responsividad: latencia de eventos UI mientras transfiere (p95/p99 mediante harness).
7. Tiempo hasta cancelación cooperativa y cleanup.
8. Tiempo `DETACH` y prueba de apertura externa RW después de liberar referencias.
9. Integridad de filas/campos/CRS y errores (siempre 0 pérdidas silenciosas).
10. Tiempo instalación limpia y tiempo apertura del panel.

## 5. Método
- Warm-up 1 corrida por variante; >= 5 corridas medidas; mediana y p95; repetir en condiciones fijas.
- Comparar batch sizes 4k, 8k, 16k, 32k, 64k, 128k; escoger por rendimiento **y** capacidad de respuesta, no únicamente throughput.
- Baseline directo DuckDB `relation.to_arrow_reader` separado del overhead GeoDuck→QGIS.
- No usar `fetchall()` de todas las filas en tests de producción.
- Inspeccionar memory peak y tasa de eventos; invalidar corridas con swapping masivo o proceso externo saturando disco.

## 6. Gates de desempeño
No fijar metas universales de millones de filas/s sin datos. Inicialmente:
- 0 crash, 0 fila silenciosamente omitida, 0 capa publicada incompleta.
- Aceptación de cancelación en el siguiente punto seguro definido; latencia observada se publica.
- En equipo/control fijos, una regresión de mediana mayor al 20% en tiempo de transferencia exige investigación/justificación o rollback del cambio. No mezclar mediciones entre hardware o versiones QGIS distintas.
- Presupuesto RAM por tamaño de dataset debe documentarse; si se supera RAM disponible, abortar informando, no prometer carga ilimitada.
- Los valores de referencia se incorporarán al repositorio con evidencia del primer gate E2E.

## 7. Resultados y artefactos
Guardar `json`/`csv` de métricas, commit, archivos de fixture, entorno, gráficos de evolución y comparación por QGIS 3/4. Un benchmark sin número de repeticiones, versión y hardware no respalda una decisión técnica.
