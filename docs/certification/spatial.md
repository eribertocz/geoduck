# Extensión DuckDB `spatial` — plan de instalación y verificación

**Estado:** no verificada por ejecución (la sesión del implementador no tiene red hacia
`extensions.duckdb.org`, decisión D7). Este plan se ejecuta en el equipo Windows de certificación.

## 1. Qué es y qué necesita GeoDuck

- Extensión oficial y **firmada** de DuckDB (licencia MIT; enlaza GEOS LGPL-2.1, PROJ y GDAL MIT).
  GeoDuck **no** la redistribuye.
- En DuckDB ≥ 1.5 el tipo `GEOMETRY`, `ST_AsWKB`, `ST_CRS`, `ST_SetCRS` y el CRS `OGC:CRS84` funcionan
  **sin** spatial (verificado, evidencia F-05/F-10). Los CRS `EPSG:*` en el tipo, `ST_Transform`,
  `geometry_always_xy` y la mayoría de funciones `ST_*` requieren spatial (verificado: sin spatial,
  `GEOMETRY('EPSG:4326')` falla con «unrecognized coordinate system»).
- G0 no depende de spatial. G4 (Spatial Confidence) sí.

## 2. Dónde se instala

DuckDB guarda cada extensión por versión de DuckDB y plataforma:
`%USERPROFILE%\.duckdb\extensions\v<versión DuckDB>\windows_amd64\spatial.duckdb_extension`.
Consecuencia: **cambiar de DuckDB (p. ej. 1.5.6 → 2.0.0) exige reinstalar spatial** para la nueva
versión. El diagnóstico de GeoDuck informa el directorio efectivo (`extension_directory`).

## 3. Métodos de instalación

| Método | Cómo | Cuándo |
|---|---|---|
| S1 en línea, explícito | `INSTALL spatial; LOAD spatial;` desde el repositorio oficial. En certificación: `verify_env.py --install-spatial` | Equipos con salida a `extensions.duckdb.org` |
| S2 sin conexión | Descargar `https://extensions.duckdb.org/v<versión>/windows_amd64/spatial.duckdb_extension.gz` en otro equipo, copiarlo y ejecutar `INSTALL '<ruta>\spatial.duckdb_extension.gz'; LOAD spatial;` | Redes corporativas sin salida |
| S3 directorio propio | `SET extension_directory = '<carpeta de GeoDuck>'` antes de instalar | Solo si el propietario lo aprueba por ADR (aislamiento por perfil) |

En los tres, la **firma se verifica**: GeoDuck nunca activa `allow_unsigned_extensions`, nunca hace
`INSTALL`/`LOAD` silencioso desde un origen remoto y deja que la UI (G4) pida consentimiento explícito
(spec/docs/security.md §2, GD-SEC-001).

## 4. Verificación (en cada celda de certificación)

Ejecute con el Python de QGIS de la celda:

```powershell
<lanzador python-qgis*.bat> C:\geoduck\tools\verify_env.py --out C:\geoduck-cert\<celda>-spatial --only Spatial diagnostico --install-spatial
```

La comprobación «Spatial: instalación, carga, EPSG y orden de ejes» registra:

| Dato | Qué confirma |
|---|---|
| `version` | Versión de spatial cargada para esa versión de DuckDB |
| `epsg_type` | `GEOMETRY('EPSG:4326')` se reconoce con spatial cargada |
| `transform` | `ST_Transform` de La Paz (−68,15; −16,5) de EPSG:4326 a EPSG:32719. Compare con QGIS (contradicción C4 y orden de ejes) |
| `geometry_always_xy` | Si el ajuste existe y su valor por defecto en 1.5.x y 2.x |
| `geoarrow_crs_epsg_32719` | La exportación GeoArrow incluye el CRS EPSG en sus metadatos (ADR-0008) |

Repita con DuckDB 1.5.0, 1.5.6 y 2.0.0. Cada versión instala su propio binario de spatial.

**Contraste del orden de ejes.** En QGIS, `EPSG:4326` tiene `hasAxisInverted() == True` y
`OGC:CRS84` no (verificado en QGIS 3.34, 3.44 y 4.2). Si `transform` devuelve las coordenadas
intercambiadas respecto de lo que QGIS espera, se documenta como hallazgo para G4. No se corrige en
silencio.

## 5. Desinstalación

Borre `spatial.duckdb_extension` de la carpeta indicada en el diagnóstico (o toda la carpeta
`v<versión>\windows_amd64`). DuckDB no mantiene otro registro.

## 6. Resultado esperado para cerrar G0

- Spatial carga en Windows para al menos una versión de DuckDB por cada QGIS ancla, **o**
- la limitación queda documentada y el propietario la acepta explícitamente (criterio del gate G0).
