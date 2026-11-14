# SPDX-License-Identifier: GPL-2.0-or-later
"""La sentencia que corre «Ejecutar» (workspace-pro-spec §5).

El editor la marca **antes** de ejecutar y se ejecuta exactamente lo marcado. Se calcula aquí, en Python y
sin DuckDB, por dos motivos: la interfaz la necesita a cada movimiento del cursor (sin pasar por el worker), y
el parser de DuckDB reparte los espacios entre sentencias distinto en 1.5 y en 2.0 (en 1.5 el hueco va con la
siguiente; en 2.0, con la anterior), así que el cursor en una línea en blanco elegía una sentencia distinta
según la versión. Los `;` se buscan fuera de comentarios y cadenas (`blank_code`).
"""

from __future__ import annotations

from geoduck.domain.completion import blank_code


def statement_spans(text: str) -> list[tuple[int, int]]:
    """(inicio, fin) de cada sentencia de `text`, sin los espacios ni los comentarios que la rodean; el fin
    incluye su `;`. Los tramos vacíos (solo espacios, comentarios o `;` sueltos) no cuentan."""
    code = _without_identifiers(blank_code(text)[0])
    spans: list[tuple[int, int]] = []
    start = 0
    for end in [i + 1 for i, ch in enumerate(code) if ch == ";"] + [len(code)]:
        piece = code[start:end]
        body = piece.rstrip(";").strip()
        if body:
            first = start + (len(piece) - len(piece.lstrip()))
            last = start + len(piece.rstrip())
            spans.append((first, last))
        start = end
    return spans


def _without_identifiers(code: str) -> str:
    """`blank_code` conserva los identificadores entre comillas (`"c;d"`): aquí también se tapan."""
    out = list(code)
    i = code.find('"')
    while i >= 0:
        end = i + 1
        while True:
            end = code.find('"', end)
            if end < 0 or not code.startswith('""', end):
                break
            end += 2
        end = len(code) if end < 0 else end + 1
        for j in range(i + 1, end - 1):
            if out[j] != "\n":
                out[j] = " "
        i = code.find('"', end)
    return "".join(out)


def current_span(text: str, cursor: int) -> tuple[int, int] | None:
    """La sentencia del cursor: la que lo contiene (también justo después de su `;`); entre dos, la anterior;
    antes de la primera, la primera. `None` si no hay ninguna."""
    spans = statement_spans(text)
    if not spans:
        return None
    chosen = spans[0]
    for first, last in spans:
        if first <= cursor:
            chosen = (first, last)
        if first <= cursor <= last:
            return first, last
    return chosen
