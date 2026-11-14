# SPDX-License-Identifier: GPL-2.0-or-later
"""Catálogo de traducción (G6 · E4, GD-I18N-001, AT-I18N-001). Sin Qt."""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from geoduck.domain import i18n

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import i18n as catalog  # noqa: E402  (tools/i18n.py)

PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def test_every_text_of_the_code_is_in_the_catalog_and_translated():
    sources = catalog.extract()
    assert len(sources) > 400
    assert catalog.problems(sources, catalog.read_ts()) == []


def test_translations_keep_the_placeholders_so_format_never_fails():
    for source, spanish in catalog.read_ts().items():
        assert sorted(PLACEHOLDER.findall(source)) == sorted(PLACEHOLDER.findall(spanish)), source
        args = [f"x{i}" for i in range(10)]
        spanish.format(*args)  # mismos marcadores: nunca IndexError/KeyError


def test_source_texts_are_english():
    spanish_marks = re.compile(r"[áéíóúñ¿¡]|\b(de|la|el|los|las|una|sin|para|está|cargar|capa)\b", re.I)
    suspicious = [s for s in catalog.extract() if spanish_marks.search(s)]
    assert suspicious == []


def test_without_translator_the_texts_are_english_and_never_empty(monkeypatch):
    monkeypatch.setattr(i18n, "_translate", None)
    assert i18n.tr("Load into QGIS…") == "Load into QGIS…"
    monkeypatch.setattr(i18n, "_translate", lambda _text: "")  # una traducción vacía no deja el texto vacío
    assert i18n.tr("Run") == "Run"


def test_with_the_spanish_catalog_messages_from_the_engine_are_spanish():
    from geoduck.domain.sql_text import quote_identifier

    with pytest.raises(Exception, match="no puede estar vacío"):
        quote_identifier("")


def test_the_check_command_passes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "i18n.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_zip_contains_the_compiled_translation(tmp_path):
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_zip.py"), "--out", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    (archive,) = tmp_path.glob("geoduck-*.zip")
    with zipfile.ZipFile(archive) as zf:
        assert "geoduck/i18n/geoduck_es.ts" in zf.namelist()


def test_no_interface_text_is_written_without_tr(tmp_path, monkeypatch):
    """#149: la CI falla si un texto de la interfaz no pasa por `tr()` (los registros y los nombres propios,
    como «GeoDuck» o «Ctrl+K», no cuentan)."""
    assert catalog.untranslated() == []
    package = tmp_path / "geoduck"
    package.mkdir()
    (package / "vista.py").write_text(
        "label('Guardar todo')\nbutton(tr('Save'))\nlog.warning('No se pudo cerrar')\n"
        "icon_button('close', 'Cerrar la ventana', colors)\nsetText('GeoDuck · Ctrl+K')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(catalog, "PKG", package)
    monkeypatch.setattr(catalog, "ROOT", tmp_path)
    found = catalog.untranslated()
    assert [line.split(" (")[0] for line in found] == [
        "Texto sin tr(): 'Guardar todo'",
        "Texto sin tr(): 'Cerrar la ventana'",
    ]


def test_the_plugin_card_is_in_english_and_in_spanish():
    """#149: la ficha del complemento (descripción y «Acerca de») en los dos idiomas: QGIS muestra la de su
    idioma (`description[es]`)."""
    assert catalog.metadata_problems() == []


def test_numbers_follow_the_language(monkeypatch):
    """#149: «1 000 000 filas · 3,4 s» en español y «1,000,000 rows · 3.4 s» en inglés."""
    monkeypatch.setattr(i18n, "_language", "es")
    assert (i18n.number(1_000_000), i18n.decimal(3.42), i18n.decimal(1234.5)) == (
        "1 000 000",
        "3,4",
        "1 234,5",
    )
    monkeypatch.setattr(i18n, "_language", "en")
    assert (i18n.number(1_000_000), i18n.decimal(3.42), i18n.decimal(1234.5)) == (
        "1,000,000",
        "3.4",
        "1,234.5",
    )
