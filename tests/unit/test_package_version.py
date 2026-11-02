# SPDX-License-Identifier: GPL-2.0-or-later
"""La versión que muestra la interfaz es la versión real del paquete."""

import configparser
from pathlib import Path

import pytest

import geoduck
from geoduck.domain.versions import release_stage

PKG = Path(geoduck.__file__).resolve().parent


def test_metadata_version_is_the_package_version():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(PKG / "metadata.txt", encoding="utf-8")
    assert parser["general"]["version"] == geoduck.__version__


def test_experimental_flag_matches_a_pre_release():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(PKG / "metadata.txt", encoding="utf-8")
    experimental = parser["general"]["experimental"].strip().lower() == "true"
    assert experimental is bool(release_stage(geoduck.__version__))


@pytest.mark.parametrize(
    ("version", "stage"),
    [
        ("0.1.0a1", "Alpha"),
        ("0.10.0a3", "Alpha"),
        ("1.0.0b2", "Beta"),
        ("1.0.0rc1", "RC"),
        ("1.0.0", ""),
        ("2.1.3", ""),
    ],
)
def test_release_stage_follows_pep_440(version, stage):
    assert release_stage(version) == stage
