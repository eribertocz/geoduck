# SPDX-License-Identifier: GPL-2.0-or-later
"""El editor SQL moderno (#146, puntos 17, 29 y 30; workspace-pro-spec §5).

`EditorTools` se instala en el `QgsCodeEditorSQL` de una consulta y añade, sin tocar la configuración de QGIS
(ADR-0011): pares y sangría al escribir, comentar, mover y duplicar líneas, varios cursores, formato, ayuda de
parámetros, información al pasar el ratón, Ctrl+clic al explorador, fragmentos, zoom, plegado, ajuste de
línea y desplazamiento horizontal. `FindBar` es la barra de buscar y reemplazar (Ctrl+F / Ctrl+H) y de «Ir a
la línea» (Ctrl+G). Nada de aquí ejecuta SQL del usuario: lo único que se lee de DuckDB es
`duckdb_functions()` para la ayuda de parámetros.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QSettings, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton, QToolTip, QVBoxLayout

from geoduck.domain import sql_edit
from geoduck.domain.completion import Kind, Target, target_at
from geoduck.ui.i18n import tr
from geoduck.ui.pro.tokens import Colors
from geoduck.ui.pro.widgets import button, icon_button, label

# -- mensajes de Scintilla que QScintilla no envuelve -------------------------------------------------
_SCI_GETCURRENTPOS = 2008
_SCI_MARKERSETFORE = 2041
_SCI_MARKERSETBACK = 2042
_SCI_CALLTIPSHOW = 2200
_SCI_CALLTIPCANCEL = 2201
_SCI_CALLTIPACTIVE = 2202
_SCI_SETSCROLLWIDTH = 2274
_SCI_TEXTWIDTH = 2276
_SCI_SETINDICATORCURRENT = 2500
_SCI_INDICATORFILLRANGE = 2504
_SCI_INDICATORCLEARRANGE = 2505
_SCI_SETMULTIPLESELECTION = 2563
_SCI_SETADDITIONALSELECTIONTYPING = 2565
_SCI_SCROLLRANGE = 2569
_SCI_GETSELECTIONS = 2570
_SCI_ADDSELECTION = 2573
_SCI_GETSELECTIONNSTART = 2585
_SCI_GETSELECTIONNEND = 2587
_SCI_SETMULTIPASTE = 2614
_SCI_MOVESELECTEDLINESUP = 2620
_SCI_MOVESELECTEDLINESDOWN = 2621
_SCI_GETLENGTH = 2006
_SCI_POSITIONFROMPOINT = 2022
_SCI_POSITIONFROMPOINTCLOSE = 2023
_SCI_UPPERCASE = 2341
_SCI_LOWERCASE = 2340
_STYLE_DEFAULT = 32

#: Indicadores (8–31 son de los contenedores; 20 es el error de #139/#145).
FIND_INDICATOR = 14
CURRENT_INDICATOR = 15
OCCURRENCE_INDICATOR = 16

#: Opciones del editor guardadas (QSettings de GeoDuck, no de QGIS).
WRAP_KEY = "geoduck/pro/editor_wrap"
UPPER_KEY = "geoduck/pro/editor_upper_keywords"
#: Coincidencias que se marcan como mucho (un texto enorme no se queda pegado).
MAX_MATCHES = 10_000
#: Espera tras escribir para medir el ancho real del texto y marcar las apariciones.
_IDLE_MS = 200


def _bgr(color: str) -> int:
    """Un color para Scintilla (0xBBGGRR)."""
    value = QColor(color)
    return value.red() | (value.green() << 8) | (value.blue() << 16)


def _setting(key: str, default: bool) -> bool:
    value = QSettings().value(key, default)
    return value in (True, "true", "1", 1)


@dataclass(frozen=True)
class Key:
    key: int
    ctrl: bool = False
    shift: bool = False
    alt: bool = False


def _key(event: Any) -> Key:
    mods = event.modifiers()
    return Key(
        int(event.key()),
        bool(mods & Qt.KeyboardModifier.ControlModifier),
        bool(mods & Qt.KeyboardModifier.ShiftModifier),
        bool(mods & Qt.KeyboardModifier.AltModifier),
    )


K = Qt.Key
#: Atajos del editor y su texto en los menús (workspace-pro-spec §5).
SHORTCUTS: dict[str, str] = {
    "find": "Ctrl+F",
    "replace": "Ctrl+H",
    "line": "Ctrl+G",
    "comment": "Ctrl+/",
    "format": "Shift+Alt+F",
    "wrap": "Alt+Z",
    "next": "Ctrl+D",
    "upper": "Ctrl+Shift+U",
    "move": "Alt+↑ / Alt+↓",
    "duplicate": "Shift+Alt+↓",
    "delete": "Ctrl+Shift+K",
    "params": "Ctrl+Shift+Space",
}


def _offsets(text: str) -> list[int]:
    """Dónde empieza cada línea de `text` (en caracteres)."""
    starts = [0]
    for found in re.finditer("\n", text):
        starts.append(found.end())
    return starts


def _line_index(starts: list[int], offset: int) -> tuple[int, int]:
    import bisect  # noqa: PLC0415

    line = bisect.bisect_right(starts, offset) - 1
    return line, offset - starts[line]


class EditorTools(QObject):
    """Teclado, ratón y vista del editor. `lookup()` da (catálogo, columnas, vocabulario) de la sesión;
    `read_rows(sql, n, done)` lee de DuckDB (solo `duckdb_functions()`); `reveal(Target)` lleva una tabla al
    explorador."""

    #: El ajuste de línea o las mayúsculas cambiaron (para el menú).
    options_changed = pyqtSignal()

    def __init__(
        self,
        editor: Any,
        colors: Colors,
        *,
        find_bar: FindBar | None = None,
        lookup: Callable[[], tuple[Any, Any, Any]] | None = None,
        read_rows: Callable[[str, int, Callable[[Any], None]], bool] | None = None,
        reveal: Callable[[Target], None] | None = None,
    ) -> None:
        super().__init__(editor)
        self.editor = editor
        self.colors = colors
        self.find_bar = find_bar
        self._lookup = lookup
        self._read_rows = read_rows
        self._reveal = reveal
        self._signatures: dict[str, list[str]] = {}
        self._asked: set[str] = set()
        self.upper_keywords = _setting(UPPER_KEY, False)
        self._setup_view(colors)
        editor.installEventFilter(self)
        editor.viewport().installEventFilter(self)
        editor.SCN_CHARADDED.connect(self._char_added)
        editor.SCN_DWELLSTART.connect(self._dwell)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(_IDLE_MS)
        self._idle.timeout.connect(self.measure)
        editor.textChanged.connect(self._idle.start)
        self._parameters = QTimer(self)
        self._parameters.setSingleShot(True)
        self._parameters.setInterval(0)
        self._parameters.timeout.connect(self.show_parameters)
        self._occurrences = QTimer(self)
        self._occurrences.setSingleShot(True)
        self._occurrences.setInterval(_IDLE_MS)
        self._occurrences.timeout.connect(self.mark_occurrences)
        editor.selectionChanged.connect(self._occurrences.start)
        self.measure()

    # -- vista ----------------------------------------------------------------------------------------

    def _setup_view(self, colors: Colors) -> None:
        from qgis.PyQt.Qsci import QsciScintilla  # noqa: PLC0415

        editor = self.editor
        editor.setIndentationsUseTabs(False)  # 4 espacios (punto 17)
        editor.setIndentationWidth(len(sql_edit.INDENT))
        editor.setTabWidth(len(sql_edit.INDENT))
        editor.setTabIndents(True)
        editor.setBackspaceUnindents(True)
        editor.setAutoIndent(True)
        editor.setIndentationGuides(True)
        editor.setIndentationGuidesForegroundColor(QColor(colors.line))
        editor.setIndentationGuidesBackgroundColor(QColor(colors.bg))
        editor.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)
        editor.setMatchedBraceBackgroundColor(QColor(colors.selection))
        editor.setMatchedBraceForegroundColor(QColor(colors.accent))
        editor.setUnmatchedBraceForegroundColor(QColor(colors.error))
        editor.setUnmatchedBraceBackgroundColor(QColor(colors.bg))
        editor.setCaretLineVisible(True)  # la línea actual, con el fondo suave de `paint`
        editor.setFolding(QsciScintilla.FoldStyle.BoxedTreeFoldStyle, 2)
        editor.setFoldMarginColors(QColor(colors.side), QColor(colors.side))
        for marker in range(25, 32):  # los marcadores de pliegue (no son de QScintilla): discretos
            editor.SendScintilla(_SCI_MARKERSETFORE, marker, _bgr(colors.bg))
            editor.SendScintilla(_SCI_MARKERSETBACK, marker, _bgr(colors.faint))
        editor.SendScintilla(_SCI_SETMULTIPLESELECTION, 1)
        editor.SendScintilla(_SCI_SETADDITIONALSELECTIONTYPING, 1)
        editor.SendScintilla(_SCI_SETMULTIPASTE, 1)
        for number, style, tone, alpha in (
            (FIND_INDICATOR, QsciScintilla.IndicatorStyle.StraightBoxIndicator, colors.accent, 50),
            (CURRENT_INDICATOR, QsciScintilla.IndicatorStyle.FullBoxIndicator, colors.accent, 110),
            (OCCURRENCE_INDICATOR, QsciScintilla.IndicatorStyle.StraightBoxIndicator, colors.faint, 60),
        ):
            editor.indicatorDefine(style, number)
            color = QColor(tone)
            color.setAlpha(alpha)
            editor.setIndicatorForegroundColor(color, number)
            with contextlib.suppress(AttributeError):
                editor.setIndicatorDrawUnder(True, number)
        self.set_wrap(_setting(WRAP_KEY, False), save=False)

    @property
    def wrap(self) -> bool:
        from qgis.PyQt.Qsci import QsciScintilla  # noqa: PLC0415

        return self.editor.wrapMode() != QsciScintilla.WrapMode.WrapNone

    def set_wrap(self, on: bool, *, save: bool = True) -> None:
        """Alt+Z (punto 29): ajustar las líneas largas a la ventana, o desplazarse a lo ancho."""
        from qgis.PyQt.Qsci import QsciScintilla  # noqa: PLC0415

        self.editor.setWrapMode(QsciScintilla.WrapMode.WrapWord if on else QsciScintilla.WrapMode.WrapNone)
        with contextlib.suppress(AttributeError):
            self.editor.setWrapIndentMode(QsciScintilla.WrapIndentMode.WrapIndentSame)
        if save:
            QSettings().setValue(WRAP_KEY, on)
            self.options_changed.emit()
        self.measure()

    def set_upper_keywords(self, on: bool) -> None:
        self.upper_keywords = on
        QSettings().setValue(UPPER_KEY, on)
        self.options_changed.emit()

    def measure(self) -> None:
        """El ancho real del texto (punto 29): la barra horizontal llega justo al final de la línea más larga
        (Scintilla, solo, mide unas pocas líneas y deja la barra corta o de más). Se calcula tras escribir."""
        longest = max((len(line) for line in self.editor.text().split("\n")), default=0)
        if self.wrap:
            longest = 0
        char = self.editor.SendScintilla(_SCI_TEXTWIDTH, _STYLE_DEFAULT, b"0") or 8
        self.editor.SendScintilla(_SCI_SETSCROLLWIDTH, max(1, longest * char + 2 * char))

    def zoom(self, step: int) -> None:
        if step == 0:
            self.editor.zoomTo(0)
        elif step > 0:
            self.editor.zoomIn()
        else:
            self.editor.zoomOut()
        self.measure()

    # -- utilidades de texto ---------------------------------------------------------------------------

    def _cursor(self) -> tuple[int, int, str]:
        line, index = self.editor.getCursorPosition()
        return line, index, self.editor.text(line).rstrip("\r\n")

    def _selections(self) -> int:
        return int(self.editor.SendScintilla(_SCI_GETSELECTIONS))

    def _selected_lines(self) -> tuple[int, int]:
        if not self.editor.hasSelectedText():
            line = self.editor.getCursorPosition()[0]
            return line, line
        first, _i, last, last_index = self.editor.getSelection()
        if last > first and last_index == 0:
            last -= 1  # una selección que acaba al comienzo de una línea no la incluye
        return first, last

    def _replace_lines(
        self, first: int, last: int, lines: list[str], *, keep: tuple[int, int] | None = None
    ) -> None:
        """Sustituye las líneas `first..last` por `lines` en un solo paso de deshacer (y selecciona las
        nuevas, o deja el cursor en `keep`)."""
        editor = self.editor
        end_index = len(editor.text(last).rstrip("\r\n"))
        editor.beginUndoAction()
        editor.setSelection(first, 0, last, end_index)
        editor.replaceSelectedText("\n".join(lines))
        editor.endUndoAction()
        if keep is not None:
            editor.setCursorPosition(*keep)
        elif len(lines) > 1 or first != last:
            editor.setSelection(first, 0, first + len(lines) - 1, len(lines[-1]))

    # -- teclado -----------------------------------------------------------------------------------------

    def _shortcut(self, k: Key) -> Callable[[], None] | None:  # noqa: PLR0911, PLR0912
        """La acción de una combinación del editor, o `None`."""
        if k.ctrl and not k.alt:
            if k.key == K.Key_F and not k.shift:
                return lambda: self._open_find(replace=False)
            if k.key == K.Key_H and not k.shift:
                return lambda: self._open_find(replace=True)
            if k.key == K.Key_G and not k.shift:
                return self._open_line
            if k.key == K.Key_Slash:  # en teclados españoles, Ctrl+Shift+7 también da «/»
                return self.toggle_comment
            if k.key == K.Key_D and not k.shift:
                return self.select_next
            if k.key == K.Key_K and k.shift:
                return self.delete_lines
            if k.key == K.Key_U and k.shift:
                return self.toggle_case
            if k.key in (K.Key_Plus, K.Key_Equal):
                return lambda: self.zoom(1)
            if k.key == K.Key_Minus:
                return lambda: self.zoom(-1)
            if k.key == K.Key_0 and not k.shift:
                return lambda: self.zoom(0)
            if k.key == K.Key_Space and k.shift:
                return self.show_parameters
        if k.alt and not k.ctrl:
            if k.key in (K.Key_Up, K.Key_Down):
                down = k.key == K.Key_Down
                return (
                    (lambda: self.duplicate_lines(down=down))
                    if k.shift
                    else (lambda: self.move_lines(down=down))
                )
            if k.key == K.Key_F and k.shift:
                return self.format
            if k.key == K.Key_Z and not k.shift:
                return lambda: self.set_wrap(not self.wrap)
        if k.key == K.Key_F3 and not k.ctrl and not k.alt and self.find_bar is not None:
            return lambda: self.find_bar.step(-1 if k.shift else 1)
        return None

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        kind = event.type()
        if watched is self.editor:
            if kind == QEvent.Type.ShortcutOverride and self._shortcut(_key(event)) is not None:
                event.accept()  # el editor recibe la tecla: ningún atajo de QGIS la toma antes
                return True
            if kind == QEvent.Type.KeyPress:
                return self._key_press(event)
            return False
        if kind == QEvent.Type.Wheel:
            return self._wheel(event)
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            return self._click(event)
        return False

    def _key_press(self, event: Any) -> bool:  # noqa: PLR0911 - una tecla, una salida
        k = _key(event)
        action = self._shortcut(k)
        if action is not None:
            action()
            return True
        if k.ctrl or k.alt or self._selections() > 1:
            return False  # con varios cursores, Scintilla escribe en todos
        if self.editor.isListActive() and k.key in (K.Key_Return, K.Key_Enter, K.Key_Tab):
            return False  # el autocompletado acepta
        if k.key in (K.Key_Return, K.Key_Enter) and not k.shift:
            return self._enter()
        if k.key == K.Key_Backspace and not k.shift:
            return self._backspace()
        if k.key == K.Key_Tab and not k.shift:
            return self._tab()
        text = event.text()
        if len(text) == 1 and text in "()[]{}'\"":
            return self._typed(text)
        return False

    def _typed(self, char: str) -> bool:
        """Pares (punto 17): cerrar, saltar el cierre o envolver la selección."""
        editor = self.editor
        if editor.hasSelectedText() and char in sql_edit.PAIRS:
            first, first_index, last, last_index = editor.getSelection()
            if first != last:
                return False
            selected = editor.selectedText()
            editor.beginUndoAction()
            editor.replaceSelectedText(char + selected + sql_edit.PAIRS[char])
            editor.endUndoAction()
            editor.setSelection(first, first_index + 1, last, last_index + 1)
            return True
        line, index, text = self._cursor()
        action = sql_edit.pair_action(char, text[:index], text[index:])
        if action == "skip":
            editor.setCursorPosition(line, index + 1)
            return True
        if action == "pair":
            editor.beginUndoAction()
            editor.insert(char + sql_edit.PAIRS[char])
            editor.endUndoAction()
            editor.setCursorPosition(line, index + 1)
            if char == "(":
                self._parameters.start()
            return True
        if char == ")" and not text[:index].strip():
            dedented = sql_edit.dedent_after(text[:index] + ")")
            if dedented is not None:
                self._replace_lines(line, line, [dedented + text[index:]], keep=(line, len(dedented)))
                return True
        return False

    def _enter(self) -> bool:
        editor = self.editor
        if editor.hasSelectedText():
            return False
        line, index, text = self._cursor()
        inserted, cursor = sql_edit.enter_text(text[:index], text[index:])
        rest = text[index:]
        editor.beginUndoAction()
        if rest[: len(rest) - len(rest.lstrip(" "))]:  # los espacios tras el cursor no bajan con él
            editor.setSelection(line, index, line, index + len(rest) - len(rest.lstrip(" ")))
            editor.removeSelectedText()
        editor.insert(inserted)
        editor.endUndoAction()
        head = inserted[:cursor]
        editor.setCursorPosition(line + head.count("\n"), len(head) - head.rfind("\n") - 1)
        editor.ensureCursorVisible()
        return True

    def _backspace(self) -> bool:
        editor = self.editor
        if editor.hasSelectedText():
            return False
        line, index, text = self._cursor()
        if index and sql_edit.backspace_pair(text[:index], text[index:]):
            editor.setSelection(line, index - 1, line, index + 1)
            editor.removeSelectedText()
            return True
        return False  # en la sangría, QScintilla quita 4 espacios (setBackspaceUnindents)

    def _tab(self) -> bool:
        """Tab: un fragmento si lo que hay antes del cursor es su nombre; si no, lo de siempre."""
        editor = self.editor
        if editor.hasSelectedText():
            return False
        line, index, text = self._cursor()
        found = re.search(r"(?<![\w.])([A-Za-z]+)$", text[:index])
        if found is None or not sql_edit.in_code(text[: found.start()]):
            return False
        expansion = sql_edit.expand_snippet(found.group(1), sql_edit.leading(text))
        if expansion is None:
            return False
        editor.beginUndoAction()
        editor.setSelection(line, found.start(), line, index)
        editor.replaceSelectedText(expansion.text)
        editor.endUndoAction()
        head = expansion.text[: expansion.cursor]
        column = len(head) - head.rfind("\n") - 1 if "\n" in head else found.start() + len(head)
        editor.setCursorPosition(line + head.count("\n"), column)
        return True

    def _char_added(self, char: int) -> None:
        """Tras escribir: `END` baja un nivel y, si se quiere, las palabras clave pasan a mayúsculas."""
        if self._selections() > 1:
            return
        ch = chr(char) if 0 < char < 0x110000 else ""
        line, index, text = self._cursor()
        if ch in ("D", "d") and index == len(text):
            dedented = sql_edit.dedent_after(text)
            if dedented is not None:
                self._replace_lines(line, line, [dedented], keep=(line, len(dedented)))
                return
        if self.upper_keywords and ch and not (ch.isalnum() or ch in '_."$'):
            before = text[: index - 1] if ch != "\n" else self.editor.text(line - 1).rstrip("\r\n")
            target_line = line if ch != "\n" else line - 1
            found = re.search(r"(?<![\w.\"])([A-Za-z_]+)$", before)
            if found is None or not sql_edit.in_code(before[: found.start()]):
                return
            vocabulary = self._lookup()[2] if self._lookup is not None else None
            keywords = (
                frozenset(vocabulary.keywords) if vocabulary is not None and vocabulary.keywords else None
            )
            upper = sql_edit.uppercase_word(found.group(1), keywords or sql_edit.KEYWORDS)
            if upper is not None:
                cursor = self.editor.getCursorPosition()
                self.editor.setSelection(target_line, found.start(), target_line, found.end())
                self.editor.replaceSelectedText(upper)
                self.editor.setCursorPosition(*cursor)

    # -- acciones ----------------------------------------------------------------------------------------

    def toggle_comment(self) -> None:
        first, last = self._selected_lines()
        lines = [self.editor.text(i).rstrip("\r\n") for i in range(first, last + 1)]
        line, index = self.editor.getCursorPosition()
        had_selection = self.editor.hasSelectedText()
        changed = sql_edit.toggle_comment(lines)
        self._replace_lines(
            first,
            last,
            changed,
            keep=None
            if had_selection
            else (line, max(0, index + len(changed[line - first]) - len(lines[line - first]))),
        )

    def move_lines(self, *, down: bool) -> None:
        self.editor.SendScintilla(_SCI_MOVESELECTEDLINESDOWN if down else _SCI_MOVESELECTEDLINESUP)

    def duplicate_lines(self, *, down: bool) -> None:
        """Shift+Alt+↓/↑: copia las líneas abajo (el cursor baja con la copia) o arriba (se queda)."""
        editor = self.editor
        first, last = self._selected_lines()
        line, index = editor.getCursorPosition()
        block = [editor.text(i).rstrip("\r\n") for i in range(first, last + 1)]
        selection = editor.getSelection() if editor.hasSelectedText() else None
        self._replace_lines(first, last, block + block, keep=(line, index))
        if down:
            shift = len(block)
            if selection is not None:
                editor.setSelection(selection[0] + shift, selection[1], selection[2] + shift, selection[3])
            else:
                editor.setCursorPosition(line + shift, index)
        elif selection is not None:
            editor.setSelection(*selection)

    def delete_lines(self) -> None:
        editor = self.editor
        first, last = self._selected_lines()
        editor.beginUndoAction()
        if last + 1 < editor.lines():
            editor.setSelection(first, 0, last + 1, 0)
        elif first > 0:
            editor.setSelection(
                first - 1, len(editor.text(first - 1).rstrip("\r\n")), last, len(editor.text(last))
            )
        else:
            editor.setSelection(first, 0, last, len(editor.text(last)))
        editor.removeSelectedText()
        editor.endUndoAction()

    def toggle_case(self) -> None:
        """Ctrl+Shift+U: la selección (o la palabra) en mayúsculas; si ya lo está, en minúsculas."""
        editor = self.editor
        if not editor.hasSelectedText():
            line, index, text = self._cursor()
            start, end = index, index
            while start and (text[start - 1].isalnum() or text[start - 1] == "_"):
                start -= 1
            while end < len(text) and (text[end].isalnum() or text[end] == "_"):
                end += 1
            if start == end:
                return
            editor.setSelection(line, start, line, end)
        selected = editor.selectedText()
        editor.SendScintilla(_SCI_LOWERCASE if selected == selected.upper() else _SCI_UPPERCASE)

    def select_next(self) -> None:
        """Ctrl+D: la palabra del cursor; otra vez, también su siguiente aparición (un cursor más)."""
        editor = self.editor
        if not editor.hasSelectedText():
            line, index, text = self._cursor()
            found = next((m for m in re.finditer(r"\w+", text) if m.start() <= index <= m.end()), None)
            if found is not None:
                editor.setSelection(line, found.start(), line, found.end())
            return
        text = editor.text()
        count = self._selections()
        main_end = int(editor.SendScintilla(_SCI_GETSELECTIONNEND, count - 1))
        main_start = int(editor.SendScintilla(_SCI_GETSELECTIONNSTART, count - 1))
        start_line, start_index = editor.lineIndexFromPosition(main_start)
        end_line, end_index = editor.lineIndexFromPosition(main_end)
        starts = _offsets(text)
        word = text[starts[start_line] + start_index : starts[end_line] + end_index]
        if not word:
            return
        after = starts[end_line] + end_index
        taken = set()
        for n in range(count):
            line, index = editor.lineIndexFromPosition(int(editor.SendScintilla(_SCI_GETSELECTIONNSTART, n)))
            taken.add(starts[line] + index)
        for offset in [*_find_all(text, word, after), *_find_all(text, word, 0)]:
            if offset in taken:
                continue
            first = editor.positionFromLineIndex(*_line_index(starts, offset))
            last = editor.positionFromLineIndex(*_line_index(starts, offset + len(word)))
            editor.SendScintilla(_SCI_ADDSELECTION, last, first)
            editor.SendScintilla(_SCI_SCROLLRANGE, first, last)
            return

    def format(self) -> None:
        """Shift+Alt+F: la selección o todo el texto, con `sql_edit.format_sql` (se deshace con Ctrl+Z)."""
        editor = self.editor
        line = editor.firstVisibleLine()
        if editor.hasSelectedText():
            selected = editor.selectedText()
            formatted = sql_edit.format_sql(selected)
            if not selected.endswith("\n"):
                formatted = formatted.rstrip("\n")
            if formatted != selected:
                editor.replaceSelectedText(formatted)
            return
        text = editor.text()
        formatted = sql_edit.format_sql(text)
        if formatted == text:
            return
        editor.beginUndoAction()
        editor.selectAll()
        editor.replaceSelectedText(formatted)
        editor.endUndoAction()
        editor.setFirstVisibleLine(line)

    def clean_for_save(self) -> None:
        """Al guardar (punto 30): sin espacios al final de las líneas y con un salto final (un solo paso de
        deshacer; el cursor no se mueve de línea)."""
        editor = self.editor
        text = editor.text()
        cleaned = sql_edit.clean_for_save(text)
        if cleaned == text:
            return
        line, index = editor.getCursorPosition()
        first = editor.firstVisibleLine()
        editor.beginUndoAction()
        editor.selectAll()
        editor.replaceSelectedText(cleaned)
        editor.endUndoAction()
        line = min(line, editor.lines() - 1)
        editor.setCursorPosition(line, min(index, len(editor.text(line).rstrip("\r\n"))))
        editor.setFirstVisibleLine(first)

    def _open_find(self, *, replace: bool) -> None:
        if self.find_bar is not None:
            self.find_bar.open(replace=replace)

    def _open_line(self) -> None:
        if self.find_bar is not None:
            self.find_bar.open_line()

    # -- apariciones de la palabra seleccionada ----------------------------------------------------------

    def mark_occurrences(self) -> None:
        editor = self.editor
        _clear_indicator(editor, OCCURRENCE_INDICATOR)
        if self._selections() != 1 or not editor.hasSelectedText():
            return
        word = editor.selectedText()
        if not re.fullmatch(r"[A-Za-z_][\w$]*", word):
            return
        text = editor.text()
        pattern = re.compile(rf"(?<![\w$]){re.escape(word)}(?![\w$])", re.IGNORECASE)
        _fill(
            editor,
            OCCURRENCE_INDICATOR,
            text,
            [(m.start(), m.end()) for m in pattern.finditer(text)][:MAX_MATCHES],
        )

    # -- ratón -----------------------------------------------------------------------------------------

    def _wheel(self, event: Any) -> bool:
        """Shift+rueda: a lo ancho (punto 29)."""
        mods = event.modifiers()
        if not mods & Qt.KeyboardModifier.ShiftModifier or mods & Qt.KeyboardModifier.ControlModifier:
            return False
        delta = event.angleDelta()
        step = delta.y() or delta.x()
        bar = self.editor.horizontalScrollBar()
        bar.setValue(bar.value() - step)
        return True

    def _point_offset(self, point: QPoint) -> int | None:
        position = int(self.editor.SendScintilla(_SCI_POSITIONFROMPOINTCLOSE, point.x(), point.y()))
        if position < 0:
            return None
        line, index = self.editor.lineIndexFromPosition(position)
        return _offsets(self.editor.text())[line] + index

    def _click(self, event: Any) -> bool:
        """Alt+clic: un cursor más. Ctrl+clic en una tabla o vista: al explorador."""
        mods = event.modifiers()
        point = event.position().toPoint() if hasattr(event, "position") else event.pos()
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if alt and not ctrl and not shift:
            position = int(self.editor.SendScintilla(_SCI_POSITIONFROMPOINT, point.x(), point.y()))
            if position >= 0:
                self.editor.SendScintilla(_SCI_ADDSELECTION, position, position)
                return True
            return False
        if ctrl and not alt and not shift:
            # Ctrl+clic no añade un cursor (eso es Alt+clic): en una tabla o vista la muestra en el explorador
            target = self.target(point) if self._reveal is not None else None
            if target is not None and target.source is not None and target.kind is not Kind.COLUMN:
                self._reveal(target)  # type: ignore[misc]
                return True
            position = int(self.editor.SendScintilla(_SCI_POSITIONFROMPOINT, point.x(), point.y()))
            if position >= 0:
                self.editor.setCursorPosition(*self.editor.lineIndexFromPosition(position))
            return True
        return False

    def target(self, point: QPoint) -> Target | None:
        offset = self._point_offset(point)
        if offset is None or self._lookup is None:
            return None
        catalog, columns, vocabulary = self._lookup()
        return target_at(self.editor.text(), offset, catalog=catalog, columns=columns, vocabulary=vocabulary)

    def describe(self, target: Target) -> str:
        """La información al pasar el ratón (punto 30)."""
        if target.kind is Kind.FUNCTION:
            lines = self._signatures.get(target.name.lower())
            if lines is None:
                self._fetch_signature(target.name, None)
                return ""
            return "\n".join(lines)
        if target.kind is Kind.COLUMN and target.column is not None and target.source is not None:
            return tr("Column «{0}» · {1}\nof {2}").format(
                target.column.name, target.column.data_type, ".".join(target.source)
            )
        if target.source is not None:
            what = tr("View") if target.kind is Kind.VIEW else tr("Table")
            columns = self._lookup()[1].get(target.source) if self._lookup is not None else None
            text = f"{what} · {'.'.join(target.source)}"
            if columns:
                text += "\n" + tr("{} columns").format(len(columns))
            return text + "\n" + tr("Ctrl+click: show in the explorer")
        return ""

    def _dwell(self, position: int, x: int, y: int) -> None:
        if position < 0:
            return
        line, index = self.editor.lineIndexFromPosition(position)
        status = getattr(self.editor, "status", None)
        if status is not None and status.message_at(_offsets(self.editor.text())[line] + index):
            return  # el error de la última ejecución tiene prioridad (#139)
        target = self.target(QPoint(x, y))
        if target is None:
            return
        info = self.describe(target)
        if info:
            QToolTip.showText(self.editor.viewport().mapToGlobal(QPoint(x, y)), info, self.editor)

    # -- ayuda de parámetros -----------------------------------------------------------------------------

    def show_parameters(self) -> None:
        """La firma de la función cuyo paréntesis está abierto (de `duckdb_functions()`), como nota bajo el
        cursor. La primera vez se lee de DuckDB; luego, de memoria."""
        line, index, text = self._cursor()
        call = sql_edit.call_before(text[:index])
        if call is None:
            return
        name = call[0]
        lines = self._signatures.get(name.lower())
        if lines is None:
            self._fetch_signature(name, (line, index))
            return
        if lines:
            self._calltip("\n".join(lines))

    def _fetch_signature(self, name: str, at: tuple[int, int] | None) -> None:
        if self._read_rows is None or name.lower() in self._asked:
            return
        self._asked.add(name.lower())

        def done(outcome: Any) -> None:
            rows = [] if isinstance(outcome, BaseException) else list(outcome.rows or [])
            lines = sql_edit.signature_lines(rows)
            self._signatures[name.lower()] = lines
            with contextlib.suppress(RuntimeError):  # la pestaña ya se cerró
                if at is not None and lines and self.editor.getCursorPosition() == at:
                    self._calltip("\n".join(lines))

        if not self._read_rows(sql_edit.signature_sql(name), 64, done):
            self._asked.discard(name.lower())

    def _calltip(self, text: str) -> None:
        position = int(self.editor.SendScintilla(_SCI_GETCURRENTPOS))
        self.editor.SendScintilla(_SCI_CALLTIPSHOW, position, text.encode("utf-8"))


def _find_all(text: str, word: str, start: int) -> list[int]:
    found = []
    at = text.find(word, start)
    while at >= 0 and len(found) < MAX_MATCHES:
        found.append(at)
        at = text.find(word, at + max(1, len(word)))
    return found


def _bytes(editor: Any, _text: str, starts: list[int], offset: int) -> int:
    return int(editor.positionFromLineIndex(*_line_index(starts, offset)))


def _fill(editor: Any, indicator: int, text: str, ranges: list[tuple[int, int]]) -> None:
    starts = _offsets(text)
    editor.SendScintilla(_SCI_SETINDICATORCURRENT, indicator)
    for start, end in ranges:
        first = _bytes(editor, text, starts, start)
        editor.SendScintilla(_SCI_INDICATORFILLRANGE, first, _bytes(editor, text, starts, end) - first)


def _clear_indicator(editor: Any, indicator: int) -> None:
    editor.SendScintilla(_SCI_SETINDICATORCURRENT, indicator)
    editor.SendScintilla(_SCI_INDICATORCLEARRANGE, 0, editor.SendScintilla(_SCI_GETLENGTH))


# -- buscar y reemplazar -------------------------------------------------------------------------------


class FindBar(QFrame):
    """Ctrl+F / Ctrl+H (punto 30): una barra compacta encima del editor. Intro y F3 van a la siguiente,
    Shift+Intro y Shift+F3 a la anterior, Esc cierra. Opciones: mayúsculas, palabra entera, expresión
    regular y «en la selección». Todas las coincidencias se marcan; el contador dice «3 de 12». Ctrl+G usa la
    misma barra para ir a una línea."""

    def __init__(self, editor: Any, colors: Colors) -> None:  # noqa: PLR0915 - la barra, en un solo lugar
        super().__init__()
        self.editor = editor
        self.colors = colors
        self.setProperty("pro", "find-bar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.matches: list[tuple[int, int]] = []
        self.current = -1
        self._replacing = False
        self._scope: tuple[int, int] | None = None
        self._line_mode = False
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 4, 8, 4)
        box.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(4)
        box.addLayout(top)  # antes de sus controles: sin padre, uno visible sería una ventana suelta
        self.find_edit = QLineEdit()
        self.find_edit.setProperty("pro", "find")
        self.find_edit.setPlaceholderText(tr("Find"))
        self.find_edit.setAccessibleName(tr("Find"))
        self.find_edit.textChanged.connect(self.search)
        self.find_edit.installEventFilter(self)
        top.addWidget(self.find_edit, 1)
        self.case_button = self._option("Aa", tr("Match case"))
        self.word_button = self._option("ab", tr("Whole word"))
        self.regex_button = self._option(".*", tr("Regular expression"))
        self.selection_button = self._option("⌶", tr("In the selection"))
        for option in (self.case_button, self.word_button, self.regex_button, self.selection_button):
            top.addWidget(option)
        self.count = label("", "muted")
        self.count.setMinimumWidth(64)
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(self.count)
        self.previous_button = icon_button("chevron-up", tr("Previous match (Shift+Enter)"), colors, size=14)
        self.previous_button.clicked.connect(lambda: self.step(-1))
        self.next_button = icon_button("chevron-down", tr("Next match (Enter)"), colors, size=14)
        self.next_button.clicked.connect(lambda: self.step(1))
        self.close_button = icon_button("close", tr("Close (Esc)"), colors, size=12)
        self.close_button.clicked.connect(self.close_bar)
        for item in (self.previous_button, self.next_button, self.close_button):
            item.setProperty("compact", True)
            top.addWidget(item)
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        box.addLayout(bottom)
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText(tr("Replace with"))
        self.replace_edit.setAccessibleName(tr("Replace with"))
        self.replace_edit.installEventFilter(self)
        bottom.addWidget(self.replace_edit, 1)
        self.replace_button = button(
            tr("Replace"), tooltip=tr("Replaces this match and goes to the next one")
        )
        self.replace_button.clicked.connect(self.replace_one)
        self.replace_all_button = button(tr("Replace all"))
        self.replace_all_button.clicked.connect(self.replace_all)
        bottom.addWidget(self.replace_button)
        bottom.addWidget(self.replace_all_button)
        self._replace_row = (self.replace_edit, self.replace_button, self.replace_all_button)
        # tras un cambio del texto, se vuelve a buscar (un temporizador hijo: muere con la barra)
        self._again = QTimer(self)
        self._again.setSingleShot(True)
        self._again.setInterval(0)
        self._again.timeout.connect(lambda: self.search(move=False))
        editor.textChanged.connect(self._text_changed)
        self.hide()

    def _option(self, text: str, tip: str) -> QPushButton:
        option = QPushButton(text)
        option.setProperty("pro", "find-option")
        option.setCheckable(True)
        option.setToolTip(tip)
        option.setAccessibleName(tip)
        option.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        option.setCursor(Qt.CursorShape.PointingHandCursor)
        option.toggled.connect(self._option_toggled)
        return option

    def _option_toggled(self) -> None:
        if self.sender() is self.selection_button:
            self._scope = self._selection_scope() if self.selection_button.isChecked() else None
        self.search()

    # -- abrir y cerrar ----------------------------------------------------------------------------------

    def open(self, *, replace: bool) -> None:
        self._set_line_mode(False)
        editor = self.editor
        selected = editor.selectedText() if editor.hasSelectedText() else ""
        multiline = "\n" in selected or "\r" in selected
        self.selection_button.setChecked(multiline)  # varias líneas: buscar dentro de ellas
        self._scope = self._selection_scope() if multiline else None
        for widget in self._replace_row:
            widget.setVisible(replace)
        self.show()
        if selected and not multiline:
            self.find_edit.setText(selected)
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        self.search(move=False)

    def open_line(self) -> None:
        """Ctrl+G: «Ir a la línea»."""
        self._set_line_mode(True)
        for widget in self._replace_row:
            widget.hide()
        self.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def _set_line_mode(self, on: bool) -> None:
        self._line_mode = on
        if on:
            self.find_edit.blockSignals(True)
            self.find_edit.clear()
            self.find_edit.blockSignals(False)
            self.find_edit.setPlaceholderText(tr("Go to line (1–{})").format(self.editor.lines()))
            self.find_edit.setAccessibleName(tr("Go to line"))
            self.count.setText("")
            _clear_indicator(self.editor, FIND_INDICATOR)
            _clear_indicator(self.editor, CURRENT_INDICATOR)
        else:
            self.find_edit.setPlaceholderText(tr("Find"))
            self.find_edit.setAccessibleName(tr("Find"))
        for option in (self.case_button, self.word_button, self.regex_button, self.selection_button):
            option.setVisible(not on)
        for item in (self.count, self.previous_button, self.next_button):
            item.setVisible(not on)

    def close_bar(self) -> None:
        _clear_indicator(self.editor, FIND_INDICATOR)
        _clear_indicator(self.editor, CURRENT_INDICATOR)
        self.matches = []
        self.current = -1
        self._set_line_mode(False)
        self.hide()
        self.editor.setFocus()

    def eventFilter(self, watched: Any, event: Any) -> bool:  # noqa: N802 - API de Qt
        if event.type() == QEvent.Type.ShortcutOverride and event.key() in (K.Key_Escape, K.Key_F3):
            event.accept()
            return True
        if event.type() != QEvent.Type.KeyPress:
            return False
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == K.Key_Escape:
            self.close_bar()
            return True
        if key in (K.Key_Return, K.Key_Enter):
            if self._line_mode:
                self.go_to_line()
            elif watched is self.replace_edit:
                self.replace_one()
            else:
                self.step(-1 if shift else 1)
            return True
        if key == K.Key_F3:
            self.step(-1 if shift else 1)
            return True
        return False

    # -- buscar --------------------------------------------------------------------------------------

    def pattern(self) -> re.Pattern[str] | None:
        text = self.find_edit.text()
        if not text:
            return None
        source = text if self.regex_button.isChecked() else re.escape(text)
        if self.word_button.isChecked():
            source = rf"(?<![\w$])(?:{source})(?![\w$])"
        flags = re.MULTILINE if self.case_button.isChecked() else re.MULTILINE | re.IGNORECASE
        try:
            return re.compile(source, flags)
        except re.error:
            return None

    def _selection_scope(self) -> tuple[int, int] | None:
        editor = self.editor
        if not editor.hasSelectedText():
            return None
        first, first_index, last, last_index = editor.getSelection()
        starts = _offsets(editor.text())
        return starts[first] + first_index, starts[last] + last_index

    def search(self, *_args: Any, move: bool = True) -> None:
        """Marca todas las coincidencias y va a la primera desde el cursor."""
        if self._line_mode:
            return
        editor = self.editor
        _clear_indicator(editor, FIND_INDICATOR)
        _clear_indicator(editor, CURRENT_INDICATOR)
        pattern = self.pattern()
        invalid = bool(self.find_edit.text()) and pattern is None
        self.find_edit.setProperty("invalid", invalid)
        self.find_edit.style().unpolish(self.find_edit)
        self.find_edit.style().polish(self.find_edit)
        self.matches = []
        self.current = -1
        text = editor.text()
        if pattern is not None:
            start, end = self._scope if self._scope is not None else (0, len(text))
            for found in pattern.finditer(text, start, end):
                if found.end() > found.start():
                    self.matches.append((found.start(), found.end()))
                if len(self.matches) >= MAX_MATCHES:
                    break
            _fill(editor, FIND_INDICATOR, text, self.matches)
        if self.matches:
            line, index = editor.getCursorPosition()
            if editor.hasSelectedText():
                line, index = editor.getSelection()[:2]
            cursor = _offsets(text)[line] + index
            self.current = next((i for i, m in enumerate(self.matches) if m[0] >= cursor), 0)
            self._show_current(select=move)
        self._update_count(invalid)

    def _update_count(self, invalid: bool = False) -> None:
        if invalid:
            self.count.setText(tr("Invalid"))
        elif not self.find_edit.text():
            self.count.setText("")
        elif not self.matches:
            self.count.setText(tr("No results"))
        else:
            self.count.setText(tr("{0} of {1}").format(self.current + 1, len(self.matches)))
        for item in (self.previous_button, self.next_button, self.replace_button, self.replace_all_button):
            item.setEnabled(bool(self.matches))

    def step(self, direction: int) -> None:
        if not self.isVisible():
            self.open(replace=False)
            return
        if not self.matches:
            return
        self.current = (self.current + direction) % len(self.matches)
        self._show_current(select=True)
        self._update_count()

    def _show_current(self, *, select: bool) -> None:
        editor = self.editor
        text = editor.text()
        _clear_indicator(editor, CURRENT_INDICATOR)
        start, end = self.matches[self.current]
        _fill(editor, CURRENT_INDICATOR, text, [(start, end)])
        starts = _offsets(text)
        first, last = _line_index(starts, start), _line_index(starts, end)
        if select and self._scope is None:
            editor.setSelection(first[0], first[1], last[0], last[1])
        editor.ensureLineVisible(first[0])
        editor.SendScintilla(
            _SCI_SCROLLRANGE, _bytes(editor, text, starts, end), _bytes(editor, text, starts, start)
        )

    def _text_changed(self) -> None:
        if self.isVisible() and not self._line_mode and not self._replacing:
            self._again.start()

    # -- reemplazar ----------------------------------------------------------------------------------

    def _replacement(self, found: re.Match[str]) -> str:
        if self.regex_button.isChecked():
            try:
                return found.expand(self.replace_edit.text())
            except (re.error, IndexError):
                return self.replace_edit.text()
        return self.replace_edit.text()

    def replace_one(self) -> None:
        pattern = self.pattern()
        if pattern is None or not self.matches:
            return
        editor = self.editor
        text = editor.text()
        start, end = self.matches[self.current]
        found = pattern.match(text, start)
        if found is None or found.end() != end:
            self.search()
            return
        replacement = self._replacement(found)
        starts = _offsets(text)
        self._replacing = True
        editor.beginUndoAction()
        editor.setSelection(*_line_index(starts, start), *_line_index(starts, end))
        editor.replaceSelectedText(replacement)
        editor.endUndoAction()
        self._replacing = False
        if self._scope is not None:
            self._scope = (self._scope[0], self._scope[1] + len(replacement) - (end - start))
        line, index = _line_index(_offsets(editor.text()), start + len(replacement))
        editor.setCursorPosition(line, index)
        self.search()

    def replace_all(self) -> None:
        pattern = self.pattern()
        if pattern is None or not self.matches:
            return
        editor = self.editor
        text = editor.text()
        start, end = self._scope if self._scope is not None else (0, len(text))
        segment = pattern.sub(self._replacement, text[start:end])
        count = len(self.matches)
        starts = _offsets(text)
        first_visible = editor.firstVisibleLine()
        self._replacing = True
        editor.beginUndoAction()
        editor.setSelection(*_line_index(starts, start), *_line_index(starts, end))
        editor.replaceSelectedText(segment)
        editor.endUndoAction()
        self._replacing = False
        editor.setFirstVisibleLine(first_visible)
        if self._scope is not None:
            self._scope = (start, start + len(segment))
        self.search(move=False)
        self.count.setText(tr("{} replaced").format(count))

    # -- ir a la línea --------------------------------------------------------------------------------

    def go_to_line(self) -> None:
        try:
            number = int(self.find_edit.text().strip())
        except ValueError:
            return
        line = max(1, min(number, self.editor.lines())) - 1
        self.close_bar()
        self.editor.setCursorPosition(line, 0)
        self.editor.ensureLineVisible(line)
