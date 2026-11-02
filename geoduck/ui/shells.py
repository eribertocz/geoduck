# SPDX-License-Identifier: GPL-2.0-or-later
"""Las dos presentaciones del workspace (ui-ux-spec §8, ADR-0013): ventana propia y panel acoplado.

Un shell solo aloja el `WorkspaceContent` y ofrece el botón para cambiar a la otra presentación. No guarda
estado de la sesión ni conecta señales del contenido: el contenido y las tareas pertenecen al
`WorkspaceController`. Cerrar u ocultar un shell nunca cierra la sesión.
"""

from __future__ import annotations

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCloseEvent, QHideEvent, QShowEvent
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.ui.i18n import tr

WINDOW_SIZE = (1100, 720)


class _Slot(QWidget):
    """Encabezado con el botón de alternancia y, debajo, el lugar del contenido."""

    def __init__(self, button: QPushButton, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(8, 6, 8, 0)
        header.addStretch(1)
        header.addWidget(button)
        self.content_layout.addLayout(header)

    def put(self, content: QWidget) -> None:
        # addWidget cambia el padre en un solo paso: el contenido nunca queda sin padre (ADR-0013)
        self.content_layout.addWidget(content, 1)
        content.show()

    def take(self, content: QWidget) -> None:
        self.content_layout.removeWidget(content)  # no cambia el padre: lo hará `put` del otro shell


class WindowShell(QMainWindow):
    """Ventana propia (por defecto). Hija de la ventana principal de QGIS: queda encima de QGIS, se
    minimiza con él y no tiene entrada propia en la barra de tareas. La X la oculta."""

    shown_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GeoDuckWindow")
        self.setWindowTitle(tr("GeoDuck"))
        self.toggle_button = QPushButton(QgsApplication.getThemeIcon("mDockify.svg"), tr("Acoplar a QGIS"))
        self.toggle_button.setObjectName("geoduckDockButton")
        self.toggle_button.setToolTip(tr("Muestra GeoDuck como panel acoplado a QGIS, con la misma sesión"))
        self.slot = _Slot(self.toggle_button, self)
        self.setCentralWidget(self.slot)
        self.resize(*WINDOW_SIZE)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - API de Qt
        event.accept()  # sin WA_DeleteOnClose: la ventana solo se oculta; la sesión sigue (§8 «Cerrar»)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not event.spontaneous():
            self.shown_changed.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        super().hideEvent(event)
        if not event.spontaneous():  # minimizar QGIS no cuenta como ocultar GeoDuck
            self.shown_changed.emit(False)


class DockShell(QDockWidget):
    """Panel acoplado a QGIS. Su X lo oculta (comportamiento estándar de `QDockWidget`)."""

    shown_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(tr("GeoDuck"), parent)
        self.setObjectName("GeoDuckDock")  # el mismo nombre de G0–G4: QGIS conserva su posición
        self.toggle_button = QPushButton(QgsApplication.getThemeIcon("mDockify.svg"), tr("Abrir en ventana"))
        self.toggle_button.setObjectName("geoduckWindowButton")
        self.toggle_button.setToolTip(tr("Muestra GeoDuck en su propia ventana, con la misma sesión"))
        self.slot = _Slot(self.toggle_button, self)
        self.setWidget(self.slot)
        self.visibilityChanged.connect(self.shown_changed)
