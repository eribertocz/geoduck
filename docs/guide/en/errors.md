# Common errors

When something fails, GeoDuck shows the engine's message **as is** and, when it recognises it, a title and a
button to fix it. Here are the most common ones.

## The table or column does not exist {#not-found}

> The table «predio» does not exist · Suggestion: predios.

- Check the name. If the engine suggests another, click **Change to «…»**.
- Is it in another database? Name it in full: `other_db.main.predios`, or make it the active database.
- Names with capitals or spaces go in double quotes: `"Customer Name"`.

## Syntax error {#syntax}

The engine doesn't understand the SQL. The card gives the line and the word. Most often: a missing or extra
comma, an unclosed quote, or a reserved word used as a name (put it in double quotes).

## A value cannot be converted {#conversion}

> Could not convert string 'abc' to INTEGER

Some rows have values that are not of the requested type. **Use TRY_CAST** returns `NULL` for those rows instead
of failing.

## Files {#files}

- **Doesn't exist:** check the path; **Choose file…** changes it.
- **Not a database:** the file is not a DuckDB database, or it is damaged.
- **In use:** another program has it open for writing. Close it or open the database **Read only**.

## Out of memory {#memory}

The query needed more memory than allowed. **Raise memory_limit…** writes `SET memory_limit` before the
statement. Filtering before joining, or exporting in parts, also helps.

## Spatial extension {#spatial}

> Scalar Function with name st_area does not exist… exists in the spatial extension

GeoDuck loads the spatial extension when it starts. If it couldn't (no internet), the notice has **Retry** and
**Install from a file…**. **? › Environment diagnostics** shows the exact address to download it.

## Constraints {#constraint}

> Duplicate key "id: 7" violates primary key constraint

The row breaks a rule of the table (repeated key, a null where it isn't allowed). Check the data or the rule.

## Transactions {#transaction}

After an error inside a transaction (`BEGIN`), the engine accepts no more statements until `ROLLBACK`. GeoDuck
tells you on the query bar.

## The layer is not available {#layer-unavailable}

A Connected layer whose database was closed or cannot be found. Right-click the layer › **Open the database
«…»**, or open the database from GeoDuck: the layer comes back by itself.
