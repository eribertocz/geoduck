# Evidencia C4 — orden de ejes entre DuckDB y QGIS

`qgis_axis.py` crea con DuckDB un WKB de `POINT(-68.15 -16.5)` (longitud, latitud de La Paz), lo carga en
capas memory de QGIS con CRS `EPSG:4326` y `OGC:CRS84`, y lo transforma con QGIS a `EPSG:32719`.

| Entorno | Resultado |
|---|---|
| QGIS 3.44.14 (conda-forge, Linux), DuckDB 2.0.0 | `result_q344.json` |
| QGIS 4.2.3 (conda-forge, Linux), DuckDB 2.0.0 | `result_q42.json` |

En ambos, y para ambos CRS, QGIS conserva x = −68,15 e y = −16,5, y la transformación da
`590716.04, 8175564.99`: el mismo resultado que `ST_Transform` de DuckDB 2.0.0 con el orden de ejes
declarado, observado en Windows (`../windows/win11-qgis-3.34.15/` §4). Para `EPSG:4326`,
`hasAxisInverted()` es `True`, pero QGIS trata igualmente x como longitud.

Reproducir: `QT_QPA_PLATFORM=offscreen python qgis_axis.py` dentro de un Python con QGIS y DuckDB.

## CRS ausente y desconocido

`qgis_crs_unknown.py` exporta desde DuckDB el mismo punto sin CRS, con `OGC:CRS84` y con un CRS inventado
(`FOO:123`), y lo carga en QGIS. Resultado en QGIS 3.44.14 + DuckDB 2.0.0: `result_crs_q344.json`.
Sin CRS y con `FOO:123`, QGIS deja la capa con CRS no válido (no inventa uno) y las coordenadas no cambian.
Reproducir: `QT_QPA_PLATFORM=offscreen python qgis_crs_unknown.py`.
