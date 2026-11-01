# SPDX-License-Identifier: GPL-2.0-or-later
import pytest

from geoduck.engine.probe import probe_spatial

pytestmark = pytest.mark.engine


def test_probe_never_installs_and_reports_secure_defaults():
    probe = probe_spatial()
    assert probe.allow_unsigned_extensions is False
    if not probe.installed:
        assert probe.loaded is False
    # una segunda sonda da el mismo resultado: nada se instaló como efecto secundario
    assert probe_spatial().installed == probe.installed
