# SPDX-License-Identifier: GPL-2.0-or-later
"""Búsqueda tolerante de Ctrl+K y de la barra lateral (workspace-pro-spec §6; AT-WSP-006).

Las letras de la búsqueda deben aparecer **en orden** en el texto, sin importar acentos ni mayúsculas
(«cnsm» encuentra «Consumidores», «nino» encuentra «Niño»). Puntúa mejor lo que empieza igual, las letras
seguidas y el comienzo de palabra. Sin Qt: se prueba sola y responde en milisegundos con miles de objetos.
"""

from __future__ import annotations

import heapq
import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")

_SEPARATORS = frozenset(" _-./·:")
#: Letras sueltas en orden: el tramo que ocupan no pasa de 3 veces la búsqueda («lec» no encuentra «Send
#: QGIS layers to DuckDB», donde la «c» está 13 letras después de la «l»).
MAX_SPREAD = 3


def fold(text: str) -> str:
    """Minúsculas y sin acentos («Año» → «ano»); conserva la longitud de las letras base."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def score(query: str, text: str) -> int | None:
    """Puntuación de `text` para `query` (ya plegados con `fold`), o `None` si no coincide.

    Más alta, mejor: el texto igual a la búsqueda, luego el que empieza por ella, luego el que la contiene;
    si solo coinciden letras sueltas en orden, suman las seguidas y las de comienzo de palabra.
    """
    if not query:
        return 0
    if text == query:
        return 10_000
    if text.startswith(query):
        return 5_000 - len(text)
    found = text.find(query)
    if found >= 0:
        boundary = text[found - 1] in _SEPARATORS
        return 3_000 + (500 if boundary else 0) - found - len(text)
    best: int | None = None
    begin = text.find(query[0])
    while begin >= 0:  # cada aparición de la primera letra puede empezar la coincidencia
        value = _in_order(query, text, begin)
        if value is not None and (best is None or value > best):
            best = value
        begin = text.find(query[0], begin + 1)
    return best


def in_order_pattern(query: str) -> re.Pattern[str]:
    """Las letras de `query` en orden, a cualquier distancia, como expresión regular (se busca en C)."""
    return re.compile(".*?".join(re.escape(ch) for ch in query), re.DOTALL)


def in_order(query: str, text: str) -> bool:
    """Las letras de `query` aparecen en orden en `text`, a cualquier distancia: lo que coincide con una
    búsqueda más larga siempre cumple esto con la más corta (`score` además limita la distancia)."""
    position = 0
    for ch in query:
        position = text.find(ch, position)
        if position < 0:
            return False
        position += 1
    return True


def _in_order(query: str, text: str, begin: int) -> int | None:
    """Puntuación de las letras de `query` en orden en `text` desde `begin`, o `None`."""
    limit = begin + MAX_SPREAD * len(query)  # letras demasiado separadas: no es lo buscado
    total = 0
    position = begin
    previous = begin - 2
    for ch in query:
        index = text.find(ch, position, limit)
        if index < 0:
            return None
        if index == previous + 1:
            total += 15
        if index == 0 or text[index - 1] in _SEPARATORS:
            total += 10
        total -= index - position
        previous = index
        position = index + 1
    return 1_000 + total - begin - len(text)


def rank(query: str, items: Iterable[T], text: Callable[[T], str], limit: int = 50) -> list[T]:
    """Los `items` que coinciden con `query`, de mejor a peor (estable ante empates), hasta `limit`.

    `text(item)` debe devolver el texto **ya plegado** (`fold`), para no plegarlo en cada tecla.
    """
    folded = fold(query.strip())
    scored = (
        (-value, order, item)
        for order, item in enumerate(items)
        if (value := score(folded, text(item))) is not None
    )
    # solo las mejores `limit`: sin ordenar (ni guardar) miles de coincidencias en cada tecla
    best = heapq.nsmallest(limit, scored, key=lambda entry: (entry[0], entry[1]))
    return [item for _, _, item in best]
