# SPDX-License-Identifier: GPL-2.0-or-later
"""Construye el ZIP instalable del complemento de forma reproducible y lo valida.

Reglas (plugins.qgis.org/publish y docs/licensing.md): carpeta raíz `geoduck/`, `metadata.txt` válido,
`LICENSE` incluido, sin binarios ni archivos ocultos/generados y tamaño < 20 MB.

Uso: python tools/build_zip.py [--out dist]
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "geoduck"
MAX_BYTES = 20 * 1024 * 1024
REQUIRED = (
    "name",
    "qgisMinimumVersion",
    "description",
    "about",
    "version",
    "author",
    "email",
    "repository",
    "tracker",
    "homepage",
)
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".so", ".dll", ".pyd", ".dylib", ".exe", ".whl", ".zip"}
FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # marca fija: mismo contenido → mismo ZIP


def read_version() -> str:
    text = (PKG / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', text, re.M)
    if not match:
        raise SystemExit("No se encontró __version__ en geoduck/__init__.py")
    return match.group(1)


def validate_metadata(version: str) -> list[str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(PKG / "metadata.txt", encoding="utf-8")
    general = parser["general"]
    errors = [f"metadata.txt: falta «{key}»" for key in REQUIRED if not general.get(key, "").strip()]
    if general.get("version") != version:
        errors.append(f"metadata.txt version={general.get('version')} ≠ __version__={version}")
    if not re.fullmatch(r"\d+\.\d+\.\d+(a|b|rc)\d+", version):
        errors.append(f"La versión {version} no es una pre-release Alpha/Beta/RC (no se publica estable)")
    if general.get("supportsQt6", "").lower() != "true":
        errors.append("metadata.txt: supportsQt6 debe ser True (QGIS 4)")
    if not (PKG / general.get("icon", "")).is_file():
        errors.append("metadata.txt: el icono declarado no existe")
    return errors


def collect_files() -> list[Path]:
    files = []
    for path in sorted(PKG.rglob("*")):
        rel = path.relative_to(PKG)
        if path.is_dir() or any(part.startswith((".", "__pycache__")) for part in rel.parts):
            continue
        files.append(path)
    return files


def build(out_dir: Path) -> Path:
    version = read_version()
    errors = validate_metadata(version)
    files = collect_files()
    errors += [
        f"Binario o generado no permitido: {f.relative_to(ROOT)}"
        for f in files
        if f.suffix.lower() in FORBIDDEN_SUFFIXES
    ]
    if errors:
        raise SystemExit("\n".join(errors))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"geoduck-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in [*files, ROOT / "LICENSE"]:
            arcname = "geoduck/" + (path.name if path.parent == ROOT else path.relative_to(PKG).as_posix())
            info = zipfile.ZipInfo(arcname, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    size = target.stat().st_size
    if size > MAX_BYTES:
        raise SystemExit(f"El ZIP pesa {size} bytes (> 20 MB)")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (out_dir / f"{target.name}.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    print(f"{target} ({size} bytes) sha256={digest}")
    return target


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "dist"))
    build(Path(parser.parse_args(argv).out))


if __name__ == "__main__":
    main(sys.argv[1:])
