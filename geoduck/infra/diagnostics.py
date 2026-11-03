# SPDX-License-Identifier: GPL-2.0-or-later
"""Diagnóstico del entorno (GD-BOOT-002, AT-BOOT-002).

Inspecciona Python, QGIS/Qt, DuckDB, PyArrow, NumPy, la extensión `spatial` y paquetes cargados desde
el `user site` de Python. Nunca instala nada ni ejecuta `pip` (spec/docs/technology.md, Empaquetado):
solo informa y recomienda una acción concreta.

Las dependencias se importan dinámicamente porque este módulo debe funcionar precisamente cuando
faltan (ADR-0010 permite la importación dinámica en `infra` para diagnosticar).
"""

from __future__ import annotations

import importlib
import os
import platform
import re
import site
import struct
import sys
import sysconfig
from collections.abc import Callable
from types import ModuleType

from geoduck import __version__ as geoduck_version
from geoduck.domain.diagnostics import Check, CheckStatus, DiagnosticReport, SpatialProbe
from geoduck.domain.i18n import tr
from geoduck.domain.versions import Version

#: Mismos valores que geoduck/engine/compat.py; aquí no se importa `engine` (requiere duckdb).
DUCKDB_MINIMUM = (1, 5, 0)
DUCKDB_RECOMMENDED = (1, 5, 6)  # D5: recomendada en la rama 1.5
#: Versión que corrige los defectos de geometría F-04 (to_arrow_table de GEOMETRY).
DUCKDB_GEOMETRY_FIXES = (1, 5, 4)
PYTHON_MINIMUM = (3, 10)

Importer = Callable[[str], ModuleType]
SpatialProber = Callable[[], SpatialProbe]

_DOCS = "docs/certification/windows.md"

#: Mínimo aprobado de PyArrow (ADR-0009): 18.1.0, la mínima verificada (la de QGIS 3.34.15 en Windows).
PYARROW_MINIMUM = (18, 1, 0)


def collect(
    *,
    import_module: Importer = importlib.import_module,
    spatial_prober: SpatialProber | None = None,
    python_version: tuple[int, int, int] | None = None,
    user_site: str | None = None,
) -> DiagnosticReport:
    """Ejecuta todas las comprobaciones. Los parámetros permiten probar cada caso sin el entorno real."""
    py = python_version or (sys.version_info[0], sys.version_info[1], sys.version_info[2])
    usersite = user_site if user_site is not None else _user_site()
    facts: dict[str, str] = {
        "GeoDuck": geoduck_version,
        "Python": ".".join(map(str, py)),
        "Ejecutable": sys.executable,
        "Plataforma": f"{platform.system()} {platform.release()} {platform.machine()}",
        "ABI": str(sysconfig.get_config_var("EXT_SUFFIX") or sys.implementation.cache_tag),
        "Bits": str(struct.calcsize("P") * 8),
    }
    checks: list[Check] = [_check_python(py)]
    checks.append(_check_qgis(import_module, facts))

    duckdb_mod, duckdb_check = _import_check(
        import_module,
        "duckdb",
        "DuckDB",
        action=tr("Install duckdb>={0} in the QGIS Python ({1}).").format(
            ".".join(map(str, DUCKDB_MINIMUM)), _DOCS
        ),
    )
    if duckdb_mod is not None:
        duckdb_check = _check_duckdb_version(str(getattr(duckdb_mod, "__version__", "0.0.0")))
    checks.append(duckdb_check)
    if duckdb_mod is not None:
        facts[tr("DuckDB from")] = str(getattr(duckdb_mod, "__file__", "?"))
        checks.append(_check_duckdb_origin(duckdb_mod))

    numpy_mod, _ = _import_check(import_module, "numpy", "NumPy", action="")
    numpy_version = str(getattr(numpy_mod, "__version__", "")) if numpy_mod else ""
    if numpy_version:
        facts["NumPy"] = numpy_version

    pyarrow_mod, pyarrow_check = _import_check(
        import_module,
        "pyarrow",
        "PyArrow",
        action=tr("Install a pyarrow version compatible with this cell of the matrix ({0}).").format(_DOCS),
    )
    if pyarrow_mod is not None:
        pyarrow_check = _check_pyarrow(str(getattr(pyarrow_mod, "__version__", "0")), numpy_version)
        facts[tr("PyArrow from")] = str(getattr(pyarrow_mod, "__file__", "?"))
    elif "DLL load failed" in pyarrow_check.detail:
        pyarrow_check = Check(
            "pyarrow",
            "PyArrow",
            CheckStatus.FAIL,
            pyarrow_check.detail,
            tr(
                "There is a PyArrow different from the one included in QGIS and its "
                "DLLs clash with the ones already loaded (F-13). Uninstall the added "
                "PyArrow (e.g. «pip uninstall pyarrow» if it is in the user site) "
                "and use the QGIS one."
            ),
        )
    elif "NumPy 2" in pyarrow_check.detail or "numpy" in pyarrow_check.detail.lower():
        pyarrow_check = Check(
            "pyarrow",
            "PyArrow",
            CheckStatus.FAIL,
            pyarrow_check.detail,
            tr(
                "This PyArrow requires NumPy 2, but QGIS comes with NumPy {0}. "
                "Install pyarrow<26 (ADR-0009, {1}). Do not upgrade the QGIS NumPy."
            ).format(numpy_version or "1.x", _DOCS),
        )
    checks.append(pyarrow_check)

    checks.append(_check_spatial(spatial_prober if duckdb_mod is not None else None))
    checks.append(_check_user_site(usersite, [m for m in (duckdb_mod, pyarrow_mod, numpy_mod) if m]))
    return DiagnosticReport(tuple(checks), facts)


# -- comprobaciones ----------------------------------------------------------------------------------


def _check_python(py: tuple[int, int, int]) -> Check:
    text = ".".join(map(str, py))
    if py[:2] < PYTHON_MINIMUM:
        return Check(
            "python",
            tr("QGIS Python"),
            CheckStatus.FAIL,
            tr("Python {0}: there are no DuckDB ≥ 1.5 wheels for this version.").format(text),
            tr("Use a QGIS version whose Python is 3.10 or later (QGIS 3.40+ on Windows)."),
        )
    if struct.calcsize("P") * 8 != 64:
        return Check(
            "python",
            tr("QGIS Python"),
            CheckStatus.FAIL,
            tr("32-bit interpreter."),
            tr("Install 64-bit QGIS."),
        )
    return Check("python", tr("QGIS Python"), CheckStatus.OK, tr("Python {0}, 64 bits").format(text))


def _check_qgis(import_module: Importer, facts: dict[str, str]) -> Check:
    try:
        core = import_module("qgis.core")
        qtcore = import_module("qgis.PyQt.QtCore")
    except ImportError:
        return Check("qgis", "QGIS", CheckStatus.INFO, tr("Running outside QGIS (without PyQGIS)."))
    qgis_version = str(core.Qgis.version())
    qt = str(getattr(qtcore, "QT_VERSION_STR", "?"))
    pyqt = str(getattr(qtcore, "PYQT_VERSION_STR", "?"))
    facts.update({"QGIS": qgis_version, "Qt": qt, "PyQt": pyqt})
    return Check(
        "qgis", "QGIS", CheckStatus.OK, tr("QGIS {0}, Qt {1}, PyQt {2}").format(qgis_version, qt, pyqt)
    )


def _import_check(
    import_module: Importer, name: str, title: str, *, action: str
) -> tuple[ModuleType | None, Check]:
    try:
        module = import_module(name)
    except Exception as exc:  # ImportError y errores de carga nativa (DLL, ABI, NumPy)
        detail = tr("{0} could not be imported: {1}: {2}").format(
            name, type(exc).__name__, str(exc).strip().splitlines()[0]
        )
        status = CheckStatus.FAIL if action else CheckStatus.INFO
        return None, Check(name, title, status, detail, action)
    return module, Check(name, title, CheckStatus.OK, f"{name} importado")


def _check_duckdb_version(text: str) -> Check:
    try:
        v = Version.parse(text)
    except ValueError:
        return Check(
            "duckdb",
            "DuckDB",
            CheckStatus.FAIL,
            tr("Unrecognized version: {0}").format(text),
            _duckdb_action(),
        )
    if not v.at_least(*DUCKDB_MINIMUM):
        return Check(
            "duckdb",
            "DuckDB",
            CheckStatus.FAIL,
            tr("DuckDB {0} is older than the minimum supported {1}.").format(
                text, ".".join(map(str, DUCKDB_MINIMUM))
            ),
            _duckdb_action(),
        )
    if not v.at_least(*DUCKDB_RECOMMENDED):
        return Check(
            "duckdb",
            "DuckDB",
            CheckStatus.WARN,
            tr("DuckDB {0}: supported").format(text)
            + (
                tr(", with known geometry defects (F-04/F-05).")
                if not v.at_least(*DUCKDB_GEOMETRY_FIXES)
                else "."
            ),
            tr("Recommended version: duckdb {0} (1.5 branch) or 2.x (D5).").format(
                ".".join(map(str, DUCKDB_RECOMMENDED))
            ),
        )
    return Check("duckdb", "DuckDB", CheckStatus.OK, f"DuckDB {text}")


def _duckdb_action() -> str:
    return tr("Install duckdb>={0} in the QGIS Python ({1}).").format(
        ".".join(map(str, DUCKDB_MINIMUM)), _DOCS
    )


def _check_pyarrow(pyarrow_version: str, numpy_version: str) -> Check:
    """Reglas de ADR-0009: mínimo 18.1.0; PyArrow ≥ 26 requiere NumPy ≥ 2 si NumPy está presente (F-03)."""
    try:
        pa = Version.parse(pyarrow_version)
    except ValueError:
        return Check(
            "pyarrow", "PyArrow", CheckStatus.WARN, tr("Unrecognized version: {0}").format(pyarrow_version)
        )
    if pa.release() < PYARROW_MINIMUM or (pa.is_prerelease and pa.release() == PYARROW_MINIMUM):
        minimum = ".".join(map(str, PYARROW_MINIMUM))
        return Check(
            "pyarrow",
            "PyArrow",
            CheckStatus.FAIL,
            tr("PyArrow {0} is older than the minimum accepted ({1}).").format(pyarrow_version, minimum),
            tr(
                "GeoDuck requires PyArrow ≥ {0} (ADR-0009). If it is the PyArrow "
                "included in QGIS, use a QGIS version from the compatibility matrix; "
                "do not replace it inside QGIS ({1})."
            ).format(minimum, _DOCS),
        )
    if numpy_version:
        try:
            np_major = Version.parse(numpy_version).major
        except ValueError:
            np_major = 0
        if pa.major >= 26 and np_major < 2:
            return Check(
                "pyarrow",
                "PyArrow",
                CheckStatus.FAIL,
                tr("PyArrow {0} requires NumPy ≥ 2 and this QGIS comes with NumPy {1}.").format(
                    pyarrow_version, numpy_version
                ),
                tr("Install pyarrow<26 (ADR-0009, {0}). Do not upgrade the QGIS NumPy.").format(_DOCS),
            )
    return Check("pyarrow", "PyArrow", CheckStatus.OK, f"PyArrow {pyarrow_version}")


def _check_spatial(prober: SpatialProber | None) -> Check:
    title = tr("spatial extension")
    if prober is None:
        return Check("spatial", title, CheckStatus.INFO, tr("Not evaluated: DuckDB is not available."))
    try:
        probe = prober()
    except Exception as exc:
        return Check(
            "spatial",
            title,
            CheckStatus.WARN,
            tr("Could not be queried: {0}").format(type(exc).__name__),
            tr("See docs/certification/spatial.md."),
        )
    if probe.allow_unsigned_extensions:
        return Check(
            "spatial",
            title,
            CheckStatus.WARN,
            tr("DuckDB allows unsigned extensions in this environment."),
            tr("Turn off allow_unsigned_extensions (spec/docs/security.md §2)."),
        )
    if probe.loaded:
        axis = tr(" · geometry_always_xy: {0}").format(probe.always_xy) if probe.always_xy else ""
        return Check(
            "spatial",
            title,
            CheckStatus.OK,
            tr("Loadable ({0}){1}").format(probe.version or tr("version ?"), axis),
        )
    if probe.installed:
        return Check(
            "spatial",
            title,
            CheckStatus.WARN,
            tr("Installed but it could not be loaded: {0}").format(probe.load_error),
            tr("Reinstall it as described in docs/certification/spatial.md."),
        )
    return Check(
        "spatial",
        title,
        CheckStatus.WARN,
        tr(
            "Not installed (extension directory: {0}). GeoDuck works without it; "
            "advanced ST_* functions and EPSG CRSs will not be available."
        ).format(probe.extension_directory or "predeterminado"),
        tr(
            "Install it explicitly as described in "
            "docs/certification/spatial.md. GeoDuck does not install it by "
            "itself."
        ),
    )


#: Paquetes que QGIS ya trae y cuya sustitución desde el site de usuario rompe QGIS o GeoDuck:
#: NumPy 2 encima de la de QGIS rompe GDAL/scipy (QGIS #63733, F-15); otra PyArrow choca con sus DLL (F-13).
#: `duckdb` en el site de usuario es un método de instalación válido y no se advierte.
_QGIS_OWNED = ("numpy", "pyarrow")

_PLUGIN_DIR = re.compile(r"/python/plugins/([^/]+)/", re.IGNORECASE)


def _check_duckdb_origin(module: ModuleType) -> Check:
    """R11: avisa si `duckdb` lo aporta otro complemento que lo incrusta en su carpeta."""
    title = tr("DuckDB origin")
    path = str(getattr(module, "__file__", "") or "").replace("\\", "/")
    match = _PLUGIN_DIR.search(path)
    if match and match.group(1).lower() != "geoduck":
        plugin = match.group(1)
        return Check(
            "duckdb_origin",
            title,
            CheckStatus.WARN,
            tr(
                "DuckDB {0} is provided by the plugin «{1}», which includes it in "
                "its folder. QGIS can only have one DuckDB loaded: GeoDuck and that "
                "plugin share this version (risk R11)."
            ).format(getattr(module, "__version__", "?"), plugin),
            tr(
                "If the version is not the one GeoDuck needs, disable «{0}», restart "
                "QGIS and run this diagnosis again."
            ).format(plugin),
        )
    return Check("duckdb_origin", title, CheckStatus.OK, path or "desconocido")


def _check_user_site(user_site: str, modules: list[ModuleType]) -> Check:
    title = tr("User packages")
    if not user_site:
        return Check("user_site", title, CheckStatus.OK, tr("The user site is disabled."))
    norm = os.path.normcase(os.path.abspath(user_site))
    in_user_site = [
        m.__name__
        for m in modules
        if getattr(m, "__file__", None)
        and os.path.normcase(os.path.abspath(str(m.__file__))).startswith(norm)
    ]
    risky = [name for name in in_user_site if name in _QGIS_OWNED]
    if risky:
        return Check(
            "user_site",
            title,
            CheckStatus.WARN,
            tr(
                "{0} are loaded from {1} instead of the QGIS version (known "
                "conflicts: QGIS issue #63733, F-13, F-15)."
            ).format(", ".join(risky), user_site),
            tr("Uninstall them from the user site («pip uninstall {0}») to use the QGIS ones.").format(
                " ".join(risky)
            ),
        )
    if in_user_site:
        return Check(
            "user_site",
            title,
            CheckStatus.OK,
            tr("{0} installed in the user site; NumPy and PyArrow are the QGIS ones.").format(
                ", ".join(in_user_site)
            ),
        )
    return Check("user_site", title, CheckStatus.OK, tr("No dependency comes from the user site."))


def _user_site() -> str:
    if not site.ENABLE_USER_SITE:
        return ""
    try:
        return str(site.getusersitepackages())
    except Exception:
        return ""
