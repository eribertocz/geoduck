# SPDX-License-Identifier: GPL-2.0-or-later
"""Diálogo «Abrir base DuckDB» / «Crear base DuckDB» (G1 paso 8; session-spec §2; G5 E4b).

Construye una `AttachRequest`; las comprobaciones de archivo las hace el motor en su operación serial. El
diálogo solo avisa antes (archivo que no existe al abrir, o que ya existe al crear), sin crear ni tocar nada.

Decisiones del propietario (2026-11-02): casilla «Solo lectura», marcada por defecto; etiqueta «Alias»
con el alias por defecto a la vista. «Crear» no muestra acceso: una base nueva siempre es de lectura y
escritura, y GeoDuck nunca sobrescribe un archivo (el motor lo rechaza igualmente).

Acceso según DuckDB 2.0 (docs «Concurrency»): en lectura y escritura un solo proceso usa la base; en solo
lectura varios procesos pueden leerla y ninguno escribir.
"""

from __future__ import annotations

import os

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
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
READ_ONLY_HELP = "Varios programas pueden abrirla a la vez; ninguno puede modificarla."
READ_WRITE_HELP = "Solo GeoDuck podrá abrir el archivo mientras esté adjunto."


def default_alias(path: str) -> str:
    """El alias que DuckDB usará si no se escribe otro: el nombre del archivo sin extensión."""
    name = os.path.basename(path.strip().rstrip("\\/"))
    stem, dot, _ext = name.rpartition(".")
    return stem if dot and stem else name


class AttachDialog(QDialog):
    def __init__(self, action: OpenAction, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._action = action
        self.request: AttachRequest | None = None
        self.creating = action is OpenAction.CREATE_NEW
        self.setWindowTitle(tr("Crear base DuckDB") if self.creating else tr("Abrir base DuckDB"))
        self.setMinimumWidth(480)

        form = self._build_fields()
        self.error_label = QLabel()
        self.error_label.setProperty("geoduck", "error-text")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        buttons = self._build_buttons()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        if self.creating:
            note = QLabel(
                tr("Se crea un archivo nuevo, en lectura y escritura. Nunca se sobrescribe uno existente.")
            )
            note.setProperty("geoduck", "muted")
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self.path_edit.textChanged.connect(self._refresh)
        self.readonly_check.toggled.connect(self._refresh)
        self._refresh()

    def _build_fields(self) -> QFormLayout:
        self.path_edit = QLineEdit()
        self.path_edit.setAccessibleName(tr("Ruta del archivo"))
        self.path_edit.setPlaceholderText(
            tr("Dónde crear el archivo .duckdb") if self.creating else tr("Archivo .duckdb")
        )
        browse = QPushButton(tr("Examinar…"))
        browse.setProperty("geoduck", "secondary")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        self.path_hint = QLabel()
        self.path_hint.setProperty("geoduck", "error-text")
        self.path_hint.setWordWrap(True)
        self.path_hint.hide()

        self.readonly_check = QCheckBox(tr("Solo lectura"))
        self.readonly_check.setChecked(True)
        self.access_help = QLabel()
        self.access_help.setProperty("geoduck", "muted")
        self.access_help.setWordWrap(True)

        self.alias_edit = QLineEdit()
        self.alias_edit.setAccessibleName(tr("Alias de la base"))
        self.alias_edit.setToolTip(tr("Nombre de la base en SQL; si lo deja vacío, el del archivo"))

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow(tr("Archivo"), path_row)
        form.addRow("", self.path_hint)
        if not self.creating:
            form.addRow("", self.readonly_check)
            form.addRow("", self.access_help)
        form.addRow(tr("Alias"), self.alias_edit)
        return form

    def _build_buttons(self) -> QHBoxLayout:
        self.ok_button = QPushButton(tr("Crear") if self.creating else tr("Abrir"))
        self.ok_button.setProperty("geoduck", "primary")
        self.ok_button.setDefault(True)
        cancel = QPushButton(tr("Cancelar"))
        cancel.setProperty("geoduck", "secondary")
        self.ok_button.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok_button)
        return buttons

    @property
    def access(self) -> AccessMode:
        if self.creating or not self.readonly_check.isChecked():
            return AccessMode.READ_WRITE
        return AccessMode.READ_ONLY

    def _refresh(self) -> None:
        path = self.path_edit.text().strip()
        alias = default_alias(path) if path else ""
        self.alias_edit.setPlaceholderText(alias or tr("El nombre del archivo, si lo deja vacío"))
        self.access_help.setText(
            tr(READ_ONLY_HELP) if self.access is AccessMode.READ_ONLY else tr(READ_WRITE_HELP)
        )
        problem = ""  # aviso previo; el motor vuelve a comprobarlo en su operación serial
        if path and self.creating and os.path.exists(path):
            problem = tr("Ya existe un archivo con ese nombre: GeoDuck no lo sobrescribe.")
        elif path and not self.creating and not os.path.isfile(path):
            problem = tr("No se encuentra el archivo.")
        self.path_hint.setText(problem)
        self.path_hint.setVisible(bool(problem))
        self.ok_button.setEnabled(bool(path) and not problem)

    def _browse(self) -> None:
        if self.creating:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("Crear base DuckDB"), "", _FILTER, options=QFileDialog.Option.DontConfirmOverwrite
            )
        else:
            path, _ = QFileDialog.getOpenFileName(self, tr("Abrir base DuckDB"), "", _FILTER)
        if path:
            self.path_edit.setText(path)

    def build_request(self) -> AttachRequest:
        alias = self.alias_edit.text().strip() or None
        return AttachRequest(self.path_edit.text().strip(), self.access, self._action, alias)

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
