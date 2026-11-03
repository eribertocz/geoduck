# SPDX-License-Identifier: GPL-2.0-or-later
"""Diálogo de cierre con una transacción abierta (decisión del 2026-11-01; session-spec §2, CloseSession).

Tres opciones: COMMIT, ROLLBACK o cancelar el cierre. Cancelar no modifica la transacción. Si COMMIT no es
válido (transacción abortada, u operación en curso), el botón está deshabilitado. Cerrar el diálogo con la
tecla Escape o la «X» equivale a cancelar: nunca se confirma ni se descartan cambios sin una elección.
"""

from __future__ import annotations

from qgis.PyQt.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from geoduck.app.events import CloseConfirmationRequired
from geoduck.domain.transaction import CloseChoice, TransactionState
from geoduck.ui.i18n import tr


class CloseTransactionDialog(QDialog):
    def __init__(self, request: CloseConfirmationRequired, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("GeoDuck — Open transaction"))
        self.setModal(True)
        self.choice = CloseChoice.CANCEL

        if request.transaction is TransactionState.ABORTED:
            text = tr(
                "The transaction is aborted. To close the session it must be rolled back (ROLLBACK); "
                "committing it is not possible."
            )
        else:
            text = tr(
                "There is an open transaction. What should happen to its changes before closing the session?"
            )
        message = QLabel(text)
        message.setWordWrap(True)

        self.commit_button = QPushButton(tr("Commit (COMMIT) and close"))
        self.rollback_button = QPushButton(tr("Roll back (ROLLBACK) and close"))
        self.cancel_button = QPushButton(tr("Cancel closing"))
        self.commit_button.setEnabled(request.commit_allowed)
        if not request.commit_allowed:
            self.commit_button.setToolTip(tr("COMMIT is not valid right now"))
        self.cancel_button.setDefault(True)  # la opción por defecto no modifica nada
        self.cancel_button.setAutoDefault(True)
        self.commit_button.setAutoDefault(False)
        self.rollback_button.setAutoDefault(False)

        self.commit_button.clicked.connect(lambda: self._choose(CloseChoice.COMMIT))
        self.rollback_button.clicked.connect(lambda: self._choose(CloseChoice.ROLLBACK))
        self.cancel_button.clicked.connect(lambda: self._choose(CloseChoice.CANCEL))

        buttons = QHBoxLayout()
        buttons.addWidget(self.commit_button)
        buttons.addWidget(self.rollback_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        layout = QVBoxLayout(self)
        layout.addWidget(message)
        layout.addLayout(buttons)

    def _choose(self, choice: CloseChoice) -> None:
        self.choice = choice
        if choice is CloseChoice.CANCEL:
            self.reject()
        else:
            self.accept()

    @classmethod
    def ask(cls, request: CloseConfirmationRequired, parent: QWidget | None = None) -> CloseChoice:
        dialog = cls(request, parent)
        dialog.exec()
        return dialog.choice
