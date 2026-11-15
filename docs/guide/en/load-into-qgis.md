# Load into QGIS

<span class="gd-time">3 minutes</span>

## The quick way

Drag one or more tables from the explorer onto the map (or the layers panel) and choose **Copy** or
**Connected**. Also: right-click › **Load in QGIS ▸**, or the icon on the "Result" bar of a query.

See [Copy and Connected](concepts.md#copy-and-connected) to choose.

## With options

Right-click › Load in QGIS › **More options…**: the layer name, the mode and which geometry columns to load (one
layer per column).

## Coordinate reference system

GeoDuck takes the CRS from the geometry column (`GEOMETRY('EPSG:4326')`). If it is missing, it asks for one,
once for all tables.

## When you save the project

- **Copy:** GeoDuck offers **Save the copies next to the project** (a GeoPackage beside the `.qgz`). Otherwise,
  when the project reopens, the layer shows as "unavailable" with its reason.
- **Connected to a file database:** comes back by itself when the project opens.
- **Connected to an in-memory database:** GeoDuck warns that it cannot reopen it and offers **Save the database
  as a file**.
