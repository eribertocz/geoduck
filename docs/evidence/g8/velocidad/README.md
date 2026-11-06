# G8 · Velocidad publicada de «Enviar a DuckDB» (E5)

Envío real de GeoDuck (`LayerSender` → `LayerImport`: `QgsTask` que lee la capa, lotes Arrow de 50 000 y una
transacción en el worker) de un GeoPackage de puntos con tres campos (entero, texto, real) en EPSG:32719, a una
sesión en memoria. Se mide desde «Enviar» hasta `SendFinished`, conteo incluido.

- **general**: camino general (§5.3), la capa GeoPackage leída por QGIS.
- **conectada**: la misma tabla cargada como capa Conectada y enviada (§5.1): DuckDB copia sin pasar por QGIS.

Máquina: contenedor Linux de 2 núcleos y 7 GB, QGIS de conda-forge sin pantalla. Reproducir:

```bash
QT_QPA_PLATFORM=offscreen python bench_send.py /tmp/g8vel 100000 1000000
```

| QGIS · DuckDB | general 100 mil | general 1 millón | conectada 1 millón |
|---|---|---|---|
| 3.34.6 · 2.0.0 | 0,78 s (128 mil/s) | 8,30 s (121 mil/s) | 0,10 s |
| 3.44.14 · 2.0.0 | 0,71 s (141 mil/s) | 5,74 s (174 mil/s) | 0,05 s |
| 3.44.14 · 1.5.0 | 0,62 s (162 mil/s) | 6,35 s (157 mil/s) | 0,31 s |
| 4.2.3 · 2.0.0 | 0,66 s (152 mil/s) | 5,88 s (170 mil/s) | 0,05 s |

Salidas completas: `q334-duckdb2.0.0.txt`, `q344-duckdb2.0.0.txt`, `q344-duckdb1.5.0.txt`, `q42-duckdb2.0.0.txt`.

**Lectura.** El camino general va a 120–175 mil entidades por segundo, por encima de la cifra prudente de
100 mil/s con la que el diálogo estima y avisa de una «capa grande» (más de un minuto, qgis-import-spec §3):
el aviso queda del lado seguro. Coincide con el spike (F-114: 1 millón en 5–7 s). La lectura de QGIS es la
mayor parte del tiempo; una capa Conectada no la necesita y se copia en décimas de segundo.
