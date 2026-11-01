# Evidencia Windows · QGIS 3.34.15 LTR · 2026-11-01

Primera ejecución de GeoDuck en Windows real, en el equipo del propietario y guiada paso a paso por el
implementador. Las salidas se transcriben **tal como se obtuvieron**; solo se reemplazó el nombre de la
carpeta de usuario por `<usuario>`.

- **Alcance:** prueba de humo manual (*smoke*), no certificación completa: no se ejecutaron las suites
  `pytest` en Windows y se probó una sola versión de DuckDB (2.0.0).
- **Build probado:** código de `main` en `890a0a6` (merge del PR #19), empaquetado con
  `tools/build_zip.py`, con una única diferencia: `qgisMinimumVersion=3.34` en lugar de `3.44`
  (decisión D8, tomada durante esta misma prueba).
  SHA-256 del ZIP probado: `7dc6248845958317eebf6df84ada253521cbb3a31d309196ee08a5eb29155bb7`, idéntico al
  que genera `tools/build_zip.py` en esta rama (el ZIP es reproducible).

## 1. Entorno

| Dato | Valor |
|---|---|
| Sistema | Windows 11 AMD64 |
| QGIS | 3.34.15-Prizren (LTR), instalada sobre una carpeta llamada `QGIS 3.22.9` |
| Qt / PyQt | 5.15.13 / 5.15.11 |
| Python | 3.12.8, 64 bits (`apps\Python312`) |
| NumPy de QGIS | 1.26.4 |
| PyArrow de QGIS | **18.1.0** (incluida en la instalación de QGIS) |
| Complementos activos | MetaSearch, cartodruid_sync, db_manager, layerfromclipboard, processing, **qduckdb** |
| DuckDB previo | 1.4.4, **incrustado por el complemento QDuckDB** en su carpeta (`plugins\qduckdb\embedded_external_libs\duckdb`) |

## 2. Instalación de dependencias (lo que pasó realmente)

1. Se ejecutó `!pip install duckdb pyarrow numpy --upgrade` en la consola de QGIS. Como `site-packages`
   de QGIS no es escribible, pip instaló en el *user site*
   (`C:\Users\<usuario>\AppData\Roaming\Python\Python312\site-packages`):
   `duckdb-2.0.0`, `pyarrow-26.0.0`, `numpy-2.5.4`, y avisó:
   `scipy 1.13.0 requires numpy<2.3,>=1.22.4, but you have numpy 2.5.4 which is incompatible.`
2. Reversión: `!pip uninstall -y numpy pyarrow` y luego `!pip install --user --no-deps pyarrow==25.0.1`.
3. Tras reiniciar QGIS, `import pyarrow` cargó la 25.0.1 del *user site* y falló:

   ```
   File "C:\Users\<usuario>\AppData\Roaming\Python\Python312\site-packages\pyarrow\__init__.py", line 71, in <module>
     from pyarrow.lib import (BuildInfo, CppBuildInfo, RuntimeInfo, set_timezone_db_path,
   ImportError: DLL load failed while importing lib: No se encontró el proceso especificado.
   ```
4. `!pip uninstall -y pyarrow` y `!pip list --user` → en el *user site* solo queda `duckdb 2.0.0` de lo
   relevante.
5. Con QDuckDB desactivado y QGIS reiniciado:

   ```
   numpy 1.26.4 C:\PROGRA~1\QGIS32~1.9\apps\Python312\Lib\site-packages\numpy\__init__.py
   pyarrow 18.1.0 C:\PROGRA~1\QGIS32~1.9\apps\Python312\Lib\site-packages\pyarrow\__init__.py
   duckdb 2.0.0 C:\Users\<usuario>\AppData\Roaming\Python\Python312\site-packages\duckdb\__init__.py
   ```

## 3. GeoDuck

- Instalación desde ZIP (Complementos → Instalar a partir de ZIP): **sin errores**.
- Diagnóstico del panel (copiado con el botón «Copiar»):

```
Diagnóstico de GeoDuck

GeoDuck: 0.1.0a1
Python: 3.12.8
Ejecutable: C:\Program Files\QGIS 3.22.9\bin\qgis-ltr-bin.exe
Plataforma: Windows 11 AMD64
ABI: .cp312-win_amd64.pyd
Bits: 64
QGIS: 3.34.15-Prizren
Qt: 5.15.13
PyQt: 5.15.11
NumPy: 1.26.4

[OK] Python de QGIS: Python 3.12.8, 64 bits
[OK] QGIS: QGIS 3.34.15-Prizren, Qt 5.15.13, PyQt 5.15.11
[OK] DuckDB: DuckDB 2.0.0
[OK] PyArrow: PyArrow 18.1.0
[OK] Extensión spatial: Cargable (a3dbcd1781)
[WARN] Paquetes del usuario: duckdb se cargan desde C:\Users\<usuario>\AppData\Roaming\Python\Python312\site-packages, fuera de la instalación de QGIS (conflicto conocido, QGIS issue #63733).
       → Elimine esos paquetes del site de usuario o defina PYTHONNOUSERSITE=1 para QGIS.

Resultado: utilizable
```

- «Iniciar sesión» → estado **«Lista»**, «DuckDB 2.0.0 · cancelación inmediata disponible»
  (`01_sesion_lista.png`).
- «Cerrar sesión» → estado **«Sin sesión»** (`02_sesion_cerrada.png`).

## 4. Extensión spatial (DuckDB 2.0.0, ya instalada en el equipo)

```
epsg: GEOMETRY('EPSG:4326')
```

`ST_Transform` sin indicar el orden de ejes:

```
_duckdb.Error: 'ST_Transform' is sensitive to the coordinate axis order of the input geometry.
Unless 'geometry_always_xy' is enabled, the axis order of the input geometry is assumed to be the same as defined by the source CRS.
E.g., EPSG:4326 expects [NORTHING, EASTING] (= LATITUDE, LONGITUDE).
Alternatively, pass 'true' or 'false' as the last optional 'always_xy' parameter to override this per-call.
In DuckDB v2.0, the 'geometry_always_xy' setting must be set explicitly to use this functionality.
In DuckDB v2.1, 'geometry_always_xy = true' will become the default.
```

Con el orden explícito por llamada:

```
xy (lon,lat): POINT (590716.0415307175 8175564.990768843)
no xy (lat,lon): POINT (590716.0415307175 8175564.990768843)
```

Lectura del ajuste:

```
current_setting('geometry_always_xy') → CatalogException: Setting with name "geometry_always_xy" is not in the catalog, but it exists in the spatial extension.
duckdb_settings() → [('geometry_always_xy', None, 'BOOLEAN')]
crs geoarrow: True   (GEOMETRY('EPSG:32719') exporta el CRS en los metadatos GeoArrow)
```

## 5. Con QDuckDB activo

QDuckDB reactivado y QGIS reiniciado: el diagnóstico es idéntico al de §3 (**DuckDB 2.0.0** desde el
*user site*) y la sesión de GeoDuck inicia («Lista», `03_con_qduckdb_activo.png`). En este equipo y este
orden de carga, la copia del *user site* prevaleció, de modo que **QDuckDB pasó a ejecutarse con DuckDB
2.0.0** en lugar de su 1.4.4 incrustada. No se verificó el funcionamiento de QDuckDB en esa situación.

## 6. Hallazgos

| ID | Hallazgo | Consecuencia |
|---|---|---|
| F-13 | En QGIS para Windows (OSGeo4W), una PyArrow distinta de la incluida por QGIS (18.1.0) falla con `DLL load failed … No se encontró el proceso especificado`. La causa probable es que la DLL de Arrow que trae QGIS ya está cargada en el proceso con otra versión | En QGIS Windows se usa la PyArrow de QGIS; GeoDuck solo instala `duckdb`. Verificado en Linux que GeoDuck funciona con PyArrow 18.1.0 + NumPy 1.26.4 + DuckDB 2.0.0 (108 pruebas) |
| F-14 | En DuckDB 2.0 + spatial, `ST_Transform` exige el orden de ejes explícito (ajuste `geometry_always_xy` sin fijar, `None`); en 2.1 pasará a `true` por defecto. El ajuste se lee con `duckdb_settings()`, no con `current_setting()` | Resuelve la contradicción C4. GeoDuck no fija el ajuste en silencio; G4 decidirá cómo informarlo |
| F-15 | `pip install … --upgrade` sin `--no-deps` instaló NumPy 2.5.4 en el *user site*, por encima de la NumPy 1.26.4 de QGIS, rompiendo la compatibilidad declarada de scipy | Las instrucciones de instalación usan siempre `--no-deps` y nunca instalan NumPy |
| R11 | Un complemento que incrusta otra versión de DuckDB (QDuckDB 1.4.4) comparte el proceso con GeoDuck: solo puede haber un `duckdb` cargado y prevalece el primero según el orden de carga | Riesgo nuevo para el arquitecto: el diagnóstico debe advertirlo |
| — | El aviso de *user site* es demasiado amplio: DuckDB en el *user site* es un método de instalación válido; el riesgo real son NumPy y PyArrow | Ajuste del diagnóstico |

## 7. Resultado por criterio

| Criterio | Resultado |
|---|---|
| AT-BOOT-001: el panel abre en QGIS 3 (Qt5) | ✅ |
| AT-BOOT-002: diagnóstico accionable en Windows | ✅ (con el ajuste pendiente del aviso de *user site*) |
| GD-SES-001: iniciar y cerrar sesión `:memory:` | ✅ |
| Spatial: carga, CRS EPSG, transformación, GeoArrow | ✅ (con orden de ejes explícito, F-14) |
| Suites pytest en Windows, DuckDB 1.5.x, QGIS 4.x, método M2 | ⏳ no ejecutado |
