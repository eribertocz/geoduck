# SPDX-License-Identifier: GPL-2.0-or-later
"""Lo que hace el editor SQL al escribir (#146, puntos 17, 30): pares, sangría, comentarios, formato,
fragmentos, mayúsculas y la limpieza al guardar.

Lógica pura, sin Qt: el editor le pasa el texto de la línea antes y después del cursor y aplica lo que se le
devuelve. Nada de aquí ejecuta SQL ni cambia lo que hay dentro de un texto entre comillas o un comentario.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

#: Una sangría: cuatro espacios.
INDENT = "    "
#: Pares que se cierran solos.
PAIRS = {"(": ")", "[": "]", "{": "}", "'": "'", '"': '"'}
CLOSERS = frozenset({")", "]", "}"})


def in_code(before: str) -> bool:
    """Si el final de `before` (la línea hasta el cursor) está fuera de un texto entre comillas, de un nombre
    entre comillas dobles y de un comentario `--`."""
    quote = ""
    i = 0
    while i < len(before):
        ch = before[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif before.startswith("--", i):
            return False
        i += 1
    return not quote


def pair_action(char: str, before: str, after: str) -> str:  # noqa: PLR0911
    """Qué hacer al escribir `char` (#146, punto 17): «skip» (saltar el cierre que ya está), «pair» (escribir
    también el cierre) o «» (lo normal). Nada dentro de un texto o un comentario."""
    if char in "'\"" and after.startswith(char) and not in_code(before) and in_code(before + char):
        return "skip"  # el cierre del texto que se está escribiendo
    if not in_code(before):
        return ""
    if char in CLOSERS or char in "'\"":
        if after.startswith(char):
            return "skip"
        if char in CLOSERS:
            return ""
    if char not in PAIRS:
        return ""
    following = after[:1]
    if following and not (following.isspace() or following in ")]},;"):
        return ""  # delante de una palabra no se cierra nada
    if char in "'\"" and before[-1:].isalnum():
        return ""  # «it's», «ab"»: no es el comienzo de un texto
    return "pair"


def backspace_pair(before: str, after: str) -> bool:
    """Borrar un par vacío entero: `(|)` → `|`."""
    return (
        bool(before) and before[-1] in PAIRS and after.startswith(PAIRS[before[-1]]) and in_code(before[:-1])
    )


def leading(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


_OPENS_BLOCK = re.compile(r"(\(\s*$)|(\bCASE\s*$)", re.IGNORECASE)


def enter_text(before: str, after: str) -> tuple[str, int]:
    """Lo que escribe Enter (#146, punto 17) y dónde queda el cursor dentro de ello. La sangría se mantiene;
    aumenta después de `(`, `CASE` o `WITH … AS (`; Enter entre `(` y `)` deja una línea con 4 espacios y baja
    el cierre."""
    base = leading(before)
    if not in_code(before):
        return "\n" + base, len(base) + 1
    opened = bool(_OPENS_BLOCK.search(before))
    if before.rstrip().endswith("(") and after.lstrip().startswith(")"):
        inner = "\n" + base + INDENT
        return inner + "\n" + base, len(inner)
    if opened:
        return "\n" + base + INDENT, len(base) + len(INDENT) + 1
    return "\n" + base, len(base) + 1


def dedent_after(line: str) -> str | None:
    """Al escribir `)` o `END` como lo primero de una línea, la sangría baja un nivel. Devuelve la línea nueva
    o `None` si no cambia."""
    text = line.lstrip(" \t")
    indent = leading(line)
    if len(indent) < len(INDENT):
        return None
    if text == ")" or re.fullmatch(r"END", text, re.IGNORECASE):
        return indent[: -len(INDENT)] + text
    return None


def reindent(text: str, indent: str) -> str:
    """Al pegar varias líneas, la sangría se ajusta a la del lugar: la primera línea queda como está y las
    demás conservan su forma relativa, a partir de `indent`."""
    lines = text.split("\n")
    if len(lines) < 2:
        return text
    rest = [line for line in lines[1:] if line.strip()]
    common = min((len(leading(line)) for line in rest), default=0)
    out = [lines[0]]
    for line in lines[1:]:
        out.append(indent + line[common:] if line.strip() else line.strip(" \t"))
    return "\n".join(out)


def toggle_comment(lines: list[str]) -> list[str]:
    """Ctrl+/ (#146, punto 30): comenta las líneas con `-- ` (a la sangría de la menos sangrada) o, si ya lo
    están todas, quita el comentario."""
    code = [line for line in lines if line.strip()]
    if not code:
        return lines
    if all(line.lstrip().startswith("--") for line in code):
        out = []
        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith("--"):
                rest = stripped[3:] if stripped.startswith("-- ") else stripped[2:]
                out.append(leading(line) + rest)
            else:
                out.append(line)
        return out
    column = min(len(leading(line)) for line in code)
    return [line[:column] + "-- " + line[column:] if line.strip() else line for line in lines]


def clean_for_save(text: str) -> str:
    """Al guardar (#146, punto 30): sin espacios al final de las líneas y con un salto de línea final."""
    if not text:
        return text
    cleaned = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    return cleaned.rstrip("\n") + "\n"


def uppercase_word(word: str, keywords: frozenset[str]) -> str | None:
    """Palabras clave en mayúsculas al escribir (opcional): la palabra en mayúsculas, o `None` si no es una
    palabra clave o ya lo está."""
    if word.lower() in keywords and word != word.upper():
        return word.upper()
    return None


# -- fragmentos ----------------------------------------------------------------------------------------

#: Fragmentos (#146, punto 30): palabra + Tab. `|` marca dónde queda el cursor.
SNIPPETS: dict[str, str] = {
    "sel": "SELECT *\nFROM |;",
    "selw": "SELECT *\nFROM |\nWHERE ;",
    "cnt": "SELECT count(*)\nFROM |;",
    "cte": "WITH | AS (\n    \n)\nSELECT *\nFROM ;",
    "case": "CASE\n    WHEN | THEN \n    ELSE \nEND",
    "join": "JOIN | ON ",
    "gb": "GROUP BY |",
    "ob": "ORDER BY |",
    "ins": "INSERT INTO | VALUES ();",
    "ct": "CREATE TABLE | AS\nSELECT *\nFROM ;",
    "str": "FROM ST_Read('|');",
}


@dataclass(frozen=True)
class Expansion:
    text: str
    cursor: int  # dentro de `text`


def expand_snippet(word: str, indent: str) -> Expansion | None:
    """El fragmento de `word`, con la sangría del lugar en sus líneas siguientes."""
    template = SNIPPETS.get(word.lower())
    if template is None:
        return None
    text = template.replace("\n", "\n" + indent)
    cursor = text.index("|")
    return Expansion(text.replace("|", "", 1), cursor)


# -- formato (Shift+Alt+F) -----------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""(?P<space>\s+)
    |(?P<comment>--[^\n]*|/\*.*?\*/)
    |(?P<string>'(?:[^']|'')*'?)
    |(?P<ident>"(?:[^"]|"")*"?)
    |(?P<number>\d+(?:\.\d*)?(?:[eE][-+]?\d+)?)
    |(?P<word>[A-Za-z_][A-Za-z0-9_$]*)
    |(?P<op>::|<=|>=|<>|!=|\|\||->>|->|[^\sA-Za-z0-9_])""",
    re.VERBOSE | re.DOTALL,
)
#: Palabras clave que el formato escribe en mayúsculas.
KEYWORDS = frozenset(
    [
        "select",
        "from",
        "where",
        "group",
        "by",
        "order",
        "having",
        "limit",
        "offset",
        "union",
        "all",
        "except",
        "intersect",
        "join",
        "left",
        "right",
        "inner",
        "full",
        "outer",
        "cross",
        "natural",
        "on",
        "using",
        "with",
        "as",
        "and",
        "or",
        "not",
        "in",
        "is",
        "null",
        "like",
        "ilike",
        "between",
        "case",
        "when",
        "then",
        "else",
        "end",
        "distinct",
        "insert",
        "into",
        "values",
        "update",
        "set",
        "delete",
        "create",
        "table",
        "view",
        "replace",
        "or",
        "temp",
        "temporary",
        "if",
        "exists",
        "drop",
        "alter",
        "add",
        "column",
        "primary",
        "key",
        "unique",
        "default",
        "qualify",
        "window",
        "over",
        "partition",
        "asc",
        "desc",
        "nulls",
        "first",
        "last",
        "returning",
        "cast",
        "try_cast",
        "true",
        "false",
        "interval",
        "copy",
        "to",
        "attach",
        "detach",
        "use",
        "describe",
        "show",
        "explain",
        "analyze",
        "pivot",
        "unpivot",
        "lateral",
        "recursive",
        "materialized",
        "filter",
        "within",
        "exclude",
        "rename",
        "summarize",
    ]
)
#: Comienzan una línea propia (al nivel de su paréntesis).
_CLAUSES = (
    ("SELECT",),
    ("FROM",),
    ("WHERE",),
    ("GROUP", "BY"),
    ("ORDER", "BY"),
    ("HAVING",),
    ("QUALIFY",),
    ("WINDOW",),
    ("LIMIT",),
    ("OFFSET",),
    ("UNION",),
    ("EXCEPT",),
    ("INTERSECT",),
    ("VALUES",),
    ("SET",),
    ("RETURNING",),
    ("LEFT",),
    ("RIGHT",),
    ("INNER",),
    ("FULL",),
    ("CROSS",),
    ("NATURAL",),
    ("JOIN",),
    ("WITH",),
)
_JOIN_PREFIX = frozenset(
    {"LEFT", "RIGHT", "INNER", "FULL", "CROSS", "NATURAL", "OUTER", "ASOF", "POSITIONAL"}
)


def _tokens(text: str) -> list[tuple[str, str]]:
    out = []
    for found in _TOKEN.finditer(text):
        kind = found.lastgroup or "op"
        out.append((kind, found.group(0)))
    return out


def format_sql(text: str) -> str:  # noqa: PLR0912, PLR0915 - un formateador en una pasada
    """Shift+Alt+F (#146, punto 30): palabras clave en mayúsculas, cada cláusula en su línea, la lista de
    `SELECT` una columna por línea, `AND`/`OR` del `WHERE` en líneas propias y las subconsultas sangradas.
    Solo cambia espacios y mayúsculas de palabras clave: nunca un texto, un nombre entre comillas ni un
    comentario (los comentarios `--` conservan su línea)."""
    tokens = _tokens(text)
    out: list[str] = []
    depth = 0
    clause = ""
    line_start = True
    previous = ""  # el último token significativo, en mayúsculas si es palabra
    previous_kind = ""
    stack: list[tuple[str, bool]] = []  # (cláusula de fuera, es subconsulta)

    def newline(extra: int = 0) -> None:
        nonlocal line_start
        while out and out[-1].strip() == "" and not out[-1].endswith("\n"):
            out.pop()
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append(INDENT * (depth + extra))
        line_start = True

    def emit(value: str) -> None:
        nonlocal line_start
        glued = value in (",", ")", ";", ".", "::") or previous in (".", "::", "(")
        if value == "(" and (
            previous_kind == "word" and (previous.lower() not in KEYWORDS or previous in _CALLS)
        ):
            glued = True
        if not line_start and not glued:
            out.append(" ")
        out.append(value)
        line_start = False

    def significant_after(index: int) -> str:
        return next((v.upper() for k, v in tokens[index + 1 :] if k not in ("space", "comment")), "")

    for i, (kind, value) in enumerate(tokens):
        if kind == "space":
            continue
        if kind == "comment":
            if value.startswith("--"):
                if not line_start:
                    out.append(" ")
                out.append(value)
                newline()
            else:
                emit(value)
            continue
        upper = value.upper() if kind == "word" else value
        if kind == "word":
            shown = upper if value.lower() in KEYWORDS else value
            following = significant_after(i)
            starts = (upper,) in _CLAUSES or (upper, following) in _CLAUSES
            if starts and previous not in _JOIN_PREFIX and not (upper == "SET" and previous in ("RESET", "")):
                newline()
                clause = upper
            elif (
                upper in ("AND", "OR")
                and clause in ("WHERE", "HAVING", "QUALIFY", "JOIN")
                and not _between_pending(tokens, i)
            ):
                newline(1)
            elif upper == "ON" and clause in _JOIN_PREFIX | {"JOIN"}:
                clause = "JOIN"
            emit(shown)
        elif value == "(":
            sub = significant_after(i) in ("SELECT", "WITH", "FROM", "VALUES")
            emit(value)
            stack.append((clause, sub))
            depth += 1
            clause = ""
        elif value == ")":
            outer, sub = stack.pop() if stack else ("", False)
            depth = max(0, depth - 1)
            if sub:
                newline()
            emit(value)
            clause = outer
        elif value == "," and clause == "SELECT":
            emit(value)
            newline(1)
        elif value == ";":
            emit(value)
            out.append("\n\n")
            line_start = True
            depth = 0
            stack.clear()
            clause = ""
            upper = ""
        else:
            emit(value)
        previous, previous_kind = upper, kind
    result = "\n".join(line.rstrip() for line in "".join(out).split("\n"))
    result = re.sub(r"\n{3,}", "\n\n", result).strip("\n")
    return result + "\n" if result else result


#: Palabras clave que se escriben como funciones: `CAST(`, no `CAST (`.
_CALLS = frozenset({"CAST", "TRY_CAST", "REPLACE", "LEFT", "RIGHT", "IF", "FILTER", "OVER"})


def _between_pending(tokens: list[tuple[str, str]], index: int) -> bool:
    """El `AND` de `BETWEEN a AND b` no parte la línea."""
    seen = 0
    for kind, value in reversed(tokens[:index]):
        if kind == "space":
            continue
        seen += 1
        if kind == "word" and value.upper() == "BETWEEN":
            return True
        if seen > 3 or (kind == "word" and value.upper() in ("AND", "OR", "WHERE")):
            return False
    return False


# -- ayuda de parámetros (#146, punto 30) --------------------------------------------------------------

#: Firmas que se muestran como mucho (DuckDB tiene funciones con decenas de variantes).
MAX_SIGNATURES = 6


def signature_sql(name: str) -> str:
    """Las variantes de una función según `duckdb_functions()` (solo lee el catálogo de DuckDB)."""
    from geoduck.domain.sql_text import quote_string_literal  # noqa: PLC0415

    return (
        "SELECT function_name, parameters, parameter_types, varargs, return_type, description "
        f"FROM duckdb_functions() WHERE lower(function_name) = lower({quote_string_literal(name)}) "
        "AND function_type IN ('scalar', 'aggregate', 'macro', 'table', 'table_macro') LIMIT 64"
    )


def signature_lines(rows: Sequence[Sequence[Any]]) -> list[str]:
    """`nombre(param TIPO, …) → TIPO` por variante, sin repetir, y la descripción de DuckDB al final."""
    lines: list[str] = []
    description = ""
    for row in rows:
        name, parameters, types, varargs, returns, about = (list(row) + [None] * 6)[:6]
        names = list(parameters or [])
        kinds = list(types or [])
        params = [
            f"{p} {t}" if t and str(t) != "ANY" else str(p)
            for p, t in zip(names, kinds + [""] * (len(names) - len(kinds)), strict=False)
        ]
        if varargs and str(varargs) not in ("", "NULL", "INVALID"):
            params.append(f"{varargs}…")
        line = f"{name}({', '.join(params)})"
        if returns:
            line += f" → {returns}"
        if line not in lines:
            lines.append(line)
        if about and not description:
            description = str(about).strip()
    shown = lines[:MAX_SIGNATURES]
    if len(lines) > MAX_SIGNATURES:
        shown.append(f"… +{len(lines) - MAX_SIGNATURES}")
    if description:
        shown.append(description if len(description) <= 160 else description[:159] + "…")
    return shown


def call_before(before: str) -> tuple[str, int] | None:
    """La función cuyo paréntesis está abierto antes del cursor y en qué argumento se está (0, 1…)."""
    depth = 0
    commas = 0
    quote = ""
    for i in range(len(before) - 1, -1, -1):
        ch = before[i]
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                found = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", before[:i])
                return (found.group(1), commas) if found else None
            depth -= 1
        elif ch == "," and depth == 0:
            commas += 1
        elif ch == ";":
            return None
    return None
