# Exportar

<span class="gd-time">2 minutos</span>

Desde una tabla o un resultado: **Exportar ▾** y elige el formato: Parquet, GeoPackage o CSV a la vista, y en
«Más formatos ▸» FlatGeobuf, Arrow, JSON, Shapefile, GeoJSON, KML, FileGDB y Excel. Se exporta todo lo
filtrado, no solo lo que ves. En CSV, la geometría sale como texto (WKT).

La línea de tiempo muestra el avance. Al terminar: **Abrir carpeta** o **Cargar en QGIS**. **Cancelar** no deja
archivos a medias.

También con SQL:

```sql
COPY (SELECT * FROM lecturas WHERE zona = 'Sur') TO 'C:/datos/sur.parquet' (FORMAT parquet);
```
