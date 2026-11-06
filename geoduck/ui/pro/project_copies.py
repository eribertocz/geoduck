# SPDX-License-Identifier: GPL-2.0-or-later
"""«Guardar las copias junto al proyecto» (workspace-pro-spec §7; GD-WSP-006; AT-WSP-007).

Al guardar el proyecto, si tiene capas «Copia» de GeoDuck (que viven en memoria y no sobreviven a reabrirlo,
spike E0b), un aviso ofrece en un clic **«Guardar las copias junto al proyecto»**: un GeoPackage al lado del
`.qgz`; cada capa pasa a leerlo y el proyecto se vuelve a guardar. Con «No, gracias» no se vuelve a preguntar
por esas capas en esta sesión de QGIS. Al abrir un proyecto con copias que no se guardaron, se dice cuáles y
por qué están vacías o no disponibles: nunca rotas sin explicación.

Las capas y el GeoPackage los maneja `qgis_bridge.copies` (ADR-0010: la interfaz no lo importa); el
complemento lo pasa como `bridge`, con `copies`, `is_copy`, `save_copies` y `target_for`.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import QObject, Qt, QTimer
from qgis.PyQt.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from geoduck.ui.i18n import tr
from geoduck.ui.pro import icons, style
from geoduck.ui.pro.widgets import button, label

#: (capas, archivo de destino) → guardar (True) o no (False).
Ask = Callable[[list[QgsVectorLayer], Path, QWidget], bool]


class SaveCopiesDialog(QDialog):
    """La maqueta aprobada (E4): «2 capas son «Copia»», qué pasa y un clic para guardarlas."""

    def __init__(self, layers: list[QgsVectorLayer], target: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        colors = style.apply(self)
        self.setWindowTitle(tr("GeoDuck"))
        box = QVBoxLayout(self)
        box.setContentsMargins(22, 20, 22, 18)
        box.setSpacing(10)
        top = QHBoxLayout()
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("info", colors.accent, 22))
        top.addWidget(glyph, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(6)
        title = (
            tr("1 layer is a «Copy»") if len(layers) == 1 else tr("{} layers are «Copy»").format(len(layers))
        )
        texts.addWidget(label(title, "title"))
        body = label(
            tr(
                "They live in memory and are not saved with the project: when you reopen it they will not be "
                "there. Save them in a file next to the project and they will always open."
            ),
            "muted",
        )
        body.setWordWrap(True)
        texts.addWidget(body)
        names = ", ".join(layer.name() for layer in layers)
        files = label(f"{names} → {target.name}", "faint")
        files.setWordWrap(True)
        texts.addWidget(files)
        top.addLayout(texts, 1)
        box.addLayout(top)
        row = QHBoxLayout()
        row.addStretch(1)
        self.no_button = button(tr("No, thanks"))
        self.no_button.clicked.connect(self.reject)
        self.save_button = button(tr("Save the copies next to the project"), "primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        row.addWidget(self.no_button)
        row.addWidget(self.save_button)
        box.addLayout(row)
        self.setFixedWidth(540)

    @staticmethod
    def ask(layers: list[QgsVectorLayer], target: Path, parent: QWidget) -> bool:
        return SaveCopiesDialog(layers, target, parent).exec() == QDialog.DialogCode.Accepted


class ProjectCopies(QObject):
    """Escucha el guardado y la apertura del proyecto. Nunca toca capas que no sean «Copia» de GeoDuck."""

    def __init__(
        self,
        parent: QWidget,
        notify: Callable[[str], None],
        bridge: Any,
        ask: Ask | None = None,
        project: QgsProject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._parent = parent
        self._notify = notify
        self._ask = ask or SaveCopiesDialog.ask
        self._project = project or QgsProject.instance()
        self._declined: set[str] = set()
        self._saving = False
        self._project.projectSaved.connect(self._after_save)
        self._project.readProject.connect(self._read)

    def _after_save(self) -> None:
        """Se pregunta cuando QGIS terminó de guardar: dentro de su guardado no se puede volver a guardar."""
        if not self._saving:
            QTimer.singleShot(0, self._saved)

    def _saved(self) -> None:
        target = self._bridge.target_for(self._project)
        layers = [layer for layer in self._bridge.copies(self._project) if layer.id() not in self._declined]
        if target is None or not layers:
            return
        if not self._ask(layers, target, self._parent):
            self._declined.update(layer.id() for layer in layers)
            self._notify(tr("The copies stay in memory: they will not be there when you reopen the project."))
            return
        saved, errors = self._bridge.save_copies(self._project, layers)
        self._saving = True  # el segundo guardado, el nuestro, no vuelve a preguntar
        try:
            self._project.write()
        finally:
            self._saving = False
        if errors:
            self._notify(tr("Some copies could not be saved: ") + "; ".join(errors))
        else:
            self._notify(tr("Copies saved in {}").format(saved.name))

    def _read(self, *_args: Any) -> None:
        QTimer.singleShot(0, self._explain_lost)  # cuando las capas ya están en el proyecto

    def _explain_lost(self) -> None:
        """Copias de un proyecto guardado sin ellas: vacías (memoria) o no disponibles (`/vsimem`)."""
        lost = [layer.name() for layer in self._project.mapLayers().values() if self._bridge.is_copy(layer)]
        if lost:
            self._notify(
                tr(
                    "{} were «Copy» layers not saved with the project: they are empty. Load them again."
                ).format(", ".join(f"«{name}»" for name in lost))
            )

    def detach(self) -> None:
        for signal, slot in (
            (self._project.projectSaved, self._after_save),
            (self._project.readProject, self._read),
        ):
            with contextlib.suppress(TypeError, RuntimeError):
                signal.disconnect(slot)
