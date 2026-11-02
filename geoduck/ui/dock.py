# SPDX-License-Identifier: GPL-2.0-or-later
"""Panel acoplable de GeoDuck: estado de sesión, inicio/cierre, bases de datos y diagnóstico.

G1 añade el explorador del catálogo y los controles «Abrir existente», «Crear nueva» y «Desadjuntar»
(GD-SES-002..004, GD-CAT-001). El editor SQL llega en G2 (spec/docs/roadmap.md).
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from geoduck import __version__
from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    AppEvent,
    AttachFailed,
    CatalogChanged,
    CatalogUnavailable,
    CloseConfirmationRequired,
    DatabaseAttached,
    DatabaseDetached,
    DetachFailed,
    SessionFailed,
    SessionInvalidated,
    SessionStarted,
    SessionStateChanged,
    TransactionFailed,
)
from geoduck.domain.catalog import AttachRequest, OpenAction
from geoduck.domain.diagnostics import CheckStatus, DiagnosticReport
from geoduck.domain.session import ErrorCause, SessionState
from geoduck.domain.transaction import CloseChoice
from geoduck.ui.attach_dialog import AttachDialog
from geoduck.ui.close_dialog import CloseTransactionDialog
from geoduck.ui.diagnostics_dialog import DiagnosticsDialog
from geoduck.ui.explorer import CatalogExplorer
from geoduck.ui.i18n import tr
from geoduck.ui.sql_panel import SqlPanel

STATE_TEXT = {
    SessionState.DISCONNECTED: "Sin sesión",
    SessionState.CONNECTING: "Conectando…",
    SessionState.READY: "Lista",
    SessionState.BUSY: "Ejecutando…",
    SessionState.DETACHING: "Desadjuntando…",
    SessionState.CLOSING: "Cerrando…",
    SessionState.ERROR_RECOVERABLE: "Fallo recuperable",
}

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
        *,
        ask_close_choice: Callable[[CloseConfirmationRequired, QWidget], CloseChoice] | None = None,
        ask_attach_request: Callable[[OpenAction, QWidget], AttachRequest | None] | None = None,
    ) -> None:
        super().__init__(tr("GeoDuck"), parent)
        self.setObjectName("GeoDuckDock")
        self._coordinator = coordinator
        self._run_diagnostics = run_diagnostics
        self._report: DiagnosticReport | None = None
        self._ask_close_choice = ask_close_choice or CloseTransactionDialog.ask
        self._ask_attach_request = ask_attach_request or AttachDialog.ask

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addLayout(self._build_header())
        layout.addWidget(self._build_session_card())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_databases_card(), tr("Bases de datos"))
        self.sql_panel = SqlPanel(coordinator, on_message=self._show_plain_message)
        self.tabs.addTab(self.sql_panel, tr("SQL"))
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self._build_message())
        layout.addWidget(self._build_env_banner())
        layout.addLayout(self._build_footer())
        self.setWidget(body)

        self.start_button.clicked.connect(self._start)
        self.rollback_button.clicked.connect(self._coordinator.rollback_transaction)
        self.close_button.clicked.connect(self._close)
        self.diagnostics_button.clicked.connect(self.show_diagnostics)
        self.open_button.clicked.connect(lambda: self._attach(OpenAction.OPEN_EXISTING))
        self.create_button.clicked.connect(lambda: self._attach(OpenAction.CREATE_NEW))
        self.detach_button.clicked.connect(self._detach)
        self.explorer.itemSelectionChanged.connect(lambda: self._render(self._coordinator.state))
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
        self.rollback_button = QPushButton(tr("Revertir transacción"))
        self.rollback_button.setToolTip(
            tr("La transacción está abortada: ROLLBACK para volver a usar la sesión")
        )
        self.rollback_button.hide()
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.rollback_button)
        buttons.addStretch(1)
        card_layout.addLayout(buttons)
        self.engine_label = _secondary(QLabel())
        card_layout.addWidget(self.engine_label)
        return card

    def _build_databases_card(self) -> QFrame:
        """Bases de la sesión y sus esquemas, tablas y vistas (GD-CAT-001)."""
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)
        card_layout.addWidget(self._bold(QLabel(tr("Bases de datos"))))
        self.open_button = QPushButton(tr("Abrir existente…"))
        self.open_button.setToolTip(tr("Adjunta un archivo DuckDB existente; nunca crea uno"))
        self.create_button = QPushButton(tr("Crear nueva…"))
        self.create_button.setToolTip(tr("Crea un archivo DuckDB nuevo; nunca sobrescribe uno existente"))
        self.detach_button = QPushButton(tr("Desadjuntar"))
        self.detach_button.setToolTip(tr("Desadjunta la base seleccionada y libera el archivo"))
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.create_button)
        buttons.addStretch(1)
        buttons.addWidget(self.detach_button)
        card_layout.addLayout(buttons)
        self.explorer = CatalogExplorer()
        card_layout.addWidget(self.explorer, 1)
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
        self._coordinator.request_close()

    def _attach(self, action: OpenAction) -> None:
        request = self._ask_attach_request(action, self)
        if request is None:
            return
        self.message_label.hide()
        if self._coordinator.can_start:
            self._coordinator.start_file_session(request)  # StartSession(mode=file)
        else:
            self._coordinator.attach_database(request)

    def _detach(self) -> None:
        name = self.explorer.selected_database()
        if name is not None:
            self.message_label.hide()
            self._coordinator.detach_database(name)

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
        self.sql_panel.detach()

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
        elif isinstance(event, CatalogChanged):
            self.explorer.show_catalog(event.catalog)
            self._render(self._coordinator.state)
        elif isinstance(event, CatalogUnavailable):
            self._show_message(tr("No se pudo leer el catálogo."), event.code.value, event.message)
        elif isinstance(event, DatabaseAttached):
            self.explorer.select_database(event.database.name)
        elif isinstance(event, DatabaseDetached):
            self._render(self._coordinator.state)
        elif isinstance(event, AttachFailed):
            self._show_message(tr("No se adjuntó la base."), event.code.value, event.message)
        elif isinstance(event, DetachFailed):
            self._show_message(tr("No se desadjuntó la base."), event.code.value, event.message)
        elif isinstance(event, CloseConfirmationRequired):
            self._coordinator.resolve_close(self._ask_close_choice(event, self))
        elif isinstance(event, SessionInvalidated):
            self.message_label.setText(
                tr("Sesión invalidada:")
                + f" {event.message} [{event.code.value}] "
                + tr("Inicie una sesión nueva o cierre.")
            )
            self.message_label.show()
        elif isinstance(event, TransactionFailed):
            self.message_label.setText(
                tr("No se completó la operación sobre la transacción.")
                + f" [{event.code.value}] {event.message}"
            )
            self.message_label.show()
        elif isinstance(event, SessionFailed):
            self.message_label.setText(
                tr("No se pudo completar la operación.") + f" [{event.code.value}] {event.message}"
            )
            self.message_label.show()

    def _show_plain_message(self, text: str) -> None:
        self.message_label.setText(text)
        self.message_label.show()

    def _show_message(self, summary: str, code: str, detail: str) -> None:
        self.message_label.setText(f"{summary} [{code}] {detail}")
        self.message_label.show()

    def _render(self, state: SessionState) -> None:
        env_ok = self._report is None or self._report.ok
        can_start = env_ok and self._coordinator.can_start
        ready = state is SessionState.READY
        self.state_label.setText(tr(STATE_TEXT[state]))
        self.start_button.setEnabled(can_start)
        aborted = (
            state is SessionState.ERROR_RECOVERABLE
            and self._coordinator.error_cause is ErrorCause.TRANSACTION_ABORTED
        )
        self.rollback_button.setVisible(aborted)
        self.open_button.setEnabled(can_start or ready)
        self.create_button.setEnabled(can_start or ready)
        selected = self.explorer.selected_database()
        catalog = self._coordinator.catalog
        self.detach_button.setEnabled(
            ready and selected is not None and catalog is not None and not catalog.is_root(selected)
        )
        self.close_button.setEnabled(state in _CAN_CLOSE)
        if state is SessionState.DISCONNECTED:
            self.engine_label.setText(tr("Sin sesión activa."))
