# SPDX-License-Identifier: GPL-2.0-or-later
"""«Abrir existente» y «Crear nueva»: adjuntar un archivo DuckDB a la sesión (G1 paso 3, GD-SES-002).

Todo ocurre en una sola operación del worker serial (ADR-0006), así que nada se intercala entre las
comprobaciones, el `ATTACH` y la lectura del catálogo resultante.

Hechos verificados con DuckDB 1.5.0, 1.5.6 y 2.0.0 que fijan este diseño:

Evidencia: `docs/evidence/g1/README.md`.

- `ATTACH` en lectura y escritura de una ruta inexistente **crea el archivo sin avisar** (F-18). Por eso
  «Abrir existente» comprueba antes que el archivo existe, y después que es el mismo: dispositivo, inodo,
  tamaño y fecha de modificación. Solo el inodo no basta, porque Linux reutiliza al instante el de un
  archivo borrado. Si fue sustituido o borrado entre ambos momentos, la base se desadjunta y la
  operación falla. Adjuntar un archivo existente, en RO o RW, no cambia esos datos.
- Un archivo vacío no es una base válida, así que no se puede reservar el nombre creando el archivo antes.
- `ATTACH ?` con parámetro no funciona en 1.5 (F-06): ruta y alias van como literales citados.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import duckdb

from geoduck.domain.catalog import (
    MEMORY_PATH,
    RESERVED_CATALOG_NAMES,
    AccessMode,
    AttachRequest,
    AttachResult,
    CatalogSnapshot,
    OpenAction,
    catalog_key,
)
from geoduck.domain.errors import AttachError, EngineError, ErrorCode, InvalidArgumentError
from geoduck.domain.i18n import tr
from geoduck.domain.sql_text import quote_identifier, quote_string_literal
from geoduck.engine.catalog import read_catalog

if TYPE_CHECKING:
    from geoduck.engine.worker import ConnectionHandle

_log = logging.getLogger("geoduck.engine")

#: Reglas para clasificar los errores de `ATTACH` de DuckDB, en orden. Texto en minúsculas.
_RULES: tuple[tuple[str, ErrorCode, str], ...] = (
    (
        "current transaction is aborted",
        ErrorCode.TRANSACTION_ABORTED,
        tr("The transaction is aborted; roll it back."),
    ),
    ("conflicting lock is held", ErrorCode.DB_LOCKED, tr("Another process has locked the file.")),
    ("could not set lock", ErrorCode.DB_LOCKED, tr("Another process has locked the file.")),
    (
        "unique file handle conflict",
        ErrorCode.DB_ALIAS_CONFLICT,
        tr("The file is already attached in this session."),
    ),
    ("already exists", ErrorCode.DB_ALIAS_CONFLICT, tr("There is already a database with that alias.")),
    ("reserved name", ErrorCode.DB_ALIAS_CONFLICT, tr("That alias is reserved by DuckDB.")),
    ("database does not exist", ErrorCode.DB_NOT_FOUND, tr("The file does not exist.")),
    ("no such file or directory", ErrorCode.DB_NOT_FOUND, tr("The file or its folder does not exist.")),
    ("permission denied", ErrorCode.DB_READ_ONLY, tr("There is no write permission on the file.")),
    ("read-only file system", ErrorCode.DB_READ_ONLY, tr("The file system is read only.")),
    (
        "not a valid duckdb database file",
        ErrorCode.ENGINE_ERROR,
        tr("The file is not a valid DuckDB database."),
    ),
)


def classify_attach_error(exc: BaseException) -> AttachError:
    """Traduce un error de DuckDB al código estable de session-spec §5.

    `detail` solo lleva la clase de excepción y la regla aplicada, nunca la ruta ni datos del usuario.
    """
    text = str(exc).lower()
    for needle, code, message in _RULES:
        if needle in text:
            return AttachError(message, code=code, detail=f"{type(exc).__name__}: {needle}")
    return AttachError(
        tr("DuckDB could not attach the file."), code=ErrorCode.ENGINE_ERROR, detail=type(exc).__name__
    )


def attach_database(handle: ConnectionHandle, request: AttachRequest, root: str) -> AttachResult:
    alias = request.effective_alias
    _check_alias(read_catalog(handle, root), alias)
    if request.action is OpenAction.IN_MEMORY:  # #168: sin archivo, nada que comprobar en disco
        path, identity = MEMORY_PATH, None
    else:
        path = os.path.abspath(request.path)
        identity = _check_path(path, request.action)
    sql = f"ATTACH {quote_string_literal(path)} AS {quote_identifier(alias)}"
    if request.access is AccessMode.READ_ONLY:
        sql += " (READ_ONLY)"
    try:
        _execute_attach(handle, sql)
    except duckdb.FatalException:
        raise  # no es un fallo del ATTACH: el worker invalida la sesión (C13 §4 bis)
    except duckdb.Error as exc:
        raise classify_attach_error(exc) from exc
    if identity is not None and _identity(path) != identity:
        _detach_quietly(handle, alias)
        raise AttachError(
            tr("The file changed or disappeared while it was being opened; it was not used."),
            code=ErrorCode.DB_NOT_FOUND,
            detail="file_replaced_during_attach",
        )
    catalog = read_catalog(handle, root)
    database = catalog.get(alias)
    if database is None or database.access is not request.access:
        _detach_quietly(handle, alias)
        raise EngineError(tr("The attached database does not match the request; it was detached"))
    return AttachResult(database, catalog)


def _check_alias(catalog: CatalogSnapshot, alias: str) -> None:
    if catalog_key(alias) in RESERVED_CATALOG_NAMES:
        raise AttachError(
            tr("The alias «{0}» is reserved by DuckDB.").format(alias),
            code=ErrorCode.DB_ALIAS_CONFLICT,
            detail="reserved",
        )
    existing = catalog.get(alias)
    if existing is not None:
        raise AttachError(
            tr("There is already a database called «{0}» in the session.").format(existing.name),
            code=ErrorCode.DB_ALIAS_CONFLICT,
            detail="alias_in_catalog",
        )


def _check_path(path: str, action: OpenAction) -> tuple[int, int, int, int] | None:
    """Comprueba la ruta antes del `ATTACH`. Devuelve la identidad del archivo para «Abrir existente»."""
    if action is OpenAction.OPEN_EXISTING:
        if not os.path.isfile(path):
            raise AttachError(
                tr("The file does not exist."), code=ErrorCode.DB_NOT_FOUND, detail="missing_file"
            )
        return _identity(path)
    if os.path.lexists(path):
        raise InvalidArgumentError(
            tr("A file with that name already exists; «Create new» never overwrites it.")
        )
    if os.path.lexists(path + ".wal"):
        raise InvalidArgumentError(
            tr(
                "There is a .wal file with that name; DuckDB would apply it to the "
                "new database. Choose another name."
            )
        )
    if not os.path.isdir(os.path.dirname(path)):
        raise AttachError(
            tr("The folder does not exist."), code=ErrorCode.DB_NOT_FOUND, detail="missing_directory"
        )
    return None


def _identity(path: str) -> tuple[int, int, int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns


def _execute_attach(handle: ConnectionHandle, sql: str) -> None:
    handle.execute(sql)


def _detach_quietly(handle: ConnectionHandle, alias: str) -> None:
    try:
        handle.execute(f"DETACH {quote_identifier(alias)}")
    except duckdb.FatalException:
        raise  # nunca se silencia un error fatal: invalida la sesión
    except duckdb.Error:
        _log.warning("No se pudo desadjuntar una base rechazada", exc_info=True)
