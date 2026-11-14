# SPDX-License-Identifier: GPL-2.0-or-later
"""Errores de primer nivel (#145, punto 13): de un error de DuckDB a una tarjeta que dice qué pasó, dónde y
cómo arreglarlo, **solo con lo que dice DuckDB**.

Sin Qt ni DuckDB. La tarjeta se elige por la clase de la excepción de DuckDB (`BinderException`,
`CatalogException`, `ParserException`, `ConversionException`, `IOException`, `OutOfMemoryException`…) o, si
no se tiene, por el prefijo de su mensaje («Binder Error:»…); el lugar sale de su marca `LINE n ^^^^`
(`error_offset_in`); las sugerencias y los arreglos, de lo que DuckDB propone: «Candidate bindings» y «Did you
mean» → «Cambiar a…»; «exists in the spatial extension» → «Cargar spatial…» (con permiso, ADR-0011). Los
arreglos solo cambian el texto del editor; nunca ejecutan nada. GeoDuck solo traduce el título.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from geoduck.domain.i18n import tr
from geoduck.domain.sql import error_token
from geoduck.domain.sql_text import quote_identifier

#: Arreglos posibles (lo que hace el botón de la tarjeta).
REPLACE, LOAD_EXTENSION, CHOOSE_FILE, OPEN_FOLDER, INSERT = "replace", "extension", "file", "folder", "insert"

#: Clases de error de DuckDB: clase de la excepción → prefijo de su mensaje.
KINDS = {
    "ParserException": "Parser Error",
    "BinderException": "Binder Error",
    "CatalogException": "Catalog Error",
    "ConversionException": "Conversion Error",
    "IOException": "IO Error",
    "HTTPException": "HTTP Error",
    "OutOfMemoryException": "Out of Memory Error",
    "ConstraintException": "Constraint Error",
    "InvalidInputException": "Invalid Input Error",
    "NotImplementedException": "Not implemented Error",
    "PermissionException": "Permission Error",
    "TransactionException": "TransactionContext Error",
    "OutOfRangeException": "Out of Range Error",
    "TypeMismatchException": "Mismatch Type Error",
    "DependencyException": "Dependency Error",
    "SequenceException": "Sequence Error",
    "SerializationException": "Serialization Error",
    "SyntaxException": "Syntax Error",
}
_PREFIX = re.compile(r"^([A-Za-z ]+ Error):\s*")
_SIMPLE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class Fix:
    """Un botón de la tarjeta. `REPLACE`: el texto de `start` a `end` (en el editor) pasa a ser `text`;
    `INSERT`: `text` se inserta en `start`; `LOAD_EXTENSION`: cargar la extensión `value` (con permiso);
    `CHOOSE_FILE`: elegir otro archivo para la ruta de `start` a `end`; `OPEN_FOLDER`: abrir la carpeta
    `value`."""

    kind: str
    label: str
    start: int = -1
    end: int = -1
    text: str = ""
    value: str = ""


@dataclass(frozen=True)
class ErrorCard:
    """Lo que la tarjeta muestra, en orden: qué pasó (`title`), dónde (`where`), por qué y la sugerencia
    (`explanation`), los arreglos (`fixes`) y el mensaje original de DuckDB (`original`)."""

    kind: str
    title: str
    where: str
    explanation: str
    fixes: tuple[Fix, ...]
    original: str
    offset: int | None
    line: int | None
    #: El título es el mensaje de DuckDB tal cual (un error que GeoDuck no reconoce): sin pliegue.
    raw: bool = False


def error_class(kind: str, message: str) -> str:
    """La clase de error: el prefijo de DuckDB («Binder Error»), de la excepción o del mensaje."""
    if kind in KINDS:
        return KINDS[kind]
    found = _PREFIX.match(message.strip())
    return found.group(1) if found else ""


def _body(message: str) -> str:
    """El mensaje sin su prefijo ni la marca `LINE n` (lo que dice DuckDB, en una o dos líneas)."""
    text = _PREFIX.sub("", message.strip(), count=1)
    kept: list[str] = []
    for line in text.splitlines():
        if line.startswith("LINE ") or (kept and not line.strip() and len(kept) > 1):
            break
        if line.strip():
            kept.append(line.strip())
    return " ".join(kept)


def headline(message: str) -> str:
    """El mensaje de DuckDB tal cual, sin la marca `LINE n` que señala la posición (la dice «dónde»)."""
    kept: list[str] = []
    for line in message.strip().splitlines():
        if line.startswith("LINE "):
            break
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def _quoted(name: str) -> str:
    """Un nombre que DuckDB sugiere, listo para el editor (entre comillas si hace falta)."""
    name = name.strip()
    if _SIMPLE.match(name) or (name.startswith('"') and name.endswith('"')):
        return name
    if "." in name and all(_SIMPLE.match(part) for part in name.split(".")):
        return name
    return quote_identifier(name)


def _line_of(text: str, offset: int | None) -> int | None:
    if offset is None or not 0 <= offset <= len(text):
        return None
    return text.count("\n", 0, offset)


def _token_span(text: str, offset: int | None, message: str) -> tuple[int, int, str]:
    word = error_token(text, offset, message)
    if offset is None or not word:
        return -1, -1, ""
    return offset, offset + len(word), word


def _where(text: str, offset: int | None, word: str, statement_start: int) -> tuple[str, int | None]:
    line = _line_of(text, offset if offset is not None else statement_start)
    if line is None:
        return "", None
    if offset is None:
        return tr("Line {0} · the whole statement").format(line + 1), line
    if word:
        return tr("Line {0} · near «{1}»").format(line + 1, word), line
    return tr("Line {0}").format(line + 1), line


def explain(  # noqa: PLR0911, PLR0912, PLR0915 - una rama por clase de error de DuckDB
    kind: str,
    message: str,
    text: str,
    offset: int | None,
    *,
    statement_start: int = 0,
    statement_end: int | None = None,
) -> ErrorCard:
    """La tarjeta de un error de DuckDB. `kind`: la clase de la excepción (o vacío); `message`: el mensaje
    completo de DuckDB; `text`: el texto del editor; `offset`: la posición del error en él (o `None`)."""
    original = message.strip()
    cls = error_class(kind, original)
    body = _body(original)
    start, end, word = _token_span(text, offset, original)
    where, line = _where(text, offset, word, statement_start)
    fixes: list[Fix] = []

    def card(title: str, explanation: str = "") -> ErrorCard:
        return ErrorCard(cls, title, where, explanation, tuple(fixes), original, offset, line)

    def raw() -> ErrorCard:
        """Un error que GeoDuck no reconoce: el texto de DuckDB, tal cual, es el título (#189)."""
        return ErrorCard(cls, headline(original), where, "", tuple(fixes), original, offset, line, raw=True)

    suggestion = _suggestion(original)
    if cls == "Parser Error":
        title = tr("Syntax error near «{}»").format(word) if word else tr("Syntax error")
        return card(title, tr("The SQL could not be read here: {}").format(body))
    if cls == "Binder Error":
        referenced = re.search(r'Referenced column "((?:[^"]|"")+)" not found', original)
        if referenced:
            name = referenced.group(1)
            if suggestion and start >= 0:
                fixes.append(
                    Fix(REPLACE, tr("Change to «{}»").format(suggestion), start, end, _quoted(suggestion))
                )
            hint = tr("Suggestion: {}.").format(suggestion) if suggestion else body
            return card(tr("The column «{}» does not exist").format(name), hint)
        return raw()
    if cls == "Catalog Error":
        extension = re.search(
            r'with name "?([\w.]+)"? is not in the catalog, but it exists in the (\w+) extension', original
        )
        if extension:
            name, ext = extension.group(1), extension.group(2)
            if ext == "spatial":  # la única que GeoDuck carga, y solo con permiso (spatial-spec §10)
                fixes.append(Fix(LOAD_EXTENSION, tr("Load «{}»").format(ext), value=ext))
            else:  # las demás: se escribe en el editor; nunca se cargan solas (ADR-0011)
                load = f"INSTALL {ext};\nLOAD {ext};\n"
                fixes.append(
                    Fix(INSERT, tr("Write LOAD {}").format(ext), statement_start, statement_start, load)
                )
            return card(
                tr("This query needs the «{}» extension").format(ext),
                tr("«{0}» exists in the «{1}» extension, which is not loaded.").format(name, ext),
            )
        missing = re.search(
            r"(Table|View|Schema|Catalog|Type|(?:Scalar |Table |Aggregate )?Function) "
            r'with name "?([^"!]+?)"? does not exist',
            original,
        )
        if suggestion and start >= 0:
            fixes.append(
                Fix(REPLACE, tr("Change to «{}»").format(suggestion), start, end, _quoted(suggestion))
            )
        hint = tr("Suggestion: {}.").format(suggestion) if suggestion else body
        if missing:
            what, name = missing.group(1).lower(), missing.group(2).strip()
            titles = {
                "table": tr("The table «{}» does not exist"),
                "view": tr("The view «{}» does not exist"),
                "schema": tr("The schema «{}» does not exist"),
                "catalog": tr("The database «{}» is not attached"),
                "type": tr("The type «{}» does not exist"),
            }
            title = titles.get(what, tr("The function «{}» does not exist")).format(name)
            return card(title, hint)
        return raw()
    if cls == "Conversion Error":
        value = re.search(r"Could not convert (?:string )?'((?:[^']|'')*)' to (\w+)", original)
        source = re.search(r"from source column (\S+)", original)
        target = value.group(2) if value else ""
        column = source.group(1).strip('"') if source else (word or "")
        if target in ("DOUBLE", "FLOAT", "INTEGER", "BIGINT", "DECIMAL", "SMALLINT", "TINYINT", "HUGEINT"):
            title = (
                tr("A value of «{}» is not a number").format(column)
                if column
                else tr("A value is not a number")
            )
        elif target in ("DATE", "TIMESTAMP", "TIME"):
            title = (
                tr("A value of «{}» is not a date").format(column) if column else tr("A value is not a date")
            )
        else:
            title = tr("A value cannot be converted")
        cast = _try_cast(text, offset)
        if cast is not None:
            fixes.append(Fix(REPLACE, tr("Use TRY_CAST"), cast[0], cast[1], cast[2]))
            if "::" in text[cast[0] : cast[1]] and line is not None:  # «cerca de «kwh::DOUBLE»»
                where = tr("Line {0} · near «{1}»").format(line + 1, text[cast[0] : cast[1]])
        if value:
            hint = tr("The value «{0}» cannot be converted to {1}.").format(value.group(1), target)
            if cast is not None:
                hint += " " + tr("TRY_CAST leaves it empty instead.")
        else:
            hint = body
        if source:
            where_text = tr("source column «{}»").format(column)
            where = f"{where} · {where_text}" if where else where_text
        return ErrorCard(cls, title, where, hint, tuple(fixes), original, offset, line)
    if cls in ("IO Error", "HTTP Error"):
        path = re.search(r'No files found that match the pattern "(.+?)"', original)
        if path:
            pattern = path.group(1)
            span = _literal_span(text, pattern, statement_start, statement_end)
            if span is not None:
                fixes.append(Fix(CHOOSE_FILE, tr("Choose file…"), span[0], span[1], value=pattern))
                line = _line_of(text, span[0])
            folder = _folder_of(pattern)
            if folder:
                fixes.append(Fix(OPEN_FOLDER, tr("Open folder"), value=folder))
            where = tr("Line {0} · «{1}»").format((line or 0) + 1, pattern) if line is not None else pattern
            return ErrorCard(
                cls,
                tr("The file is not found"),
                where,
                tr("There is no file with that path."),
                tuple(fixes),
                original,
                offset,
                line,
            )
        return raw()
    if cls == "Out of Memory Error":
        used = re.search(r"\(([\d.]+ ?\w+)/([\d.]+ ?\w+) used\)", original)
        hint = (
            tr("{0} of {1} were used (session «memory_limit»).").format(used.group(1), used.group(2))
            if used
            else body
        )
        limit = _double(used.group(2)) if used else ""
        if limit:
            fixes.append(
                Fix(
                    INSERT,
                    tr("Raise memory_limit…"),
                    statement_start,
                    statement_start,
                    f"SET memory_limit = '{limit}';\n",
                )
            )
        return card(tr("The query needs more memory than allowed"), hint)
    if cls == "Constraint Error":
        return raw()
    if cls == "TransactionContext Error":
        return raw()
    if cls in ("Invalid Input Error", "Out of Range Error", "Mismatch Type Error"):
        return raw()
    if cls == "Not implemented Error":
        return raw()
    if cls == "Permission Error":
        return raw()
    return raw()


def _suggestion(message: str) -> str:
    """Lo que DuckDB propone: «Did you mean "x"?» o el primer nombre de «Candidate bindings»."""
    found = re.search(r'Did you mean "((?:[^"]|"")+)"', message)
    if found:
        return found.group(1).replace('""', '"')
    found = re.search(r'Candidate bindings:\s*"((?:[^"]|"")+)"', message)
    if found:
        name = found.group(1).replace('""', '"')
        return name.rsplit(".", 1)[-1] if "." in name else name
    return ""


_CAST = re.compile(r"CAST\s*\(", re.IGNORECASE)
_SHORT_CAST = re.compile(r'((?:"(?:[^"]|"")+"|[\w.]+))::(\w+(?:\s*\([^)]*\))?)')


def _try_cast(text: str, offset: int | None) -> tuple[int, int, str] | None:
    """«Usar TRY_CAST» donde DuckDB marcó el error: `CAST(` → `TRY_CAST(`; `x::T` → `TRY_CAST(x AS T)`."""
    if offset is None or not 0 <= offset < len(text):
        return None
    if _CAST.match(text, offset) and not text[max(0, offset - 4) : offset].upper().endswith("TRY_"):
        return offset, offset + 4, "TRY_CAST"
    if text.startswith("::", offset):  # DuckDB marca el «::»: la expresión está justo antes
        before = re.search(r'(?:"(?:[^"]|"")+"|[\w.]+)$', text[:offset])
        offset = before.start() if before else offset
    found = _SHORT_CAST.match(text, offset)
    if found:
        return found.start(), found.end(), f"TRY_CAST({found.group(1)} AS {found.group(2)})"
    return None


def _literal_span(text: str, pattern: str, start: int, end: int | None) -> tuple[int, int] | None:
    """Dónde está la ruta (el texto entre comillas simples) en la sentencia."""
    literal = "'" + pattern.replace("'", "''") + "'"
    found = text.find(literal, start, end if end is not None else len(text))
    return (found, found + len(literal)) if found >= 0 else None


def _folder_of(pattern: str) -> str:
    """La carpeta de una ruta local sin comodines (para «Abrir carpeta»); vacío si no hay."""
    if "://" in pattern or any(ch in pattern for ch in "*?["):
        return ""
    for sep in ("\\", "/"):
        if sep in pattern:
            return pattern.rsplit(sep, 1)[0] or sep
    return ""


def _double(size: str) -> str:
    """El doble de un tamaño de DuckDB («4.0 GiB» → «8GB»), para subir `memory_limit`."""
    found = re.match(r"([\d.]+)\s*(\w+)", size)
    if not found:
        return ""
    value = float(found.group(1)) * 2
    unit = {"KiB": "KB", "MiB": "MB", "GiB": "GB", "TiB": "TB"}.get(found.group(2), found.group(2))
    return f"{value:g}{unit}"


def syntax_error(serialized: dict[str, object]) -> tuple[str, int | None] | None:
    """El aviso mientras se escribe (#145): de lo que devuelve `json_serialize_sql`, el error de sintaxis y su
    posición (en bytes de UTF-8); `None` si no hay error de sintaxis (lo demás, p. ej. «solo SELECT», no
    cuenta: no es un error del texto)."""
    if not serialized.get("error") or str(serialized.get("error_type", "")).lower() != "parser":
        return None
    position = serialized.get("position")
    try:
        offset = int(str(position)) if position is not None else None
    except (TypeError, ValueError):
        offset = None
    return str(serialized.get("error_message", "")), offset


def char_offset(text: str, byte_offset: int) -> int:
    """La posición en caracteres de una posición en bytes de UTF-8 (DuckDB cuenta bytes)."""
    return len(text.encode("utf-8")[:byte_offset].decode("utf-8", errors="ignore"))
