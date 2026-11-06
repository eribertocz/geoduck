# SPDX-License-Identifier: GPL-2.0-or-later
"""Búsqueda tolerante de Ctrl+K (G9 · E2; workspace-pro-spec §6; AT-WSP-006)."""

from __future__ import annotations

import time

from geoduck.ui.pro.fuzzy import fold, rank, score


def names(query, texts):
    return rank(query, texts, fold)


def test_letters_in_order_without_accents_or_case():
    assert names("cnsm", ["Consumidores", "zonas"]) == ["Consumidores"]
    assert names("nino", ["Niño", "Nina"]) == ["Niño"]
    assert names("AÑO", ["ano_2025"]) == ["ano_2025"]


def test_letters_too_far_apart_do_not_match():
    assert score(fold("lec"), fold("Send QGIS layers to DuckDB…")) is None


def test_exact_then_prefix_then_contained_then_scattered():
    found = names("lect", ["mis_lecturas", "lecturas_2025", "lect", "l_e_c_t", "lecturas"])
    assert found == ["lect", "lecturas", "lecturas_2025", "mis_lecturas", "l_e_c_t"]


def test_empty_query_keeps_the_order():
    assert names("", ["b", "a"]) == ["b", "a"]


def test_a_thousand_objects_answer_well_under_50_ms_per_key():
    texts = [fold(f"tabla_{i:04d}_consumo_municipal") for i in range(1000)]
    worst = 0.0
    for query in ("t", "ta", "tab", "tab0", "tab05", "cnsm", "zzz"):
        start = time.perf_counter()
        rank(query, texts, lambda t: t)
        worst = max(worst, time.perf_counter() - start)
    assert worst < 0.05, worst
