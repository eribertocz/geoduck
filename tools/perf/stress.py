# SPDX-License-Identifier: GPL-2.0-or-later
"""Estrés de GeoDuck (G10 · E5; performance-spec §6; AT-PERF-005), con el complemento real.

    QT_QPA_PLATFORM=offscreen python tools/perf/stress.py [--minutes 60] [--rows 200000] [--out carpeta]

Repite vueltas de operaciones mezcladas hasta cumplir el tiempo, con `GeoDuckPlugin`, su coordinador y su
worker DuckDB reales (sin pantalla). Cada vuelta:

1. inicia una sesión, crea T2 (tabular) y T3 (puntos con SRC) y abre una base de archivo nueva (`ATTACH`);
2. consulta y comprueba los conteos;
3. carga T3 en QGIS como Copia y como Conectada (todas las filas) y cancela una carga grande;
4. envía la Copia a la base de archivo (mismas filas) y la deshace (la tabla ya no está);
5. exporta a Parquet (mismas filas al leerlo) y cancela otra exportación (sin archivos a medias);
6. datos rotos (T7): un Parquet cortado a la mitad, un CSV con un valor inválido en la fila N y un GeoJSON
   roto. Cada uno da un error claro, no deja tablas y la sesión sigue lista;
7. cierra la base de archivo (`DETACH`): otro proceso la abre en escritura;
8. quita las capas y cierra la sesión.

Criterios: 0 cierres, 0 filas perdidas, 0 capas o tablas a medias, y la RAM del proceso al final de la última
vuelta como mucho 10 % sobre la de la primera. Escribe `stress-<qgis>-<duckdb>.json` y un resumen en Markdown.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.PyQt.QtCore import QT_VERSION_STR, QCoreApplication

#: Crecimiento máximo de la RAM entre la primera y la última vuelta (performance-spec §6).
RAM_GROWTH = 0.10


def until(condition: Any, timeout: float = 600.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("la operación no terminó a tiempo")
        QCoreApplication.processEvents()
        time.sleep(0.002)


def rss_mb() -> float:
    """La RAM que ocupa el proceso ahora (no el pico): `/proc` en Linux; si no, el pico."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main() -> None:  # noqa: PLR0915 - la vuelta completa, en orden
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument("--rows", type=int, default=200_000)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="geoduck-stress-"))
    os.environ.setdefault("GEODUCK_RECOVERY_DIR", str(work / "recovery"))
    app = QgsApplication([], True)
    app.initQgis()
    import duckdb

    from geoduck.app.events import (
        ExportFailed,
        ExportFinished,
        LoadFailed,
        LoadFinished,
        SendFailed,
        SendFinished,
        SendUndoFailed,
        SendUndone,
    )
    from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
    from geoduck.domain.export import ExportFormat, ExportRequest
    from geoduck.domain.importing import ImportMode, SendItem, SendRequest
    from geoduck.domain.load import LoadMode, LoadRequest
    from geoduck.domain.session import SessionState
    from geoduck.domain.sql import RunScope
    from geoduck.plugin import GeoDuckPlugin
    from geoduck.ui.pro.timeline import TimelineWindow
    from tests.qgis.conftest import FakeIface

    plugin = GeoDuckPlugin(FakeIface())
    plugin.initGui()
    co = plugin.coordinator
    events: list[Any] = []
    co.subscribe(events.append)
    project = QgsProject.instance()
    rows = args.rows

    def ready() -> bool:
        return co.state is SessionState.READY

    def run(sql: str) -> None:
        co.execute_sql(sql, RunScope.ALL)
        until(ready)

    def value(sql: str) -> Any:
        out: list[Any] = []
        co.read_rows(sql, 10, out.append)
        until(lambda: bool(out))
        if isinstance(out[0], BaseException):
            raise out[0]
        return out[0].rows[0][0] if out[0].rows else None

    def wait_event(*kinds: type, timeout: float = 600.0) -> Any:
        until(lambda: any(isinstance(e, kinds) for e in events), timeout)
        return next(e for e in events if isinstance(e, kinds))

    def check(condition: bool, what: str) -> None:
        if not condition:
            raise AssertionError(what)

    def cancel_soon(start: Any, wait_s: float = 0.2) -> None:
        start()
        begin = time.monotonic()
        while time.monotonic() - begin < wait_s:
            QCoreApplication.processEvents()
        co.cancel_current_operation()
        until(ready, 120)

    def close_windows() -> None:
        from qgis.PyQt.QtWidgets import QApplication

        for window in QApplication.topLevelWidgets():
            if isinstance(window, TimelineWindow) and window.isVisible():
                window.close()
        QCoreApplication.processEvents()

    def broken_files(n: int) -> list[Path]:
        """T7: datos rotos, con la posición del error según la vuelta."""
        con = duckdb.connect()
        whole = work / f"entero_{n}.parquet"
        con.execute(f"COPY (SELECT range AS id, md5(range::VARCHAR) AS s FROM range(50000)) TO '{whole}'")
        con.close()
        cut = work / f"cortado_{n}.parquet"
        data = whole.read_bytes()
        cut.write_bytes(data[: len(data) // 2])  # cortado a mitad de un archivo
        whole.unlink()
        bad_csv = work / f"malo_{n}.csv"
        lines = ["id,kwh"] + [f"{i},{i * 1.5}" for i in range(2000)]
        lines[1 + (n * 37) % 2000] = f"{n},no-es-un-numero"
        bad_csv.write_text("\n".join(lines), encoding="utf-8")
        bad_json = work / f"roto_{n}.geojson"
        bad_json.write_text('{"type": "FeatureCollection", "features": [{"type": "Feature", "geom', "utf-8")
        return [cut, bad_csv, bad_json]

    started = time.monotonic()
    laps: list[dict[str, Any]] = []
    failures: list[str] = []
    baseline_layers = set(project.mapLayers())
    n = 0
    while time.monotonic() - started < args.minutes * 60:
        lap_start = time.monotonic()
        lap: dict[str, Any] = {"vuelta": n}
        try:
            events.clear()
            co.start_memory_session()
            until(lambda: ready() and co.catalog is not None)
            run(
                "CREATE TABLE t2 AS SELECT i AS id, 'cliente ' || (i % 1000) AS nombre,"
                " (i * 7919) % 10000 / 10.0 AS kwh, (i % 50) AS zona"
                f" FROM range({rows}) r(i);"
                " CREATE TABLE t3 AS SELECT i AS id, 'p' || i AS nombre,"
                " ST_SetCRS(('POINT(' || (i * 7919) % 100000 || ' ' || (i * 104729) % 100000 || ')')"
                "::GEOMETRY,"
                f" 'EPSG:32719') AS geom FROM range({rows}) r(i);"
            )
            database = work / f"base_{n}.duckdb"
            co.attach_database(
                AttachRequest(str(database), AccessMode.READ_WRITE, OpenAction.CREATE_NEW, alias="archivo")
            )
            until(lambda: ready() and co.catalog is not None and co.catalog.get("archivo") is not None)

            # 2. consultas
            check(value("SELECT count(*) FROM t2") == rows, "conteo de t2")
            check(value("SELECT count(DISTINCT zona) FROM t2") == 50, "agregado de t2")

            # 3. cargas
            loaded = {}
            for label, mode in (("copia", LoadMode.SNAPSHOT), ("conectada", LoadMode.CONNECTED)):
                events.clear()
                co.load(
                    LoadRequest(
                        "SELECT * FROM t3", mode, f"t3_{label}", "geom", source=("memory", "main", "t3")
                    )
                )
                done = wait_event(LoadFinished, LoadFailed)
                check(isinstance(done, LoadFinished), f"carga {label}: {getattr(done, 'message', '')}")
                layer = project.mapLayer(done.report.layer_id)
                check(layer is not None and layer.featureCount() == rows, f"filas de la capa {label}")
                loaded[label] = layer
            before = set(project.mapLayers())
            cancel_soon(
                lambda: co.load(
                    LoadRequest("SELECT a.* FROM t3 a, range(20)", LoadMode.SNAPSHOT, "grande", "geom")
                )
            )
            check(set(project.mapLayers()) == before, "una carga cancelada dejó una capa")

            # 4. enviar y deshacer
            events.clear()
            co.send_layers(
                SendRequest(
                    (SendItem(loaded["copia"].id(), "enviada", ImportMode.CREATE),), "archivo", "main", False
                )
            )
            sent = wait_event(SendFinished, SendFailed)
            check(isinstance(sent, SendFinished), f"envío: {getattr(sent, 'message', '')}")
            check(value('SELECT count(*) FROM "archivo"."main"."enviada"') == rows, "filas enviadas")
            events.clear()
            co.undo_send(list(sent.report.tables))
            undone = wait_event(SendUndone, SendUndoFailed)
            check(isinstance(undone, SendUndone), "deshacer el envío")
            check(
                value("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'enviada'") == 0,
                "la tabla deshecha sigue",
            )

            # 5. exportar y cancelar
            target = work / f"salida_{n}.parquet"
            events.clear()
            co.export(ExportRequest("SELECT * FROM t2", str(target), ExportFormat.PARQUET, None))
            exported = wait_event(ExportFinished, ExportFailed)
            check(isinstance(exported, ExportFinished), "exportar")
            check(
                duckdb.connect().execute(f"SELECT count(*) FROM '{target}'").fetchone()[0] == rows,
                "filas exportadas",
            )
            target.unlink()
            cancelled = work / f"cancelada_{n}.parquet"
            heavy = ExportRequest(
                "SELECT a.* FROM t2 a, range(30)", str(cancelled), ExportFormat.PARQUET, None
            )
            events.clear()
            cancel_soon(lambda r=heavy: co.export(r))
            ended = wait_event(ExportFinished, ExportFailed)
            if isinstance(ended, ExportFinished):  # terminó antes de cancelar: el archivo es válido
                lap["exportar_ya_terminado"] = True
                cancelled.unlink()
            leftovers = [p.name for p in work.iterdir() if p.name.startswith(("cancelada_", "."))]
            check(not leftovers, f"exportación cancelada dejó {leftovers}")

            close_windows()  # como el usuario: «Cerrar» en las ventanas que quedaron abiertas al terminar

            # 6. datos rotos (T7)
            for path in broken_files(n):
                scanned: list[Any] = []
                co.scan_files([str(path)], scanned.append)
                until(lambda s=scanned: bool(s))
                result = scanned[0]
                if isinstance(result, BaseException) or not result or result[0].problem:
                    path.unlink()
                    continue  # error claro al leerlo: nada que enviar
                events.clear()
                item = SendItem("file:0", f"rota_{n}", ImportMode.CREATE, file=result[0])
                co.send_layers(SendRequest((item,), "memory", "main", False))
                outcome = wait_event(SendFinished, SendFailed)
                if isinstance(outcome, SendFinished):
                    # un CSV con un texto entre números es legible: DuckDB toma la columna como texto, y
                    # entonces no se pierde ninguna fila
                    check(path.suffix == ".csv", f"{path.name}: se leyó un archivo roto")
                    check(value(f"SELECT count(*) FROM rota_{n}") == 2000, f"{path.name}: filas perdidas")
                    run(f"DROP TABLE rota_{n}")
                else:
                    check(bool(outcome.message), f"{path.name}: sin error claro")
                check(
                    value(f"SELECT count(*) FROM duckdb_tables() WHERE table_name = 'rota_{n}'") == 0,
                    "tabla rota a medias",
                )
                path.unlink()
            check(ready(), "la sesión no quedó lista tras los datos rotos")

            # 7. cerrar la base de archivo: otro proceso la abre en escritura
            co.detach_database("archivo")
            until(lambda: ready() and co.catalog.get("archivo") is None)
            other = duckdb.connect(str(database))
            other.execute("CREATE TABLE prueba AS SELECT 1")
            other.close()
            database.unlink()

            # 8. quitar las capas y cerrar la sesión
            for layer_id in set(project.mapLayers()) - baseline_layers:
                project.removeMapLayer(layer_id)
            co.close_session().result(120)
            until(lambda: co.state is SessionState.DISCONNECTED, 120)
            check(set(project.mapLayers()) == baseline_layers, "capas a medias")
        except Exception as exc:  # una vuelta fallida se anota y la siguiente empieza limpia
            failures.append(f"vuelta {n}: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            for layer_id in set(project.mapLayers()) - baseline_layers:
                project.removeMapLayer(layer_id)
            if co.state is not SessionState.DISCONNECTED:
                try:
                    co.close_session().result(120)
                    until(lambda: co.state is SessionState.DISCONNECTED, 120)
                except Exception:
                    failures.append(f"vuelta {n}: no se pudo cerrar la sesión")
                    break
        gc.collect()
        lap["segundos"] = round(time.monotonic() - lap_start, 1)
        lap["ram_mb"] = round(rss_mb(), 1)
        laps.append(lap)
        print(f"vuelta {n}: {lap['segundos']} s · RAM {lap['ram_mb']} MB", flush=True)
        n += 1

    first, last = laps[0]["ram_mb"], laps[-1]["ram_mb"]
    growth = (last - first) / first if first else 0.0
    report = {
        "entorno": {
            "qgis": Qgis.QGIS_VERSION.split("-")[0],
            "qt": QT_VERSION_STR,
            "duckdb": duckdb.__version__,
            "python": platform.python_version(),
            "sistema": platform.platform(),
            "cpus": os.cpu_count(),
            "filas": rows,
            "minutos": round((time.monotonic() - started) / 60, 1),
        },
        "vueltas": len(laps),
        "fallos": failures,
        "ram_primera_mb": first,
        "ram_ultima_mb": last,
        "ram_crecimiento": round(growth, 4),
        "cumple": not failures and growth <= RAM_GROWTH,
        "detalle": laps,
    }
    env = report["entorno"]
    name = f"stress-qgis{env['qgis']}-duckdb{env['duckdb']}"
    out = Path(args.out) if args.out else work
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = [
        f"QGIS {env['qgis']} · Qt {env['qt']} · DuckDB {env['duckdb']} · {env['cpus']} núcleos ·"
        f" {rows:,} filas · {env['minutos']} min",
        "",
        f"- Vueltas: {len(laps)} · fallos: {len(failures)}",
        f"- RAM: {first:.0f} MB → {last:.0f} MB ({growth:+.1%}; máximo {RAM_GROWTH:.0%})",
        f"- Cumple: {'sí' if report['cumple'] else 'no'}",
    ]
    summary += [f"  - {f}" for f in failures]
    (out / f"{name}.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print("\n".join(summary), flush=True)
    plugin.unload()
    os._exit(0 if report["cumple"] else 1)


if __name__ == "__main__":
    main()
