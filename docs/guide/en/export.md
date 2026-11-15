# Export

<span class="gd-time">2 minutes</span>

From a table or a result: **Export ▾** and choose the format: Parquet, GeoPackage or CSV in view, and under
"More formats ▸" FlatGeobuf, Arrow, JSON, Shapefile, GeoJSON, KML, FileGDB and Excel. Everything filtered is
exported, not only what you see. In CSV, geometry is written as text (WKT).

The timeline shows the progress. When done: **Open folder** or **Load in QGIS**. **Cancel** leaves no
half-written files.

With SQL too:

```sql
COPY (SELECT * FROM lecturas WHERE zona = 'South') TO 'C:/data/south.parquet' (FORMAT parquet);
```
