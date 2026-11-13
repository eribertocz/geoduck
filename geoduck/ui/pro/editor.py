# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL de Workspace Pro: el `QgsCodeEditorSQL` de QGIS con los colores de GeoDuck (workspace-pro-spec
§5, §10).

El editor de QGIS usa su propio esquema de colores, que no sigue el tema de la interfaz: con GeoDuck en oscuro
quedaba blanco. Los colores se ponen **en este editor** (su lexer y sus márgenes, API de QScintilla), nunca en
las opciones de QGIS (ADR-0011). `QgsCodeEditor.setCustomAppearance` no está en Python.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtGui import QColor, QFont

from geoduck.domain.files import editor_readable
from geoduck.ui.pro.drag import LAYERS_MIME, file_paths
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
    """Quita esas teclas de los comandos de QScintilla de este editor para que lleguen
    a los atajos de GeoDuck (p. ej. Ctrl+Enter). Solo en los editores de GeoDuck."""
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

    def __init__(self, editor: Any) -> None:
        super().__init__(editor)
        self._editor = editor
        #: Archivos soltados en el editor (los pone la página de consulta): devuelve si los tomó.
        self.on_files: Callable[[list[str]], bool] | None = None

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        if event.type() not in self._KINDS:
            return False
        data = event.mimeData()
        if data.hasFormat(LAYERS_MIME):
            event.ignore()  # sin aceptar: Qt la pasa al contenedor (el área de trabajo, que abre el diálogo)
            return True
        paths = file_paths(data)
        if not paths:
            return False
        # Archivos en el editor (decisión del propietario, 2026-11-07): llevarlos a DuckDB con SQL sin
        # ejecutarlo. Si ninguno se lee con SQL (Arrow, no compatibles), siguen al área de trabajo.
        if self.on_files is None or not any(editor_readable(p) for p in paths):
            event.ignore()
            return True
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if event.type() == QEvent.Type.Drop:
            self.on_files(paths)
        return True


def insert_sql(editor: Any, text: str) -> None:
    """Escribe `text` donde está el cursor: si la línea ya tiene texto, después de ella y con una línea en
    blanco, para que cada sentencia quede aparte. El cursor queda en la primera sentencia escrita."""
    line, _index = editor.getCursorPosition()
    current = editor.text(line).rstrip("\r\n") if line < editor.lines() else ""
    if current.strip():
        editor.setCursorPosition(line, len(current))
        text = "\n\n" + text
        line += 2
    editor.insert(text + "\n")
    editor.setCursorPosition(line, 0)
    editor.setFocus()


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


#: ▶ en el margen, junto a la sentencia marcada (propietario, 2026-11-12): un clic la ejecuta.
PLAY = 19  # 25–31 son de los pliegues de Scintilla; 20–24, de la marca y de los estados
_PLAY_MARGIN = 3


def prepare_play(editor: Any, colors: Colors, on_click: Any) -> None:
    """Un margen angosto con ▶ en la primera línea de la sentencia marcada; `on_click(line)` al pulsarlo."""
    from qgis.PyQt.Qsci import QsciScintilla  # noqa: PLC0415

    from geoduck.ui.pro import icons  # noqa: PLC0415

    editor.setMarginType(_PLAY_MARGIN, QsciScintilla.MarginType.SymbolMargin)
    editor.setMarginWidth(_PLAY_MARGIN, 16)
    editor.setMarginMarkerMask(_PLAY_MARGIN, 1 << PLAY)
    for margin in (m for m in range(_STATUS_MARGIN + 1) if m != _PLAY_MARGIN):  # el ▶, solo en su margen
        editor.setMarginMarkerMask(margin, editor.marginMarkerMask(margin) & ~(1 << PLAY))
    editor.setMarginSensitivity(_PLAY_MARGIN, True)
    # a escala 1: QScintilla pinta el mapa de bits a su tamaño real, sin la densidad de la pantalla
    editor.markerDefine(icons.pixmap("play", colors.accent, 11, scale=1.0), PLAY)
    editor.marginClicked.connect(
        lambda margin, line, _keys: on_click(line) if margin == _PLAY_MARGIN else None
    )


def mark_play(editor: Any, line: int | None) -> None:
    editor.markerDeleteAll(PLAY)
    if line is not None:
        editor.markerAdd(line, PLAY)


def mark_lines(editor: Any, lines: tuple[int, int] | None) -> None:
    """Marca las líneas `lines` (primera y última, incluidas); `None` quita la marca."""
    editor.markerDeleteAll(MARK)
    if lines is not None:
        for line in range(lines[0], lines[1] + 1):
            editor.markerAdd(line, MARK)


#: Estado de cada sentencia tras ejecutar (#139): ✓, ✕ o – en un margen junto al texto; la línea del error con
#: fondo rojizo y la palabra subrayada con una onda.
OK_MARK, ERROR_MARK, SKIPPED_MARK, ERROR_LINE = 21, 22, 23, 24
_STATUS_MARGIN = 4
_ERROR_INDICATOR = 20
_SCI_SETMOUSEDWELLTIME = 2264
_DWELL_MS = 400


def _symbol(text: str, color: str, size: int) -> Any:
    from qgis.PyQt.QtGui import QPainter, QPixmap  # noqa: PLC0415

    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont()
    font.setPixelSize(max(9, size - 4))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(pixmap.rect(), int(Qt.AlignmentFlag.AlignCenter), text)
    painter.end()
    return pixmap


class StatusMarks(QObject):
    """Las marcas de la última ejecución en el editor: `show()` las pone, `clear()` las quita. Al pasar el
    ratón por la palabra del error se ve su mensaje."""

    def __init__(self, editor: Any, colors: Colors) -> None:
        from qgis.PyQt.Qsci import QsciScintilla  # noqa: PLC0415

        super().__init__(editor)
        self._editor = editor
        self._errors: list[tuple[int, int, str]] = []  # (inicio, fin) en caracteres y mensaje
        height = max(12, editor.fontMetrics().height())
        editor.setMarginType(_STATUS_MARGIN, QsciScintilla.MarginType.SymbolMargin)
        editor.setMarginWidth(_STATUS_MARGIN, 0)
        editor.setMarginSensitivity(_STATUS_MARGIN, False)
        mask = (1 << OK_MARK) | (1 << ERROR_MARK) | (1 << SKIPPED_MARK)
        editor.setMarginMarkerMask(_STATUS_MARGIN, mask)
        for margin in range(_STATUS_MARGIN):  # los símbolos solo en su margen
            editor.setMarginMarkerMask(margin, editor.marginMarkerMask(margin) & ~mask)
        self._width = height + 4
        editor.markerDefine(_symbol("✓", colors.ok, height), OK_MARK)
        editor.markerDefine(_symbol("✕", colors.error, height), ERROR_MARK)
        editor.markerDefine(_symbol("–", colors.faint, height), SKIPPED_MARK)
        editor.markerDefine(QsciScintilla.MarkerSymbol.Background, ERROR_LINE)
        tint = QColor(colors.error)
        tint.setAlpha(28)
        editor.setMarkerBackgroundColor(tint, ERROR_LINE)
        editor.indicatorDefine(QsciScintilla.IndicatorStyle.SquiggleIndicator, _ERROR_INDICATOR)
        editor.setIndicatorForegroundColor(QColor(colors.error), _ERROR_INDICATOR)
        editor.SendScintilla(_SCI_SETMOUSEDWELLTIME, _DWELL_MS)
        editor.SCN_DWELLSTART.connect(self._dwell)
        editor.SCN_DWELLEND.connect(self._dwell_end)

    @property
    def shown(self) -> bool:
        return self._editor.marginWidth(_STATUS_MARGIN) > 0

    def show(self, marks: list[tuple[int, int]], errors: list[tuple[int, int, str]]) -> None:
        """`marks`: (línea, marcador) por sentencia; `errors`: (inicio, fin, mensaje) en caracteres."""
        self.clear()
        editor = self._editor
        for line, marker in marks:
            editor.markerAdd(line, marker)
        text = editor.text()
        for start, end, _message in errors:
            line, index = _line_index(text, start)
            last, last_index = _line_index(text, max(start + 1, end))
            editor.markerAdd(line, ERROR_LINE)
            editor.fillIndicatorRange(line, index, last, last_index, _ERROR_INDICATOR)
        self._errors = list(errors)
        editor.setMarginWidth(_STATUS_MARGIN, self._width if marks or errors else 0)

    def clear(self) -> None:
        editor = self._editor
        for marker in (OK_MARK, ERROR_MARK, SKIPPED_MARK, ERROR_LINE):
            editor.markerDeleteAll(marker)
        lines = max(1, editor.lines())
        editor.clearIndicatorRange(0, 0, lines - 1, len(editor.text(lines - 1)), _ERROR_INDICATOR)
        editor.setMarginWidth(_STATUS_MARGIN, 0)
        self._errors = []

    def message_at(self, position: int) -> str:
        """El mensaje del error en esa posición del texto (caracteres), o vacío."""
        for start, end, message in self._errors:
            if start <= position <= max(start + 1, end):
                return message
        return ""

    def _dwell(self, position: int, x: int, y: int) -> None:
        from qgis.PyQt.QtCore import QPoint  # noqa: PLC0415
        from qgis.PyQt.QtWidgets import QToolTip  # noqa: PLC0415

        if position < 0 or not self._errors:
            return
        line, index = self._editor.lineIndexFromPosition(position)
        message = self.message_at(_offset(self._editor.text(), line, index))
        if message:
            QToolTip.showText(self._editor.viewport().mapToGlobal(QPoint(x, y)), message, self._editor)

    def _dwell_end(self, *_args: int) -> None:
        from qgis.PyQt.QtWidgets import QToolTip  # noqa: PLC0415

        QToolTip.hideText()


def _line_index(text: str, offset: int) -> tuple[int, int]:
    before = text[:offset]
    line = before.count("\n")
    return line, offset - (before.rfind("\n") + 1)


def _offset(text: str, line: int, index: int) -> int:
    lines = text.split("\n")
    return sum(len(t) + 1 for t in lines[:line]) + index


class RunKeys(QObject):
    """Ctrl+Enter y Ctrl+Shift+Enter en el editor (#139). El editor las toma antes que cualquier atajo (de
    QGIS o de otro complemento con la misma tecla, que dejaría el atajo ambiguo y sin efecto) y cierra la
    lista de autocompletado si está abierta: así «Ejecutar» funciona siempre que se escribe. Esc, solo
    mientras `cancel()` diga que hay algo que cancelar (#143): el resto del tiempo, Esc es del editor."""

    _KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)

    def __init__(
        self, editor: Any, run: Callable[[bool], None], cancel: Callable[[], bool] | None = None
    ) -> None:
        super().__init__(editor)
        self._editor = editor
        self._run = run
        self._cancel = cancel

    def _wanted(self, event: Any) -> bool:
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        others = modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)
        return control and not others and event.key() in self._KEYS

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        kind = event.type()
        if kind not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self._cancel is not None:
            return self._cancel()  # True: había algo que cancelar y la tecla se usó
        if not self._wanted(event):
            return False
        event.accept()
        if kind == QEvent.Type.ShortcutOverride:
            return True  # el editor recibirá la tecla: ningún atajo la toma antes
        if event.isAutoRepeat():
            return True
        editor = self._editor
        with contextlib.suppress(AttributeError):
            if editor.isListActive():
                editor.cancelList()
            if editor.isCallTipActive():
                editor.cancelCallTip()
        self._run(bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        return True


def make(colors: Colors, *, dark: bool) -> Any:
    """Un `QgsCodeEditorSQL` de GeoDuck: números de línea, sin marco, colores del tema y los atajos de la
    consulta libres (Ctrl+Enter, Ctrl+Shift+Enter, Ctrl+S, Ctrl+O, Ctrl+W) y las marcas de la última
    ejecución (`editor.status`)."""
    from qgis.gui import QgsCodeEditorSQL  # noqa: PLC0415
    from qgis.PyQt.QtWidgets import QFrame  # noqa: PLC0415

    editor = QgsCodeEditorSQL()
    editor.setLineNumbersVisible(True)
    editor.setFrameShape(QFrame.Shape.NoFrame)
    free_keys(editor, ("Ctrl+Return", "Ctrl+Shift+Return", "Ctrl+S", "Ctrl+O", "Ctrl+W", "Ctrl+T", "Ctrl+J"))
    paint(editor, colors, dark=dark)
    editor.layer_drops = _LayerDrops(editor)
    editor.viewport().installEventFilter(editor.layer_drops)
    editor.status = StatusMarks(editor, colors)
    return editor
