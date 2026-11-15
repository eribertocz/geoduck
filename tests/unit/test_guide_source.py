# SPDX-License-Identifier: GPL-2.0-or-later
"""La guía de uso (#150): las mismas páginas, anclas e imágenes en español e inglés, y las páginas y
secciones que GeoDuck abre existen."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _build_guide():
    spec = importlib.util.spec_from_file_location("build_guide", ROOT / "tools" / "build_guide.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_guide"] = module
    spec.loader.exec_module(module)
    return module


def test_both_languages_have_the_same_pages_anchors_and_images():
    assert _build_guide().check_source() == []


@pytest.mark.parametrize("lang", ["es", "en"])
def test_every_page_and_error_section_geoduck_opens_exists(lang):
    pages = set(_build_guide().pages())
    text = (ROOT / "geoduck" / "ui" / "guide.py").read_text(encoding="utf-8")
    opened = set(re.findall(r'^[A-Z_]+ = "([a-z-]+)"$', text, re.M))
    assert opened <= pages, opened - pages
    errors = (ROOT / "docs" / "guide" / lang / "errors.md").read_text(encoding="utf-8")
    anchors = set(re.findall(r"\{#([a-z0-9-]+)\}", errors))
    sections = set(re.findall(r'": "([a-z-]+)",$', text, re.M)) | {"spatial"}
    assert sections <= anchors, sections - anchors
