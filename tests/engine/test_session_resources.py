# SPDX-License-Identifier: GPL-2.0-or-later
"""#172 (performance-spec §4, AT-PERF-003): la carpeta temporal propia de la sesión y su tope de disco."""

from __future__ import annotations

import os

from geoduck.domain.resources import DISK_CAP, size_text, temp_limit
from geoduck.engine.worker import SessionWorker

TIMEOUT = 120


def sql(worker, text, max_rows=10):
    return worker.submit(lambda h, t: h.execute(text, max_rows=max_rows)).future.result(TIMEOUT).rows


def test_a_query_that_does_not_fit_in_memory_uses_the_session_folder_and_it_goes_away():
    worker = SessionWorker()
    info = worker.start().result(TIMEOUT)
    try:
        folder = info.temp_directory
        assert folder and os.path.isdir(folder) and os.path.basename(os.path.dirname(folder)) == "geoduck"
        setting = sql(worker, "SELECT value FROM duckdb_settings() WHERE name = 'temp_directory'")
        assert setting == ((folder,),)  # nunca el `.tmp` de la carpeta de trabajo de QGIS
        assert 0 < info.temp_limit <= DISK_CAP
        sql(worker, "SET memory_limit = '64MB'")  # una sesión con poca memoria
        rows = sql(
            worker,
            "SELECT count(*) FROM"
            " (SELECT range AS n, md5(range::VARCHAR) AS k FROM range(3000000) ORDER BY k)",
        )
        assert rows == ((3_000_000,),)  # terminó usando disco en vez de fallar
    finally:
        worker.close().result(TIMEOUT)
    assert not os.path.exists(folder)  # sin restos


def test_two_sessions_never_share_the_folder():
    first, second = SessionWorker(), SessionWorker()
    try:
        a = first.start().result(TIMEOUT).temp_directory
        b = second.start().result(TIMEOUT).temp_directory
        assert a and b and a != b
    finally:
        first.close().result(TIMEOUT)
        second.close().result(TIMEOUT)


def test_the_disk_cap_is_20_gb_or_half_the_free_space():
    gb = 1024**3
    assert temp_limit(100 * gb) == 20 * gb
    assert temp_limit(10 * gb) == 5 * gb
    assert temp_limit(gb) == gb  # al menos 1 GB
    assert size_text(20 * gb) == "20 GB" and size_text(640 * 1024**2) == "640 MB"
