# SPDX-License-Identifier: GPL-2.0-or-later
"""Cuadernos en disco (G7; ADR-0014).

- **Archivo `.sql`** que el usuario elige («Guardar cuaderno…» / «Abrir cuaderno…»). Formato:
  `geoduck.domain.notebook_file`. Un cuaderno con archivo se autoguarda en él tras cada cambio.
- **Copia de recuperación**, activada por defecto y desactivable: todos los cuadernos, tras cada cambio, en
  la carpeta del perfil de QGIS (`geoduck/recuperacion/<sesión>/`). Cada QGIS abierto usa su propia carpeta,
  con un `QLockFile`; al cerrar bien se borra. Si al abrir GeoDuck queda una carpeta sin dueño (QGIS se cerró
  por un fallo), se ofrece recuperar sus cuadernos. Solo el SQL y la base de cada celda: nunca resultados.

Toda escritura es atómica (temporal y renombrado): un corte no deja un archivo a medias.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import uuid
from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QLockFile

from geoduck.domain.notebook import Notebook
from geoduck.domain.notebook_file import dumps, loads

#: Para las pruebas: otra carpeta en lugar de la del perfil de QGIS.
RECOVERY_ENV = "GEODUCK_RECOVERY_DIR"
_INDEX = "cuadernos.json"
_LOCK = "sesion.lock"


def write_text(path: Path, text: str) -> None:
    """Escritura atómica en UTF-8 (temporal junto al destino y renombrado)."""
    partial = path.with_name(f".{path.name}.geoduck-{uuid.uuid4().hex[:8]}.tmp")
    try:
        partial.write_text(text, encoding="utf-8", newline="\n")
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def save_notebook(notebook: Notebook, path: str) -> None:
    write_text(Path(path), dumps(notebook))


def open_notebook(path: str) -> Notebook:
    """El cuaderno de un `.sql` (con o sin marcas de celda); su nombre es el del archivo."""
    target = Path(path)
    notebook = loads(target.read_text(encoding="utf-8-sig"), target.stem)
    notebook.path = str(target)
    return notebook


def recovery_root() -> Path:
    custom = os.environ.get(RECOVERY_ENV)
    if custom:
        return Path(custom)
    return Path(QgsApplication.qgisSettingsDirPath()) / "geoduck" / "recuperacion"


class RecoveryStore:
    """Copia de recuperación de los cuadernos de esta sesión de QGIS."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else recovery_root()
        self.folder: Path | None = None
        self._lock: QLockFile | None = None

    def _own(self) -> Path:
        if self.folder is None:
            self.folder = self.root / uuid.uuid4().hex[:12]
            self.folder.mkdir(parents=True, exist_ok=True)
            self._lock = QLockFile(str(self.folder / _LOCK))
            self._lock.setStaleLockTime(0)  # solo cuenta si el proceso dueño sigue vivo
            self._lock.tryLock(0)
        return self.folder

    def save(self, notebooks: list[Notebook]) -> None:
        folder = self._own()
        index = []
        for number, notebook in enumerate(notebooks, start=1):
            name = f"{number}.sql"
            write_text(folder / name, dumps(notebook))
            index.append({"archivo": name, "nombre": notebook.name, "ruta": notebook.path})
        for old in folder.glob("*.sql"):
            if old.name not in {item["archivo"] for item in index}:
                old.unlink(missing_ok=True)
        write_text(folder / _INDEX, json.dumps(index, ensure_ascii=False, indent=1))

    def stop(self) -> None:
        """Cierre normal (o copia desactivada): se borra la copia de esta sesión."""
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None
        if self.folder is not None:
            shutil.rmtree(self.folder, ignore_errors=True)
            self.folder = None

    def orphans(self) -> list[Path]:
        """Copias de sesiones que no se cerraron bien: su QGIS ya no existe (su candado está libre)."""
        if not self.root.is_dir():
            return []
        found = []
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir() or folder == self.folder or not (folder / _INDEX).is_file():
                continue
            lock = QLockFile(str(folder / _LOCK))
            lock.setStaleLockTime(0)
            if lock.tryLock(0):  # nadie la tiene: QGIS se cerró sin borrarla
                lock.unlock()
                found.append(folder)
        return found

    @staticmethod
    def read(folder: Path) -> list[Notebook]:
        notebooks = []
        for item in json.loads((folder / _INDEX).read_text(encoding="utf-8")):
            with contextlib.suppress(OSError, ValueError, KeyError):
                notebook = loads((folder / item["archivo"]).read_text(encoding="utf-8"), item["nombre"])
                notebook.path = item.get("ruta") or None
                notebooks.append(notebook)
        return notebooks

    @staticmethod
    def discard(folder: Path) -> None:
        shutil.rmtree(folder, ignore_errors=True)
