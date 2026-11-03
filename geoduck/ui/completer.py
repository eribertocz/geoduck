# SPDX-License-Identifier: GPL-2.0-or-later
"""Autocompletado del editor SQL (G6 · E2, GD-SQL-007, AT-SQL-007; sql-editor-spec §7, ui-ux-spec §9).

Usa la lista de usuario de QScintilla: GeoDuck decide qué sugerir (`geoduck.domain.completion`) y qué texto
insertar; aceptar solo escribe en el editor, nunca ejecuta. Se abre sola al escribir dos letras de un nombre o
un `.`, y con Ctrl+Espacio; Escape la cierra; Intro o Tab aceptan solo con la lista abierta. El
autocompletado propio de `QgsCodeEditorSQL` se desactiva para que no haya dos listas.
"""

from __future__ import annotations

from typing import Any

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QObject, Qt
from qgis.PyQt.QtGui import QKeySequence
from qgis.PyQt.QtWidgets import QShortcut

from geoduck.app.coordinator import SessionCoordinator
from geoduck.domain.completion import Completion, Kind, complete
from geoduck.ui.widgets import offset_from

#: Identificador de la lista de usuario de QScintilla (cualquiera > 0).
LIST_ID = 7
#: Imagen de cada tipo de sugerencia en la lista (iconos de QGIS, comprobados en 3.34 y 4.2).
ICONS = {
    Kind.COLUMN: "mIconFieldText.svg",
    Kind.TABLE: "mIconTableLayer.svg",
    Kind.VIEW: "mIconVirtualLayer.svg",
    Kind.SCHEMA: "mIconDbSchema.svg",
    Kind.DATABASE: "mIconDbSchema.svg",
    Kind.FUNCTION: "mIconExpression.svg",
}
_IMAGE_ID = {kind: i + 1 for i, kind in enumerate(ICONS)}
_SCI_AUTOCSETORDER = 2660
_SC_ORDER_CUSTOM = 2
_SCI_AUTOCSETTYPESEPARATOR = 2286
_SEPARATOR = "\x1e"  # nunca aparece en un nombre válido de la lista


class SqlCompleter(QObject):
    """Autocompletado de un editor. `editor`: el `QgsCodeEditorSQL` del panel."""

    def __init__(self, editor: Any, coordinator: SessionCoordinator) -> None:
        super().__init__(editor)
        self._editor = editor
        self._coordinator = coordinator
        #: Lista abierta: (prefijo, {etiqueta mostrada: texto a insertar}).
        self._open: tuple[str, dict[str, str]] | None = None
        #: Petición en espera de columnas: explícita o no.
        self._waiting: bool | None = None
        editor.setAutoCompletionSource(type(editor).AutoCompletionSource.AcsNone)
        editor.SendScintilla(_SCI_AUTOCSETORDER, _SC_ORDER_CUSTOM)  # nuestro orden, no el alfabético
        editor.SendScintilla(_SCI_AUTOCSETTYPESEPARATOR, ord(_SEPARATOR))
        for kind, icon in ICONS.items():
            pixmap = QgsApplication.getThemeIcon(icon).pixmap(16, 16)
            editor.registerImage(_IMAGE_ID[kind], pixmap)
        editor.SCN_CHARADDED.connect(self._char_added)
        editor.userListActivated.connect(self._accepted)
        self.shortcut = QShortcut(QKeySequence("Ctrl+Space"), editor)
        self.shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.shortcut.activated.connect(lambda: self.show(explicit=True))

    @property
    def is_open(self) -> bool:
        return bool(self._editor.isListActive())

    def _char_added(self, char: int) -> None:
        ch = chr(char)
        if ch == "." or ch.isalnum() or ch == "_":
            self.show(explicit=False)
        elif self.is_open:
            self._editor.cancelList()

    def _texts(self) -> tuple[str, str]:
        text = self._editor.text()
        line, index = self._editor.getCursorPosition()
        offset = offset_from(text, line, index)
        return text[:offset], text[offset:]

    def compute(self, *, explicit: bool) -> Completion | None:
        """Sugerencias para el cursor actual; pide al worker las columnas que falten (sin esperar)."""
        before, after = self._texts()
        vocabulary = self._coordinator.vocabulary()
        result = complete(
            before,
            catalog=self._coordinator.catalog,
            columns=self._coordinator.known_columns(),
            vocabulary=vocabulary,
            text_after_cursor=after,
            explicit=explicit,
        )
        if result is not None and vocabulary is None:
            self._waiting = explicit  # al llegar el vocabulario, la lista se rehace (y cita bien)
        if result is not None and result.missing:
            self._waiting = explicit
            for source in result.missing:
                try:
                    self._coordinator.list_columns(source)
                except Exception:
                    self._waiting = None
        return result

    def show(self, *, explicit: bool) -> None:
        result = self.compute(explicit=explicit)
        if result is None or not result.items:
            if self.is_open:
                self._editor.cancelList()
            self._open = None
            return
        mapping = {item.label: item.insert for item in result.items}
        entries = [
            f"{item.label}{_SEPARATOR}{_IMAGE_ID[item.kind]}" if item.kind in _IMAGE_ID else item.label
            for item in result.items
        ]
        self._open = (result.prefix, mapping)
        self._editor.showUserList(LIST_ID, entries)

    def refresh(self) -> None:
        """Llegaron columnas o el vocabulario: si se esperaban, la lista se vuelve a calcular."""
        if self._waiting is None or not self._editor.hasFocus():
            return
        explicit, self._waiting = self._waiting, None
        self.show(explicit=explicit)

    def _accepted(self, list_id: int, label: str) -> None:
        if list_id != LIST_ID or self._open is None:
            return
        prefix, mapping = self._open
        self._open = None
        text = mapping.get(label, label)
        line, index = self._editor.getCursorPosition()
        start = index - len(prefix)
        self._editor.setSelection(line, start, line, index)
        self._editor.replaceSelectedText(text)
