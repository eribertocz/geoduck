"""F-01: con un lector Arrow abierto, otra sentencia en la misma conexión.

DuckDB 1.5.x acepta la sentencia y el lector termina con menos filas SIN error.
DuckDB 2.0.x rechaza la sentencia con ResourceInUseException.
Uso: python -I repro_reader_truncation.py
"""
import duckdb

con = duckdb.connect(":memory:")
con.execute("CREATE TABLE big AS SELECT range AS i FROM range(100000)")
reader = con.sql("SELECT * FROM big").to_arrow_reader(batch_size=1000)
rows = reader.read_next_batch().num_rows
try:
    con.execute("SELECT 1").fetchall()
    interleaved = "aceptada"
except Exception as exc:  # noqa: BLE001
    interleaved = type(exc).__name__
error = None
try:
    for batch in reader:
        rows += batch.num_rows
except Exception as exc:  # noqa: BLE001
    error = repr(exc)
print(f"duckdb={duckdb.__version__} sentencia_intercalada={interleaved} filas_leidas={rows} esperadas=100000 error={error}")
