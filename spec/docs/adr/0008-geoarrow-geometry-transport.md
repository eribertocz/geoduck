# ADR-0008: transporte de geometría y CRS con el esquema GeoArrow nativo

**Estado:** Aceptado (dictamen del arquitecto, 2026-11-01)
**Fase de implementación:** G3 (una geometría) y G4 (varias)

## Contexto

`spatial-spec` §5 pide generar una proyección SQL con `ST_AsWKB(...)` para transportar la geometría.
La auditoría G0 (F-10) mostró que:

- Al leer una relación con `to_arrow_reader()`, DuckDB 1.5.0+ exporta las columnas `GEOMETRY` como
  campos `binary` con la extensión `geoarrow.wkb` y el CRS en PROJJSON dentro de
  `ARROW:extension:metadata`.
- `ST_AsWKB(geom)` produce `binary` **sin** esos metadatos: descarta el CRS.
- `QgsCoordinateReferenceSystem.createFromUserInput(<PROJJSON>)` reconstruyó `OGC:CRS84` en QGIS 3.44 y
  4.2 (`createFromString` falló).

## Decisión

1. Para columnas `GEOMETRY`, GeoDuck lee la relación tal cual y usa los metadatos GeoArrow del esquema
   Arrow como fuente primaria de tipo y CRS. No introduce conversiones SQL que descarten metadatos.
2. La resolución de CRS sigue el orden de `spatial-spec` §4, donde «CRS asociado al tipo» se obtiene
   de la PROJJSON GeoArrow. Una columna sin CRS (`metadata = {}`) sigue siendo «CRS desconocido»;
   nunca se asume EPSG:4326.
3. `ST_AsWKB` queda solo como alternativa explícita para tipos espaciales que DuckDB no exporte como
   GeoArrow, y se documenta que pierde el CRS.
4. La lectura usa `to_arrow_reader()`, no `to_arrow_table()` (F-04 en 1.5.0–1.5.3).
5. No se impone `ST_AsWKB` ni se añade ninguna extensión o paquete adicional (p. ej. `duck_geoarrow`): basta
   la exportación GeoArrow que DuckDB ya hace (dictamen del 2026-11-01).

## Consecuencias

- Pro: se preserva el CRS de extremo a extremo y se evita una reescritura del SQL del usuario.
- Contra: dependemos del formato de metadatos GeoArrow; se cubre con tests por versión de DuckDB.

## Verificación

Tests G3/G4: columna con CRS (`OGC:CRS84`, EPSG con spatial), sin CRS, dos columnas, nulos; comparación
del CRS resultante en QGIS 3 y 4.
