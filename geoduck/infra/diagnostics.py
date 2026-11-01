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
        action=f"Instale duckdb>={'.'.join(map(str, DUCKDB_MINIMUM))} en el Python de QGIS ({_DOCS}).",
    )
    if duckdb_mod is not None:
        duckdb_check = _check_duckdb_version(str(getattr(duckdb_mod, "__version__", "0.0.0")))
    checks.append(duckdb_check)
    if duckdb_mod is not None:
        facts["DuckDB desde"] = str(getattr(duckdb_mod, "__file__", "?"))
        checks.append(_check_duckdb_origin(duckdb_mod))

    numpy_mod, _ = _import_check(import_module, "numpy", "NumPy", action="")
    numpy_version = str(getattr(numpy_mod, "__version__", "")) if numpy_mod else ""
    if numpy_version:
        facts["NumPy"] = numpy_version

    pyarrow_mod, pyarrow_check = _import_check(
        import_module,
        "pyarrow",
        "PyArrow",
        action=f"Instale una versión de pyarrow compatible con esta celda de la matriz ({_DOCS}).",
    )
    if pyarrow_mod is not None:
        pyarrow_check = _check_pyarrow(str(getattr(pyarrow_mod, "__version__", "0")), numpy_version)
        facts["PyArrow desde"] = str(getattr(pyarrow_mod, "__file__", "?"))
    elif "DLL load failed" in pyarrow_check.detail:
        pyarrow_check = Check(
            "pyarrow",
            "PyArrow",
            CheckStatus.FAIL,
            pyarrow_check.detail,
            "Hay una PyArrow distinta de la que incluye QGIS y sus DLL chocan con las ya cargadas (F-13). "
            "Desinstale la PyArrow añadida (p. ej. «pip uninstall pyarrow» si está en el site de usuario) "
            "y use la de QGIS.",
        )
    elif "NumPy 2" in pyarrow_check.detail or "numpy" in pyarrow_check.detail.lower():
        pyarrow_check = Check(
            "pyarrow",
            "PyArrow",
            CheckStatus.FAIL,
            pyarrow_check.detail,
            f"Esta PyArrow exige NumPy 2, pero QGIS trae NumPy {numpy_version or '1.x'}. Instale "
            f"pyarrow<26 (ADR-0009, {_DOCS}). No actualice la NumPy de QGIS.",
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
            "Python de QGIS",
            CheckStatus.FAIL,
            f"Python {text}: no existen wheels de DuckDB ≥ 1.5 para esta versión.",
            "Use una versión de QGIS cuyo Python sea 3.10 o superior (QGIS 3.40+ en Windows).",
        )
    if struct.calcsize("P") * 8 != 64:
        return Check(
            "python",
            "Python de QGIS",
            CheckStatus.FAIL,
            "Intérprete de 32 bits.",
            "Instale QGIS de 64 bits.",
        )
    return Check("python", "Python de QGIS", CheckStatus.OK, f"Python {text}, 64 bits")


def _check_qgis(import_module: Importer, facts: dict[str, str]) -> Check:
    try:
        core = import_module("qgis.core")
        qtcore = import_module("qgis.PyQt.QtCore")
    except ImportError:
        return Check("qgis", "QGIS", CheckStatus.INFO, "Ejecución fuera de QGIS (sin PyQGIS).")
    qgis_version = str(core.Qgis.version())
    qt = str(getattr(qtcore, "QT_VERSION_STR", "?"))
    pyqt = str(getattr(qtcore, "PYQT_VERSION_STR", "?"))
    facts.update({"QGIS": qgis_version, "Qt": qt, "PyQt": pyqt})
    return Check("qgis", "QGIS", CheckStatus.OK, f"QGIS {qgis_version}, Qt {qt}, PyQt {pyqt}")


def _import_check(
    import_module: Importer, name: str, title: str, *, action: str
) -> tuple[ModuleType | None, Check]:
    try:
        module = import_module(name)
    except Exception as exc:  # ImportError y errores de carga nativa (DLL, ABI, NumPy)
        detail = f"No se pudo importar {name}: {type(exc).__name__}: {str(exc).strip().splitlines()[0]}"
        status = CheckStatus.FAIL if action else CheckStatus.INFO
        return None, Check(name, title, status, detail, action)
    return module, Check(name, title, CheckStatus.OK, f"{name} importado")


def _check_duckdb_version(text: str) -> Check:
    try:
        v = Version.parse(text)
    except ValueError:
        return Check("duckdb", "DuckDB", CheckStatus.FAIL, f"Versión no reconocida: {text}", _duckdb_action())
    if not v.at_least(*DUCKDB_MINIMUM):
        return Check(
            "duckdb",
            "DuckDB",
            CheckStatus.FAIL,
            f"DuckDB {text} es anterior al mínimo soportado {'.'.join(map(str, DUCKDB_MINIMUM))}.",
            _duckdb_action(),
        )
    if not v.at_least(*DUCKDB_RECOMMENDED):
        return Check(
            "duckdb",
            "DuckDB",
            CheckStatus.WARN,
            f"DuckDB {text}: soportado"
            + (
                ", con defectos conocidos en geometría (F-04/F-05)."
                if not v.at_least(*DUCKDB_GEOMETRY_FIXES)
                else "."
            ),
            f"Versión recomendada: duckdb {'.'.join(map(str, DUCKDB_RECOMMENDED))} (rama 1.5) o 2.x (D5).",
        )
    return Check("duckdb", "DuckDB", CheckStatus.OK, f"DuckDB {text}")


def _duckdb_action() -> str:
    return f"Instale duckdb>={'.'.join(map(str, DUCKDB_MINIMUM))} en el Python de QGIS ({_DOCS})."


def _check_pyarrow(pyarrow_version: str, numpy_version: str) -> Check:
    """Regla verificada F-03 / ADR-0009: PyArrow ≥ 26 requiere NumPy ≥ 2 si NumPy está presente."""
    try:
        pa = Version.parse(pyarrow_version)
    except ValueError:
        return Check("pyarrow", "PyArrow", CheckStatus.WARN, f"Versión no reconocida: {pyarrow_version}")
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
                f"PyArrow {pyarrow_version} requiere NumPy ≥ 2 y este QGIS trae NumPy {numpy_version}.",
                f"Instale pyarrow<26 (ADR-0009, {_DOCS}). No actualice la NumPy de QGIS.",
            )
    return Check("pyarrow", "PyArrow", CheckStatus.OK, f"PyArrow {pyarrow_version}")


def _check_spatial(prober: SpatialProber | None) -> Check:
    title = "Extensión spatial"
    if prober is None:
        return Check("spatial", title, CheckStatus.INFO, "No evaluada: DuckDB no está disponible.")
    try:
        probe = prober()
    except Exception as exc:
        return Check(
            "spatial",
            title,
            CheckStatus.WARN,
            f"No se pudo consultar: {type(exc).__name__}",
            "Ver docs/certification/spatial.md.",
        )
    if probe.allow_unsigned_extensions:
        return Check(
            "spatial",
            title,
            CheckStatus.WARN,
            "DuckDB permite extensiones sin firma en este entorno.",
            "Desactive allow_unsigned_extensions (spec/docs/security.md §2).",
        )
    if probe.loaded:
        return Check("spatial", title, CheckStatus.OK, f"Cargable ({probe.version or 'versión ?'})")
    if probe.installed:
        return Check(
            "spatial",
            title,
            CheckStatus.WARN,
            f"Instalada pero no se pudo cargar: {probe.load_error}",
            "Reinstálela según docs/certification/spatial.md.",
        )
    return Check(
        "spatial",
        title,
        CheckStatus.WARN,
        f"No instalada (directorio de extensiones: {probe.extension_directory or 'predeterminado'}). "
        "GeoDuck funciona sin ella; las funciones ST_* avanzadas y los CRS EPSG no estarán disponibles.",
        "Instálela de forma explícita según docs/certification/spatial.md. GeoDuck no la instala solo.",
    )


#: Paquetes que QGIS ya trae y cuya sustitución desde el site de usuario rompe QGIS o GeoDuck:
#: NumPy 2 encima de la de QGIS rompe GDAL/scipy (QGIS #63733, F-15); otra PyArrow choca con sus DLL (F-13).
#: `duckdb` en el site de usuario es un método de instalación válido y no se advierte.
_QGIS_OWNED = ("numpy", "pyarrow")

_PLUGIN_DIR = re.compile(r"/python/plugins/([^/]+)/", re.IGNORECASE)


def _check_duckdb_origin(module: ModuleType) -> Check:
    """R11: avisa si `duckdb` lo aporta otro complemento que lo incrusta en su carpeta."""
    title = "Origen de DuckDB"
    path = str(getattr(module, "__file__", "") or "").replace("\\", "/")
    match = _PLUGIN_DIR.search(path)
    if match and match.group(1).lower() != "geoduck":
        plugin = match.group(1)
        return Check(
            "duckdb_origin",
            title,
            CheckStatus.WARN,
            f"DuckDB {getattr(module, '__version__', '?')} lo aporta el complemento «{plugin}», que lo "
            "incluye en su carpeta. En QGIS solo puede haber un DuckDB cargado: GeoDuck y ese complemento "
            "comparten esta versión (riesgo R11).",
            f"Si la versión no es la que GeoDuck necesita, desactive «{plugin}», reinicie QGIS y vuelva a "
            "ejecutar este diagnóstico.",
        )
    return Check("duckdb_origin", title, CheckStatus.OK, path or "desconocido")


def _check_user_site(user_site: str, modules: list[ModuleType]) -> Check:
    title = "Paquetes del usuario"
    if not user_site:
        return Check("user_site", title, CheckStatus.OK, "El site de usuario está desactivado.")
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
            f"{', '.join(risky)} se cargan desde {user_site} en lugar de la versión de QGIS "
            "(conflictos conocidos: QGIS issue #63733, F-13, F-15).",
            f"Desinstálelos del site de usuario («pip uninstall {' '.join(risky)}») para usar los de QGIS.",
        )
    if in_user_site:
        return Check(
            "user_site",
            title,
            CheckStatus.OK,
            f"{', '.join(in_user_site)} instalado en el site de usuario; NumPy y PyArrow son los de QGIS.",
        )
    return Check("user_site", title, CheckStatus.OK, "Ninguna dependencia proviene del site de usuario.")


def _user_site() -> str:
    if not site.ENABLE_USER_SITE:
        return ""
    try:
        return str(site.getusersitepackages())
    except Exception:
        return ""
