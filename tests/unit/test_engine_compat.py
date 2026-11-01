# SPDX-License-Identifier: GPL-2.0-or-later
"""Capacidades por versión (sin importar duckdb)."""

import pytest

from geoduck.engine.compat import EngineCapabilities, is_interrupt_error


@pytest.mark.parametrize(
    ("version", "supported", "recommended", "interrupt", "guards"),
    [
        ("1.4.4", False, False, False, False),
        ("1.5.0", True, False, True, False),
        ("1.5.3", True, False, True, False),
        ("1.5.4", True, True, True, False),
        ("1.5.6", True, True, True, False),
        ("1.5.7", True, True, False, False),  # no verificada todavía: solo cancelación cooperativa
        ("2.0.0", True, True, True, True),
        ("2.0.1", True, True, False, True),
        ("2.1.0.dev5", True, True, False, True),
    ],
)
def test_capabilities(version, supported, recommended, interrupt, guards):
    caps = EngineCapabilities.for_version(version)
    assert caps.supported is supported
    assert caps.recommended is recommended
    assert caps.interrupt_verified is interrupt
    assert caps.engine_guards_open_result is guards
    assert caps.attach_accepts_parameters is guards
    assert caps.has_complete is guards


def test_interrupt_error_recognition():
    class InterruptException(Exception):  # noqa: N818 - nombre real de DuckDB
        pass

    assert is_interrupt_error(InterruptException("x"))
    assert is_interrupt_error(OSError("INTERRUPT Error: Interrupted!"))
    assert not is_interrupt_error(OSError("disk full"))
    assert not is_interrupt_error(RuntimeError("INTERRUPT Error"))
