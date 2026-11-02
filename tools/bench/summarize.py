# SPDX-License-Identifier: GPL-2.0-or-later
# ruff: noqa: E501 - cabeceras de tablas Markdown en una línea
"""Genera docs/evidence/g3/tablas.md a partir de los JSON del spike G3-A (no es código del complemento).

Uso: python tools/bench/summarize.py docs/evidence/g3
"""

from __future__ import annotations

import glob
import json
import os
import sys


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _yes(v) -> str:
    return "—" if v is None else ("sí" if v else "**no**")


def bench(path: str) -> list[str]:
    rows = _load(path)
    out = [
        "| datos | filas | lote | etapa | estrategia | tramo | fechas | total s | filas/s | hilo principal s "
        "| bloqueo máx ms | ΔRSS MB |",
        "|---|---:|---:|---|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        if "error" in r:
            out.append(
                f"| {r['dataset']} | {r['rows']:,} | {r['batch']} | {r['stage']} | {r['strategy']} | "
                f"| | **error** {r['error']} | | | | |"
            )
            continue
        out.append(
            f"| {r['dataset']} | {r['rows']:,} | {r['batch']} | {r['stage']} | {r['strategy']} | "
            f"{r.get('chunk') or '—'} | {r.get('temporal', '—') if r['stage'] == 'qgis' else '—'} | {r['seconds']} | "
            f"{r['rows_per_s']:,} | {r.get('main_thread_s', '—')} | {r.get('max_main_block_ms', '—')} | "
            f"{r['rss_growth_mb']} |"
        )
    return out


def compare(path: str) -> list[str]:
    rows = _load(path)
    out = [
        "| ruta | filas | proveedor | total s | bloqueo máx ms | RAM retenida MB | /vsimem MB | disco MB | CRS "
        "| íntegra | tras DETACH y cierre | tras reabrir proyecto | editable | dibujar s | leer todo s |",
        "|---|---:|---|---:|---:|---:|---:|---:|---|---|---|---|---|---:|---:|",
    ]
    for r in rows:
        if r.get("cancel"):
            continue
        if "integrity" not in r:
            out.append(f"| {r['route']} | {r['rows']:,} | **error**: {r.get('error')} |" + " |" * 12)
            continue
        out.append(
            f"| {r['route']} | {r['rows']:,} | {r['provider']} | {r['seconds']} | {r['max_main_block_ms']} | "
            f"{r['resident_after_load_mb']} | {r['vsimem_mb']} | {r.get('disk_mb', 0)} | {r['crs']} | "
            f"{_yes(r['integrity'])} | {_yes(r['survives_detach_close'])} | {_yes(r.get('survives_project_reopen'))} "
            f"| {_yes(r['editable'])} | {r['render_s'][1]} | {r['iterate_s']} |"
        )
    out += [
        "",
        "Cancelación a mitad de la carga:",
        "",
        "| ruta | filas | cancelada | filas antes de cancelar | capas en el proyecto | restos | sesión usable |",
        "|---|---:|---|---:|---:|---|---|",
    ]
    for r in rows:
        if not r.get("cancel"):
            continue
        out.append(
            f"| {r['route']} | {r['rows']:,} | {_yes(r.get('cancelled'))} | {r.get('rows_before_cancel')} | "
            f"{r.get('project_layers')} | {'**sí**' if r.get('leftover_file') else 'no'} | "
            f"{_yes(r.get('session_usable'))} |"
        )
    return out


def types(path: str) -> list[str]:
    data = _load(path)
    out = [
        f"Geometría principal: tipo {data['geometria']['tipo']}, CRS {data['geometria']['crs']}, "
        f"`{data['geometria']['wkt']}`. Segunda geometría accesible: {_yes(data['segunda_geometria_accesible'])}.",
        "",
        "| columna | Arrow | campo QGIS | valor en QGIS |",
        "|---|---|---|---|",
    ]
    for c in data["campos"]:
        value = c["valor_qgis"].replace("|", "\\|")
        out.append(f"| `{c['columna']}` | `{c['arrow']}` | {c['qgis']} | `{value}` |")
    return out


def ondemand(path: str) -> list[str]:
    rows = _load(path)
    out = [
        "| ruta | filas | escribir s | abrir s | conteo s | filtro 1 % área (filas · s) | filtro atributo s "
        "| recorrer todo s | dibujar todo s | dibujar zoom s | CRS | editable |",
        "|---|---:|---:|---:|---:|---|---:|---:|---:|---:|---|---|",
    ]
    for r in rows:
        if not r.get("valid"):
            out.append(
                f"| {r['route']} | {r['rows']:,} | **no se abre** {r.get('tables_listed', '')} |" + " |" * 9
            )
            continue
        out.append(
            f"| {r['route']} | {r['rows']:,} | {r.get('write_s', '—')} | {r['open_s']} | {r['count_s']} | "
            f"{r['bbox_rows']:,} · {r['bbox_s']} | {r['attr_s']} | {r['scan_s']} | {r['render_full_s']} | "
            f"{r['render_zoom_s']} | {r['crs'] or '(ninguno)'} | {_yes(r['editable'])} |"
        )
        if "tables_listed" in r:
            out.append(f"| ↳ tablas que lista ADBC: `{r['tables_listed']}` |" + " |" * 11)
    return out


def main() -> None:
    folder = sys.argv[1] if len(sys.argv) > 1 else "docs/evidence/g3"
    lines = [
        "# Tablas del spike G3-A (generadas)",
        "",
        "Generado por `tools/bench/summarize.py` a partir de los JSON de esta carpeta. No editar a mano.",
        "",
    ]
    sections = [
        ("compare_*.json", "Comparación de rutas", compare),
        ("ondemand_*.json", "Lectura bajo demanda", ondemand),
        ("types_*.json", "Fidelidad de tipos (driver Arrow de GDAL)", types),
        ("result_q*.json", "Bench de transferencia a capa memory", bench),
        ("result_engine_*.json", "Etapa de motor (sin QGIS)", bench),
    ]
    for pattern, title, fn in sections:
        for path in sorted(glob.glob(os.path.join(folder, pattern))):
            lines += [f"## {title} — `{os.path.basename(path)}`", "", *fn(path), ""]
    with open(os.path.join(folder, "tablas.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    main()
