# Import files

<span class="gd-time">2 minutes</span>

1. Drag the files onto a database in the explorer, or "+" › **Import files…**
2. Check the table names and click **Send**.

GeoDuck reads CSV, Parquet and JSON directly and, with the spatial extension, GeoPackage, Shapefile, GeoJSON
and other GDAL formats.

## Query without importing

Drop a file into the **editor**: GeoDuck writes `FROM 'path';` (or `FROM ST_Read('path');`) without running it.
That way you query the file without creating a table:

```sql
SELECT * FROM read_csv('C:/data/readings.csv', delim = ';');
```
