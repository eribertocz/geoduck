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
        ("1.5.4", CheckStatus.WARN),
        ("1.5.6", CheckStatus.OK),
        ("2.0.0", CheckStatus.OK),
    ],
)
def test_duckdb_version_policy(version, status):
    report = run({**HEALTHY, "duckdb": module("duckdb", version)})
    assert report.by_id("duckdb").status is status


def test_duckdb_warning_mentions_geometry_defects_only_before_1_5_4():
    old = run({**HEALTHY, "duckdb": module("duckdb", "1.5.3")}).by_id("duckdb")
    mid = run({**HEALTHY, "duckdb": module("duckdb", "1.5.5")}).by_id("duckdb")
    assert "F-04" in old.detail and "F-04" not in mid.detail
    assert "1.5.6" in mid.action


def test_pyarrow_26_with_numpy_1_fails_with_matrix_action():
    """F-03 / ADR-0009."""
    report = run({**HEALTHY, "pyarrow": module("pyarrow", "26.0.0"), "numpy": module("numpy", "1.26.4")})
    check = report.by_id("pyarrow")
    assert check.status is CheckStatus.FAIL
    assert "pyarrow<26" in check.action


def test_pyarrow_26_with_numpy_2_is_ok():
    report = run({**HEALTHY, "pyarrow": module("pyarrow", "26.0.0"), "numpy": module("numpy", "2.5.4")})
    assert report.by_id("pyarrow").status is CheckStatus.OK


@pytest.mark.parametrize(
    "version, status",
    [
        ("17.0.0", CheckStatus.FAIL),
        ("18.0.0", CheckStatus.FAIL),
        ("18.1.0rc1", CheckStatus.FAIL),
        ("18.1.0", CheckStatus.OK),
        ("18.1.1", CheckStatus.OK),
        ("21.0.0", CheckStatus.OK),
    ],
)
def test_pyarrow_minimum_is_18_1_0(version, status):
    """ADR-0009: mínimo PyArrow 18.1.0; por debajo el entorno no es utilizable."""
    report = run({**HEALTHY, "pyarrow": module("pyarrow", version)})
    check = report.by_id("pyarrow")
    assert check.status is status
    if status is CheckStatus.FAIL:
        assert not report.ok
        assert "18.1.0" in check.action and "ADR-0009" in check.action


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


USER_SITE = "C:/Users/u/AppData/Roaming/Python/Python312/site-packages"


def test_numpy_or_pyarrow_in_user_site_is_reported():
    """F-15 / QGIS #63733: NumPy del usuario por encima de la de QGIS."""
    leaking = module("numpy", "2.5.4", file=f"{USER_SITE}/numpy/__init__.py")
    report = run({**HEALTHY, "numpy": leaking}, user_site=USER_SITE)
    check = report.by_id("user_site")
    assert check.status is CheckStatus.WARN
    assert "numpy" in check.detail and "pip uninstall numpy" in check.action


def test_duckdb_in_user_site_is_a_valid_install():
    """Verificado en Windows (QGIS 3.34.15): duckdb en el site de usuario no es un problema."""
    duck = module("duckdb", "2.0.0", file=f"{USER_SITE}/duckdb/__init__.py")
    check = run({**HEALTHY, "duckdb": duck}, user_site=USER_SITE).by_id("user_site")
    assert check.status is CheckStatus.OK
    assert "duckdb" in check.detail


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\u\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\qduckdb\embedded_external_libs\duckdb\__init__.py",
        "/home/u/.local/share/QGIS/QGIS3/profiles/default/python/plugins/qduckdb/embedded_external_libs/duckdb/__init__.py",
    ],
)
def test_duckdb_embedded_by_another_plugin_is_warned(path):
    """R11: DuckDB incrustado por QDuckDB (ruta real observada en Windows)."""
    report = run({**HEALTHY, "duckdb": module("duckdb", "1.4.4", file=path)})
    check = report.by_id("duckdb_origin")
    assert check.status is CheckStatus.WARN
    assert "qduckdb" in check.detail and "qduckdb" in check.action
    assert report.by_id("duckdb").status is CheckStatus.FAIL  # 1.4.4 < 1.5.0
    assert report.facts["DuckDB desde"] == path


def test_duckdb_from_qgis_or_user_site_has_ok_origin():
    report = run({**HEALTHY, "duckdb": module("duckdb", "2.0.0", file=f"{USER_SITE}/duckdb/__init__.py")})
    assert report.by_id("duckdb_origin").status is CheckStatus.OK


def test_pyarrow_dll_conflict_is_explained():
    """F-13: mensaje real de Windows con una PyArrow distinta de la de QGIS."""
    available = {k: v for k, v in HEALTHY.items() if k != "pyarrow"}
    failures = {
        "pyarrow": ImportError("DLL load failed while importing lib: No se encontró el proceso especificado.")
    }
    check = run(available, failures).by_id("pyarrow")
    assert check.status is CheckStatus.FAIL
    assert "F-13" in check.action and "pip uninstall pyarrow" in check.action


def test_windows_qgis_334_combination_is_usable():
    """Combinación real del equipo Windows: QGIS 3.34.15, DuckDB 2.0.0, PyArrow 18.1.0, NumPy 1.26.4."""
    report = run(
        {
            "duckdb": module("duckdb", "2.0.0", file=f"{USER_SITE}/duckdb/__init__.py"),
            "pyarrow": module("pyarrow", "18.1.0"),
            "numpy": module("numpy", "1.26.4"),
        },
        user_site=USER_SITE,
    )
    assert report.ok
    assert all(c.status is not CheckStatus.WARN for c in report.checks if c.id != "spatial")


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
