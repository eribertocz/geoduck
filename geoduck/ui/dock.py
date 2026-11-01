# SPDX-License-Identifier: GPL-2.0-or-later
"""Panel acoplable de GeoDuck (G0): estado de sesión, inicio/cierre en memoria y diagnóstico.

El alcance de v0.1.0a1 es deliberadamente mínimo (spec/docs/roadmap.md, G0): sin editor SQL, sin
explorador y sin ATTACH. Esas superficies llegan en G1–G2 dentro de este mismo dock.
"""

from __future__ import annotations

from collections.abc import Callable

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QPalette
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from geoduck import __version__
from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    AppEvent,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
)
from geoduck.domain.diagnostics import CheckStatus, DiagnosticReport
from geoduck.domain.session import SessionState
from geoduck.ui.diagnostics_dialog import DiagnosticsDialog
from geoduck.ui.i18n import tr

STATE_TEXT = {
    SessionState.DISCONNECTED: "Sin sesión",
    SessionState.CONNECTING: "Conectando…",
    SessionState.READY: "Lista",
    SessionState.BUSY: "Ejecutando…",
    SessionState.DETACHING: "Desadjuntando…",
    SessionState.CLOSING: "Cerrando…",
    SessionState.ERROR_RECOVERABLE: "Fallo recuperable",
}

_CAN_START = {SessionState.DISCONNECTED, SessionState.ERROR_RECOVERABLE}
_CAN_CLOSE = {SessionState.CONNECTING, SessionState.READY, SessionState.BUSY, SessionState.ERROR_RECOVERABLE}


def _secondary(label: QLabel) -> QLabel:
    """Texto secundario derivado del color de texto del tema activo (claro u oscuro).

    No se usa `PlaceholderText`: en Qt5 puede ser transparente y ocultar el texto (visto en QGIS 3.44).
    """
    palette = label.palette()
    color = palette.color(QPalette.ColorRole.WindowText)
    color.setAlpha(170)
    palette.setColor(QPalette.ColorRole.WindowText, color)
    label.setPalette(palette)
    label.setWordWrap(True)
    return label


class GeoDuckDock(QDockWidget):
    def __init__(
        self,
        coordinator: SessionCoordinator,
        run_diagnostics: Callable[[], DiagnosticReport],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(tr("GeoDuck"), parent)
        self.setObjectName("GeoDuckDock")
        self._coordinator = coordinator
        self._run_diagnostics = run_diagnostics
        self._report: DiagnosticReport | None = None

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addLayout(self._build_header())
        layout.addWidget(self._build_session_card())
        layout.addWidget(self._build_message())
        layout.addWidget(self._build_env_banner())
        layout.addStretch(1)
        layout.addLayout(self._build_footer())
        self.setWidget(body)

        self.start_button.clicked.connect(self._start)
        self.close_button.clicked.connect(self._close)
        self.diagnostics_button.clicked.connect(self.show_diagnostics)
        self._unsubscribe = coordinator.subscribe(self._on_event)

        self.refresh_environment()
        self._render(coordinator.state)

    # -- construcción ------------------------------------------------------------------------------

    @staticmethod
    def _bold(label: QLabel) -> QLabel:
        font = QFont(label.font())
        font.setBold(True)
        label.setFont(font)
        return label

    def _build_header(self) -> QHBoxLayout:
        """Título de sección y estado siempre visible (ui-ux-spec §6)."""
        header = QHBoxLayout()
        self.state_label = QLabel()
        self.state_label.setObjectName("geoduckStateLabel")
        self.state_label.setAccessibleName(tr("Estado de la sesión"))
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._bold(QLabel(tr("Sesión DuckDB"))))
        header.addStretch(1)
        header.addWidget(self.state_label)
        return header

    def _build_session_card(self) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)
        card_layout.addWidget(self._bold(QLabel(tr("En memoria"))))
        card_layout.addWidget(
            _secondary(
                QLabel(
                    tr(
                        "Sesión DuckDB temporal (:memory:). Las tablas que cree desaparecen al cerrar "
                        "la sesión; las capas ya entregadas a QGIS no dependen de ella."
                    )
                )
            )
        )
        self.start_button = QPushButton(tr("Iniciar sesión"))
        self.start_button.setAccessibleName(tr("Iniciar sesión en memoria"))
        self.start_button.setDefault(True)
        self.close_button = QPushButton(tr("Cerrar sesión"))
        self.close_button.setAccessibleName(tr("Cerrar la sesión DuckDB"))
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.close_button)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)
        self.engine_label = _secondary(QLabel())
        card_layout.addWidget(self.engine_label)
        return card

    def _build_message(self) -> QLabel:
        """Errores recuperables: texto comprensible + código, seleccionable (ui-ux-spec §3)."""
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message_label.setAccessibleName(tr("Mensaje"))
        self.message_label.hide()
        return self.message_label

    def _build_env_banner(self) -> QFrame:
        self.env_banner = QFrame()
        self.env_banner.setFrameShape(QFrame.Shape.StyledPanel)
        banner_layout = QHBoxLayout(self.env_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        self.env_label = QLabel()
        self.env_label.setWordWrap(True)
        self.env_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        banner_layout.addWidget(self.env_label, 1)
        self.env_banner.hide()
        return self.env_banner

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        self.diagnostics_button = QPushButton(tr("Diagnóstico del entorno…"))
        self.diagnostics_button.setFlat(True)
        self.diagnostics_button.setToolTip(
            tr("Comprueba Python, QGIS, DuckDB, PyArrow y la extensión spatial")
        )
        footer.addWidget(self.diagnostics_button)
        footer.addStretch(1)
        footer.addWidget(_secondary(QLabel(f"v{__version__} · Alpha")))
        return footer

    # -- acciones ----------------------------------------------------------------------------------

    def _start(self) -> None:
        self.message_label.hide()
        self._coordinator.start_memory_session()

    def _close(self) -> None:
        self._coordinator.close_session()

    def refresh_environment(self) -> DiagnosticReport:
        self._report = self._run_diagnostics()
        if self._report.ok:
            self.env_banner.hide()
        else:
            failing = [c.title for c in self._report.checks if c.status is CheckStatus.FAIL]
            self.env_label.setText(
                tr("El entorno no está listo para GeoDuck: ")
                + ", ".join(failing)
                + ". "
                + tr("Abra «Diagnóstico del entorno» para ver qué hacer.")
            )
            self.env_banner.show()
        self._render(self._coordinator.state)
        return self._report

    def show_diagnostics(self) -> None:
        report = self.refresh_environment()
        DiagnosticsDialog(report, self).exec()

    def detach(self) -> None:
        self._unsubscribe()

    # -- render ------------------------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, SessionStateChanged):
            self._render(event.current)
        elif isinstance(event, SessionStarted):
            info = event.info
            cancel = (
                tr("cancelación inmediata disponible")
                if info.interrupt_enabled
                else tr("cancelación entre lotes")
            )
            self.engine_label.setText(f"DuckDB {info.duckdb_version} · {cancel}")
        elif isinstance(event, SessionInvalidated):
            self.message_label.setText(
                tr("Sesión invalidada:")
                + f" {event.message} [{event.code.value}] "
                + tr("Inicie una sesión nueva o cierre.")
            )
            self.message_label.show()
        elif isinstance(event, SessionFailed):
            self.message_label.setText(
                tr("No se pudo completar la operación.") + f" [{event.code.value}] {event.message}"
            )
            self.message_label.show()

    def _render(self, state: SessionState) -> None:
        env_ok = self._report is None or self._report.ok
        self.state_label.setText(tr(STATE_TEXT[state]))
        self.start_button.setEnabled(env_ok and state in _CAN_START)
        self.close_button.setEnabled(state in _CAN_CLOSE)
        if state is SessionState.DISCONNECTED:
            self.engine_label.setText(tr("Sin sesión activa."))
