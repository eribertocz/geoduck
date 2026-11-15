# Concepts

<span class="gd-time">4 minutes</span>

## Session

While GeoDuck is started there is a **session**: an analytical database engine (DuckDB) running inside QGIS.
The dot on the logo tells its state: green **active**, amber **busy**, red **with error**; no dot, **stopped**.
"Close session" is in the logo menu.

## Database and schema

- A **database** is a `.duckdb` file or an **in-memory** database (lost when the session closes). You can have
  several open at once.
- The **active database** (teal stripe and "active" label in the explorer) is where queries run and where new
  things go. Name another database in full in SQL: `other_db.main.table`.
- A **schema** groups tables inside a database. The usual one is `main`.

## Copy and Connected

When you load a table into QGIS you choose how:

| | Copy | Connected |
|---|---|---|
| What it does | Copies the data into QGIS | Reads straight from the database, no copy |
| Depends on the database | No | Yes: if the database closes, the layer becomes "unavailable" |
| Editing | Edits the copy | What you edit is saved in the database |
| Best for | Medium tables, working without the database | Large tables, changing data |

When you save a project with **Copy** layers, GeoDuck offers to save them in a GeoPackage next to the project
so they come back when you reopen it. A **Connected** layer on a file database comes back by itself: when the
project opens, GeoDuck starts and opens the database.

## Direct path

When you bring layers or files into GeoDuck, whenever it can the engine reads them directly (⚡ "read directly
by GeoDuck"), skipping QGIS. It is faster. When it cannot (a format only QGIS reads, a QGIS filter), QGIS reads
it and the timeline says why.

## Traceability

Every send, import, export or load shows a **timeline**: where it comes from, how it is read, how many rows,
where it goes and how long each step took. If something fails, the step turns red with its error. When done,
**Undo** removes what was created.
