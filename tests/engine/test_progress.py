# SPDX-License-Identifier: GPL-2.0-or-later
"""El avance que informa DuckDB (0–100) durante una operación larga, con DuckDB 1.5 y 2.0 (#174, punto 3)."""

from __future__ import annotations

import threading
import time

from geoduck.engine.worker import SessionWorker

TIMEOUT = 120


def test_a_long_operation_reports_its_progress_from_the_first_moment(tmp_path):
    worker = SessionWorker()
    try:
        worker.start().result(TIMEOUT)
        worker.submit(
            lambda h, t: h.execute(
                "CREATE TABLE t AS SELECT range AS id, md5(range::VARCHAR) AS s FROM range(4000000)",
                max_rows=1,
            )
        ).future.result(TIMEOUT)
        target = tmp_path / "t.csv"
        running = worker.submit(
            lambda h, t: h.execute(f"COPY (SELECT * FROM t ORDER BY s) TO '{target}'", max_rows=1)
        )
        seen = []
        done = threading.Event()
        running.future.add_done_callback(lambda _f: done.set())
        while not done.is_set():
            value = worker.progress()
            if value:
                seen.append(value)
            time.sleep(0.01)
        running.future.result(TIMEOUT)
        assert seen and all(0 < v <= 100 for v in seen)
        assert worker.progress() is None  # sin operación en curso
    finally:
        worker.close().result(TIMEOUT)
