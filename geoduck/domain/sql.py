# SPDX-License-Identifier: GPL-2.0-or-later
"""Modelo de ejecución de SQL del usuario (G2; spec/specs/sql-editor-spec.md §2–§4, ADR-0004).

Puro: sin DuckDB. El motor divide el script con el parser oficial y devuelve estos registros.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from geoduck.domain.errors import ErrorCode
from geoduck.domain.i18n import tr
from geoduck.domain.transaction import TransactionState

#: Tamaños de vista previa permitidos (sql-editor-spec §4). 200 por defecto.
PREVIEW_LIMITS = (50, 200, 500, 1000)
DEFAULT_PREVIEW_LIMIT = 200

#: Tipos de sentencia de DuckDB que solo leen. Son las únicas que se pueden repetir para cargar el resultado
#: completo en QGIS (GD-SQL-006); todas las demás cambian, o pueden cambiar, estructura, datos o estado.
_READ_TYPES = frozenset({"SELECT"})
_PLAN_TYPES = frozenset({"EXPLAIN"})
#: Lo que «Explicar» acepta (G6 · E3): lecturas y DML. Verificado con DuckDB 1.5.0 y 2.0.0: `EXPLAIN` de
#: INSERT, UPDATE o DELETE no los ejecuta. Lo demás (configuración, transacciones, extensiones, ATTACH…) se
#: rechaza aunque DuckDB lo admita, para no arriesgar efectos (ADR-0011).
EXPLAINABLE_TYPES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})


class OutputKind(str, Enum):
    """sql-editor-spec §3."""

    STATUS = "STATUS"
    TABULAR = "TABULAR"
    MUTATION_ROWS = "MUTATION_ROWS"
    PLAN = "PLAN"


class StatementStatus(str, Enum):
    OK = "OK"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    #: No se ejecutó porque una sentencia anterior falló o se canceló (sql-editor-spec §2).
    SKIPPED = "SKIPPED"


class RunScope(str, Enum):
    """GD-SQL-004: qué se ejecuta."""

    CURRENT = "CURRENT"
    SELECTION = "SELECTION"
    ALL = "ALL"


@dataclass(frozen=True)
class SqlStatement:
    """Una sentencia tal como la delimita el parser de DuckDB, con su rango en el texto del editor."""

    index: int
    #: Tipo que da el parser de DuckDB (`SELECT`, `INSERT`, `CREATE`, `TRANSACTION`, …); nunca la primera
    #: palabra del texto (un `WITH` puede preceder a un `INSERT`).
    type: str
    text: str
    #: Desplazamientos en caracteres dentro del texto completo del editor: [start, end).
    start: int
    end: int

    @property
    def is_read(self) -> bool:
        return self.type in _READ_TYPES

    @property
    def is_plan(self) -> bool:
        return self.type in _PLAN_TYPES

    @property
    def replayable(self) -> bool:
        """GD-SQL-006: solo una lectura puede volver a ejecutarse para cargar su resultado completo. Nunca
        DDL, DML (con o sin `RETURNING`), `ATTACH`/`DETACH`, transacciones ni configuración."""
        return self.is_read

    @property
    def may_change_state(self) -> bool:
        """Decisión del 2026-11-01: toda sentencia que no sea una lectura o un plan puede cambiar estructura,
        datos o estado de la sesión (invalidación conservadora de vistas previas)."""
        return not (self.is_read or self.is_plan)


@dataclass(frozen=True)
class Preview:
    """Vista previa acotada: nunca el resultado completo (sql-editor-spec §4)."""

    columns: tuple[str, ...]
    types: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    #: Había más filas que el límite; no se cuentan (no hay `COUNT(*)` automático).
    truncated: bool
    limit: int


@dataclass(frozen=True)
class StatementResult:
    statement: SqlStatement
    status: StatementStatus
    output: OutputKind | None = None
    duration_ms: float = 0.0
    message: str = ""
    preview: Preview | None = None
    error_code: ErrorCode | None = None
    #: Posición del error en el texto del editor (caracteres), si DuckDB la da (F-39).
    error_offset: int | None = None
    #: Estado transaccional comprobado después de la sentencia (decisión del 2026-11-01).
    transaction: TransactionState | None = None


@dataclass(frozen=True)
class ScriptRun:
    run_id: int
    scope: RunScope
    results: tuple[StatementResult, ...]
    #: Error de sintaxis que impidió ejecutar nada (F-38).
    parse_error: str = ""
    parse_error_offset: int | None = None
    #: Base en uso al terminar (G7: la de la celda, o la que fije un `USE` escrito en ella); `None` si no
    #: se pudo leer.
    current_database: str | None = None

    @property
    def failed(self) -> bool:
        return bool(self.parse_error) or any(
            r.status in (StatementStatus.FAILED, StatementStatus.CANCELLED) for r in self.results
        )

    @property
    def last_transaction(self) -> TransactionState | None:
        known = [r.transaction for r in self.results if r.transaction is not None]
        return known[-1] if known else None


def statement_at(statements: tuple[SqlStatement, ...], offset: int) -> SqlStatement | None:
    """Sentencia «actual» para el cursor: la que lo contiene; si está entre dos, la anterior."""
    chosen = None
    for st in statements:
        if st.start <= offset:
            chosen = st
        if st.start <= offset < st.end:
            return st
    return chosen or (statements[0] if statements else None)


_LINE = re.compile(r"^LINE (\d+): (.*)$")


def error_offset_in(text: str, message: str) -> int | None:
    """Desplazamiento en `text` que DuckDB señala con `LINE n:` y `^` (F-39), o `None` si no se puede
    determinar con seguridad (por ejemplo, si DuckDB recortó la línea con «...»)."""
    lines = message.splitlines()
    for i, line in enumerate(lines[:-1]):
        m = _LINE.match(line)
        if not m:
            continue
        caret = lines[i + 1]
        column = caret.find("^") - (len(line) - len(m.group(2)))
        snippet = m.group(2)
        if column < 0 or snippet.startswith("..."):
            return None
        text_lines = text.split("\n")
        number = int(m.group(1)) - 1
        if number >= len(text_lines) or not text_lines[number].startswith(snippet.rstrip(".")[:column]):
            return None
        return sum(len(t) + 1 for t in text_lines[:number]) + column
    return None


# -- títulos de resultado -------------------------------------------------------------------------

_TITLE_MAX = 28
_COMMENT = re.compile(r"^\s*--\s*(.+?)\s*$")
_IDENT = r'(?:"(?:[^"]|"")+"|[A-Za-z_À-￿][\w$À-￿]*)'
_QUALIFIED = rf"({_IDENT}(?:\s*\.\s*{_IDENT})*)"
_FROM = re.compile(rf"\bFROM\s+{_QUALIFIED}", re.IGNORECASE)
_DML_TARGET = re.compile(
    rf"\b(INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM)\s+{_QUALIFIED}", re.IGNORECASE
)
_ONLY_COUNT = re.compile(
    r"^\s*(?:WITH\b.*?\)\s*)?SELECT\s+COUNT\s*\(\s*\*?\s*\)(?:\s+(?:AS\s+)?\w+)?\s+FROM\b", re.I | re.S
)
_SINGLE_ALIAS = re.compile(r"^\s*SELECT\s+[^,]+?\s+AS\s+(" + _IDENT + r")\s*;?\s*$", re.I | re.S)
_STRINGS = re.compile(r"'(?:[^']|'')*'|\$\$.*?\$\$", re.S)
_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


def explicit_title(editor_text: str, statement: SqlStatement) -> str | None:
    """Nombre explícito: un comentario `-- …` en la línea inmediatamente anterior al código de la sentencia
    (sin línea en blanco entre ambos). En 1.5.x ese comentario forma parte del texto de la sentencia (F-35);
    en 2.0 queda antes: se busca en el texto del editor."""
    offset = statement.start
    for line in statement.text.split("\n"):
        if line.strip() and not _COMMENT.match(line):
            offset += len(line) - len(line.lstrip())
            break
        offset += len(line) + 1
    line_start = editor_text.rfind("\n", 0, offset) + 1
    if editor_text[line_start:offset].strip():
        return None  # hay código antes en la misma línea: el comentario de arriba no describe esta sentencia
    above_end = line_start - 1
    if above_end < 0:
        return None
    above = editor_text[editor_text.rfind("\n", 0, above_end) + 1 : above_end]
    match = _COMMENT.match(above)
    return _short(match.group(1)) if match else None


def automatic_title(statement: SqlStatement) -> str:
    """Nombre legible deducido del SQL, sin ejecutar nada: «Productos», «Total productos», «Plan ventas»…"""
    sql = _COMMENTS.sub(" ", _STRINGS.sub("''", statement.text)).strip()
    if statement.type in {"INSERT", "UPDATE", "DELETE"}:
        target = _DML_TARGET.search(sql)
        verb = {"INSERT": tr("Inserted into"), "UPDATE": tr("Updated in"), "DELETE": tr("Deleted from")}[
            statement.type
        ]
        return _short(f"{verb} {_humanize(target.group(2), lower=True)}" if target else verb)
    if statement.is_plan:
        source = _FROM.search(sql)
        plan = tr("Plan")
        return _short(f"{plan} {_humanize(source.group(1), lower=True)}" if source else plan)
    if not statement.is_read:
        return _short(_command_title(statement.type, sql))  # un CREATE … AS SELECT … FROM x crea, no lee x
    source = _FROM.search(sql)
    if source:
        name = _humanize(source.group(1))
        total = tr("Total")
        return _short(f"{total} {name[:1].lower() + name[1:]}" if _ONLY_COUNT.match(sql) else name)
    alias = _SINGLE_ALIAS.match(sql)
    if alias:
        return _short(_humanize(alias.group(1)))
    return tr("Result")


_DDL_OBJECT = re.compile(
    r"^\s*(CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?"
    r"(?:TABLE|VIEW|SCHEMA|MACRO|FUNCTION|SEQUENCE|INDEX|TYPE|SECRET)?\s*"
    rf"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?{_QUALIFIED}",
    re.IGNORECASE,
)
_ATTACH_ALIAS = re.compile(rf"\bAS\s+{_QUALIFIED}", re.IGNORECASE)
_DETACH_NAME = re.compile(rf"^\s*DETACH\s+(?:DATABASE\s+)?(?:IF\s+EXISTS\s+)?{_QUALIFIED}", re.IGNORECASE)
_FIRST_WORDS = re.compile(r"^\s*(\w+(?:\s+\w+)?)")


def _command_title(kind: str, sql: str) -> str:
    """Sentencias sin resultado de datos: verbo y objeto («Crear productos», «Adjuntar comercial»)."""
    verbs = {"CREATE": tr("Create"), "DROP": tr("Drop"), "ALTER": tr("Alter")}
    ddl = _DDL_OBJECT.match(sql)
    if ddl and kind in {"CREATE", "DROP", "ALTER"}:
        return f"{verbs[ddl.group(1).upper()]} {_humanize(ddl.group(2), lower=True)}"
    if kind == "ATTACH":
        alias = _ATTACH_ALIAS.search(sql)
        attach = tr("Attach")
        return f"{attach} {_humanize(alias.group(1), lower=True)}" if alias else attach
    if kind == "DETACH":
        name = _DETACH_NAME.match(sql)
        detach = tr("Detach")
        return f"{detach} {_humanize(name.group(1), lower=True)}" if name else detach
    if kind in {"TRANSACTION", "SET", "PRAGMA", "VARIABLE_SET"}:
        words = _FIRST_WORDS.match(sql)
        return words.group(1).upper() if words else kind
    return kind.capitalize()


def result_title(editor_text: str, statement: SqlStatement) -> str:
    return explicit_title(editor_text, statement) or automatic_title(statement)


def _humanize(qualified: str, *, lower: bool = False) -> str:
    last = re.split(r"\s*\.\s*(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", qualified)[-1]
    if last.startswith('"'):
        return last[1:-1].replace('""', '"')  # identificador citado: se respeta tal cual
    words = last.replace("_", " ").strip()
    if lower:
        return words.lower()
    return words[:1].upper() + words[1:].lower()


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _TITLE_MAX else text[: _TITLE_MAX - 1].rstrip() + "…"


_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_DETACH_TARGET = re.compile(
    r'^\s*DETACH\s+(?:DATABASE\s+)?(?:IF\s+EXISTS\s+)?(?:"(?P<quoted>(?:[^"]|"")+)"|(?P<bare>[^\s;"]+))',
    re.IGNORECASE,
)


def detach_target(statement: SqlStatement) -> str | None:
    """Base que desadjunta una sentencia `DETACH` real (tipo del parser de DuckDB), o None si no lo es.

    Se decide por el tipo de sentencia, nunca por el texto: un `DETACH` dentro de una cadena o de un
    comentario no cuenta (qgis-bridge-spec §5.5). Si el nombre no se puede leer, devuelve "" (desconocido).
    """
    if statement.type != "DETACH":
        return None
    match = _DETACH_TARGET.match(_COMMENTS.sub(" ", statement.text))
    if match is None:
        return ""
    if match["quoted"] is not None:
        return match["quoted"].replace('""', '"')
    return str(match["bare"])
