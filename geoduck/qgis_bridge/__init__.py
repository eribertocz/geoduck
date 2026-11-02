# SPDX-License-Identifier: GPL-2.0-or-later
"""Puente hacia QGIS: las tres modalidades de carga de ADR-0012.

Fronteras (ADR-0010): puede importar `domain`, `pyarrow`, `qgis` y `osgeo`; nunca `duckdb`, `engine`,
`app` ni `ui`. Habla con la sesión solo mediante el objeto motor que recibe de la raíz de composición.
"""
