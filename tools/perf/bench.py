# SPDX-License-Identifier: GPL-2.0-or-later
"""Banco de medidas de GeoDuck (G10 · E1; performance-spec §2; AT-PERF-001), con el complemento real.

    QT_QPA_PLATFORM=offscreen python tools/perf/bench.py [--rows 1000000] [--repeat 3] [--out carpeta]

Con `GeoDuckPlugin`, su coordinador y su worker DuckDB reales (sin pantalla), mide de punta a punta cada
operación con datos generados (semilla fija; T2 tabular y T3 puntos de `spec/qa/benchmarks.md`):

- consulta y primera página; contar;
- «Cargar en QGIS» como Copia y como Conectada;
- capa de QGIS → DuckDB (por QGIS) y archivo Parquet → DuckDB (por DuckDB);
- «Exportar ▾» a Parquet y a CSV;
- cancelar una consulta, una exportación y una carga: tiempo hasta que la sesión vuelve a estar lista.

De cada una: tiempo (mediana y máximo de las repeticiones), la pausa más larga y el p95 de las pausas del
hilo de la interfaz (un temporizador de 5 ms) y la memoria pico del proceso. Escribe
`bench-<qgis>-<duckdb>.json` y una tabla Markdown. Solo números medidos aquí: no se comparan equipos
distintos (benchmarks §6).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.PyQt.QtCore import QT_VERSION_STR, QCoreApplication, QElapsedTimer, QTimer


class Stall:
    """Pausas del hilo de la interfaz: un temporizador de 5 ms anota el hueco entre disparos."""

    def __init__(self) -> None:
        self.clock = QElapsedTimer()
        self.timer = QTimer()
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._tick)
        self.gaps: list[float] = []

    def _tick(self) -> None:
        self.gaps.append(float(self.clock.restart()))

    def __enter__(self) -> Stall:
        self.gaps = []
        self.clock.start()
        self.timer.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.timer.stop()

    @property
    def worst(self) -> float:
        return max(self.gaps, default=0.0)

    @property
    def p95(self) -> float:
        if not self.gaps:
            return 0.0
        ordered = sorted(self.gaps)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def until(condition: Any, timeout: float = 600.0) -> float:
    """Procesa eventos hasta que `condition()`; devuelve los ms transcurridos."""
    start = time.perf_counter()
    while not condition():
        QCoreApplication.processEvents()
        if time.perf_counter() - start > timeout:
            raise TimeoutError
        time.sleep(0.0005)
    return (time.perf_counter() - start) * 1000


def peak_mb() -> float:
    """Memoria residente pico del proceso (QGIS + worker), en MB."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def main() -> None:  # noqa: PLR0915 - todas las medidas, en orden
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    rows, repeat = args.rows, args.repeat
    work = Path(tempfile.mkdtemp(prefix="geoduck-bench-"))
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
    )
    from geoduck.domain.export import ExportFormat, ExportRequest
    from geoduck.domain.importing import ImportMode, SendItem, SendRequest
    from geoduck.domain.load import LoadMode, LoadRequest
    from geoduck.domain.session import SessionState
    from geoduck.domain.sql import RunScope
    from geoduck.plugin import GeoDuckPlugin
    from tests.qgis.conftest import FakeIface

    plugin = GeoDuckPlugin(FakeIface())
    plugin.initGui()
    co = plugin.coordinator
    events: list[Any] = []
    co.subscribe(events.append)
    co.start_memory_session()
    until(lambda: co.state is SessionState.READY and co.catalog is not None)

    def ready() -> bool:
        return co.state is SessionState.READY

    def run(sql: str) -> None:
        co.execute_sql(sql, RunScope.ALL)
        until(ready)

    def got(*kinds: type) -> bool:
        return any(isinstance(e, kinds) for e in events)

    # T2 (tabular, 10 columnas) y T3 (puntos con SRC), con valores deterministas
    run(
        "CREATE TABLE t2 AS SELECT i AS id, 'cliente ' || (i % 1000) AS nombre,"
        " (i * 7919) % 10000 / 10.0 AS kwh,"
        " DATE '2020-01-01' + (i % 2000)::INT AS fecha, (i % 50) AS zona, i % 3 = 0 AS activo,"
        " (i * 31) % 100000 AS codigo, CASE WHEN i % 17 = 0 THEN NULL ELSE 'obs ' || i END AS nota,"
        " (i % 997)::DECIMAL(10,2) AS monto, TIMESTAMP '2024-01-01' + INTERVAL (i % 86400) SECOND AS ts"
        f" FROM range({rows}) r(i);"
        " CREATE TABLE t3 AS SELECT i AS id, 'p' || i AS nombre,"
        " ST_SetCRS(('POINT(' || (i * 7919) % 100000 || ' ' || (i * 104729) % 100000 || ')')::GEOMETRY,"
        " 'EPSG:32719') AS geom"
        f" FROM range({rows}) r(i);"
    )
    parquet = work / "t2.parquet"
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT i AS id, 'cliente ' || (i % 1000) AS nombre, (i * 7919) % 10000 / 10.0 AS kwh"
        f" FROM range({rows}) r(i)) TO '{parquet}' (FORMAT parquet)"
    )
    con.close()

    results: dict[str, list[dict[str, float]]] = {}

    def measure(name: str, start: Any, done: Any, timeout: float = 900.0) -> None:
        events.clear()
        with Stall() as stall:
            begin = time.perf_counter()
            start()
            until(done, timeout)
            ms = (time.perf_counter() - begin) * 1000
        results.setdefault(name, []).append(
            {"ms": ms, "pausa_max_ms": stall.worst, "pausa_p95_ms": stall.p95, "ram_pico_mb": peak_mb()}
        )
        until(ready)

    def cancel(name: str, start: Any, wait_ms: int = 300) -> None:
        events.clear()
        start()
        begin = time.perf_counter()
        while (time.perf_counter() - begin) * 1000 < wait_ms:
            QCoreApplication.processEvents()
        with Stall() as stall:
            begin = time.perf_counter()
            cancelled = co.cancel_current_operation()
            until(ready, 120)
            ms = (time.perf_counter() - begin) * 1000
        results.setdefault(name, []).append(
            {
                "ms": ms,
                "pausa_max_ms": stall.worst,
                "pausa_p95_ms": stall.p95,
                "habia_que_cancelar": float(cancelled),
            }
        )

    heavy = "SELECT count(*) FROM t2 a JOIN t2 b ON a.zona = b.zona AND a.kwh < b.kwh"
    for n in range(repeat):
        measure(
            "Consulta: primera página (10 columnas)",
            lambda: co.execute_sql("SELECT * FROM t2", RunScope.ALL),
            ready,
        )
        measure(
            "Consulta: agregado por zona",
            lambda: co.execute_sql("SELECT zona, count(*), avg(kwh) FROM t2 GROUP BY zona", RunScope.ALL),
            ready,
        )
        for label, mode in (("Copia", LoadMode.SNAPSHOT), ("Conectada", LoadMode.CONNECTED)):
            request = LoadRequest(
                "SELECT * FROM t3",
                mode,
                f"t3_{label}_{n}",
                "geom",
                source=("memory", "main", "t3"),
                source_kind="table",
            )
            measure(
                f"Cargar en QGIS · {label} (puntos)",
                lambda r=request: co.load(r),
                lambda: got(LoadFinished, LoadFailed),
            )
            assert not got(LoadFailed), [e for e in events if isinstance(e, LoadFailed)]
        copia = next(
            layer for layer in QgsProject.instance().mapLayers().values() if layer.name() == f"t3_Copia_{n}"
        )
        send = SendRequest(
            (SendItem(copia.id(), f"desde_qgis_{n}", ImportMode.CREATE),), "memory", "main", False
        )
        measure(
            "Capa de QGIS → DuckDB (por QGIS, puntos)",
            lambda r=send: co.send_layers(r),
            lambda: got(SendFinished, SendFailed),
        )
        assert not got(SendFailed), [e for e in events if isinstance(e, SendFailed)]
        scanned: list[Any] = []
        co.scan_files([str(parquet)], scanned.append)
        until(lambda s=scanned: bool(s))
        item = SendItem("file:0", f"desde_archivo_{n}", ImportMode.CREATE, file=scanned[0][0])
        measure(
            "Archivo Parquet → DuckDB (por DuckDB)",
            lambda i=item: co.send_layers(SendRequest((i,), "memory", "main", False)),
            lambda: got(SendFinished, SendFailed),
        )
        assert not got(SendFailed), [e for e in events if isinstance(e, SendFailed)]
        for fmt in (ExportFormat.PARQUET, ExportFormat.CSV):
            target = work / f"salida_{n}{fmt.suffix}"
            measure(
                f"Exportar ▾ · {fmt.value}",
                lambda f=fmt, t=target: co.export(ExportRequest("SELECT * FROM t2", str(t), f, None)),
                lambda: got(ExportFinished, ExportFailed),
            )
        cancel("Cancelar · consulta pesada", lambda: co.execute_sql(heavy, RunScope.ALL))
        cancel(
            "Cancelar · exportar",
            lambda n=n: co.export(
                ExportRequest(
                    "SELECT a.* FROM t2 a, range(20)",
                    str(work / f"c_{n}.parquet"),
                    ExportFormat.PARQUET,
                    None,
                )
            ),
        )
        big = LoadRequest("SELECT a.* FROM t3 a, range(10)", LoadMode.SNAPSHOT, f"cancelada_{n}", "geom")
        cancel("Cancelar · cargar en QGIS (Copia)", lambda r=big: co.load(r))
        leftovers = [p.name for p in work.iterdir() if p.name.startswith("c_") or p.name.startswith(".")]
        assert not leftovers, leftovers
        for layer in list(QgsProject.instance().mapLayers().values()):
            QgsProject.instance().removeMapLayer(layer.id())
        run("; ".join(f"DROP TABLE IF EXISTS {t}_{n}" for t in ("desde_qgis", "desde_archivo")) + ";")

    summary = {}
    for name, runs in results.items():
        times = [r["ms"] for r in runs]
        summary[name] = {
            "mediana_ms": round(statistics.median(times), 1),
            "max_ms": round(max(times), 1),
            "pausa_max_ms": round(max(r["pausa_max_ms"] for r in runs), 1),
            "pausa_p95_ms": round(max(r["pausa_p95_ms"] for r in runs), 1),
        }
        if "habia_que_cancelar" in runs[0]:  # False = la operación ya había terminado: la medida no vale
            summary[name]["seguia_en_curso"] = all(r["habia_que_cancelar"] for r in runs)
    report = {
        "entorno": {
            "qgis": Qgis.QGIS_VERSION.split("-")[0],
            "qt": QT_VERSION_STR,
            "duckdb": duckdb.__version__,
            "python": platform.python_version(),
            "sistema": platform.platform(),
            "cpus": os.cpu_count(),
            "filas": rows,
            "repeticiones": repeat,
            "ram_pico_mb": round(peak_mb(), 1),
        },
        "medidas": summary,
    }
    out = Path(args.out) if args.out else work
    out.mkdir(parents=True, exist_ok=True)
    env = report["entorno"]
    name = f"bench-qgis{env['qgis']}-duckdb{env['duckdb']}"
    (out / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [
        f"QGIS {env['qgis']} · Qt {env['qt']} · DuckDB {env['duckdb']} · {env['cpus']} núcleos ·"
        f" {rows:,} filas ·"
        f" {repeat} repeticiones · RAM pico {env['ram_pico_mb']} MB",
        "",
        "| Operación | Mediana | Máximo | Pausa máx. de la interfaz | Pausa p95 |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {k} | {v['mediana_ms']:,.0f} ms | {v['max_ms']:,.0f} ms | {v['pausa_max_ms']:.0f} ms |"
        f" {v['pausa_p95_ms']:.0f} ms |"
        for k, v in summary.items()
    ]
    (out / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    plugin.unload()


if __name__ == "__main__":
    main()
