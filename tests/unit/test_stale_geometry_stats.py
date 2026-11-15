# SPDX-License-Identifier: GPL-2.0-or-later
"""Las versiones de DuckDB que se saltan filas al filtrar por rectángulo una base reabierta (#154)."""

import pytest

from geoduck.domain.bridge_types import stale_geometry_stats


@pytest.mark.parametrize(
    ("version", "stale"),
    [
        ("1.5.0", True),
        ("1.5.3", True),
        ("v1.5.1", True),
        ("1.5.4", False),
        ("1.5.6", False),
        ("2.0.0", False),
        ("1.4.4", False),
        ("", False),
    ],
)
def test_only_duckdb_1_5_0_to_1_5_3(version, stale):
    assert stale_geometry_stats(version) is stale
