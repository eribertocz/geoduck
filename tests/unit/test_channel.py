# SPDX-License-Identifier: GPL-2.0-or-later
"""Canal acotado entre el worker y el consumidor de una carga (qgis-bridge-spec §6, F-60)."""

from __future__ import annotations

import queue
import threading
import time

import pytest

from geoduck.domain.channel import BatchChannel, ConsumerGoneError


def test_backpressure_limits_batches_in_flight():
    ch: BatchChannel[int] = BatchChannel(capacity=2)
    produced = []

    def producer():
        for i in range(5):
            ch.put(i)
            produced.append(i)
        ch.finish()

    t = threading.Thread(target=producer)
    t.start()
    time.sleep(0.3)
    assert produced == [0, 1]  # el tercero espera sitio
    got = []
    while True:
        ok, item = ch.get(timeout=5)
        if not ok:
            break
        got.append(item)
    t.join(5)
    assert got == [0, 1, 2, 3, 4]


def test_abandon_stops_a_blocked_producer():
    ch: BatchChannel[int] = BatchChannel(capacity=1)
    outcome = {}

    def producer():
        try:
            for i in range(100):
                ch.put(i)
        except ConsumerGoneError:
            outcome["stopped"] = True

    t = threading.Thread(target=producer)
    t.start()
    time.sleep(0.1)
    ch.abandon()
    t.join(5)
    assert not t.is_alive()
    assert outcome == {"stopped": True}


def test_stop_callback_interrupts_put():
    ch: BatchChannel[int] = BatchChannel(capacity=1)
    ch.put(1)
    with pytest.raises(ConsumerGoneError):
        ch.put(2, stop=lambda: True)


def test_producer_error_reaches_the_consumer():
    ch: BatchChannel[int] = BatchChannel()
    ch.put(1)
    ch.fail(RuntimeError("motor"))
    assert ch.get(timeout=1) == (True, 1)
    with pytest.raises(RuntimeError, match="motor"):
        ch.get(timeout=1)


def test_get_times_out_without_data():
    with pytest.raises(queue.Empty):
        BatchChannel().get(timeout=0.05)


def test_finish_after_abandon_does_not_block():
    ch: BatchChannel[int] = BatchChannel(capacity=1)
    ch.put(1)
    ch.abandon()
    ch.finish()  # no espera sitio en un canal abandonado
    assert ch.abandoned
