# SPDX-License-Identifier: GPL-2.0-or-later
"""`tools/perf/compare.py` (#176): la regresión es más del 20 % **y** más de 50 ms, en el mismo equipo."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _compare():
    spec = importlib.util.spec_from_file_location("perf_compare", ROOT / "tools" / "perf" / "compare.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["perf_compare"] = module
    spec.loader.exec_module(module)
    return module


def run(folder: Path, **medians: float) -> str:
    folder.mkdir(parents=True)
    medidas = {name: {"mediana_ms": ms} for name, ms in medians.items()}
    (folder / "bench-x.json").write_text(json.dumps({"medidas": medidas}), encoding="utf-8")
    return str(folder)


def test_only_slower_by_more_than_20_percent_and_50_ms_is_a_regression(tmp_path):
    compare = _compare()
    base = [
        run(tmp_path / "b1", lenta=1000, rapida=10, igual=300),
        run(tmp_path / "b2", lenta=1100, rapida=12, igual=320),
    ]
    head = [
        run(tmp_path / "h1", lenta=1400, rapida=30, igual=330),
        run(tmp_path / "h2", lenta=1500, rapida=31, igual=340),
    ]
    assert compare.main(["--base", *base, "--head", *head]) == 1
    _, regressions = compare.compare(compare.read(base), compare.read(head))
    assert regressions == ["lenta"]  # «rapida» triplica, pero son 20 ms: ruido


def test_the_same_numbers_pass(tmp_path):
    compare = _compare()
    base = run(tmp_path / "b", consulta=500)
    head = run(tmp_path / "h", consulta=540)
    assert compare.main(["--base", base, "--head", head, "--out", str(tmp_path / "c.md")]) == 0
    assert "Sin regresiones." in (tmp_path / "c.md").read_text(encoding="utf-8")
