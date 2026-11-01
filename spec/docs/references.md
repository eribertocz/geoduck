# GeoDuck — Fuentes técnicas oficiales consultadas

**Fecha de consulta y corte de especificación:** 2026-11-01. Se priorizan documentación oficial de QGIS, DuckDB y Apache Arrow. Las referencias son fuentes para implementar; los requisitos `GD-*` son decisiones de producto.

| Ref | Tema y aplicación | URL |
|---|---|---|
| REF-01 | QGIS releases 4.2.3 / 3.44.15 | https://github.com/qgis/QGIS/releases |
| REF-02 | QGIS guía de instalación y versiones | https://qgis.github.io/QGIS-Website/resources/installation-guide/ |
| REF-03 | Migración de plugins a QGIS 4 y qgis.PyQt | https://plugins.qgis.org/docs/migrate-qgis4 |
| REF-04 | PyQGIS cookbook, memory layer | https://github.com/qgis/QGIS-Documentation/blob/master/docs/pyqgis_developer_cookbook/vector.rst |
| REF-05 | PyQGIS cookbook, tareas/hilos | https://documentation.qgis.org/testing/en/docs/pyqgis_developer_cookbook/tasks.html |
| REF-06 | DuckDB 2.0 API Python/migración | https://duckdb.org/docs/2.0/clients/python/migration |
| REF-07 | DuckDB 2.0 Relational API | https://duckdb.org/docs/2.0/clients/python/relational_api |
| REF-08 | DuckDB 2.0 exportación Arrow | https://www.duckdb.org/docs/2.0/guides/python/export_arrow |
| REF-09 | DuckDB ATTACH/DETACH | https://duckdb.org/docs/current/sql/statements/attach |
| REF-10 | DuckDB 2.0 Python DB-API y cursores | https://duckdb.org/docs/2.0/clients/python/dbapi |
| REF-11 | DuckDB tipos GEOMETRY, CRS | https://duckdb.org/docs/current/sql/data_types/geometry |
| REF-12 | DuckDB funciones espaciales ST_AsWKB | https://duckdb.org/docs/current/core_extensions/spatial/functions |
| REF-13 | DuckDB seguridad extensiones | https://duckdb.org/docs/current/operations_manual/securing_duckdb/securing_extensions |
| REF-14 | Apache Arrow/PyArrow instalación | https://arrow.apache.org/docs/python/install.html |
| REF-15 | PyPI paquetes oficiales DuckDB | https://pypi.org/project/duckdb/2.0.0/ |
| REF-16 | PyPI paquetes oficiales PyArrow | https://pypi.org/project/pyarrow/ |

## Notas de rigor
1. DuckDB 1.5.x y 2.x pueden diferir en el comportamiento de readers Arrow y sesiones. Probar bloqueo, cancelación y concurrencia para cada versión y aislar divergencias en un adaptador mínimo.
2. DuckDB 1.5+ dispone de geometrías con CRS tipado; no repetir documentación antigua como si todo GEOMETRY careciera de CRS.
3. Las páginas oficiales evolucionan: registrar commit, versión o fecha cuando una API cambie; el código debe testarse contra dependencias realmente fijadas.
4. Apache Arrow puede proporcionar wheels para una versión Python cuyo texto de compatibilidad oficial todavía no está actualizado. La prueba de import + ABI del Python de QGIS decide compatibilidad real.
5. La lista de releases de QGIS solo prueba que existe el binario; no prueba GeoDuck funcionando allí.

| REF-16 | DuckDB 1.5 Relational API | https://duckdb.org/docs/1.5/clients/python/relational_api |
| REF-17 | DuckDB Geometry y compatibilidad almacenamiento v1.5 | https://duckdb.org/docs/stable/sql/data_types/geometry |
