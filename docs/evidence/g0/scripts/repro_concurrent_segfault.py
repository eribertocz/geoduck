"""F-02: la misma conexión usada por dos hilos a la vez.

DuckDB 1.5.0: segfault (proceso termina con código -11 en Linux).
DuckDB 1.5.6: sin error observado en 3 corridas (no prueba seguridad).
DuckDB 2.0.0: ResourceInUseException.
Uso: python -I -X faulthandler repro_concurrent_segfault.py
"""
import threading

import duckdb

con = duckdb.connect(":memory:")
errors = []


def work():
    try:
        for _ in range(200):
            con.execute("SELECT sum(range) FROM range(100000)").fetchall()
    except Exception as exc:  # noqa: BLE001
        errors.append(type(exc).__name__)


threads = [threading.Thread(target=work) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print(f"duckdb={duckdb.__version__} errores={sorted(set(errors)) or 'ninguno'}")
