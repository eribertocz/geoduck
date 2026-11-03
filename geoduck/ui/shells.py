# SPDX-License-Identifier: GPL-2.0-or-later
"""Las dos presentaciones del workspace (ui-ux-spec §8, ADR-0013): ventana propia y panel acoplado.

Un shell solo aloja el `WorkspaceContent` y ofrece el botón para cambiar a la otra presentación. No guarda
estado de la sesión ni conecta señales del contenido: el contenido y las tareas pertenecen al
`WorkspaceController`. Cerrar u ocultar un shell nunca cierra la sesión.
"""

from __future__ import annotations

from pathlib import Path

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QCloseEvent, QFont, QHideEvent, QIcon, QShowEvent
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.ui.i18n import tr

WINDOW_SIZE = (1100, 720)
ICON = str(Path(__file__).resolve().parents[1] / "resources" / "icon.svg")


class _Slot(QWidget):
    """El lugar del contenido dentro de un shell."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)

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
        self.setWindowIcon(QIcon(ICON))
        #: Botón «Acoplar a QGIS»: vive en la barra de sesión del contenido; lo asigna el controlador.
        self.toggle_button: QPushButton | None = None
        self.slot = _Slot(self)
        self.slot.setObjectName("geoduckWindowCentral")
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
        # Barra de título propia (inventario P1, P4): «GeoDuck», «Abrir en ventana» y una X que lo oculta
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        title = QWidget()
        title.setObjectName("geoduckDockTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(title)
        row.setContentsMargins(12, 6, 6, 6)
        row.setSpacing(6)
        name = QLabel(tr("GeoDuck"))
        font = QFont(name.font())
        font.setBold(True)
        name.setFont(font)
        row.addWidget(name)
        row.addStretch(1)
        self.toggle_button = QPushButton(QgsApplication.getThemeIcon("mDockify.svg"), tr("Open in a window"))
        self.toggle_button.setObjectName("geoduckWindowButton")
        self.toggle_button.setProperty("geoduck", "secondary")
        self.toggle_button.setToolTip(tr("Shows GeoDuck in its own window, with the same session"))
        row.addWidget(self.toggle_button)
        self.close_button = QToolButton()
        self.close_button.setObjectName("geoduckDockClose")
        self.close_button.setIcon(QgsApplication.getThemeIcon("mIconClose.svg"))
        self.close_button.setText("✕")
        self.close_button.setAutoRaise(True)
        self.close_button.setToolTip(tr("Hide the panel (the session stays open)"))
        self.close_button.setAccessibleName(tr("Hide the panel"))
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)
        self.title_bar = title
        self.setTitleBarWidget(title)
        self.slot = _Slot(self)
        self.slot.setObjectName("geoduckDockBody")
        self.setWidget(self.slot)
        self.visibilityChanged.connect(self.shown_changed)
