# SPDX-License-Identifier: GPL-2.0-or-later
"""Diálogo «Abrir existente» / «Crear nueva» (G1 paso 8; session-spec §2).

Construye una `AttachRequest`; las comprobaciones de archivo las hace el motor en su operación serial.
«Crear nueva» solo admite lectura y escritura, y el selector de archivos no ofrece sobrescribir: GeoDuck
nunca sobrescribe (el motor lo rechaza igualmente).
"""

from __future__ import annotations

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from geoduck.domain.catalog import AccessMode, AttachRequest, OpenAction
from geoduck.domain.errors import InvalidArgumentError
from geoduck.ui.i18n import tr

_FILTER = "DuckDB (*.duckdb *.ddb *.db);;Todos los archivos (*)"


class AttachDialog(QDialog):
    def __init__(self, action: OpenAction, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._action = action
        self.request: AttachRequest | None = None
        creating = action is OpenAction.CREATE_NEW
        self.setWindowTitle(
            tr("GeoDuck — Crear base nueva") if creating else tr("GeoDuck — Abrir base existente")
        )

        self.path_edit = QLineEdit()
        self.path_edit.setAccessibleName(tr("Ruta del archivo"))
        browse = QPushButton(tr("Examinar…"))
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)

        self.access_combo = QComboBox()
        self.access_combo.addItem(tr("Solo lectura"), AccessMode.READ_ONLY)
        self.access_combo.addItem(tr("Lectura y escritura"), AccessMode.READ_WRITE)
        if creating:
            self.access_combo.setCurrentIndex(1)
            self.access_combo.setEnabled(False)  # «Crear nueva» solo en RW

        self.alias_edit = QLineEdit()
        self.alias_edit.setPlaceholderText(tr("Nombre del archivo sin extensión"))
        self.alias_edit.setAccessibleName(tr("Alias de la base"))

        form = QFormLayout()
        form.addRow(tr("Archivo"), path_row)
        form.addRow(tr("Acceso"), self.access_combo)
        form.addRow(tr("Alias"), self.alias_edit)

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(tr("Crear") if creating else tr("Abrir"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        if creating:
            note = QLabel(tr("Se crea un archivo nuevo. Si ya existe uno con ese nombre, no se sobrescribe."))
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        if self._action is OpenAction.CREATE_NEW:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("Crear base nueva"), "", _FILTER, options=QFileDialog.Option.DontConfirmOverwrite
            )
        else:
            path, _ = QFileDialog.getOpenFileName(self, tr("Abrir base existente"), "", _FILTER)
        if path:
            self.path_edit.setText(path)

    def build_request(self) -> AttachRequest:
        alias = self.alias_edit.text().strip() or None
        return AttachRequest(
            self.path_edit.text().strip(), self.access_combo.currentData(), self._action, alias
        )

    def _accept(self) -> None:
        try:
            self.request = self.build_request()
        except InvalidArgumentError as exc:
            self.error_label.setText(exc.message)
            self.error_label.show()
            return  # el diálogo sigue abierto para corregir
        self.accept()

    @classmethod
    def ask(cls, action: OpenAction, parent: QWidget | None = None) -> AttachRequest | None:
        dialog = cls(action, parent)
        return dialog.request if dialog.exec() else None
