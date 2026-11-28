# SPDX-License-Identifier: GPL-2.0-or-later
"""Compara dos corridas del banco (`bench.py`) hechas en el mismo equipo (#176; performance-spec §7).

    python tools/perf/compare.py --base <carpeta(s)> --head <carpeta(s)> [--out comparacion.md]

Cada carpeta tiene un `bench-*.json`. Con varias por lado (rondas alternadas: base, nueva, base, nueva…), cada
operación usa la mediana de sus medianas. Hay **regresión** si la nueva tarda más del 20 % que la base **y**
al menos 50 ms más: por debajo de eso, la diferencia es ruido del equipo (los runners de la CI varían 30–180 %
entre corridas; por eso se compara en el mismo trabajo, nunca contra números guardados de otro equipo).
Sale con 1 si hay alguna regresión.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

#: Más lenta que la base en más de esta fracción…
TOLERANCE = 0.20
#: …y en más de estos milisegundos.
FLOOR_MS = 50.0


def read(folders: list[str]) -> dict[str, float]:
    """Operación → mediana de las medianas de todas las rondas."""
    samples: dict[str, list[float]] = {}
    for folder in folders:
        for path in sorted(Path(folder).glob("bench-*.json")):
            for name, values in json.loads(path.read_text(encoding="utf-8"))["medidas"].items():
                samples.setdefault(name, []).append(float(values["mediana_ms"]))
    return {name: statistics.median(values) for name, values in samples.items()}


def compare(base: dict[str, float], head: dict[str, float]) -> tuple[list[str], list[str]]:
    """Las filas de la tabla y las operaciones con regresión."""
    rows = ["| Operación | Base | Nueva | Cambio | |", "|---|---|---|---|---|"]
    regressions: list[str] = []
    for name, before in base.items():
        if name not in head:
            continue
        after = head[name]
        change = (after - before) / before if before else 0.0
        slower = change > TOLERANCE and after - before > FLOOR_MS
        if slower:
            regressions.append(name)
        mark = "⚠ regresión" if slower else ""
        rows.append(f"| {name} | {before:,.0f} ms | {after:,.0f} ms | {change:+.0%} | {mark} |")
    return rows, regressions


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", nargs="+", required=True)
    parser.add_argument("--head", nargs="+", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    base, head = read(args.base), read(args.head)
    if not base or not head:
        print("Faltan medidas: ¿se ejecutó bench.py?")
        return 1
    rows, regressions = compare(base, head)
    text = "\n".join(
        [
            f"Regresión: más de {TOLERANCE:.0%} y más de {FLOOR_MS:.0f} ms sobre la base,"
            " en el mismo equipo.",
            "",
            *rows,
            "",
            f"**{len(regressions)} regresiones**: " + ", ".join(regressions)
            if regressions
            else "Sin regresiones.",
        ]
    )
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
