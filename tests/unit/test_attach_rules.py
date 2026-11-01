# SPDX-License-Identifier: GPL-2.0-or-later
"""Petición de adjuntar y clasificación de errores de ATTACH (G1 paso 3), sin abrir archivos.

Los textos son los que devuelven DuckDB 1.5.0, 1.5.6 y 2.0.0 (verificados; ver docs/evidence/g1/README.md).
"""

import pytest

from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.errors import ErrorCode, InvalidArgumentError
from geoduck.engine.attach import classify_attach_error

RO, RW = AccessMode.READ_ONLY, AccessMode.READ_WRITE
OPEN, CREATE = OpenAction.OPEN_EXISTING, OpenAction.CREATE_NEW


class IOException(Exception):  # noqa: N818 (mismos nombres que DuckDB)
    pass


class BinderException(Exception):  # noqa: N818
    pass


class ResourceInUseException(Exception):  # noqa: N818
    pass


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (
            IOException(
                'IO Error: Could not set lock on file "/u/x.duckdb": Conflicting lock is held in '
                "/usr/bin/python3 (PID 748)"
            ),
            ErrorCode.DB_LOCKED,
        ),
        (
            IOException(
                'IO Error: Cannot open database "/u/no.duckdb" in read-only mode: database does not exist'
            ),
            ErrorCode.DB_NOT_FOUND,
        ),
        (
            IOException('IO Error: Cannot open file "/u/nodir/x.duckdb": No such file or directory'),
            ErrorCode.DB_NOT_FOUND,
        ),
        (
            BinderException('Binder Error: Failed to attach database: database with name "G" already exists'),
            ErrorCode.DB_ALIAS_CONFLICT,
        ),
        (
            BinderException(
                'Binder Error: Attached database name "temp" cannot be used because it is a reserved name'
            ),
            ErrorCode.DB_ALIAS_CONFLICT,
        ),
        (
            BinderException(
                'Binder Error: Unique file handle conflict: Cannot attach "g3" - the database file '
                '"/u/g.duckdb" is already attached by database "g"'
            ),
            ErrorCode.DB_ALIAS_CONFLICT,
        ),
        (
            ResourceInUseException('Resource In Use Error: Unique file handle conflict: Cannot attach "l1"'),
            ErrorCode.DB_ALIAS_CONFLICT,
        ),
        (
            IOException('IO Error: The file "/u/t.txt" exists, but it is not a valid DuckDB database file!'),
            ErrorCode.ENGINE_ERROR,
        ),
        (IOException('IO Error: Cannot open file "/u/x.duckdb": Permission denied'), ErrorCode.DB_READ_ONLY),
        (IOException("IO Error: algo inesperado"), ErrorCode.ENGINE_ERROR),
    ],
)
def test_attach_errors_map_to_stable_codes(exc, code):
    error = classify_attach_error(exc)
    assert error.code is code
    assert "/u/" not in error.detail and "/u/" not in error.message  # sin rutas del usuario
    assert error.detail.startswith(type(exc).__name__)


@pytest.mark.parametrize(
    ("path", "alias"),
    [
        ("/datos/Ventas.duckdb", "Ventas"),
        (r"C:\GIS\datos de Año.duckdb", "datos de Año"),
        ("/datos/b.c.duckdb", "b.c"),
        ("/datos/sin_extension", "sin_extension"),
        ("/datos/.oculto", ".oculto"),
        ("relativo/x.db", "x"),
    ],
)
def test_default_alias_is_the_file_name_without_extension(path, alias):
    assert AttachRequest(path, RO, OPEN).effective_alias == alias


def test_explicit_alias_is_kept_verbatim():
    assert AttachRequest("/d/x.duckdb", RO, OPEN, alias="Mi Base").effective_alias == "Mi Base"


@pytest.mark.parametrize(
    ("path", "access", "action", "alias"),
    [
        ("", RO, OPEN, None),
        ("   ", RW, OPEN, None),
        ("/d/x\x00.duckdb", RO, OPEN, None),
        ("/d/x.duckdb", RO, CREATE, None),  # «Crear nueva» solo en RW
        ("/d/x.duckdb", RW, OPEN, ""),
        ("/d/x.duckdb", RW, OPEN, "a\x00b"),
    ],
)
def test_invalid_requests_are_rejected_before_the_engine(path, access, action, alias):
    with pytest.raises(InvalidArgumentError):
        AttachRequest(path, access, action, alias)
