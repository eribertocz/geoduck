# SPDX-License-Identifier: GPL-2.0-or-later
"""Construye la guía de uso (#150) en español e inglés, dentro del complemento.

    python tools/build_guide.py [--check]

Fuente: `docs/guide/<idioma>/*.md` (los mismos nombres de página en los dos idiomas) y `docs/guide/assets/`.
Salida: `geoduck/guide/<idioma>/<página>.html`, que GeoDuck abre en el navegador, también sin internet
(MkDocs Material con `offline`: buscador sin servidor y sin fuentes de la web). `--strict`: un enlace o un
ancla rota, o una imagen que falta, detiene la construcción. `--check` solo revisa la fuente (sin MkDocs).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "guide"
OUT = ROOT / "geoduck" / "guide"
LANGUAGES = ("es", "en")

#: Las páginas, en orden, con su título en el menú de cada idioma: (sección, [(página, es, en)]).
NAV: list[tuple[tuple[str, str] | None, list[tuple[str, str, str]]]] = [
    (None, [("index", "Empieza aquí", "Start here"), ("concepts", "Conceptos", "Concepts")]),
    (
        ("Cómo hacer…", "How to…"),
        [
            ("open-database", "Abrir, crear y cerrar bases", "Open, create and close databases"),
            ("explore-table", "Explorar una tabla", "Explore a table"),
            ("load-into-qgis", "Cargar en QGIS", "Load into QGIS"),
            ("send-layers", "Enviar capas de QGIS", "Send QGIS layers"),
            ("import-files", "Importar archivos", "Import files"),
            ("export", "Exportar", "Export"),
            ("spatial-index", "Índice espacial", "Spatial index"),
        ],
    ),
    (
        None,
        [
            ("sql-editor", "Editor SQL", "SQL editor"),
            ("shortcuts", "Atajos del teclado", "Keyboard shortcuts"),
        ],
    ),
    (
        None,
        [
            ("errors", "Errores frecuentes", "Common errors"),
            ("performance", "Rendimiento", "Performance"),
            ("faq", "Preguntas frecuentes", "FAQ"),
            ("whats-new", "Novedades", "What's new"),
            ("report-a-problem", "Reportar un problema", "Report a problem"),
        ],
    ),
]

SITE = {"es": "Guía de GeoDuck", "en": "GeoDuck guide"}


def pages() -> list[str]:
    return [page for _, items in NAV for page, _, _ in items]


def check_source() -> list[str]:
    """Las dos guías tienen las mismas páginas (y solo las del menú) y cada imagen citada existe."""
    errors: list[str] = []
    wanted = set(pages())
    for lang in LANGUAGES:
        folder = SOURCE / lang
        found = {p.stem for p in folder.glob("*.md")}
        errors += [f"{lang}: falta {p}.md" for p in sorted(wanted - found)]
        errors += [f"{lang}: {p}.md no está en el menú" for p in sorted(found - wanted)]
        for md in sorted(folder.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            for image in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
                if not (folder / image).is_file():
                    errors.append(f"{lang}/{md.name}: falta la imagen {image}")
            anchors_es = re.findall(r"\{#([a-z0-9-]+)\}", text)
            other = SOURCE / ("en" if lang == "es" else "es") / md.name
            if other.is_file():
                anchors_other = re.findall(r"\{#([a-z0-9-]+)\}", other.read_text(encoding="utf-8"))
                if anchors_es != anchors_other:
                    errors.append(f"{md.name}: anclas distintas en es y en ({anchors_es} ≠ {anchors_other})")
    return errors


def config(lang: str, docs: Path, site: Path) -> str:
    nav: list[str] = []
    title = 1 if lang == "es" else 2
    for section, items in NAV:
        entries = [f"{'    ' if section else '  '}- {item[title]}: {item[0]}.md" for item in items]
        if section:
            nav.append(f"  - {section[title - 1]}:")
        nav += entries
    return "\n".join(
        [
            f"site_name: {SITE[lang]}",
            f"docs_dir: {docs}",
            f"site_dir: {site}",
            "use_directory_urls: false",
            "strict: true",
            "validation:",
            "  links:",
            "    not_found: warn",
            "    anchors: warn",
            "theme:",
            "  name: material",
            f"  language: {lang}",
            "  font: false",
            "  logo: assets/logo.svg",
            "  favicon: assets/logo.svg",
            "  features: [navigation.sections, navigation.footer, search.highlight, content.code.copy]",
            "  palette:",
            "    - media: '(prefers-color-scheme: light)'",
            "      scheme: default",
            "      toggle: {icon: material/weather-night, name: Oscuro / Dark}",
            "    - media: '(prefers-color-scheme: dark)'",
            "      scheme: slate",
            "      toggle: {icon: material/weather-sunny, name: Claro / Light}",
            "extra_css: [assets/geoduck.css]",
            "markdown_extensions: [admonition, attr_list, tables, toc, pymdownx.superfences]",
            "plugins: [search, offline]",
            "nav:",
            *nav,
            "",
        ]
    )


#: El buscador sin servidor carga este script de la web; la guía lleva su copia (MIT, `assets/`).
_SHIM = "https://unpkg.com/iframe-worker/shim"


def _offline(site: Path) -> None:
    """Nada de la web: el script del buscador va local; fuera lo que no sirve sin servidor."""
    for page in site.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        if _SHIM in text:
            depth = len(page.relative_to(site).parts) - 1
            page.write_text(text.replace(_SHIM, "../" * depth + "assets/iframe-worker.js"), encoding="utf-8")
    for junk in [*site.rglob("*.map"), site / "sitemap.xml", site / "sitemap.xml.gz"]:
        junk.unlink(missing_ok=True)
    left = [p for p in site.rglob("*.html") if "https://unpkg.com" in p.read_text(encoding="utf-8")]
    if left:
        raise SystemExit(f"La guía todavía carga scripts de la web: {left[0]}")


def build() -> None:
    for lang in LANGUAGES:
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            shutil.copytree(SOURCE / lang, docs)
            shutil.copytree(SOURCE / "assets", docs / "assets")
            site = OUT / lang
            if site.exists():
                shutil.rmtree(site)
            cfg = Path(tmp) / "mkdocs.yml"
            cfg.write_text(config(lang, docs, site), encoding="utf-8")
            env = {**os.environ, "NO_MKDOCS_2_WARNING": "1"}
            subprocess.run(
                [sys.executable, "-m", "mkdocs", "build", "-q", "-f", str(cfg)], check=True, env=env
            )
            _offline(site)
        print(f"{lang}: {site.relative_to(ROOT)} ({sum(1 for _ in site.rglob('*.html'))} páginas HTML)")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="solo revisa la fuente")
    args = parser.parse_args(argv)
    errors = check_source()
    if errors:
        raise SystemExit("\n".join(errors))
    if not args.check:
        build()


if __name__ == "__main__":
    main(sys.argv[1:])
