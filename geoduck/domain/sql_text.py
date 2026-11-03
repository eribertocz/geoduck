# SPDX-License-Identifier: GPL-2.0-or-later
"""Citado seguro de identificadores y literales para SQL generado por GeoDuck.

Por qué no hay parámetros: `ATTACH ? AS alias` falla en DuckDB 1.5.x y funciona en 2.0 (evidencia G0,
F-06). Para tener un único camino verificable en ambas ramas, GeoDuck cita literales e identificadores
(contradicción C6). Estas funciones se aplican solo a SQL que GeoDuck construye desde la UI; el SQL
escrito por el usuario se ejecuta tal cual.
"""

from __future__ import annotations

import re

from geoduck.domain.errors import ErrorCode, GeoDuckError
from geoduck.domain.i18n import tr


def _reject_nul(value: str, what: str) -> None:
    if "\x00" in value:
        raise GeoDuckError(
            tr("{0} cannot contain the NUL character").format(what), code=ErrorCode.INVALID_ARGUMENT
        )


def quote_identifier(name: str) -> str:
    """Devuelve `name` como identificador SQL entre comillas dobles, escapando `"`."""
    if not name:
        raise GeoDuckError(tr("The identifier cannot be empty"), code=ErrorCode.INVALID_ARGUMENT)
    _reject_nul(name, tr("The identifier"))
    return '"' + name.replace('"', '""') + '"'


_BARE = re.compile(r"^[a-z_][a-z0-9_]*$")


def sql_name(name: str, reserved: frozenset[str] | None) -> str:
    """Nombre listo para escribir en SQL: tal cual si es un identificador simple en minúsculas que no es
    palabra clave; si no, entre comillas dobles. Sin la lista de palabras clave (`None`), siempre citado."""
    if reserved is not None and _BARE.match(name) and name not in reserved:
        return name
    return quote_identifier(name)


def quote_string_literal(value: str) -> str:
    """Devuelve `value` como literal SQL entre comillas simples, escapando `'`."""
    _reject_nul(value, tr("The literal"))
    return "'" + value.replace("'", "''") + "'"


def load_sql(sql: str) -> str:
    """El SQL de una sentencia listo para envolverlo en una subconsulta al cargarlo en QGIS.

    El texto de cada sentencia del editor incluye su `;` final y los comentarios de línea que la siguen
    (`split_script`); dentro de `( … )` el `;` es un error de sintaxis y un `--` final comentaría el `)`.
    Se quitan solo, del final, los espacios, los `;` y las líneas que son enteras comentario `--`; el resto
    del texto no cambia. Termina en salto de línea para que un `--` al final de la última línea no alcance
    al `)` de quien lo envuelva.
    """
    lines = sql.rstrip().split("\n")
    while lines:
        last = lines[-1].rstrip()
        if not last or last.lstrip().startswith("--"):
            lines.pop()
            continue
        if last.endswith(";"):
            lines[-1] = last.rstrip(";").rstrip()
            continue
        break
    return "\n".join(lines) + "\n"
