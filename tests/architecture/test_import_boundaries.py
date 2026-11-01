# SPDX-License-Identifier: GPL-2.0-or-later
"""Fronteras de importación de ADR-0010, verificadas por análisis estático (sin dependencias externas).

Un PR que cruce una frontera falla aquí, por ejemplo si `ui` importa `duckdb` o si `engine` importa
`qgis` (lo que permitiría tocar QGIS desde el hilo del worker).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "geoduck"
STDLIB = set(sys.stdlib_module_names) | {"__future__"}

#: Capa → (paquetes externos permitidos, subpaquetes de geoduck permitidos).
#: "" representa el módulo raíz `geoduck` (solo `__version__`).
RULES: dict[str, tuple[set[str], set[str]]] = {
    "domain": (set(), {"domain"}),
    "app": (set(), {"domain", "app"}),
    "engine": ({"duckdb", "pyarrow"}, {"domain", "engine"}),
    "infra": (set(), {"", "domain", "infra"}),
    "ui": ({"qgis"}, {"", "domain", "app", "infra", "ui"}),
}


def _layer(path: Path) -> str | None:
    rel = path.relative_to(PKG)
    return rel.parts[0] if len(rel.parts) > 1 else None


def _imports(path: Path) -> list[tuple[int, str]]:
    """(línea, módulo absoluto) de cada import, incluidos los diferidos dentro de funciones."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package_parts = ["geoduck", *path.relative_to(PKG).parts[:-1]]
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - node.level + 1]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            found.append((node.lineno, module))
    return found


def _violations(path: Path, layer: str) -> list[str]:
    externals, internals = RULES[layer]
    problems = []
    for line, module in _imports(path):
        top = module.split(".")[0]
        if top == "geoduck":
            parts = module.split(".")
            sub = parts[1] if len(parts) > 1 else ""
            if sub not in internals:
                problems.append(f"{path.relative_to(PKG.parent)}:{line} importa {module}")
        elif top not in STDLIB and top not in externals:
            problems.append(f"{path.relative_to(PKG.parent)}:{line} importa {module}")
    return problems


LAYER_FILES = [(p, _layer(p)) for p in sorted(PKG.rglob("*.py")) if _layer(p) in RULES]


@pytest.mark.parametrize(("path", "layer"), LAYER_FILES, ids=lambda v: str(v).split("geoduck/")[-1])
def test_layer_respects_import_rules(path, layer):
    assert _violations(path, layer) == []


def test_only_engine_imports_duckdb():
    offenders = [
        str(p.relative_to(PKG.parent))
        for p in PKG.rglob("*.py")
        if _layer(p) != "engine" and any(m.split(".")[0] == "duckdb" for _, m in _imports(p))
    ]
    assert offenders == []


def test_engine_never_imports_qt_or_qgis():
    """Prerrequisito estático de «ningún objeto QGIS/Qt en el hilo del worker»."""
    for path in (PKG / "engine").rglob("*.py"):
        tops = {m.split(".")[0] for _, m in _imports(path)}
        assert not tops & {"qgis", "PyQt5", "PyQt6", "sip"}, path


def test_rules_detect_a_violation(tmp_path):
    """El propio test detecta una frontera cruzada (evita un test que nunca falla)."""
    fake = PKG / "ui" / "_probe_violation.py"
    fake.write_text("import duckdb\n", encoding="utf-8")
    try:
        assert _violations(fake, "ui")
    finally:
        fake.unlink()


def test_every_package_is_covered():
    packages = {p.name for p in PKG.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    assert packages <= set(RULES) | {"resources", "i18n"}
