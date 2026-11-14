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
from geoduck.ui.i18n import N_, tr

READ_ONLY_HELP = N_("Several programs can open it at the same time; none can modify it.")
READ_WRITE_HELP = N_("Only GeoDuck can open the file while it is attached.")


def _file_filter() -> str:
    return tr("Database") + " (*.duckdb *.ddb *.db);;" + tr("All files") + " (*)"


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
        self.setWindowTitle(tr("Create database") if self.creating else tr("Open database"))
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
            note = QLabel(tr("A new file is created, read-write. An existing file is never overwritten."))
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
        self.path_edit.setAccessibleName(tr("File path"))
        self.path_edit.setPlaceholderText(
            tr("Where to create the .duckdb file") if self.creating else tr(".duckdb file")
        )
        browse = QPushButton(tr("Browse…"))
        browse.setProperty("geoduck", "secondary")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        self.path_hint = QLabel()
        self.path_hint.setProperty("geoduck", "error-text")
        self.path_hint.setWordWrap(True)
        self.path_hint.hide()

        self.readonly_check = QCheckBox(tr("Read only"))
        self.readonly_check.setChecked(True)
        self.access_help = QLabel()
        self.access_help.setProperty("geoduck", "muted")
        self.access_help.setWordWrap(True)

        self.alias_edit = QLineEdit()
        self.alias_edit.setAccessibleName(tr("Database alias"))
        self.alias_edit.setToolTip(tr("Name of the database in SQL; if left empty, the file name"))

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.addRow(tr("File"), path_row)
        form.addRow("", self.path_hint)
        if not self.creating:
            form.addRow("", self.readonly_check)
            form.addRow("", self.access_help)
        form.addRow(tr("Alias"), self.alias_edit)
        return form

    def _build_buttons(self) -> QHBoxLayout:
        self.ok_button = QPushButton(tr("Create") if self.creating else tr("Open"))
        self.ok_button.setProperty("geoduck", "primary")
        self.ok_button.setDefault(True)
        cancel = QPushButton(tr("Cancel"))
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
        self.alias_edit.setPlaceholderText(alias or tr("The file name, if left empty"))
        self.access_help.setText(
            tr(READ_ONLY_HELP) if self.access is AccessMode.READ_ONLY else tr(READ_WRITE_HELP)
        )
        problem = ""  # aviso previo; el motor vuelve a comprobarlo en su operación serial
        if path and self.creating and os.path.exists(path):
            problem = tr("A file with that name already exists: GeoDuck does not overwrite it.")
        elif path and not self.creating and not os.path.isfile(path):
            problem = tr("The file cannot be found.")
        self.path_hint.setText(problem)
        self.path_hint.setVisible(bool(problem))
        self.ok_button.setEnabled(bool(path) and not problem)

    def _browse(self) -> None:
        if self.creating:
            path, _ = QFileDialog.getSaveFileName(
                self,
                tr("Create database"),
                "",
                _file_filter(),
                options=QFileDialog.Option.DontConfirmOverwrite,
            )
        else:
            path, _ = QFileDialog.getOpenFileName(self, tr("Open database"), "", _file_filter())
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
