# ADR-0015 — Enviar capas de QGIS a DuckDB (copia puntual)

**Estado:** Aceptado (propietario, 2026-11-05) · **Fase:** G8 · `v0.9.0a1` · **Contrato:** qgis-import-spec
**Relacionados:** ADR-0002 y ADR-0012 (DuckDB → QGIS), ADR-0006 (worker), ADR-0008 (GeoArrow), ADR-0011.

## Contexto
GeoDuck lleva datos de DuckDB a QGIS (G3–G4), pero no el camino inverso. La SPEC lo excluía («importación
bidireccional QGIS→DuckDB … requiere ADR y decisión del propietario»). El propietario lo pide como la pieza
más importante para que GeoDuck sea una estación de análisis: llevar capas del proyecto a DuckDB, unirlas con
sus tablas y devolver el resultado al mapa.

## Decisión
- **Copia puntual**, nunca sincronización: crear, reemplazar o ampliar tablas (o una vista sobre un Parquet)
  en una base de la sesión en escritura. La capa de QGIS no cambia y no queda vínculo.
- **Una transacción** por envío en la base destino: todo o nada, con conteo final.
- **Tres caminos**, elegidos por el origen: capa Conectada → SQL dentro de DuckDB; Parquet → `read_parquet`;
  el resto → `QgsTask` que lee entidades y lotes Arrow que el worker inserta (único dueño de la conexión,
  ADR-0006).
- **SRC con `ST_SetCRS`** del núcleo de DuckDB, sin `spatial`; sin SRC expresable, decisión explícita del
  usuario (C4).
- Por defecto, **nunca sobrescribir**: si la tabla existe, «No enviar» hasta que el usuario elija otra cosa.

## Alternativas rechazadas
- **Leer el archivo de la capa con extensiones de DuckDB** (`spatial`/`ST_Read`, `sqlite`): exigiría
  cargarlas o instalarlas (ADR-0011) y no sirve para PostGIS ni capas en memoria.
- **Exportar a un archivo temporal y leerlo** (GeoPackage o Parquet en disco): doble escritura, archivos que
  limpiar y el mismo problema de extensiones para leerlos.
- **Sincronización QGIS ↔ DuckDB:** otra frontera de responsabilidades; sigue fuera de alcance.

## Consecuencias
- El camino general convierte cada entidad en Python: su velocidad se mide en el spike G8-A y se publica; no
  se promete una cifra antes.
- Nombres de campo: DuckDB no distingue mayúsculas; los choques se renombran con aviso.
- Reemplazar o añadir no se pueden deshacer desde GeoDuck: el diálogo lo advierte antes.
