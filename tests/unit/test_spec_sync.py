# SPDX-License-Identifier: GPL-2.0-or-later
"""Integridad de `spec/`: la maestra y el manifiesto se derivan de los archivos individuales."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("spec_sync", ROOT / "tools" / "spec_sync.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["spec_sync"] = mod
    spec.loader.exec_module(mod)
    return mod


spec_sync = _load()


def test_repository_spec_is_consistent():
    assert spec_sync.check() == []


def test_manifest_lists_every_document_except_itself():
    data = json.loads((ROOT / "spec" / spec_sync.MANIFEST).read_text(encoding="utf-8"))
    listed = {d["path"] for d in data["documents"]}
    on_disk = {f.relative_to(ROOT / "spec").as_posix() for f in (ROOT / "spec").rglob("*") if f.is_file()}
    assert listed == on_disk - {spec_sync.MANIFEST}
    for d in data["documents"]:
        raw = (ROOT / "spec" / d["path"]).read_bytes()
        assert d["bytes"] == len(raw)
        assert d["sha256"] == hashlib.sha256(raw).hexdigest()


def test_master_contains_every_chapter_verbatim():
    master = (ROOT / "spec" / spec_sync.MASTER).read_text(encoding="utf-8")
    for chapter in spec_sync.CHAPTERS:
        body = (ROOT / "spec" / chapter).read_text(encoding="utf-8").rstrip("\n")
        assert body in master, chapter


@pytest.fixture
def spec_copy(tmp_path):
    dst = tmp_path / "spec"
    shutil.copytree(ROOT / "spec", dst)
    return dst


def test_check_detects_an_edited_document(spec_copy):
    target = spec_copy / "specs" / "session-spec.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nCambio no sincronizado.\n", "utf-8")
    problems = spec_sync.check(spec_copy)
    assert len(problems) == 2  # maestra y manifiesto


def test_check_detects_an_edited_master(spec_copy):
    master = spec_copy / spec_sync.MASTER
    master.write_text(master.read_text(encoding="utf-8") + "edición manual\n", "utf-8")
    problems = spec_sync.check(spec_copy)
    assert any(spec_sync.MASTER in p for p in problems)
