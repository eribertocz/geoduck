# Send QGIS layers to GeoDuck

<span class="gd-time">3 minutes</span>

Bring vector layers from the project into a database, as tables, to query them with SQL.

## How to start

- **Drag** layers from the QGIS layers panel onto a database in the explorer.
- In QGIS, right-click the layers › **GeoDuck › Send to GeoDuck…**
- "+" › **Add QGIS layers to GeoDuck…**

## The dialog

1. **Destination:** the database and schema (or "Temporary table", only for this session).
2. **Names:** each layer already has a table name. Double-click (or F2) to change it. If it exists, GeoDuck
   suggests another (`lecturas_2`), or you can replace it or append rows.
3. **Send N layers.**

The timeline shows each layer. Finished ones stay even if you cancel the rest. At the end, **Undo** removes the
new tables.

!!! note
    Raster layers are not sent: they show in grey with the reason.
