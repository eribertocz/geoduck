# SPDX-License-Identifier: GPL-2.0-or-later
"""La tabla de transiciones del dominio es la de `spec/specs/session-spec.md` §5 (C13).

Evita que código y especificación vuelvan a divergir. Lee la tabla Markdown normativa y la compara con
`geoduck.domain.session.TRANSITIONS`.
"""

from __future__ import annotations

import re
from pathlib import Path

from geoduck.domain.session import TRANSITIONS, SessionState

SPEC = Path(__file__).resolve().parents[2] / "spec" / "specs" / "session-spec.md"
_ROW = re.compile(r"^\| `([A-Z_]+)` \| (.+) \|$")
_STATE = re.compile(r"`([A-Z_]+)`")


def spec_transitions() -> dict[str, set[str]]:
    text = SPEC.read_text(encoding="utf-8")
    section = text[text.index("## 5. Estados y errores") : text.index("## 6.")]
    table: dict[str, set[str]] = {}
    for line in section.splitlines():
        m = _ROW.match(line.strip())
        if m:
            table[m.group(1)] = set(_STATE.findall(m.group(2)))
    return table


def test_spec_table_covers_every_state():
    assert set(spec_transitions()) == {s.value for s in SessionState}


def test_domain_transitions_equal_spec_table():
    domain = {src.value: {t.value for t in targets} for src, targets in TRANSITIONS.items()}
    assert domain == spec_transitions()
