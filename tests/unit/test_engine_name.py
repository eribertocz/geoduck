# SPDX-License-Identifier: GPL-2.0-or-later
"""La interfaz no nombra al motor fuera de «Acerca de» y de la revisión de componentes de «Diagnóstico»."""

from __future__ import annotations

import ast
from pathlib import Path

from geoduck.domain import i18n

ROOT = Path(__file__).resolve().parents[2]
NAME = "DuckDB"

#: Textos que pueden nombrarlo: la marca y los componentes de «Diagnóstico».
ALLOWED_SOURCES = {
    "DuckDB is a trademark of the DuckDB Foundation.",
    "DuckDB {0} is not supported; {1} or later is required",
    "DuckDB origin",
    "DuckDB from",
    "Not evaluated: DuckDB is not available.",
    "DuckDB allows unsigned extensions in this environment.",
    "Python {0}: there are no DuckDB ≥ 1.5 wheels for this version.",
    "DuckDB {0} is older than the minimum supported {1}.",
    "DuckDB {0} is provided by the plugin «{1}», which includes it in its folder. QGIS can only have one "
    "DuckDB loaded: GeoDuck and that plugin share this version (risk R11).",
    "DuckDB {0}: supported",
}
#: Archivos de la interfaz donde un texto fijo puede nombrarlo.
ALLOWED_FILES = {"about_dialog.py"}


def test_no_translated_text_names_the_engine_outside_about_and_diagnostics():
    catalog = i18n.load_catalog(ROOT / "geoduck" / "i18n" / "geoduck_es.ts")
    named = sorted(
        source
        for source, text in catalog.items()
        if (NAME in source or NAME in (text or "")) and source not in ALLOWED_SOURCES
    )
    assert named == []


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def test_no_fixed_interface_text_names_the_engine():
    """Textos sin `tr()` en `geoduck/ui` (títulos, filtros de archivos): tampoco."""
    found = []
    for path in sorted((ROOT / "geoduck" / "ui").rglob("*.py")):
        if path.name in ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and NAME in node.value
                and id(node) not in skip
            ):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value[:60]}")
    assert found == []
