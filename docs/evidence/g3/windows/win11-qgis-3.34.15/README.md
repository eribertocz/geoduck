# Evidencia G3 · Windows 11 · QGIS 3.34.15 · GeoDuck 0.4.0a1 → 0.4.0a2

**Fecha:** 2026-11-02. **Quién:** el propietario, en su equipo, de forma manual y guiada.
**Tipo:** prueba funcional manual. **No sustituye** a la certificación con el procedimiento de
[`docs/certification/windows.md`](../../../../certification/windows.md) (#10).

## Entorno (diagnóstico de GeoDuck, copiado del panel)

```
GeoDuck: 0.4.0a1
Python: 3.12.8
Ejecutable: C:\Program Files\QGIS 3.22.9\bin\qgis-ltr-bin.exe
Plataforma: Windows 11 AMD64
QGIS: 3.34.15-Prizren · Qt 5.15.13 · PyQt 5.15.11
DuckDB desde: C:\Users\<usuario>\AppData\Roaming\Python\Python312\site-packages\duckdb\__init__.py
NumPy: 1.26.4 · PyArrow 18.1.0 (los de QGIS)
[OK] DuckDB 2.0.0 (site de usuario) · [OK] PyArrow 18.1.0 · [OK] spatial: cargable
Resultado: utilizable
```

La carpeta de instalación se llama «QGIS 3.22.9», pero la versión es 3.34.15. DuckDB está instalado con
`pip install --user --no-deps duckdb==2.0.0` (método M3, el de la evidencia de G0).

## Recorrido

| Paso | 0.4.0a1 | 0.4.0a2 |
|---|---|---|
| Instalar desde ZIP, diagnóstico | Utilizable | Utilizable |
| Sesión en memoria, SQL (CREATE + SELECT de 1000 puntos) | Correcto | Correcto |
| Cargar como copia en memoria | Correcto | Correcto |
| Cargar como copia rápida (GeoPackage `/vsimem`) | Correcto | Correcto |
| Cargar como conectada | **Falla: «Data source invalid»** (F-81) | Correcto |
| Adjuntar una base `.duckdb` en lectura y escritura; tabla real de 1 141 829 filas | — | Carga correcta; sin extensión hasta corregir F-83 |
| Capa → Filtrar… en la capa conectada | **No disponible** (F-84) | Correcto |
| Doble clic en el explorador y mensajes de carga | — | Correcto (aprobados por el propietario) |
| Edición de la capa conectada (tabla cargada desde el explorador): cambio de atributo y de geometría, guardar y comprobar en SQL | — | Correcto (confirmado por el propietario, 2026-11-02) |

## Hallazgos

| ID | Hallazgo | Resolución |
|---|---|---|
| F-81 | La capa conectada usaba API de QGIS 3.36+/3.40+ (`Qgis.VectorProviderCapability`, `Qgis.FeatureRequestFlag`/`FilterType`, `Qgis.DataProviderReadFlags`, `QgsFeatureRequest.calculateTransform`). En 3.34 el proveedor quedaba inválido. La CI no probaba la versión mínima | `qgis_bridge/qgis_compat.py`; la CI pasa a probar 3.34.6, 3.40.3, 3.44.14 y 4.2.3 (#66) |
| F-82 | QGIS 3.34 asigna en silencio un SRC a un GeoPackage cuya geometría no lo tiene | Copia rápida: SRC vacío explícito y aviso «Sin SRC asignado» (C4) (#66) |
| F-83 | Con geometrías vacías (`POINT EMPTY`), `stats(geom)` de DuckDB da extensión `-inf…inf`: capa conectada sin extensión | Si las estadísticas no sirven, se recorre la geometría una vez (1,14 M de puntos: 4,4 s) (#66) |
| F-84 | El proveedor `geoduck` no admitía el filtro de capa (`subsetString`) | Filtro en SQL de DuckDB, comprobado antes de aplicarse y guardado en la fuente (#66) |
| F-85 | El usuario cargó `SELECT * FROM db.tabla` esperando poder editar; el aviso de solo lectura no explicaba cómo | Mensajes con origen y acceso; doble clic en el explorador (#66, #67) |

## Pendiente para la certificación (#10)

- Ejecutar el procedimiento de `docs/certification/windows.md` en esta celda (3.34) y en 3.44 y 4.2.
- DuckDB 1.5.0 y 1.5.6 en Windows (aquí solo 2.0.0).
- En Windows se confirmó editar y guardar. Altas, bajas y el aviso de conflicto quedan cubiertos solo por
  las pruebas automáticas en Linux.
