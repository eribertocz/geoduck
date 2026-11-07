# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL de Workspace Pro: el `QgsCodeEditorSQL` de QGIS con los colores de GeoDuck (workspace-pro-spec
§5, §10).

El editor de QGIS usa su propio esquema de colores, que no sigue el tema de la interfaz: con GeoDuck en oscuro
quedaba blanco. Los colores se ponen **en este editor** (su lexer y sus márgenes, API de QScintilla), nunca en
las opciones de QGIS (ADR-0011). `QgsCodeEditor.setCustomAppearance` no está en Python.
"""

from __future__ import annotations

import contextlib
from typing import Any

from qgis.PyQt.QtCore import QEvent, QObject
from qgis.PyQt.QtGui import QColor, QFont

from geoduck.ui.pro.drag import LAYERS_MIME
from geoduck.ui.pro.tokens import Colors

#: Estilos del lexer SQL que se colorean (los demás quedan con el color del texto).
_STYLES = {
    "comment": ("Comment", "CommentLine", "CommentDoc", "CommentLineHash"),
    "keyword": ("Keyword",),
    "string": ("SingleQuotedString", "DoubleQuotedString"),
    "number": ("Number",),
}


def paint(editor: Any, colors: Colors, *, dark: bool) -> None:
    """Fondo, texto, márgenes, cursor, selección y resaltado del SQL con los tokens del tema."""
    background, text = QColor(colors.bg), QColor(colors.text)
    tones = {
        "comment": QColor(colors.faint),
        "keyword": QColor(colors.accent),
        "string": QColor("#7fc58a" if dark else "#1a7f45"),
        "number": QColor("#e8a35c" if dark else "#955b00"),
    }
    lexer = editor.lexer()
    font = _monospace()
    if lexer is not None:
        lexer.setDefaultPaper(background)
        lexer.setDefaultColor(text)
        lexer.setDefaultFont(font)
        for style in range(128):
            if lexer.description(style):
                lexer.setPaper(background, style)
                lexer.setColor(text, style)
                lexer.setFont(font, style)  # la hoja de GeoDuck pone su fuente a todo widget (Qt 5): aquí no
        with contextlib.suppress(ImportError, AttributeError):
            from qgis.PyQt.Qsci import QsciLexerSQL  # noqa: PLC0415 - QScintilla, solo para el color

            for tone, names in _STYLES.items():
                for name in names:
                    style = getattr(QsciLexerSQL, name, None)
                    if style is not None:
                        lexer.setColor(tones[tone], style)
    editor.setMarginsFont(font)
    editor.setMarginsBackgroundColor(QColor(colors.side))
    editor.setMarginsForegroundColor(QColor(colors.faint))
    editor.setCaretForegroundColor(text)
    editor.setCaretLineBackgroundColor(QColor(colors.segment))
    editor.setSelectionBackgroundColor(QColor(colors.selection))
    editor.setSelectionForegroundColor(text)
    editor.setFoldMarginColors(QColor(colors.side), QColor(colors.side))


def _monospace() -> QFont:
    """La monoespaciada de GeoDuck, la misma familia y tamaño que su hoja de estilos pone al editor: si no
    coinciden, QScintilla mide el texto con una fuente y lo dibuja con otra, y las letras se montan."""
    from geoduck.ui.pro.style import EDITOR_POINTS, first_family  # noqa: PLC0415
    from geoduck.ui.pro.tokens import MONO_FAMILIES  # noqa: PLC0415

    font = QFont(first_family(MONO_FAMILIES))  # en puntos: QScintilla no admite tamaños en píxeles
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(EDITOR_POINTS)
    return font


def free_keys(editor: Any, keys: tuple[str, ...]) -> None:
    """Quita esas teclas de los comandos de QScintilla de este editor (p. ej. Ctrl+Intro), para que lleguen
    a los atajos de GeoDuck. Solo en los editores de GeoDuck."""
    from qgis.PyQt.QtGui import QKeySequence  # noqa: PLC0415

    commands = editor.standardCommands()
    for key in keys:
        sequence = QKeySequence(key)
        code = int(sequence[0].toCombined()) if hasattr(sequence[0], "toCombined") else int(sequence[0])
        command = commands.boundTo(code)
        if command is not None:
            if command.key() == code:
                command.setKey(0)
            else:
                command.setAlternateKey(0)


class _LayerDrops(QObject):
    """Capas de QGIS arrastradas al editor: el editor no las toma como texto (las «movía» y QGIS las borraba,
    observación del propietario, 2026-11-06); siguen a GeoDuck, que las añade a DuckDB como en cualquier otra
    parte (workspace-pro-spec §9), siempre como copia."""

    _KINDS = (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop)

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        if event.type() in self._KINDS and event.mimeData().hasFormat(LAYERS_MIME):
            event.ignore()  # sin aceptar: Qt la pasa al contenedor (el área de trabajo)
            return True
        return False


#: Marcador (QScintilla) de la sentencia que correrá «Ejecutar», en un margen fino a la izquierda del texto.
MARK = 20
_MARK_MARGIN = 1


def prepare_mark(editor: Any, colors: Colors) -> None:
    """Un margen de 4 px con una barra del color de acento (workspace-pro-spec §5)."""
    from qgis.PyQt.Qsci import QsciScintilla  # noqa: PLC0415

    editor.setMarginType(_MARK_MARGIN, QsciScintilla.MarginType.SymbolMargin)
    editor.setMarginWidth(_MARK_MARGIN, 4)
    editor.setMarginMarkerMask(_MARK_MARGIN, editor.marginMarkerMask(_MARK_MARGIN) | (1 << MARK))
    editor.markerDefine(QsciScintilla.MarkerSymbol.FullRectangle, MARK)
    editor.setMarkerBackgroundColor(QColor(colors.accent), MARK)
    editor.setMarkerForegroundColor(QColor(colors.accent), MARK)


def mark_lines(editor: Any, lines: tuple[int, int] | None) -> None:
    """Marca las líneas `lines` (primera y última, incluidas); `None` quita la marca."""
    editor.markerDeleteAll(MARK)
    if lines is not None:
        for line in range(lines[0], lines[1] + 1):
            editor.markerAdd(line, MARK)


def make(colors: Colors, *, dark: bool) -> Any:
    """Un `QgsCodeEditorSQL` de GeoDuck: números de línea, sin marco, colores del tema y los atajos de la
    consulta libres (Ctrl+Intro, Ctrl+Mayús+Intro, Ctrl+S, Ctrl+O, Ctrl+W)."""
    from qgis.gui import QgsCodeEditorSQL  # noqa: PLC0415
    from qgis.PyQt.QtWidgets import QFrame  # noqa: PLC0415

    editor = QgsCodeEditorSQL()
    editor.setLineNumbersVisible(True)
    editor.setFrameShape(QFrame.Shape.NoFrame)
    free_keys(editor, ("Ctrl+Return", "Ctrl+Shift+Return", "Ctrl+S", "Ctrl+O", "Ctrl+W", "Ctrl+T"))
    paint(editor, colors, dark=dark)
    editor.layer_drops = _LayerDrops(editor)
    editor.viewport().installEventFilter(editor.layer_drops)
    return editor
