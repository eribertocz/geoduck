# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL, resultados y registro (G2; sql-editor-spec §1, §3, §4, §7 P0; GD-SQL-001..005).

Tres tarjetas en un divisor vertical que el usuario redimensiona: editor, resultados y registro (G5:
docs/g5/maqueta/inventario.md §1.4–1.6 y §2). En el panel acoplado el registro va en su propia pestaña y
«Cargar en QGIS ▾» ocupa todo el ancho al pie; en la ventana, el registro queda debajo y «Cargar en QGIS ▾»
a la derecha de las pestañas de resultados.

Editor: `QgsCodeEditorSQL` (spike G0-B, F-40). Las posiciones se traducen siempre con (línea, índice en
caracteres), nunca con posiciones absolutas de QScintilla, que son bytes (F-41).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qgis.core import QgsApplication
from qgis.gui import QgsCodeEditorSQL
from qgis.PyQt.QtCore import QRect, QSize, Qt, QTime, pyqtSignal
from qgis.PyQt.QtGui import QFont, QFontMetrics, QKeySequence, QMouseEvent, QPainter, QResizeEvent
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from geoduck.app.coordinator import SessionCoordinator
from geoduck.app.events import (
    AppEvent,
    CatalogChanged,
    ColumnsListed,
    PreviewsInvalidated,
    ScriptFinished,
    ScriptRejected,
    SessionStateChanged,
    StatementFinished,
    VocabularyChanged,
)
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.load import LoadMode
from geoduck.domain.session import SessionState
from geoduck.domain.sql import (
    DEFAULT_PREVIEW_LIMIT,
    PREVIEW_LIMITS,
    OutputKind,
    Preview,
    RunScope,
    SqlStatement,
    StatementStatus,
    result_title,
)
from geoduck.ui import theme
from geoduck.ui.completer import SqlCompleter
from geoduck.ui.i18n import tr
from geoduck.ui.load_dialog import OPTIONS
from geoduck.ui.widgets import line_index_from, offset_from

_STATUS_TEXT = {
    StatementStatus.OK: "OK",
    StatementStatus.FAILED: "Error",
    StatementStatus.CANCELLED: "Cancelada",
    StatementStatus.SKIPPED: "No ejecutada",
}
_MAX_COLUMN_WIDTH = 260
_STATUS_ROLE = int(Qt.ItemDataRole.UserRole) + 1
#: Filtros del registro: todas las filas, solo OK, solo Error (ui-ux-spec §8).
LOG_FILTERS = ("all", "ok", "error")
#: Columnas del registro (inventario V38): hora · nombre · estado · duración · mensaje.
LOG_TIME, LOG_NAME, LOG_STATUS, LOG_DURATION, LOG_MESSAGE = range(5)


def card(*, name: str = "") -> QFrame:
    """Tarjeta de la maqueta: fondo de tarjeta, borde y esquinas redondeadas (theme.py)."""
    frame = QFrame()
    frame.setProperty("geoduck", "card")
    if name:
        frame.setObjectName(name)
    return frame


def muted(label: QLabel) -> QLabel:
    label.setProperty("geoduck", "muted")
    return label


def bold(label: QLabel) -> QLabel:
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


class HintButton(QPushButton):
    """Botón con su texto y, a la derecha, el atajo en gris («Sentencia  Ctrl+Intro»). El atajo se oculta en
    un panel estrecho; el texto y la acción no."""

    def __init__(self, text: str, hint: str = "", role: str = "secondary", icon: str = "") -> None:
        super().__init__()
        self.setProperty("geoduck", role)
        self._label = QLabel(text)
        self._hint = QLabel(hint)
        self._hint.setProperty("geoduck", "hint")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 4, 12, 4)
        row.setSpacing(8)
        self._mark: QLabel | None = None
        if icon:
            self._mark = QLabel(icon)
            self._mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(self._mark)
        for label in (self._label, self._hint):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(label)
        if role == "primary":
            bold(self._label)
        self._hint.setVisible(bool(hint))
        self._role = role
        self._colors = theme.palette_for(self)
        self.setAccessibleName(text)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._paint_labels()

    def _paint_labels(self) -> None:
        """Color del texto y del atajo según el papel y el estado (la cascada de la hoja de estilo no
        llega a las etiquetas hijas de forma fiable en Qt 5 y 6)."""
        p = self._colors
        if not self.isEnabled():
            text, hint = p.muted, p.muted
        elif self._role in ("primary", "action"):
            text, hint = p.on_color, p.on_color
        else:
            text, hint = p.text, p.muted
        self._label.setStyleSheet(f"color: {text}; background: transparent;")
        if self._mark is not None:
            self._mark.setStyleSheet(f"color: {text}; background: transparent;")
        self._hint.setStyleSheet(f"color: {hint}; background: transparent;")

    def changeEvent(self, event: Any) -> None:  # noqa: N802 - API de Qt
        super().changeEvent(event)
        from qgis.PyQt.QtCore import QEvent  # noqa: PLC0415

        if event.type() == QEvent.Type.EnabledChange:
            self._paint_labels()

    def text(self) -> str:  # el texto visible (sin el atajo)
        return self._label.text()

    def sizeHint(self) -> QSize:  # noqa: N802 - API de Qt
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.layout().minimumSize()

    def set_hint_visible(self, visible: bool) -> None:
        self._hint.setVisible(visible and bool(self._hint.text()))
        self.updateGeometry()


class TypedHeader(QHeaderView):
    """Cabecera de resultados (inventario V31): marca de tipo en gris («#», «Aa») y nombre en negrita."""

    def __init__(
        self, labels: list[tuple[str, str]], muted_color: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.labels = labels
        self._muted = theme.color(muted_color)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setSectionsClickable(False)
        self.setHighlightSections(False)

    def _fonts(self) -> tuple[QFont, QFont]:
        name_font = QFont(self.font())
        name_font.setBold(True)
        return QFont(self.font()), name_font

    def sectionSizeFromContents(self, index: int) -> QSize:  # noqa: N802 - API de Qt
        size = super().sectionSizeFromContents(index)
        if 0 <= index < len(self.labels):
            marker, name = self.labels[index]
            plain, strong = self._fonts()
            width = QFontMetrics(plain).horizontalAdvance(f"{marker} ") + QFontMetrics(
                strong
            ).horizontalAdvance(name)
            size.setWidth(width + 24)
        return size

    def paintSection(self, painter: QPainter, rect: QRect, index: int) -> None:  # noqa: N802
        painter.save()
        super().paintSection(painter, rect, index)  # fondo y borde (el texto del modelo está vacío)
        painter.restore()
        if not 0 <= index < len(self.labels):
            return
        marker, name = self.labels[index]
        plain, strong = self._fonts()
        painter.save()
        x = rect.x() + 8
        if marker:
            painter.setFont(plain)
            painter.setPen(self._muted)
            painter.drawText(
                QRect(x, rect.y(), rect.width(), rect.height()), int(Qt.AlignmentFlag.AlignVCenter), marker
            )
            x += QFontMetrics(plain).horizontalAdvance(f"{marker} ")
        painter.setFont(strong)
        painter.setPen(self.palette().color(self.foregroundRole()))
        text = QFontMetrics(strong).elidedText(
            name, Qt.TextElideMode.ElideRight, max(0, rect.right() - x - 4)
        )
        painter.drawText(
            QRect(x, rect.y(), rect.right() - x, rect.height()), int(Qt.AlignmentFlag.AlignVCenter), text
        )
        painter.restore()


class ResultView(QWidget):
    """Una pestaña de resultado: siempre etiquetada como vista previa (sql-editor-spec §1, inventario P1)."""

    def __init__(self, event: StatementFinished, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.epoch = event.epoch
        self.title = title
        result = event.result
        preview = result.preview
        assert preview is not None
        self.preview = preview
        self.statement = result.statement
        self.loadable = self.statement.replayable
        self.table = self._build_table(preview)

        parts = [tr("Vista previa")]
        if result.output is OutputKind.MUTATION_ROWS:
            parts.append(tr("resultado de escritura: no se repite al cargar"))
        elif result.output is OutputKind.PLAN:
            parts.append(tr("plan de ejecución"))
        self.caption = muted(QLabel(" · ".join(parts)))
        self.stale_label = muted(QLabel(tr("Posiblemente obsoleta")))
        italic = QFont(self.stale_label.font())
        italic.setItalic(True)
        self.stale_label.setFont(italic)
        self.stale_label.setToolTip(
            tr(
                "Después de esta vista previa se ejecutó algo que pudo cambiar estructura o datos. "
                "GeoDuck no detecta cambios hechos fuera de la sesión."
            )
        )
        self.stale_label.hide()
        #: «Cargar en QGIS ▾» es uno solo, del panel, para la pestaña activa (inventario V29).
        self.load_button: Any = None
        self.load_menu: Any = None
        caption_row = QHBoxLayout()
        caption_row.setContentsMargins(12, 6, 12, 2)
        caption_row.addWidget(self.caption)
        caption_row.addStretch(1)
        caption_row.addWidget(self.stale_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(caption_row)
        layout.addWidget(self.table, 1)

    def tab_text(self, short: bool) -> str:
        """«Consumidores (200 filas · hay más)»; en el panel, «Consumidores 200+» (inventario V27, P7)."""
        n = len(self.preview.rows)
        if short:
            return f"{self.title} {n}{'+' if self.preview.truncated else ''}"
        more = " · " + tr("hay más") if self.preview.truncated else ""
        rows = tr("fila") if n == 1 else tr("filas")
        return f"{self.title} ({n} {rows}{more})"

    def _build_table(self, preview: Preview) -> QTableWidget:
        palette = theme.palette_for(self)
        table = QTableWidget(len(preview.rows), len(preview.columns))
        labels = [
            column_marker(name, kind) for name, kind in zip(preview.columns, preview.types, strict=True)
        ]
        header = TypedHeader(labels, palette.muted, table)
        table.setHorizontalHeader(header)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.setFrameShape(QFrame.Shape.NoFrame)
        rows = table.verticalHeader()
        rows.setProperty("geoduck", "rownumbers")
        rows.setDefaultSectionSize(table.fontMetrics().height() + 14)
        rows.setDefaultAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Tipo por columna (AT-UX-007): marca y nombre los dibuja la cabecera; el tipo exacto, en la ayuda
        table.setHorizontalHeaderLabels([""] * len(preview.columns))
        for c, kind in enumerate(preview.types):
            item = table.horizontalHeaderItem(c)
            if item is not None:
                item.setToolTip(kind)
                item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{preview.columns[c]}, {kind}")
        null_font = QFont(table.font())
        null_font.setItalic(True)
        numeric = {i for i, kind in enumerate(preview.types) if _is_numeric(kind)}
        for r, row in enumerate(preview.rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem("NULL" if value is None else str(value))
                if value is None:  # NULL ≠ "" y ≠ el texto 'NULL': cursiva atenuada y su propia ayuda
                    item.setFont(null_font)
                    item.setForeground(theme.color(palette.muted))
                    item.setToolTip(tr("NULL: sin valor"))
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, tr("NULL, sin valor"))
                elif value == "":
                    item.setToolTip(tr("Cadena vacía"))
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, tr("cadena vacía"))
                if c in numeric:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        for c in range(table.columnCount()):
            table.setColumnWidth(c, min(table.columnWidth(c), _MAX_COLUMN_WIDTH) + 16)
        header.setStretchLastSection(True)
        return table

    def header_labels(self) -> list[str]:
        """Las cabeceras como se ven: «# n», «Aa t», «d»."""
        header = self.table.horizontalHeader()
        return [f"{m} {n}" if m else n for m, n in header.labels]  # type: ignore[attr-defined]

    @property
    def stale(self) -> bool:
        return not self.stale_label.isHidden()

    def mark_stale(self) -> None:
        self.stale_label.show()


class ErrorView(QWidget):
    """Pestaña «Error · sentencia n» (inventario V28): el mensaje completo y «Ir a la sentencia»."""

    def __init__(self, event: StatementFinished, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        result = event.result
        self.key = (event.run_id, result.statement.index)
        self.statement = result.statement
        self.title = title
        code = f"[{result.error_code.value}] " if result.error_code else ""
        self.message = QLabel(code + result.message)
        self.message.setProperty("geoduck", "error-text")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.setAccessibleName(tr("Mensaje de error"))
        self.go_button = HintButton(tr("Ir a la sentencia"))
        self.go_button.setToolTip(tr("Selecciona en el editor la sentencia que falló"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(bold(QLabel(title)))
        layout.addWidget(self.message)
        row = QHBoxLayout()
        row.addWidget(self.go_button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)

    def tab_text(self, short: bool) -> str:
        number = self.statement.index + 1
        return f"{tr('Error')} · {number}" if short else f"{tr('Error')} · {tr('sentencia')} {number}"


class ModeItem(QFrame):
    """Entrada del menú «Cargar en QGIS ▾» en dos líneas: nombre y descripción (inventario V30)."""

    def __init__(self, name: str, description: str, action: QWidgetAction, menu: QMenu) -> None:
        super().__init__()
        self.setProperty("geoduck", "menu-item")
        self._action = action
        self._menu = menu
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        self.name_label = bold(QLabel(name))
        self.description_label = muted(QLabel(description))
        self.description_label.setWordWrap(True)
        layout.addWidget(self.name_label)
        layout.addWidget(self.description_label)
        self.setFixedWidth(320)
        self.setAccessibleName(f"{name}. {description}")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - API de Qt
        if self._action.isEnabled():
            self._menu.hide()
            self._action.trigger()
        event.accept()


#: Textos del menú: los mismos del diálogo de G4 (`load_dialog.OPTIONS`, textos de la maqueta).
MENU_TEXTS = OPTIONS


def column_marker(name: str, kind: str) -> tuple[str, str]:
    if _is_numeric(kind):
        return "#", name
    if _is_text(kind):
        return "Aa", name
    return "", name


def column_header(name: str, kind: str) -> str:
    marker, name = column_marker(name, kind)
    return f"{marker} {name}" if marker else name


def _is_text(kind: str) -> bool:
    return kind.split("(", maxsplit=1)[0].upper() in {"VARCHAR", "TEXT", "STRING", "CHAR", "BPCHAR"}


def _is_numeric(kind: str) -> bool:
    base = kind.split("(", maxsplit=1)[0].upper()
    return base in {
        "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER",
        "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE", "DECIMAL", "REAL",
    }  # fmt: skip


class SqlPanel(QWidget):
    #: (todas, OK, Error) del registro, al cambiar.
    log_counts_changed = pyqtSignal(int, int, int)
    #: Filtro del registro elegido («all», «ok», «error»).
    log_filter_changed = pyqtSignal(str)

    def __init__(
        self,
        coordinator: SessionCoordinator,
        parent: QWidget | None = None,
        *,
        on_message: Callable[[str], None] | None = None,
        load_flow: Any = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._load_flow = load_flow
        self._on_message = on_message or (lambda _m: None)
        self._running = False
        self._run_text = ""
        self._statements: dict[tuple[int, int], SqlStatement] = {}
        self._palette = theme.palette_for(self)
        self.short_titles = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.editor = QgsCodeEditorSQL()
        self.editor.setAccessibleName(tr("Editor SQL"))
        self.editor.setMinimumHeight(60)
        self.completer = SqlCompleter(self.editor, coordinator)  # G6 · E2 (GD-SQL-007)
        self._color_editor()
        self.editor_card = self._build_editor_card()
        self._build_results()
        self._build_log()
        self.log_section = self._build_log_card()
        # Divisor: editor | resultados | registro, redimensionable por el usuario.
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(12)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.editor_card)
        self.splitter.addWidget(self.results_card)
        self.splitter.addWidget(self.log_section)
        for index, stretch in enumerate((3, 5, 2)):
            self.splitter.setStretchFactor(index, stretch)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setCollapsible(2, True)  # el registro sí se puede plegar
        layout.addWidget(self.splitter, 1)
        self.bottom = QVBoxLayout()  # panel acoplado: «Cargar en QGIS ▾» a todo el ancho
        self.bottom.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.bottom)
        self._place_load_button(wide=True)

        self.run_current_button.clicked.connect(lambda: self.execute(RunScope.CURRENT))
        self.run_selection_button.clicked.connect(lambda: self.execute(RunScope.SELECTION))
        self.run_all_button.clicked.connect(lambda: self.execute(RunScope.ALL))
        self.cancel_button.clicked.connect(self._coordinator.cancel_current_operation)
        self.log.cellDoubleClicked.connect(self._select_logged_statement)
        self.results.currentChanged.connect(lambda _i: self._render(self._coordinator.state))
        # Atajos solo con el foco dentro del panel SQL, nunca en el resto de QGIS (§8, AT-UX-013)
        self.shortcuts = []
        for keys, scope in (("Ctrl+Return", RunScope.CURRENT), ("Ctrl+Shift+Return", RunScope.ALL)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda s=scope: self.execute(s))
            self.shortcuts.append(shortcut)
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._render(coordinator.state)

    # -- construcción ------------------------------------------------------------------------------

    def _color_editor(self) -> None:
        """Palabras clave en el color de la paleta, solo en este editor (inventario §0.3)."""
        lexer = self.editor.lexer()
        if lexer is None:
            return
        try:
            from qgis.PyQt.Qsci import QsciLexerSQL  # noqa: PLC0415 - QScintilla, solo para el color

            lexer.setColor(theme.color(self._palette.keyword), QsciLexerSQL.Keyword)
        except (ImportError, AttributeError):
            pass

    def _build_editor_card(self) -> QFrame:
        frame = card(name="geoduckEditorCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 12, 12, 4)
        box.setSpacing(8)
        self.actions_bar = QWidget()
        self.actions_bar.setLayout(self._build_actions())
        self.actions_bar.layout().setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.actions_bar)
        box.addWidget(self.editor, 1)
        self._wide_width = self.actions_bar.sizeHint().width() + 24  # con los atajos visibles
        # La fila no impone su ancho con los atajos: su mínimo es el de los botones sin atajo (E3)
        self.set_compact(True)
        self.actions_bar.setMinimumWidth(self.actions_bar.minimumSizeHint().width())
        self.set_compact(False)
        return frame

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - API de Qt
        super().resizeEvent(event)
        self.set_compact(event.size().width() < self._wide_width)

    def insert_text(self, text: str) -> None:
        """Escribe `text` en el editor donde está el cursor (o en lugar de la selección) y deja el cursor
        detrás, con el foco en el editor. Nunca ejecuta nada (GD-CAT-002)."""
        editor = self.editor
        if editor.hasSelectedText():
            editor.replaceSelectedText(text)
        else:
            line, index = editor.getCursorPosition()
            editor.insertAt(text, line, index)
            editor.setCursorPosition(line, index + len(text))
        editor.setFocus()

    def set_compact(self, compact: bool) -> None:
        """Panel estrecho: se ocultan los atajos de los botones y la etiqueta «Filas»; ninguna acción se
        quita (ui-ux-spec §8). El atajo sigue en la ayuda de cada botón."""
        for button in self.action_buttons:
            button.set_hint_visible(not compact)
        self.limit_label.setVisible(not compact and not self.short_titles)
        self.compact = compact

    def _build_actions(self) -> QHBoxLayout:
        self.run_all_button = HintButton(tr("Ejecutar"), tr("Ctrl+Mayús+Intro"), "primary", "▶")
        self.run_all_button.setToolTip(tr("Ejecuta todo el script, en orden (Ctrl+Mayús+Intro)"))
        self.run_current_button = HintButton(tr("Sentencia"), tr("Ctrl+Intro"))
        self.run_current_button.setToolTip(tr("Ejecuta la sentencia bajo el cursor (Ctrl+Intro)"))
        self.run_selection_button = HintButton(tr("Selección"))
        self.run_selection_button.setToolTip(tr("Ejecuta solo el texto seleccionado"))
        self.cancel_button = HintButton(tr("Cancelar"))
        self.cancel_button.setToolTip(tr("Cancela la ejecución en curso"))
        self.limit_combo = QComboBox()
        for limit in PREVIEW_LIMITS:
            self.limit_combo.addItem(str(limit), limit)
        self.limit_combo.setCurrentIndex(PREVIEW_LIMITS.index(DEFAULT_PREVIEW_LIMIT))
        self.limit_combo.setToolTip(tr("Filas de cada vista previa"))
        self.limit_combo.setAccessibleName(tr("Filas de cada vista previa"))
        self.action_buttons = (
            self.run_all_button,
            self.run_current_button,
            self.run_selection_button,
            self.cancel_button,
        )
        self.compact = False
        actions = QHBoxLayout()
        actions.setSpacing(8)
        for button in self.action_buttons:
            actions.addWidget(button)
        actions.addStretch(1)
        self.limit_label = muted(QLabel(tr("Filas")))
        actions.addWidget(self.limit_label)
        actions.addWidget(self.limit_combo)
        return actions

    def _build_results(self) -> None:
        self.results = QTabWidget()
        self.results.setProperty("geoduck", "results")
        self.results.setDocumentMode(True)
        self.results.setUsesScrollButtons(True)
        self.results.setElideMode(Qt.TextElideMode.ElideRight)
        self.empty_results = muted(QLabel(tr("Sin resultados todavía. Ejecute una consulta (Ctrl+Intro).")))
        self.empty_results.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.empty_results)
        self.results_stack.addWidget(self.results)
        self.results_stack.setMinimumHeight(60)
        self.results_card = card(name="geoduckResultsCard")
        box = QVBoxLayout(self.results_card)
        box.setContentsMargins(4, 4, 4, 4)
        box.addWidget(self.results_stack)
        # «Cargar en QGIS ▾»: uno solo, para la pestaña activa (inventario V29, P9). Clic = diálogo de G4;
        # flecha = las tres modalidades, cada una abre el diálogo con ella marcada (ui-ux-spec §8).
        self.load_button = QToolButton()
        self.load_button.setObjectName("geoduckLoadButton")
        self.load_button.setProperty("geoduck", "load")
        self.load_button.setIcon(QgsApplication.getThemeIcon("mActionAddLayer.svg"))
        self.load_button.setText(tr("Cargar en QGIS"))
        self.load_button.setToolTip(tr("Carga el resultado completo como capa de QGIS"))
        self.load_button.setAccessibleName(tr("Cargar en QGIS"))
        self.load_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.load_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.load_menu = QMenu(self.load_button)
        self.load_menu.setObjectName("geoduckLoadMenu")
        self.load_button.setMenu(self.load_menu)
        self.load_button.clicked.connect(lambda _c=False: self._load_current())
        self.load_menu.aboutToShow.connect(lambda: self._fill_load_menu(self.current_view()))

    def _place_load_button(self, *, wide: bool) -> None:
        """Ventana: a la derecha de las pestañas de resultados. Panel: al pie, a todo el ancho."""
        if wide:
            self.bottom.removeWidget(self.load_button)
            self.results.setCornerWidget(self.load_button, Qt.Corner.TopRightCorner)
            self.load_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        else:
            self.results.setCornerWidget(None, Qt.Corner.TopRightCorner)
            self.bottom.addWidget(self.load_button)
            self.load_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.load_button.show()

    def _build_log_card(self) -> QFrame:
        frame = card(name="geoduckLogCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 10, 12, 8)
        box.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.log_title = bold(QLabel(tr("Registro")))
        header.addWidget(self.log_title)
        header.addWidget(self._build_log_filters())
        header.addStretch(1)
        box.addLayout(header)
        box.addWidget(self.log, 1)
        return frame

    def set_presentation(self, *, wide: bool, tabs: QTabWidget | None = None) -> None:
        """Ventana (`wide`): registro debajo (plegable) y «Cargar en QGIS ▾» junto a las pestañas. Panel: el
        registro en la pestaña «Registro» de `tabs`, «Cargar en QGIS ▾» al pie y títulos compactos. Los
        mismos widgets."""
        if wide:
            self.splitter.addWidget(self.log_section)  # addWidget lo saca de la pestaña
            self.splitter.setStretchFactor(2, 2)
            self.splitter.setCollapsible(2, True)
            self.log_title.show()
        elif tabs is not None:
            tabs.insertTab(2, self.log_section, tr("Registro"))
            self.log_title.hide()  # el título ya está en la pestaña
        self.short_titles = not wide
        self._place_load_button(wide=wide)
        self.limit_label.setVisible(wide and not self.compact)
        self._retitle()

    def dock_log(self, tabs: QTabWidget | None) -> None:  # compatibilidad con E4
        self.set_presentation(wide=tabs is None, tabs=tabs)

    def _retitle(self) -> None:
        palette = self._palette
        for i in range(self.results.count()):
            view = self.results.widget(i)
            if isinstance(view, (ResultView, ErrorView)):
                self.results.setTabText(i, view.tab_text(self.short_titles))
                if isinstance(view, ErrorView):
                    self.results.tabBar().setTabTextColor(i, theme.color(palette.error))

    def _build_log_filters(self) -> QWidget:
        """Todo / OK / Error con su número (ui-ux-spec §8, AT-UX-009). Filtrar oculta filas, no las borra."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.log_filter_group = QButtonGroup(box)
        self.log_filter_group.setExclusive(True)
        self.log_filter_buttons: dict[str, QPushButton] = {}
        for key in LOG_FILTERS:
            button = QPushButton()
            button.setCheckable(True)
            button.setProperty("geoduck", "chip")
            button.setObjectName(f"geoduckLogFilter_{key}")
            self.log_filter_group.addButton(button)
            self.log_filter_buttons[key] = button
            button.clicked.connect(lambda _c=False, k=key: self.set_log_filter(k))
            row.addWidget(button)
        self.log_filter = "all"
        self.log_filter_buttons["all"].setChecked(True)
        self._update_log_counts()
        return box

    def log_counts(self) -> tuple[int, int, int]:
        """(todas, OK, Error) del registro."""
        statuses = [self._row_status(r) for r in range(self.log.rowCount())]
        return len(statuses), statuses.count("ok"), statuses.count("error")

    def _row_status(self, row: int) -> str:
        item = self.log.item(row, LOG_STATUS)
        if item is None:
            return "other"
        status = item.data(_STATUS_ROLE)
        if status is StatementStatus.OK:
            return "ok"
        if status is StatementStatus.FAILED:
            return "error"
        return "other"  # cancelada o no ejecutada: solo en «Todo»

    def set_log_filter(self, key: str) -> None:
        if key not in LOG_FILTERS:
            key = "all"
        self.log_filter = key
        self.log_filter_buttons[key].setChecked(True)
        for row in range(self.log.rowCount()):
            self.log.setRowHidden(row, key != "all" and self._row_status(row) != key)
        self.log_filter_changed.emit(key)

    def _update_log_counts(self) -> None:
        total, ok, errors = self.log_counts()
        for key, text, number in (
            ("all", tr("Todo"), total),
            ("ok", tr("OK"), ok),
            ("error", tr("Error"), errors),
        ):
            button = self.log_filter_buttons[key]
            button.setText(f"{text} ({number})")
            button.setAccessibleName(f"{text}: {number}")
        self.log_counts_changed.emit(total, ok, errors)

    def _build_log(self) -> None:
        self.log = QTableWidget(0, 5)
        self.log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.log.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.log.setShowGrid(False)
        self.log.setFrameShape(QFrame.Shape.NoFrame)
        self.log.horizontalHeader().hide()
        self.log.verticalHeader().hide()
        self.log.verticalHeader().setDefaultSectionSize(self.log.fontMetrics().height() + 10)
        header = self.log.horizontalHeader()
        header.setStretchLastSection(True)
        for col in range(LOG_MESSAGE):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.log.setToolTip(tr("Doble clic para seleccionar la sentencia en el editor"))
        self.log.setAccessibleName(tr("Registro de ejecuciones"))
        self.log.setMinimumHeight(48)

    # -- acciones ----------------------------------------------------------------------------------

    def execute(self, scope: RunScope) -> None:
        if self._coordinator.state is not SessionState.READY:
            return
        full_text = self.editor.text()
        text, base, cursor = full_text, 0, 0
        if scope is RunScope.SELECTION:
            if not self.editor.hasSelectedText():
                return
            line_from, index_from, _l, _i = self.editor.getSelection()
            base = offset_from(full_text, line_from, index_from)
            text = self.editor.selectedText()
        elif scope is RunScope.CURRENT:
            line, index = self.editor.getCursorPosition()
            cursor = offset_from(full_text, line, index)
        if not text.strip():
            return
        self.editor.clearWarnings()
        self._clear_results()
        self._run_text = full_text
        self._running = True
        try:
            self._coordinator.execute_sql(
                text, scope, cursor=cursor, base=base, preview_limit=int(self.limit_combo.currentData())
            )
        except GeoDuckError as exc:  # p. ej. DETACH con capas Conectadas sin guardar (§5.5)
            self._running = False
            self._on_message(exc.message)

    def detach(self) -> None:
        self._unsubscribe()

    # -- eventos -----------------------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, (ColumnsListed, VocabularyChanged)):
            self.completer.refresh()
        elif isinstance(event, CatalogChanged):
            self._coordinator.vocabulary()  # se pide ya, para que el autocompletado lo tenga a tiempo
        elif isinstance(event, SessionStateChanged):
            if event.current is not SessionState.BUSY:
                self._running = False
            self._render(event.current)
        elif isinstance(event, StatementFinished):
            self._on_statement(event)
        elif isinstance(event, PreviewsInvalidated):
            for view in self.result_views():
                if self._coordinator.is_stale(view.epoch):
                    view.mark_stale()
        elif isinstance(event, ScriptFinished):
            self._on_script(event)
        elif isinstance(event, ScriptRejected):
            self._on_message(f"[{event.code.value}] {event.message}")

    def _on_statement(self, event: StatementFinished) -> None:
        result = event.result
        title = result_title(self._run_text, result.statement)
        self._statements[(event.run_id, result.statement.index)] = result.statement
        self._add_log(event, title)
        tab: ResultView | ErrorView | None = None
        if result.preview is not None:
            tab = ResultView(event, title)
            tab.load_button = self.load_button
            tab.load_menu = self.load_menu
        elif result.status is StatementStatus.FAILED:
            tab = ErrorView(event, title)
            tab.go_button.clicked.connect(lambda _c=False, k=tab.key: self._select_statement(k))
        if tab is not None:
            index = self.results.addTab(tab, tab.tab_text(self.short_titles))
            self.results.setTabToolTip(index, result.statement.text.strip()[:500])
            if isinstance(tab, ErrorView):
                self.results.tabBar().setTabTextColor(index, theme.color(self._palette.error))
            self.results_stack.setCurrentWidget(self.results)
        if result.status is StatementStatus.FAILED and result.error_offset is not None:
            self._point_error(result.error_offset, result.message)
        self._render(self._coordinator.state)

    def _on_script(self, event: ScriptFinished) -> None:
        run = event.run
        if run.parse_error:
            self._on_message(tr("Error de sintaxis: no se ejecutó nada.") + f" {run.parse_error}")
            if run.parse_error_offset is not None:
                self._point_error(run.parse_error_offset, run.parse_error)
        elif run.failed:
            failed = next(r for r in run.results if r.status is not StatementStatus.OK)
            code = failed.error_code.value if failed.error_code else ""
            self._on_message(f"[{code}] {failed.message}")
        if self.results.count():
            self.results.setCurrentIndex(self.results.count() - 1)

    def _add_log(self, event: StatementFinished, title: str) -> None:
        r = event.result
        palette = self._palette
        row = self.log.rowCount()
        self.log.insertRow(row)
        duration = (
            f"{r.duration_ms:.0f} ms" if r.status in (StatementStatus.OK, StatementStatus.FAILED) else ""
        )
        values = (
            QTime.currentTime().toString("HH:mm:ss"),
            title,
            tr(_STATUS_TEXT[r.status]),
            duration,
            r.message,
        )
        failed = r.status is StatementStatus.FAILED
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == LOG_TIME:
                item.setForeground(theme.color(palette.muted))
                item.setToolTip(tr("Ejecución {} · sentencia {}").format(event.run_id, r.statement.index + 1))
            elif col == LOG_STATUS:
                if r.status is StatementStatus.OK:
                    item.setForeground(theme.color(palette.primary))
                elif failed:
                    item.setForeground(theme.color(palette.error))
                else:
                    item.setForeground(theme.color(palette.muted))
            elif col == LOG_DURATION:
                item.setForeground(theme.color(palette.muted))
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            elif col == LOG_MESSAGE:  # mensaje completo: ayuda y nombre accesible (AT-UX-009)
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.AccessibleTextRole, value)
                item.setForeground(theme.color(palette.error if failed else palette.muted))
            item.setData(Qt.ItemDataRole.UserRole, (event.run_id, r.statement.index))
            item.setData(_STATUS_ROLE, r.status)
            self.log.setItem(row, col, item)
        self.log.setRowHidden(row, self.log_filter != "all" and self._row_status(row) != self.log_filter)
        self._update_log_counts()
        self.log.scrollToBottom()

    def _select_logged_statement(self, row: int, _column: int) -> None:
        """Navegación: doble clic en el registro selecciona la sentencia en el editor."""
        item = self.log.item(row, 0)
        key = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if key:
            self._select_statement(tuple(key))

    def _select_statement(self, key: tuple[int, int]) -> None:
        statement = self._statements.get(key)
        text = self.editor.text()
        if statement is None or statement.end > len(text):
            return
        start = statement.start + len(statement.text) - len(statement.text.lstrip())
        self.editor.setSelection(*line_index_from(text, start), *line_index_from(text, statement.end))
        self.editor.setFocus()

    def _point_error(self, offset: int, message: str) -> None:
        line, index = line_index_from(self.editor.text(), offset)
        self.editor.addWarning(line, message)
        self.editor.setCursorPosition(line, index)

    def _clear_results(self) -> None:
        while self.results.count():
            widget = self.results.widget(0)
            self.results.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self.results_stack.setCurrentWidget(self.empty_results)

    def current_view(self) -> ResultView | None:
        view = self.results.currentWidget()
        return view if isinstance(view, ResultView) else None

    def _load_current(self) -> None:
        view = self.current_view()
        if view is not None:
            self._load(view)

    def _load(self, view: ResultView, mode: LoadMode | None = None) -> None:
        if self._load_flow is not None and view.loadable:
            self._load_flow.start(view.statement.text, view.title, mode=mode)

    def _fill_load_menu(self, view: ResultView | None) -> None:
        """Las tres modalidades en dos líneas; las no disponibles, desactivadas con el motivo."""
        menu = self.load_menu
        menu.clear()
        reasons = self._coordinator.load_modes()
        ready = self._coordinator.state is SessionState.READY
        for mode, (name, description) in MENU_TEXTS.items():
            reason = reasons.get(mode)
            action = QWidgetAction(menu)
            item = ModeItem(name, description if reason is None else reason, action, menu)
            action.setDefaultWidget(item)
            action.setText(f"{name} — {description if reason is None else reason}")
            action.setObjectName(f"geoduckLoad_{mode.value}")
            enabled = reason is None and view is not None and view.loadable and ready
            action.setEnabled(enabled)
            item.setProperty("enabled", "true" if enabled else "false")
            action.triggered.connect(lambda _c=False, m=mode, v=view: v is not None and self._load(v, m))
            menu.addAction(action)

    def result_views(self) -> list[ResultView]:
        views = [self.results.widget(i) for i in range(self.results.count())]
        return [v for v in views if isinstance(v, ResultView)]

    def _render(self, state: SessionState) -> None:
        ready = state is SessionState.READY
        for button in (self.run_current_button, self.run_selection_button, self.run_all_button):
            button.setEnabled(ready)
        loading = self._load_flow is not None and self._load_flow.loading
        self.cancel_button.setEnabled(state is SessionState.BUSY and (self._running or loading))
        view = self.current_view()
        self.load_button.setEnabled(
            view is not None and view.loadable and ready and self._load_flow is not None
        )
        if view is not None and not view.loadable:
            self.load_button.setToolTip(
                tr("Solo se pueden cargar consultas de lectura: esta sentencia no se repite")
            )
        else:
            self.load_button.setToolTip(tr("Carga el resultado completo como capa de QGIS"))
