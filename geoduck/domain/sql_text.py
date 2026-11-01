# SPDX-License-Identifier: GPL-2.0-or-later
"""Citado seguro de identificadores y literales para SQL generado por GeoDuck.

Por qué no hay parámetros: `ATTACH ? AS alias` falla en DuckDB 1.5.x y funciona en 2.0 (evidencia G0,
F-06). Para tener un único camino verificable en ambas ramas, GeoDuck cita literales e identificadores
(contradicción C6). Estas funciones se aplican solo a SQL que GeoDuck construye desde la UI; el SQL
escrito por el usuario se ejecuta tal cual.
"""

from __future__ import annotations

from geoduck.domain.errors import ErrorCode, GeoDuckError


def _reject_nul(value: str, what: str) -> None:
    if "\x00" in value:
        raise GeoDuckError(f"{what} no puede contener el carácter NUL", code=ErrorCode.INVALID_ARGUMENT)


def quote_identifier(name: str) -> str:
    """Devuelve `name` como identificador SQL entre comillas dobles, escapando `"`."""
    if not name:
        raise GeoDuckError("El identificador no puede estar vacío", code=ErrorCode.INVALID_ARGUMENT)
    _reject_nul(name, "El identificador")
    return '"' + name.replace('"', '""') + '"'


def quote_string_literal(value: str) -> str:
    """Devuelve `value` como literal SQL entre comillas simples, escapando `'`."""
    _reject_nul(value, "El literal")
    return "'" + value.replace("'", "''") + "'"
