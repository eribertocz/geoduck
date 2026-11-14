# SPDX-License-Identifier: GPL-2.0-or-later
"""El código no cita quién decidió algo: las decisiones viven en la SPEC y en los issues."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUOTE = re.compile(r"propietari[oa]s?", re.IGNORECASE)
ALLOWED = re.compile(r"(hilo|único) propietario", re.IGNORECASE)


def test_code_does_not_quote_who_decided():
    found = []
    for folder in ("geoduck", "tests", "tools"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            if path == Path(__file__).resolve():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if QUOTE.search(ALLOWED.sub("", line)):
                    found.append(f"{path.relative_to(ROOT)}:{number}")
    assert found == []
