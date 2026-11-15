# Open, create and close databases

<span class="gd-time">3 minutes</span>

## Open a database

1. "+" in the explorer › **Open database…**
2. Choose the file (`.duckdb`, `.ddb` or `.db`).
3. If you only want to read it, tick **Read only**.

The database name in the explorer is the file name (without the extension). If that name is taken, GeoDuck
suggests another.

## Create a database

- **Create database…**: a new file. GeoDuck never overwrites an existing one.
- **New database in memory…**: no file. Lost when the session closes, unless you save it as a file.

## Use as active database

Right-click a database › **Use as active database**. Also from "Active database ▾" in the editor or with
**Ctrl+K**. Queries run in the active database.

## Close a database

Right-click › **Close database**. The active database and the last one cannot be closed: the menu says so in
grey.

- If it has **Connected layers**, they become "unavailable" and come back with **Open again**.
- If it is **in memory** and has layers, GeoDuck asks you to save it as a file first.
- If a layer has **unsaved changes**, save or discard them in QGIS first.
