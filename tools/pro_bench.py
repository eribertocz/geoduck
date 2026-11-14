# SPDX-License-Identifier: GPL-2.0-or-later
"""Medidas de Workspace Pro (G9 · E7; workspace-pro-spec §13; AT-WSP-012) con la interfaz real.

    QT_QPA_PLATFORM=offscreen python tools/pro_bench.py [repeticiones]

Con un `ProWorkspace` real, su sesión DuckDB real (en memoria) y un `ProController` con un `iface` de prueba:

1. abrir una tabla de 1 millón de filas: tiempo hasta ver la primera página;
2. ordenar, filtrar con dos chips, buscar y desplazar a la mitad: tiempo hasta ver el resultado y la pausa más
   larga de la interfaz mientras tanto (un temporizador de 5 ms mide si el hilo principal se bloquea);
3. Ctrl+K con 1 000 objetos: tiempo de cada tecla (filtrar y pintar la lista);
4. alternar ventana ↔ panel.

Imprime una tabla en Markdown (mediana y máximo de las repeticiones).
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QT_VERSION_STR, QCoreApplication, QElapsedTimer, QTimer

ROWS = 1_000_000
OBJECTS = 1_000


class Stall:
    """La pausa más larga del hilo principal: un temporizador de 5 ms anota el mayor hueco entre disparos."""

    def __init__(self) -> None:
        self.clock = QElapsedTimer()
        self.timer = QTimer()
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._tick)
        self.worst = 0.0

    def _tick(self) -> None:
        gap = self.clock.restart()
        self.worst = max(self.worst, float(gap))

    def __enter__(self) -> Stall:
        self.worst = 0.0
        self.clock.start()
        self.timer.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.timer.stop()


def until(condition, timeout: float = 30.0) -> float:
    """Procesa eventos hasta que `condition()`; devuelve los ms transcurridos."""
    start = time.perf_counter()
    while not condition():
        QCoreApplication.processEvents()
        if time.perf_counter() - start > timeout:
            raise TimeoutError
        time.sleep(0.0005)
    return (time.perf_counter() - start) * 1000


def main() -> None:  # noqa: PLR0915 - todas las medidas, en orden
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    os.environ.setdefault("GEODUCK_RECOVERY_DIR", tempfile.mkdtemp())
    app = QgsApplication([], True)
    app.initQgis()
    from geoduck.app.coordinator import SessionCoordinator
    from geoduck.domain.browse import GT, LT, Filter
    from geoduck.domain.session import SessionState
    from geoduck.domain.sql import RunScope
    from geoduck.plugin import make_memory_engine
    from geoduck.ui.dispatcher import QtDispatcher
    from geoduck.ui.pro.places import Place
    from geoduck.ui.pro.shell import Mode, ProController
    from geoduck.ui.pro.table_page import TablePage
    from geoduck.ui.pro.workspace import ProWorkspace
    from tests.qgis.conftest import FakeIface
    from tools.pro_shots import Store

    coordinator = SessionCoordinator(make_memory_engine, QtDispatcher())
    coordinator.start_memory_session()
    until(lambda: coordinator.state is SessionState.READY and coordinator.catalog is not None)
    tables = "; ".join(f"CREATE TABLE o_{i:04d} (x INTEGER)" for i in range(OBJECTS))
    coordinator.execute_sql(
        f"CREATE TABLE medidores AS SELECT range AS id, 'MEDIDOR ' || range AS nombre,"
        f" (range * 7919) % 10000 / 10.0 AS kwh, range % 50 AS zona FROM range({ROWS}); {tables};",
        RunScope.ALL,
    )
    until(lambda: coordinator.state is SessionState.READY, 120)
    coordinator.refresh_catalog()
    until(lambda: len(coordinator.catalog.objects) > OBJECTS)

    ws = ProWorkspace(coordinator, lambda: None, Store())
    ws.resize(1440, 900)
    ws.show()
    QCoreApplication.processEvents()
    results: dict[str, list[tuple[float, float]]] = {}

    def record(name: str, ms: float, stall: float) -> None:
        results.setdefault(name, []).append((ms, stall))

    for _ in range(repeat):
        # 1. abrir la tabla de 1 millón de filas
        with Stall() as stall:
            ws.open_place(Place("table", "medidores", "memory", "main"))
            page = ws.tabs.page(ws.tabs.bar.currentIndex())
            assert isinstance(page, TablePage)
            ms = until(lambda p=page: p.model.rowCount() > 0)
        record("Abrir 1 millón de filas: primera página", ms, stall.worst)
        until(lambda p=page: p.total == ROWS)

        def measured(name: str, action, page=page) -> None:
            page.model.set_page((), (), 0)  # vacía: se ve cuando llega la página nueva
            with Stall() as stall:
                action()
                ms = until(lambda: page.model.rowCount() > 0)
            record(name, ms, stall.worst)

        measured("Ordenar por una columna", lambda p=page: p.data.sort_by(2))
        measured("Filtro: primer chip", lambda p=page: p.add_filter(Filter("kwh", GT, "100")))
        measured("Filtro: segundo chip", lambda p=page: p.add_filter(Filter("zona", LT, "10")))
        page.search.edit.setText("MEDIDOR 9")
        measured("Buscar", page._search_changed)
        until(lambda p=page: p.total is not None)
        with Stall() as stall:  # desplazamiento continuo (#170): hasta ver las filas de esa posición
            page.data.scroll_to(ROWS // 2)
            ms = until(lambda p=page: p.model.rowCount() > 0 and not p.model.missing())
        record("Desplazar a la mitad", ms, stall.worst)
        ws.tabs.close_tab(ws.tabs.bar.currentIndex())

        # 3. Ctrl+K con 1 000 objetos, tecla a tecla
        palette = ws.command_palette
        palette.open()
        for text in ("o", "o_", "o_0", "o_09", "o_099", "o_0999"):
            clock = time.perf_counter()
            palette.edit.setText(text)  # filtra en el momento (sin esperar al worker)
            palette.repaint()
            record("Ctrl+K: una tecla (1 000 objetos)", (time.perf_counter() - clock) * 1000, 0.0)
        palette.close_palette()

    # 4. ventana ↔ panel, con el controlador real
    iface = FakeIface()
    controller = ProController(iface, ws, Store())
    controller.set_visible(True)
    for _ in range(repeat):
        for mode in (Mode.DOCK, Mode.WINDOW):
            clock = time.perf_counter()
            controller.set_mode(mode)
            QCoreApplication.processEvents()
            record("Alternar ventana ↔ panel", (time.perf_counter() - clock) * 1000, 0.0)

    qt = QT_VERSION_STR
    print(f"| Medida (Qt {qt}, {repeat} repeticiones) | Mediana | Máximo | Pausa máx. de la interfaz |")
    print("|---|---|---|---|")
    for name, values in results.items():
        times = [v[0] for v in values]
        stalls = [v[1] for v in values]
        stall_text = f"{max(stalls):.0f} ms" if any(stalls) else "—"
        print(f"| {name} | {statistics.median(times):.1f} ms | {max(times):.1f} ms | {stall_text} |")
    sys.stdout.flush()
    controller.unload()
    coordinator.shutdown(10)
    os._exit(0)  # como pro_shots: sin la limpieza de PyQt5 al salir


if __name__ == "__main__":
    main()
