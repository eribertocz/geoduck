# Performance

GeoDuck is made for large tables. A few ideas to make it even faster.

- **Look without copying.** Opening a table or a result only reads the visible rows. No need for `LIMIT`.
- **Connected for large tables.** The layer only reads what is visible on the map.
- **Spatial index** on tables with millions of geometries: the map draws faster when you zoom in. See
  [Spatial index](spatial-index.md).
- **Parquet** is the fastest format to save and read data again.
- **Filter in SQL** before loading into QGIS: less arrives, sooner.
- **Cancel without fear.** "Cancel" stops loads, queries and exports without leaving anything half done.
- **Memory.** If a very large query doesn't fit in memory, the engine uses temporary disk space. If it still
  doesn't fit, see [Out of memory](errors.md#memory).

## Measured numbers {#measured}

With **1,000,000 rows** (points), QGIS 4.2 and engine 2.0, in CI (Linux, 4 cores). The median of 7 runs;
on your computer the numbers will differ.

| Operation | Median |
|---|---|
| First page of a query | 33 ms |
| Aggregate (GROUP BY) | 6 ms |
| Load into QGIS · Connected | 91 ms |
| Load into QGIS · Copy | 2,046 ms |
| Import a Parquet file | 50 ms |
| Send a QGIS layer | 3,854 ms |
| Export to Parquet | 151 ms |
| Export to CSV | 287 ms |
| Cancel an export | 40 ms |
