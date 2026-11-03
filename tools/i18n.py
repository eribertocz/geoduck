# SPDX-License-Identifier: GPL-2.0-or-later
"""Catálogo de traducción de GeoDuck (G6 · E4, GD-I18N-001, issue #68).

Los textos del código están en inglés, dentro de `tr("…")` o `N_("…")`. El español vive en
`geoduck/i18n/geoduck_es.ts` (XML de Qt Linguist, editable) y se compila a `geoduck_es.qm` con
`lrelease` de Qt.

    python tools/i18n.py --check    # CI: el .ts tiene cada texto del código, traducido y con los
                                    # mismos marcadores ({0}, {}); con lrelease, el .qm está al día
    python tools/i18n.py --write    # actualiza el .ts (añade los nuevos sin traducir, quita los que
                                    # ya no están) y, con lrelease, recompila el .qm
    python tools/i18n.py --write --seed pares.json    # rellena traducciones desde [[es, en], …]

`lrelease`: el de la variable `LRELEASE`, o `lrelease`/`lrelease6` del PATH (vienen con QGIS en conda-forge).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "geoduck"
TS = PKG / "i18n" / "geoduck_es.ts"
QM = TS.with_suffix(".qm")
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


def lrelease() -> str | None:
    for name in (os.environ.get("LRELEASE"), "lrelease", "lrelease6"):
        if name and shutil.which(name):
            return shutil.which(name)
    return None


def compile_qm(target: Path) -> None:
    tool = lrelease()
    if tool is None:
        raise SystemExit("No se encontró lrelease (variable LRELEASE, o lrelease/lrelease6 en el PATH)")
    subprocess.run([tool, "-silent", "-removeidentical", str(TS), "-qm", str(target)], check=True)


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
        if lrelease() is not None:
            compile_qm(QM)
            print(f"{TS.relative_to(ROOT)} y {QM.relative_to(ROOT)} al día ({len(sources)} textos)")
        else:
            print(f"{TS.relative_to(ROOT)} al día ({len(sources)} textos); sin lrelease, .qm sin compilar")
        missing = problems(sources, read_ts())
        for line in missing:
            print("  " + line)
        return 1 if missing else 0
    errors = problems(sources, translations)
    if lrelease() is not None:
        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "fresh.qm"
            compile_qm(fresh)
            if not QM.exists() or fresh.read_bytes() != QM.read_bytes():
                errors.append(f"{QM.relative_to(ROOT)} no corresponde al .ts: python tools/i18n.py --write")
    elif not QM.exists():
        errors.append(f"Falta {QM.relative_to(ROOT)}")
    for line in errors:
        print(line)
    if not errors:
        print(f"Traducción completa: {len(sources)} textos")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
