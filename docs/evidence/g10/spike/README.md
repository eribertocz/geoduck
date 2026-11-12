# Spike G10-A · medidas (2026-11-12)

`tools/perf/spike_g10a.py` con DuckDB real, **10 millones de filas**, base en disco, 2 núcleos (contenedor Linux
de desarrollo; no es el equipo de la CI ni Windows: sirve para decidir el diseño, no como línea base). Una corrida
por versión; JSON completos en `duckdb-2.0.0.json` y `duckdb-1.5.0.json`.

## 1. Resultados de consulta: ¿repetir o guardar? (performance-spec §8)

Consulta barata (filtro simple, 9,5 millones de filas de resultado):

| | DuckDB 2.0.0 | DuckDB 1.5.0 |
|---|---|---|
| Ejecutarla entera (sin guardar) | 0,12 s | 0,15 s |
| Guardarla en una tabla temporal | 0,37 s | 0,63 s |
| Hoy: última página con `OFFSET` (repite la consulta) | 0,09 s | 0,17 s |
| Propuesto: cualquier página por `rowid` del resultado guardado | 1,5 ms | 3,7 ms |
| Propuesto: total | 1 ms | 1 ms |

**Conclusión honesta:** guardar **siempre** no es lo mejor. En una consulta barata, guardar cuesta 3–4 veces la
ejecución (no cumple la meta de ≤ 15 %) y repetirla ya es rápido (< 0,2 s). En una consulta cara (uniones,
agregados: segundos o minutos), repetirla por página es justo lo que hay que evitar, y leer del resultado guardado
tarda 1–4 ms. → **Diseño adaptativo** (SPEC §8 actualizada): primera página por flujo; se guarda solo si la
consulta resultó cara.

## 2. Tablas: `OFFSET` frente a `rowid` (performance-spec §9)

Fila 9 000 000: `OFFSET` 4–7 ms; `rowid` 1–3 ms. Las dos cumplen ≤ 100 ms con 10 millones; `rowid` no crece con la
posición, así que es la que escala a 100 millones.

## 3. Cancelar con `interrupt()` desde otro hilo (performance-spec §3)

Peor caso de 5 intentos, desde `interrupt()` hasta que la consulta se detiene:

| Operación | DuckDB 2.0.0 | DuckDB 1.5.0 |
|---|---|---|
| Unión pesada | 12–103 ms | 347–625 ms |
| `CREATE TABLE AS` | 21–39 ms | 4 ms |
| `COPY … TO` Parquet | 95–159 ms | 136–144 ms |
| `ORDER BY` de 10 millones | 38–42 ms | 26–28 ms |

- Todas terminan con `InterruptException` y la conexión responde después (`SELECT 42`). La meta p95 ≤ 1 s es
  alcanzable en las dos versiones; el margen menor está en uniones pesadas con 1.5.
- **Hallazgo F-133:** con DuckDB 1.5.0, un `COPY … TO` cancelado **deja el archivo a medias** en disco (2.0.0 lo
  borra). GeoDuck ya exporta a una carpeta temporal y mueve al final (#130), así que el usuario no lo ve; E2 añade
  la prueba que lo fija.

## 4. Pendiente del spike (necesita QGIS; va en E1 con el banco)

Bloqueos del hilo de la interfaz y RAM pico durante las transferencias; cancelación de la lectura por lotes hacia
QGIS, de `ST_Read` y de PyArrow.
