# SPDX-License-Identifier: GPL-2.0-or-later
"""Núcleo de dominio puro.

Reglas (ADR-0010): este paquete solo importa la biblioteca estándar. No conoce Qt, QGIS, DuckDB ni
PyArrow, por lo que se prueba en milisegundos y sin dependencias nativas.
"""
