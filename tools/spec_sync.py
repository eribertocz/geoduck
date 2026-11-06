# SPDX-License-Identifier: GPL-2.0-or-later
"""Sincroniza los artefactos derivados de `spec/` y verifica su integridad.

Los archivos individuales de `spec/` son normativos. De ellos se derivan:

- `spec/GEODUCK_SPEC_MAESTRA.md`: consolidación por capítulos (se regenera, no se edita a mano);
- `spec/docs/manifest.json`: tamaño y SHA-256 de cada documento.

Uso:
    python tools/spec_sync.py --check   # falla si algo no coincide (CI)
    python tools/spec_sync.py --write   # regenera maestra y manifiesto
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SPEC = Path(__file__).resolve().parents[1] / "spec"
MASTER = "GEODUCK_SPEC_MAESTRA.md"
MANIFEST = "docs/manifest.json"

#: Orden de capítulos de la maestra (el mismo del paquete recibido).
CHAPTERS = (
    "README.md",
    "docs/vision.md",
    "docs/product-spec.md",
    "docs/architecture.md",
    "docs/technology.md",
    "specs/session-spec.md",
    "specs/sql-editor-spec.md",
    "specs/qgis-bridge-spec.md",
    "specs/spatial-spec.md",
    "specs/ui-ux-spec.md",
    "specs/qgis-import-spec.md",
    "specs/workspace-pro-spec.md",
    "docs/security.md",
    "docs/compatibility-distribution.md",
    "qa/test-strategy.md",
    "qa/benchmarks.md",
    "docs/roadmap.md",
    "docs/implementation-handoff.md",
    "docs/references.md",
)


def _master_header(spec: Path) -> str:
    """Conserva la cabecera vigente de la maestra (todo lo anterior al primer capítulo)."""
    text = (spec / MASTER).read_text(encoding="utf-8")
    cut = text.index('\n---\n\n<a id="capitulo-1"></a>')
    head = text[:cut]
    return head[: head.index("## Índice de capítulos")]


def build_master(spec: Path = SPEC) -> str:
    index = "".join(f"- [{i:02d}. {p}](#capitulo-{i})\n" for i, p in enumerate(CHAPTERS, 1))
    chapters = []
    for i, p in enumerate(CHAPTERS, 1):
        body = (spec / p).read_text(encoding="utf-8").rstrip("\n")
        chapters.append(f'\n---\n\n<a id="capitulo-{i}"></a>\n\n## CAPÍTULO {i:02d} — `{p}`\n\n{body}\n\n')
    # Los capítulos van separados por una línea en blanco adicional, como en el paquete recibido.
    return _master_header(spec) + "## Índice de capítulos\n" + index + "\n" + "\n".join(chapters)


def _documents(spec: Path) -> list[Path]:
    files = [f for f in spec.rglob("*") if f.is_file()]
    return sorted(
        (f for f in files if f.relative_to(spec).as_posix() != MANIFEST),
        key=lambda f: f.relative_to(spec).as_posix(),
    )


def build_manifest(spec: Path = SPEC, master_text: str | None = None) -> str:
    data = json.loads((spec / MANIFEST).read_text(encoding="utf-8"))
    docs = []
    for f in _documents(spec):
        rel = f.relative_to(spec).as_posix()
        raw = master_text.encode("utf-8") if (rel == MASTER and master_text is not None) else f.read_bytes()
        docs.append({"path": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    data["documents"] = docs
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def check(spec: Path = SPEC) -> list[str]:
    problems = []
    master = build_master(spec)
    if (spec / MASTER).read_text(encoding="utf-8") != master:
        problems.append(f"{MASTER} no coincide con los archivos individuales")
    if (spec / MANIFEST).read_text(encoding="utf-8") != build_manifest(spec):
        problems.append(f"{MANIFEST} no coincide con los tamaños y SHA-256 de spec/")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    if args.write:
        master = build_master()
        (SPEC / MASTER).write_text(master, encoding="utf-8", newline="\n")
        (SPEC / MANIFEST).write_text(build_manifest(), encoding="utf-8", newline="\n")
        print("Maestra y manifiesto regenerados")
        return 0
    problems = check()
    for p in problems:
        print("ERROR:", p, file=sys.stderr)
    if not problems:
        print("spec/ íntegro: maestra y manifiesto coinciden")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
