# Frequently asked questions

## Which DuckDB version do I need?

DuckDB 1.5.4 or later (1.5.6 or 2.x recommended), installed in the QGIS Python. **? › Environment diagnostics**
checks it and tells you how to install it.

## Does my data leave my computer?

No. Everything runs inside QGIS. Only the spatial extension is downloaded the first time, from the official
repository.

## Can I use GeoDuck without internet?

Yes. Without the spatial extension installed, GeoDuck works the same, but without spatial functions. You can
install it from a file (see [Common errors](errors.md#spatial)).

## Where are my queries saved?

Wherever you save them with Ctrl+S (`.sql` files). GeoDuck also keeps recovery copies while you type.

## Can I open the same database from another program?

Yes, if all of them open it **Read only**. A program that opens it for writing locks it for the others.

## What happens to my layers when I close the session?

**Copy** layers stay as they are. **Connected** layers become "unavailable" and come back when you start
GeoDuck and open their database (or by themselves, when the project opens).
