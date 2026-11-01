# SPDX-License-Identifier: GPL-2.0-or-later
"""Verificador de entorno y pruebas funcionales de certificación (gate G0, GD-10/GD-11).

Se ejecuta con el **Python de QGIS** (no con un Python externo). Escribe `report.json` y `report.txt`
en la carpeta de salida y termina con código 0 solo si todas las comprobaciones obligatorias pasan.

    python tools/verify_env.py --out resultados/<celda> [--deps-dir DIR] [--install-spatial]

`--deps-dir` antepone una carpeta de dependencias a `sys.path` (método de instalación M2).
`--install-spatial` ejecuta `INSTALL spatial` desde el repositorio oficial de DuckDB. Solo con este
indicador explícito se descarga algo (spec/docs/security.md §2).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

Result = dict[str, Any]
CHECKS: list[tuple[str, bool, Callable[[argparse.Namespace], Result]]] = []


def check(name: str, *, mandatory: bool = True) -> Callable[[Callable[..., Result]], Callable[..., Result]]:
    def register(fn: Callable[..., Result]) -> Callable[..., Result]:
        CHECKS.append((name, mandatory, fn))
        return fn

    return register


# -- entorno ------------------------------------------------------------------------------------------


@check("diagnostico")
def c_diagnostics(_args: argparse.Namespace) -> Result:
    from geoduck.engine.probe import probe_spatial
    from geoduck.infra.diagnostics import collect

    report = collect(spatial_prober=probe_spatial)
    return {"ok": report.ok, "detail": report.to_dict()}


@check("importaciones")
def c_imports(_args: argparse.Namespace) -> Result:
    timings: dict[str, Any] = {}
    for name in ("duckdb", "pyarrow", "numpy"):
        t0 = time.perf_counter()
        try:
            module = __import__(name)
        except ImportError as exc:
            if name == "numpy":  # opcional: PyArrow >= 16 no la exige
                timings[name] = f"no instalada ({exc})"
                continue
            raise
        timings[name] = {
            "version": getattr(module, "__version__", "?"),
            "file": getattr(module, "__file__", "?"),
            "import_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    return {"ok": True, "detail": timings}


# -- motor (GeoDuck real) -----------------------------------------------------------------------------


def _worker() -> Any:
    from geoduck.engine.worker import SessionWorker

    worker = SessionWorker()
    worker.start().result(60)
    return worker


@check("AT-SES-001 sesión :memory:")
def c_session(_args: argparse.Namespace) -> Result:
    worker = _worker()
    try:

        def op(h: Any, _t: Any) -> Any:
            h.execute("CREATE TEMP TABLE t AS SELECT 1 AS id, 'Válvula; ñ' AS nombre")
            return h.execute("SELECT * FROM t")

        out = worker.submit(op).future.result(60)
        return {"ok": out.rows == ((1, "Válvula; ñ"),), "detail": repr(out.rows)}
    finally:
        worker.close().result(60)


@check("ADR-0006 lector íntegro y guardia de resultado abierto")
def c_reader_guard(_args: argparse.Namespace) -> Result:
    from geoduck.domain.errors import ActiveResultError

    worker = _worker()
    try:

        def op(h: Any, _t: Any) -> Any:
            with h.arrow_batches("SELECT range AS i FROM range(100000)", batch_size=1000) as reader:
                rows = reader.read_next_batch().num_rows
                try:
                    h.execute("SELECT 1")
                    rejected = False
                except ActiveResultError:
                    rejected = True
                rows += sum(b.num_rows for b in reader)
            return rows, rejected

        rows, rejected = worker.submit(op).future.result(60)
        return {"ok": rows == 100000 and rejected, "detail": {"rows": rows, "rejected": rejected}}
    finally:
        worker.close().result(60)


@check("ADR-0007 cancelación")
def c_cancel(_args: argparse.Namespace) -> Result:
    from geoduck.domain.errors import OperationCancelledError

    worker = _worker()
    try:
        handle = worker.submit(
            lambda h, t: h.execute("SELECT count(*) FROM range(5000000000) t(a) WHERE a % 7 = 3")
        )
        while not handle.future.running():
            time.sleep(0.01)
        time.sleep(0.3)
        t0 = time.perf_counter()
        worker.cancel(handle.op_id)
        try:
            handle.future.result(60)
            cancelled = False
        except OperationCancelledError:
            cancelled = True
        latency = round((time.perf_counter() - t0) * 1000, 1)
        alive = worker.submit(lambda h, t: h.execute("SELECT 1").rows).future.result(60) == ((1,),)
        caps = worker.capabilities
        return {
            "ok": cancelled and alive,
            "detail": {"latency_ms": latency, "interrupt_verified": bool(caps and caps.interrupt_verified)},
        }
    finally:
        worker.close().result(60)


@check("GeoArrow: geometría con CRS en metadatos (F-10)")
def c_geoarrow(_args: argparse.Namespace) -> Result:
    import duckdb

    con = duckdb.connect()
    try:
        reader = con.sql("SELECT 'POINT(1 2)'::GEOMETRY('OGC:CRS84') AS g").to_arrow_reader(batch_size=10)
        field = reader.schema.field("g")
        meta = {k.decode(): v.decode()[:80] for k, v in (field.metadata or {}).items()}
        reader.close()
        return {"ok": meta.get("ARROW:extension:name") == "geoarrow.wkb", "detail": meta}
    finally:
        con.close()


@check("Bloqueo liberado tras DETACH (proceso externo)")
def c_lock_release(_args: argparse.Namespace) -> Result:
    from geoduck.domain.sql_text import quote_string_literal

    folder = Path(tempfile.mkdtemp(prefix="geoduck_cert_ñá "))
    db = folder / "rw prueba.duckdb"
    worker = _worker()
    probe = (
        "import duckdb,sys; c=duckdb.connect(sys.argv[1]); "
        "c.execute('INSERT INTO t VALUES (2)'); c.close(); print('EXTERNAL_RW_OK')"
    )

    def external() -> str:
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}  # incluye --deps-dir
        proc = subprocess.run(
            [sys.executable, "-c", probe, str(db)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=env,
        )
        lines = (proc.stdout + proc.stderr).strip().splitlines()
        return lines[-1] if lines else ""

    try:

        def attach(h: Any, _t: Any) -> None:
            h.execute(f"ATTACH {quote_string_literal(str(db))} AS rw")
            h.execute("CREATE TABLE rw.t AS SELECT 1 AS i")

        worker.submit(attach).future.result(60)
        while_attached = external()
        worker.submit(lambda h, t: h.execute("DETACH rw")).future.result(60)
        after_detach = external()
        return {
            "ok": "EXTERNAL_RW_OK" not in while_attached and "EXTERNAL_RW_OK" in after_detach,
            "detail": {"mientras_adjunta": while_attached[:160], "tras_detach": after_detach},
        }
    finally:
        worker.close().result(60)


# -- QGIS (si se ejecuta con el Python de QGIS) -----------------------------------------------------------

_APP: Any = None


def _qgis_app() -> Any:
    global _APP  # noqa: PLW0603
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication

    if _APP is None:
        _APP = QgsApplication([], True)
        _APP.initQgis()
    return _APP


@check("PyQGIS: Arrow → capa memory con CRS (viabilidad G3)")
def c_qgis_layer(_args: argparse.Namespace) -> Result:
    import duckdb
    from qgis.core import QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsVectorLayer

    _qgis_app()
    con = duckdb.connect()
    sql = (
        "SELECT range AS id, ('POINT(' || (range % 360 - 180) || ' ' || (range % 180 - 90) || ')')"
        "::GEOMETRY('OGC:CRS84') AS geom FROM range(20000)"
    )
    reader = con.sql(sql).to_arrow_reader(batch_size=8192)
    meta = json.loads(reader.schema.field("geom").metadata[b"ARROW:extension:metadata"])
    crs = QgsCoordinateReferenceSystem()
    crs.createFromUserInput(json.dumps(meta["crs"]))
    layer = QgsVectorLayer("Point", "certificacion", "memory")
    layer.setCrs(crs)
    provider = layer.dataProvider()
    rows = added = 0
    for batch in reader:
        geoms = batch.column("geom").to_pylist()
        feats = []
        for wkb in geoms:
            feature = QgsFeature()
            geometry = QgsGeometry()
            geometry.fromWkb(wkb)
            feature.setGeometry(geometry)
            feats.append(feature)
        ok, _ = provider.addFeatures(feats)
        rows += batch.num_rows
        added += len(feats) if ok else 0
    con.close()
    return {
        "ok": rows == added == layer.featureCount() == 20000 and crs.authid() == "OGC:CRS84",
        "detail": {"rows": rows, "featureCount": layer.featureCount(), "crs": crs.authid()},
    }


@check("G0-B: QgsCodeEditorSQL disponible")
def c_editor(_args: argparse.Namespace) -> Result:
    _qgis_app()
    from qgis.gui import QgsCodeEditorSQL

    editor = QgsCodeEditorSQL()
    editor.setText("SELECT 1;")
    return {"ok": editor.text() == "SELECT 1;", "detail": type(editor).__mro__[1].__name__}


@check("Complemento: carga del panel e inicio/cierre de sesión (AT-BOOT-001)")
def c_plugin(_args: argparse.Namespace) -> Result:
    _qgis_app()
    from qgis.PyQt.QtCore import QCoreApplication

    import geoduck
    from geoduck.domain.session import SessionState

    sys.path.insert(0, str(ROOT))
    from tests.qgis.conftest import FakeIface

    plugin = geoduck.classFactory(FakeIface())
    plugin.initGui()
    plugin.dock.start_button.click()
    deadline = time.monotonic() + 30
    while plugin.coordinator.state is not SessionState.READY and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    ready = plugin.coordinator.state is SessionState.READY
    plugin.unload()
    return {"ok": ready, "detail": {"estado": "READY" if ready else "sin READY en 30 s"}}


# -- spatial (opcional; descarga solo con --install-spatial) --------------------------------------------


@check("Spatial: instalación, carga, EPSG y orden de ejes", mandatory=False)
def c_spatial(args: argparse.Namespace) -> Result:
    import duckdb

    con = duckdb.connect()
    detail: dict[str, Any] = {}
    try:
        if args.install_spatial:
            con.execute("INSTALL spatial")
        con.execute("SET autoinstall_known_extensions = false")
        con.execute("LOAD spatial")
        detail["version"] = con.execute(
            "SELECT extension_version FROM duckdb_extensions() WHERE extension_name = 'spatial'"
        ).fetchone()[0]
        detail["epsg_type"] = con.execute("SELECT typeof('POINT(1 2)'::GEOMETRY('EPSG:4326'))").fetchone()[0]
        detail["transform"] = con.execute(
            "SELECT ST_AsText(ST_Transform(ST_Point(-68.15, -16.5), 'EPSG:4326', 'EPSG:32719'))"
        ).fetchone()[0]
        try:
            detail["geometry_always_xy"] = con.execute(
                "SELECT current_setting('geometry_always_xy')"
            ).fetchone()[0]
        except duckdb.Error as exc:
            detail["geometry_always_xy"] = f"no existe: {str(exc).splitlines()[0][:80]}"
        reader = con.sql("SELECT 'POINT(1 2)'::GEOMETRY('EPSG:32719') g").to_arrow_reader(batch_size=1)
        meta = (reader.schema.field("g").metadata or {}).get(b"ARROW:extension:metadata", b"")
        detail["geoarrow_crs_epsg_32719"] = "32719" in meta.decode()
        reader.close()
        return {"ok": True, "detail": detail}
    except duckdb.Error as exc:
        detail["error"] = str(exc).splitlines()[0]
        return {"ok": False, "detail": detail}
    finally:
        con.close()


# -- ejecución ------------------------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--out", required=True, help="carpeta de resultados de la celda")
    parser.add_argument("--deps-dir", help="carpeta de dependencias a anteponer en sys.path (método M2)")
    parser.add_argument("--install-spatial", action="store_true", help="descarga la extensión oficial")
    parser.add_argument("--only", nargs="*", help="ejecuta solo las comprobaciones cuyo nombre contenga…")
    args = parser.parse_args(argv)

    if args.deps_dir:
        sys.path.insert(0, args.deps_dir)
    sys.path.insert(0, str(ROOT))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    results = []
    for name, mandatory, fn in CHECKS:
        if args.only and not any(token in name for token in args.only):
            continue
        t0 = time.perf_counter()
        try:
            res = fn(args)
        except ImportError as exc:
            res = {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "skipped": "qgis" in str(exc)}
        except Exception as exc:
            res = {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()}
        res.update(name=name, mandatory=mandatory, seconds=round(time.perf_counter() - t0, 2))
        results.append(res)
        print(f"[{'OK ' if res['ok'] else 'FALLA'}] {'*' if mandatory else ' '} {name}", flush=True)

    passed = all(r["ok"] for r in results if r["mandatory"])
    report = {
        "geoduck_commit": _git_commit(),
        "fecha_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "argv": argv,
        "resultado": "APTO" if passed else "NO APTO",
        "checks": results,
    }
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), "utf-8")
    lines = [f"Resultado: {report['resultado']}  ({report['platform']})"]
    lines += [f"[{'OK' if r['ok'] else 'FALLA'}] {r['name']}: {r['detail']}" for r in results]
    (out / "report.txt").write_text("\n".join(lines) + "\n", "utf-8")
    print(f"Informe: {out / 'report.json'}  →  {report['resultado']}")
    return 0 if passed else 1


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return "desconocido"


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
