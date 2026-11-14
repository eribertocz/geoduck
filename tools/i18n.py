# SPDX-License-Identifier: GPL-2.0-or-later
"""Catálogo de traducción de GeoDuck (G6 · E4, GD-I18N-001, issue #68).

Los textos del código están en inglés, dentro de `tr("…")` o `N_("…")`. El español vive en
`geoduck/i18n/geoduck_es.ts` (XML de Qt Linguist, editable), que GeoDuck lee tal cual (sin `.qm`).

    python tools/i18n.py --check    # CI: el .ts tiene cada texto del código, traducido y con los
                                    # mismos marcadores ({0}, {}); ningún texto de la interfaz
                                    # escrito sin `tr()` (#149); la ficha del complemento, en los dos
                                    # idiomas
    python tools/i18n.py --write    # actualiza el .ts (añade los nuevos sin traducir, quita los que
                                    # ya no están)
    python tools/i18n.py --write --seed pares.json    # rellena traducciones desde [[es, en], …]
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "geoduck"
TS = PKG / "i18n" / "geoduck_es.ts"
CONTEXT = "GeoDuck"
MARKERS = ("tr", "N_")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def extract() -> dict[str, list[str]]:
    """Texto inglés → lugares (`archivo:línea`), en orden de aparición."""
    found: dict[str, list[str]] = {}
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) in MARKERS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                where = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                found.setdefault(node.args[0].value, []).append(where)
    return found


def read_ts(path: Path = TS) -> dict[str, str]:
    """Texto inglés → traducción (vacía si falta)."""
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for message in ET.parse(path).getroot().iter("message"):
        source = message.findtext("source") or ""
        translation = message.find("translation")
        unfinished = translation is not None and translation.get("type") == "unfinished"
        out[source] = "" if translation is None or unfinished else (translation.text or "")
    return out


def write_ts(sources: dict[str, list[str]], translations: dict[str, str], path: Path = TS) -> None:
    root = ET.Element("TS", version="2.1", language="es_ES", sourcelanguage="en")
    context = ET.SubElement(root, "context")
    ET.SubElement(context, "name").text = CONTEXT
    for source, places in sources.items():
        message = ET.SubElement(context, "message")
        for place in places:
            filename, line = place.rsplit(":", 1)
            ET.SubElement(message, "location", filename=f"../../{filename}", line=line)
        ET.SubElement(message, "source").text = source
        translation = ET.SubElement(message, "translation")
        text = translations.get(source, "")
        if text:
            translation.text = text
        else:
            translation.set("type", "unfinished")
    ET.indent(root, space="    ")
    body = ET.tostring(root, encoding="unicode")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n' + body + "\n", encoding="utf-8")


def problems(sources: dict[str, list[str]], translations: dict[str, str]) -> list[str]:
    errors = []
    for source, places in sources.items():
        text = translations.get(source)
        if text is None:
            errors.append(f"Sin entrada en el .ts: {source!r} ({places[0]})")
        elif not text:
            errors.append(f"Sin traducir: {source!r} ({places[0]})")
        elif sorted(_PLACEHOLDER.findall(source)) != sorted(_PLACEHOLDER.findall(text)):
            errors.append(f"Marcadores distintos: {source!r} → {text!r}")
    errors += [f"Ya no está en el código: {s!r}" for s in translations if s not in sources]
    return errors


#: Funciones de Qt (y de GeoDuck) que muestran su primer argumento al usuario: con un texto escrito tal
#: cual (sin `tr()`), el inglés se vería también con QGIS en español (#149).
_SHOWS_TEXT = {
    "setText", "setToolTip", "setWindowTitle", "setPlaceholderText", "setStatusTip", "setWhatsThis",
    "addAction", "setTitle", "addItem", "setAccessibleName", "setAccessibleDescription", "showMessage",
    "pushMessage",
    "notify", "toast", "setHeaderLabels", "addMenu", "setLabelText", "setTabText", "setTabToolTip",
    "setButtonText", "information", "critical", "question", "label", "button", "QLabel", "QPushButton",
    "QCheckBox", "QRadioButton", "QAction", "QMenu", "QGroupBox", "QTreeWidgetItem", "QListWidgetItem",
    "QTableWidgetItem",
}  # fmt: skip
#: Su segundo argumento (la ayuda de un botón con ícono).
_SHOWS_SECOND = {"icon_button"}
#: Palabras que no se traducen: nombres propios, teclas, SQL y formatos.
_NAMES = frozenset(
    {
        "GeoDuck",
        "DuckDB",
        "QGIS",
        "Ctrl",
        "Shift",
        "Enter",
        "Esc",
        "Alt",
        "Space",
        "NULL",
        "WHERE",
        "SQL",
        "EPSG",
        "GPL",
        "LICENSE",
        "Duck",
        "Geo",
        "href",
        "style",
        "color",
        "span",
        "nbsp",
        "issues",
        "blob",
        "main",
        "later",
        "PyArrow",
        "GeoParquet",
        "Parquet",
        "CSV",
        "JSON",
        "GPKG",
        "WKT",
        "WKB",
        "COPY",
        "FORMAT",
        "Arrow",
    }
)


def _literals(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [text for e in node.elts for text in _literals(e)]
    if isinstance(node, ast.BinOp):
        return _literals(node.left) + _literals(node.right)
    if isinstance(node, ast.IfExp):
        return _literals(node.body) + _literals(node.orelse)
    return []


def untranslated() -> list[str]:
    """Textos de la interfaz escritos sin `tr()` (#149): `label("Guardar")` en vez de `label(tr("Save"))`.
    Los registros (`log.warning`) no son interfaz; las palabras de `_NAMES` no se traducen."""
    found = []
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if isinstance(func, ast.Attribute) and getattr(func.value, "id", "") in ("log", "logger", "_log"):
                continue
            if name in _SHOWS_TEXT:
                args = node.args[:1]
            elif name in _SHOWS_SECOND:
                args = node.args[1:2]
            else:
                continue
            for text in (t for arg in args for t in _literals(arg)):
                plain = re.sub(r"<[^>]*>|&\w+;", "", text)
                words = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]{3,}", plain) if w not in _NAMES]
                if words:
                    where = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                    found.append(f"Texto sin tr(): {text!r} ({where})")
    return found


def metadata_problems() -> list[str]:
    """La ficha del complemento (#149): `description` y `about` en inglés y en español (`[es]`)."""
    import configparser

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(PKG / "metadata.txt", encoding="utf-8")
    general = parser["general"]
    return [
        f"metadata.txt: falta «{key}»"
        for key in ("description", "about", "description[es]", "about[es]")
        if not general.get(key, "").strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--seed", type=Path, help="JSON [[es, en], …] para rellenar traducciones")
    args = parser.parse_args()
    sources = extract()
    translations = read_ts()
    if args.write:
        if args.seed:
            for es, en in json.loads(args.seed.read_text(encoding="utf-8")):
                translations.setdefault(en, es) if not translations.get(en) else None
        write_ts(sources, {s: translations.get(s, "") for s in sources})
        print(f"{TS.relative_to(ROOT)} al día ({len(sources)} textos)")
        missing = problems(sources, read_ts())
        for line in missing:
            print("  " + line)
        return 1 if missing else 0
    errors = problems(sources, translations) + untranslated() + metadata_problems()
    for line in errors:
        print(line)
    if not errors:
        print(f"Traducción completa: {len(sources)} textos")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
