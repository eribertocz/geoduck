# SPDX-License-Identifier: GPL-2.0-or-later
"""Regla de ADR-0011: GeoDuck no modifica silenciosamente paquetes, rutas de importación ni configuraciones
de otros complementos.

Análisis estático (AST) de todo el paquete `geoduck/` del complemento. Se prohíbe:

- usar `sys.path`, `sys.modules`, `sys.meta_path` o `sys.path_hooks` (alterar qué `duckdb` recibe QGIS);
- `site.addsitedir` e `importlib.reload`;
- instalar o ejecutar procesos: `subprocess`, `pip`, `ensurepip`, `os.system`, `os.spawn*`, `os.exec*`;
- cambiar variables de entorno del proceso de QGIS: asignar o borrar en `os.environ`, `os.putenv`,
  `os.unsetenv`, `os.environ.update/pop/setdefault/clear`;
- cargar, descargar o administrar otros complementos: `qgis.utils.loadPlugin/startPlugin/unloadPlugin/
  reloadPlugin/updateAvailablePlugins` y el instalador `pyplugin_installer`.

Las herramientas de desarrollo (`tools/`) y las pruebas no forman parte del complemento y no se analizan.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "geoduck"

FORBIDDEN_MODULES = {"subprocess", "pip", "ensurepip", "pyplugin_installer"}
FORBIDDEN_SYS_ATTRS = {"path", "modules", "meta_path", "path_hooks"}
FORBIDDEN_CALLS = {
    ("site", "addsitedir"),
    ("importlib", "reload"),
    ("os", "system"),
    ("os", "putenv"),
    ("os", "unsetenv"),
    ("os", "popen"),
}
FORBIDDEN_OS_PREFIXES = ("spawn", "exec")
FORBIDDEN_QGIS_UTILS = {"loadPlugin", "startPlugin", "unloadPlugin", "reloadPlugin", "updateAvailablePlugins"}
ENVIRON_MUTATORS = {"update", "pop", "setdefault", "clear", "popitem"}


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _check_import(node: ast.AST) -> list[str]:
    problems: list[str] = []
    if isinstance(node, ast.Import):
        problems += [f"importa {a.name}" for a in node.names if a.name.split(".")[0] in FORBIDDEN_MODULES]
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        names = {a.name for a in node.names}
        if module.split(".")[0] in FORBIDDEN_MODULES:
            problems.append(f"importa {module}")
        if module == "qgis.utils":
            problems += [f"importa qgis.utils.{n}" for n in sorted(names & FORBIDDEN_QGIS_UTILS)]
        if module == "sys":
            problems += [f"importa sys.{n}" for n in sorted(names & FORBIDDEN_SYS_ATTRS)]
    return problems


def _check_attribute(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Attribute):
        return []
    dotted = _dotted(node)
    head, _, attr = dotted.rpartition(".")
    forbidden = (head == "sys" and attr in FORBIDDEN_SYS_ATTRS) or (
        dotted.startswith("qgis.utils.") and attr in FORBIDDEN_QGIS_UTILS
    )
    return [f"usa {dotted}"] if forbidden else []


def _check_call(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Call):
        return []
    dotted = _dotted(node.func)
    head, _, attr = dotted.rpartition(".")
    if (head, attr) in FORBIDDEN_CALLS or (head == "os" and attr.startswith(FORBIDDEN_OS_PREFIXES)):
        return [f"llama a {dotted}"]
    if head == "os.environ" and attr in ENVIRON_MUTATORS:
        return [f"modifica os.environ con {attr}()"]
    return []


def _check_environ_write(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.Assign, ast.Delete)):
        targets = node.targets
    elif isinstance(node, ast.AugAssign):
        targets = [node.target]
    else:
        return []
    hits = [t for t in targets if isinstance(t, ast.Subscript) and _dotted(t.value) == "os.environ"]
    return ["modifica os.environ[...]"] if hits else []


CHECKS = (_check_import, _check_attribute, _check_call, _check_environ_write)


def violations_in(source: str, filename: str = "<mem>") -> list[str]:
    tree = ast.parse(source, filename=filename)
    return [
        f"{filename}:{getattr(node, 'lineno', '?')} {problem}"
        for node in ast.walk(tree)
        for check in CHECKS
        for problem in check(node)
    ]


PLUGIN_FILES = sorted(PKG.rglob("*.py"))


@pytest.mark.parametrize("path", PLUGIN_FILES, ids=lambda p: str(p.relative_to(PKG.parent)))
def test_plugin_module_does_not_touch_foreign_state(path):
    assert violations_in(path.read_text(encoding="utf-8"), str(path.relative_to(PKG.parent))) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "import sys\nsys.path.insert(0, 'x')",
        "import sys\nsys.modules['duckdb'] = None",
        "import sys\nsys.modules.pop('duckdb')",
        "from sys import path\npath.append('x')",
        "import subprocess\nsubprocess.run(['pip', 'install', 'duckdb'])",
        "from pip._internal import main",
        "import os\nos.system('pip install duckdb')",
        "import os\nos.environ['PYTHONPATH'] = 'x'",
        "import os\nos.environ.update({'A': 'b'})",
        "import os\ndel os.environ['PYTHONNOUSERSITE']",
        "import os\nos.putenv('A', 'b')",
        "import os\nos.execv('x', [])",
        "import site\nsite.addsitedir('x')",
        "import importlib, duckdb\nimportlib.reload(duckdb)",
        "from qgis.utils import unloadPlugin\nunloadPlugin('qduckdb')",
        "import qgis.utils\nqgis.utils.reloadPlugin('qduckdb')",
        "import pyplugin_installer",
    ],
)
def test_rule_detects_each_forbidden_pattern(snippet):
    """La regla no es un test que nunca falla: cada patrón prohibido se detecta."""
    assert violations_in(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        "import sys\nprint(sys.version_info, sys.executable)",
        "import os\nvalue = os.environ.get('HOME')",
        "import importlib\nm = importlib.import_module('duckdb')",
        "import site\nu = site.getusersitepackages()",
        "from qgis.utils import iface",
    ],
)
def test_rule_allows_read_only_inspection(snippet):
    """El diagnóstico puede leer el entorno; lo prohibido es modificarlo."""
    assert violations_in(snippet) == []
