# SPDX-License-Identifier: GPL-2.0-or-later
"""AT-BOOT-002: diagnóstico accionable, sin excepciones, para cada fallo de entorno."""

from types import ModuleType, SimpleNamespace

import pytest

from geoduck.domain.diagnostics import Check, CheckStatus, SpatialProbe
from geoduck.infra.diagnostics import collect


def module(name, version, file="/qgis/apps/Python312/Lib/site-packages/x/__init__.py"):
    m = ModuleType(name)
    m.__version__ = version
    m.__file__ = file
    return m


def importer(available, failures=None):
    failures = failures or {}

    def _import(name):
        if name in failures:
            raise failures[name]
        if name in available:
            return available[name]
        raise ImportError(f"No module named {name!r}")

    return _import


HEALTHY = {
    "duckdb": module("duckdb", "2.0.0"),
    "pyarrow": module("pyarrow", "25.0.1"),
    "numpy": module("numpy", "1.26.4"),
}
SPATIAL_OK = lambda: SpatialProbe(installed=True, loaded=True, version="v1.5.0")  # noqa: E731


def run(available=None, failures=None, spatial=SPATIAL_OK, py=(3, 12, 11), user_site=""):
    return collect(
        import_module=importer(available if available is not None else HEALTHY, failures),
        spatial_prober=spatial,
        python_version=py,
        user_site=user_site,
    )


def test_healthy_environment_is_usable():
    report = run()
    assert report.ok
    assert report.by_id("duckdb").status is CheckStatus.OK
    assert report.by_id("pyarrow").status is CheckStatus.OK
    assert report.by_id("spatial").status is CheckStatus.OK
    assert report.by_id("qgis").status is CheckStatus.INFO
    assert "Resultado: utilizable" in report.to_text()


def test_missing_pyarrow_is_actionable():
    """AT-BOOT-002 literal: falta pyarrow."""
    available = {k: v for k, v in HEALTHY.items() if k != "pyarrow"}
    report = run(available)
    check = report.by_id("pyarrow")
    assert not report.ok
    assert check.status is CheckStatus.FAIL
    assert "pyarrow" in check.action
    assert "NO utilizable" in report.to_text()


def test_missing_duckdb_skips_spatial_and_fails():
    available = {k: v for k, v in HEALTHY.items() if k != "duckdb"}
    report = run(available)
    assert report.by_id("duckdb").status is CheckStatus.FAIL
    assert report.by_id("spatial").status is CheckStatus.INFO


@pytest.mark.parametrize(
    ("version", "status"),
    [
        ("1.4.4", CheckStatus.FAIL),
        ("1.5.0", CheckStatus.WARN),
        ("1.5.4", CheckStatus.OK),
        ("2.0.0", CheckStatus.OK),
    ],
)
def test_duckdb_version_policy(version, status):
    report = run({**HEALTHY, "duckdb": module("duckdb", version)})
    assert report.by_id("duckdb").status is status


def test_pyarrow_26_with_numpy_1_fails_with_matrix_action():
    """F-03 / ADR-0009."""
    report = run({**HEALTHY, "pyarrow": module("pyarrow", "26.0.0"), "numpy": module("numpy", "1.26.4")})
    check = report.by_id("pyarrow")
    assert check.status is CheckStatus.FAIL
    assert "pyarrow<26" in check.action


def test_pyarrow_26_with_numpy_2_is_ok():
    report = run({**HEALTHY, "pyarrow": module("pyarrow", "26.0.0"), "numpy": module("numpy", "2.5.4")})
    assert report.by_id("pyarrow").status is CheckStatus.OK


def test_pyarrow_import_error_mentioning_numpy_is_explained():
    available = {k: v for k, v in HEALTHY.items() if k != "pyarrow"}
    failures = {"pyarrow": ImportError("pyarrow requires NumPy 2.0 or newer, found 1.26.4")}
    check = run(available, failures).by_id("pyarrow")
    assert check.status is CheckStatus.FAIL
    assert "No actualice la NumPy" in check.action


def test_native_load_error_does_not_crash():
    failures = {"duckdb": OSError("DLL load failed while importing duckdb")}
    available = {k: v for k, v in HEALTHY.items() if k != "duckdb"}
    check = run(available, failures).by_id("duckdb")
    assert check.status is CheckStatus.FAIL
    assert "DLL load failed" in check.detail


def test_old_python_fails():
    report = run(py=(3, 9, 18))
    assert report.by_id("python").status is CheckStatus.FAIL


@pytest.mark.parametrize(
    ("probe", "status"),
    [
        (SpatialProbe(installed=False, loaded=False), CheckStatus.WARN),
        (SpatialProbe(installed=True, loaded=False, load_error="bad"), CheckStatus.WARN),
        (SpatialProbe(installed=True, loaded=True, allow_unsigned_extensions=True), CheckStatus.WARN),
    ],
)
def test_spatial_states_never_block(probe, status):
    report = run(spatial=lambda: probe)
    assert report.by_id("spatial").status is status
    assert report.ok  # spatial no es requisito de G0


def test_spatial_probe_exception_is_contained():
    def boom():
        raise RuntimeError("x")

    assert run(spatial=boom).by_id("spatial").status is CheckStatus.WARN


def test_user_site_packages_are_reported():
    leaking = module(
        "numpy", "2.1.0", file="/home/u/AppData/Roaming/Python/Python312/site-packages/numpy/__init__.py"
    )
    report = run(
        {**HEALTHY, "numpy": leaking}, user_site="/home/u/AppData/Roaming/Python/Python312/site-packages"
    )
    assert report.by_id("user_site").status is CheckStatus.WARN
    assert "PYTHONNOUSERSITE" in report.by_id("user_site").action


def test_qgis_facts_when_available():
    core = SimpleNamespace(Qgis=SimpleNamespace(version=lambda: "3.44.15-Solothurn"))
    qt = SimpleNamespace(QT_VERSION_STR="5.15.13", PYQT_VERSION_STR="5.15.10")
    report = run({**HEALTHY, "qgis.core": core, "qgis.PyQt.QtCore": qt})
    assert report.by_id("qgis").status is CheckStatus.OK
    assert report.facts["QGIS"] == "3.44.15-Solothurn"


def test_fail_check_requires_action():
    with pytest.raises(ValueError):
        Check("x", "X", CheckStatus.FAIL, "detalle")


def test_report_serializes():
    d = run().to_dict()
    assert d["ok"] is True and {c["id"] for c in d["checks"]} >= {"python", "duckdb", "pyarrow", "spatial"}
