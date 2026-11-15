# Report a problem

<span class="gd-time">2 minutes</span>

1. **? › Report a problem…** copies the environment diagnostics (QGIS, Python and engine versions; never your
   data).
2. Write what you were doing, what you expected and what happened. If there is an error, copy it with the copy icon
   on its card.
3. Paste everything in the report, together with the diagnostics.

A small example that reproduces it (a few rows in SQL) helps a lot:

```sql
CREATE TABLE test AS SELECT 1 AS id, 'POINT(0 0)'::GEOMETRY AS g;
```
