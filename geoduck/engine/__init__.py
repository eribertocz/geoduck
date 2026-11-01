# SPDX-License-Identifier: GPL-2.0-or-later
"""Adaptador DuckDB. Único paquete que importa `duckdb` (ADR-0010).

La conexión pertenece en exclusiva al hilo de `SessionWorker` (ADR-0006).
"""
