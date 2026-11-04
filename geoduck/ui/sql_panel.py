# SPDX-License-Identifier: GPL-2.0-or-later
"""Editor SQL, resultados y registro (G2; sql-editor-spec §1, §3, §4, §7 P0; GD-SQL-001..005).

Dos secciones en un divisor vertical que el usuario redimensiona: el cuaderno (G7: celdas, cada una con su
editor, su resultado y su «Cargar en QGIS ▾», `ui/notebook_view.py`) y el registro (G5:
docs/g5/maqueta/inventario.md §1.4–1.6 y §2). En el panel acoplado el registro va en su propia pestaña; en la
ventana, debajo del cuaderno.

Editor: `QgsCodeEditorSQL` (spike G0-B, F-40). Las posiciones se traducen siempre con (línea, índice en
caracteres), nunca con posiciones absolutas de QScintilla, que son bytes (F-41).
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qgis.core import QgsApplication, QgsSettings
from qgis.gui import QgsCodeEditorSQL
from qgis.PyQt.QtCore import QRect, QSize, Qt, QTime, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QFont, QFontMetrics, QKeySequence, QMouseEvent, QPainter, QResizeEvent
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
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
    ExportFailed,
    ExportFinished,
    PreviewsInvalidated,
    ScriptFinished,
    ScriptRejected,
    SessionStateChanged,
    StatementFinished,
    VocabularyChanged,
)
from geoduck.app.notebook_runner import CellOutcome, NotebookRunner
from geoduck.domain.bridge_types import is_geometry_type
from geoduck.domain.errors import GeoDuckError
from geoduck.domain.export import ExportFormat, ExportRequest
from geoduck.domain.load import LoadMode
from geoduck.domain.notebook import Cell, Notebook
from geoduck.domain.notebook_file import SUFFIX as NOTEBOOK_SUFFIX
from geoduck.domain.session import SessionState
from geoduck.domain.sql import (
    DEFAULT_PREVIEW_LIMIT,
    OutputKind,
    Preview,
    RunScope,
    ScriptRun,
    SqlStatement,
    StatementStatus,
    result_title,
)
from geoduck.ui import theme
from geoduck.ui.completer import SqlCompleter
from geoduck.ui.i18n import N_, tr
from geoduck.ui.load_dialog import OPTIONS
from geoduck.ui.notebook_list import NotebookList, NotebookSelector
from geoduck.ui.notebook_store import RecoveryStore, open_notebook, save_notebook
from geoduck.ui.notebook_view import CellWidget, NotebookView
from geoduck.ui.result_summary import summary_text
from geoduck.ui.widgets import line_index_from, offset_from

_STATUS_TEXT = {
    StatementStatus.OK: N_("OK"),
    StatementStatus.FAILED: N_("Error"),
    StatementStatus.CANCELLED: N_("Cancelled"),
    StatementStatus.SKIPPED: N_("Not run"),
}
_MAX_COLUMN_WIDTH = 260
_STATUS_ROLE = int(Qt.ItemDataRole.UserRole) + 1
#: Filtros del registro: todas las filas, solo OK, solo Error (ui-ux-spec §8).
LOG_FILTERS = ("all", "ok", "error")
#: Columnas del registro (inventario V38): hora · nombre · estado · duración · mensaje.
LOG_TIME, LOG_NAME, LOG_STATUS, LOG_DURATION, LOG_MESSAGE = range(5)


def _free_keys(editor: Any, keys: tuple[str, ...]) -> None:
    """Quita esas teclas de los comandos de QScintilla de este editor (Ctrl+T intercambia líneas), para que
    lleguen a los atajos de GeoDuck. Solo en los editores de GeoDuck."""
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


#: Espera tras el último cambio antes de autoguardar (archivo del cuaderno y copia de recuperación).
AUTOSAVE_MS = 1500
#: Copia de recuperación de los cuadernos: activada por defecto (decisión del propietario, ADR-0014).
RECOVERY_SETTING = "geoduck/notebooks/recovery"


def _file_name(title: str) -> str:
    """Nombre de archivo sugerido a partir del título del resultado («Ventas del mes (3 filas)» → «Ventas del
    mes»): sin la cuenta de filas ni caracteres que Windows no admite."""
    base = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    base = re.sub(r'[<>:"/\\|?*]', "_", base).strip(" .")
    return base or tr("result")


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
    """Botón con su texto y, a la derecha, el atajo en gris, si tiene. El atajo se oculta en
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
        #: Base donde se ejecutó (G7): «Cargar» repite la consulta en ella.
        self.database = result.database
        self.loadable = self.statement.replayable
        self.table = self._build_table(preview)
        # Ctrl+C copia las celdas seleccionadas, como una hoja de cálculo (sin botón «Copiar»: propietario)
        self.copy_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.table)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_selection)

        parts = [tr("Preview")]
        if result.output is OutputKind.MUTATION_ROWS:
            parts.append(tr("write result: not repeated when loading"))
        elif result.output is OutputKind.PLAN:
            parts.append(tr("execution plan"))
        self.caption = muted(QLabel(" · ".join(parts)))
        self.stale_label = muted(QLabel(tr("Possibly outdated")))
        italic = QFont(self.stale_label.font())
        italic.setItalic(True)
        self.stale_label.setFont(italic)
        self.stale_label.setToolTip(
            tr(
                "After this preview something ran that may have changed structure or data. GeoDuck "
                "does not detect changes made outside the session."
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
        more = " · " + tr("there is more") if self.preview.truncated else ""
        rows = tr("row") if n == 1 else tr("rows")
        return f"{self.title} ({n} {rows}{more})"

    def copy_selection(self) -> None:
        """Las celdas seleccionadas al portapapeles, separadas por tabuladores (para pegar en una hoja). Con
        toda la tabla seleccionada (Ctrl+A), con la fila de nombres."""
        table = self.table
        ranges = table.selectedRanges()
        if not ranges:
            return
        rows = sorted({r for rng in ranges for r in range(rng.topRow(), rng.bottomRow() + 1)})
        columns = sorted({c for rng in ranges for c in range(rng.leftColumn(), rng.rightColumn() + 1)})
        lines = []
        if len(rows) == table.rowCount() and len(columns) == table.columnCount():
            lines.append("\t".join(self.preview.columns[c] for c in columns))
        for r in rows:
            cells = []
            for c in columns:
                item = table.item(r, c)
                cells.append(item.text() if item is not None and item.isSelected() else "")
            lines.append("\t".join(cells))
        QApplication.clipboard().setText("\n".join(lines))

    def _build_table(self, preview: Preview) -> QTableWidget:
        palette = theme.palette_for(self)
        table = QTableWidget(len(preview.rows), len(preview.columns))
        labels = [
            column_marker(name, kind) for name, kind in zip(preview.columns, preview.types, strict=True)
        ]
        header = TypedHeader(labels, palette.muted, table)
        table.setHorizontalHeader(header)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setShowGrid(True)  # grilla suave (`border_soft`, theme.py), como la maqueta (propietario)
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
                    item.setToolTip(tr("NULL: no value"))
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, tr("NULL, no value"))
                elif value == "":
                    item.setToolTip(tr("Empty string"))
                    item.setData(Qt.ItemDataRole.AccessibleTextRole, tr("empty string"))
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
        self.message.setAccessibleName(tr("Error message"))
        self.go_button = HintButton(tr("Go to the statement"))
        self.go_button.setToolTip(tr("Selects in the editor the statement that failed"))
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
        return f"{tr('Error')} · {number}" if short else f"{tr('Error')} · {tr('statement')} {number}"


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
    if is_geometry_type(kind):
        return "◈", name  # maqueta G7: «◈ geometry»
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
    #: El registro de la ventana se abrió o se plegó (se recuerda).
    log_open_changed = pyqtSignal(bool)
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
        # G6 · E3: varias pestañas de editor en la misma sesión. Cada ejecución recuerda su pestaña
        # (`_run_editors`), para señalar errores y sentencias en la pestaña correcta.
        self._completers: dict[int, SqlCompleter] = {}
        self._run_editor: Any = None
        self._run_editors: dict[int, Any] = {}
        #: Celda que se está ejecutando: sus resultados van a ella (G7).
        self._run_cell: CellWidget | None = None
        #: Celda de cada ejecución (`run_id`): los eventos de una celda no van a la siguiente (G7).
        self._run_cells: dict[int, CellWidget] = {}
        self._setup_runner(coordinator)
        self._editor_numbers = 0
        #: Archivo de «Exportar ▾»: (formato, nombre sugerido) → ruta, o "" si se cancela. El diálogo del
        #: sistema pide confirmación si el archivo ya existe (DuckDB sobrescribe sin avisar); las pruebas lo
        #: sustituyen.
        self.choose_export_path: Callable[[ExportFormat, str], str] = self._ask_export_path
        self._export_dir = ""
        self._exporting = False
        #: Pregunta al cerrar una pestaña con SQL (`nombre` → cerrar sí/no); las pruebas la sustituyen.
        self.confirm_close: Callable[[str], bool] = self._ask_close
        self._setup_notebook_files()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._build_editor_tabs()
        self.editor_card = self._build_editor_card()
        self._refresh_notebooks()  # el nombre del cuaderno en la barra superior
        self._build_log()
        self._log_foldable = True
        self._log_open_wide = False  # ventana: plegado por defecto
        self.log_section = self._build_log_card()
        self.set_log_open(False)  # ya con su tarjeta: la altura de una línea
        QTimer.singleShot(0, self.check_recovery)  # ¿quedó una copia de un QGIS que se cerró mal?
        # Divisor: celdas (cada una con su resultado, G7) | registro, redimensionable por el usuario.
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(12)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.editor_card)
        self.splitter.addWidget(self.log_section)
        for index, stretch in enumerate((8, 2)):
            self.splitter.setStretchFactor(index, stretch)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)  # el registro sí se puede plegar
        layout.addWidget(self.splitter, 1)
        self.bottom = QVBoxLayout()  # panel acoplado: «Cargar en QGIS ▾» a todo el ancho
        self.bottom.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.bottom)
        self._place_load_button(wide=True)

        self._connect_actions()
        self._unsubscribe = coordinator.subscribe(self._on_event)
        self._render(coordinator.state)

    def _connect_actions(self) -> None:
        self.run_all_button.clicked.connect(self.run_notebook)
        self.cancel_button.clicked.connect(self._coordinator.cancel_current_operation)
        self.log.cellDoubleClicked.connect(self._select_logged_statement)
        self.log.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.log.customContextMenuRequested.connect(self._log_menu)
        # Atajos solo con el foco dentro del panel SQL, nunca en el resto de QGIS (§8, AT-UX-013)
        self.shortcuts = []
        for keys, slot in (
            ("Ctrl+Return", lambda: self.run_cell(self.cell)),
            ("Ctrl+Shift+Return", lambda: self.run_selection(self.cell)),
            ("Shift+Return", lambda: self.run_cell(self.cell, advance=True)),
            ("Ctrl+T", self.new_editor_tab),
            ("Ctrl+W", self.close_current_editor_tab),
            ("Ctrl+S", self.save_notebook),
            ("Ctrl+O", self.open_notebook_file),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda s=slot: s())
            self.shortcuts.append(shortcut)

    # -- cuadernos (G7 · E2; las pestañas de G6 son cuadernos de celdas) ---------------------------------

    def _build_editor_tabs(self) -> None:
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setObjectName("geoduckEditorTabs")
        self.editor_tabs.setDocumentMode(True)
        # G7 · E3: los cuadernos se eligen en la lista «Cuadernos» (ventana) o en el selector (panel)
        self.editor_tabs.tabBar().hide()
        self.notebook_list = NotebookList(
            self.editor_tabs,
            on_new=self._new_empty_tab,
            on_rename=self.rename_notebook,
            on_close=self.close_editor_tab,
        )
        self.notebook_selector = NotebookSelector(self.editor_tabs, on_new=self._new_empty_tab)
        self.notebook_menu = self._build_notebook_menu()  # Abrir, Guardar, Guardar como, recuperación
        self.notebook_list.set_menu(self.notebook_menu, on_save=self.save_notebook)
        self.notebook_selector.set_menu(self.notebook_menu)
        self.new_tab_button = self.notebook_list.new_button
        self.new_editor_tab()
        # Después del primer cuaderno: `_render` necesita la barra de acciones, que aún no existe
        self.editor_tabs.currentChanged.connect(lambda _i: self._render(self._coordinator.state))
        self.editor_tabs.currentChanged.connect(lambda _i: self._refresh_notebooks())

    def _new_empty_tab(self) -> None:
        self.new_editor_tab()

    def _refresh_notebooks(self) -> None:
        self.notebook_list.refresh()
        self.notebook_selector.refresh()
        title = getattr(self, "notebook_title", None)
        if title is not None:
            title.setText(self.editor_tabs.tabText(self.editor_tabs.currentIndex()))

    def rename_notebook(self, index: int, name: str) -> None:
        """Renombrar un cuaderno (lista «Cuadernos»): solo su nombre; nada se guarda en disco."""
        view = self.editor_tabs.widget(index)
        name = name.strip()
        if isinstance(view, NotebookView) and name:
            view.notebook.name = name
            self.editor_tabs.setTabText(index, name)
            self.editor_tabs.setTabToolTip(index, view.notebook.path or name)
        self._refresh_notebooks()
        self._schedule_save()

    @property
    def notebook_view(self) -> NotebookView:
        """Cuaderno de la pestaña activa (siempre hay uno)."""
        return self.editor_tabs.currentWidget()

    def notebook_views(self) -> list[NotebookView]:
        return [self.editor_tabs.widget(i) for i in range(self.editor_tabs.count())]

    @property
    def cell(self) -> CellWidget:
        """Celda activa del cuaderno activo (siempre hay una)."""
        active = self.notebook_view.active
        assert active is not None
        return active

    def cell_widgets(self) -> list[CellWidget]:
        return [w for view in self.notebook_views() for w in view.cell_widgets()]

    @property
    def editor(self) -> Any:
        """Editor de la celda activa."""
        return self.cell.editor

    @property
    def results(self) -> QTabWidget:
        """Resultados de la celda activa (una pestaña por sentencia, como G2)."""
        return self.cell.results

    @property
    def results_stack(self) -> QStackedWidget:
        return self.cell.results_stack

    @property
    def empty_results(self) -> QLabel:
        return self.cell.empty_results

    @property
    def load_button(self) -> QToolButton:
        """«Cargar en QGIS ▾» de la celda activa."""
        return self.cell.load_button

    @property
    def load_menu(self) -> QMenu:
        return self.cell.load_menu

    @property
    def completer(self) -> SqlCompleter:
        return self._completers[id(self.editor)]

    def editors(self) -> list[Any]:
        return [w.editor for w in self.cell_widgets()]

    def _make_editor(self) -> Any:
        editor = QgsCodeEditorSQL()
        editor.setAccessibleName(tr("SQL editor"))
        editor.setMinimumHeight(40)
        editor.setLineNumbersVisible(True)  # números de línea, como la DuckDB UI (QGIS 3.34+ y 4.x)
        # Ctrl+T/W: cuadernos; Mayús+Intro: ejecutar la celda; Ctrl+E y Ctrl+↑/↓: celdas (G6, G7)
        _free_keys(editor, ("Ctrl+T", "Ctrl+W", "Shift+Return", "Ctrl+E", "Ctrl+Up", "Ctrl+Down"))
        self._completers[id(editor)] = SqlCompleter(editor, self._coordinator)  # G6 · E2
        self._color_editor(editor)
        return editor

    def new_editor_tab(self, text: str = "", notebook: Notebook | None = None) -> Any:
        """Cuaderno nuevo, activo, con una celda con el foco; `text`, su SQL (p. ej. del registro), o
        `notebook` ya hecho (abierto de un archivo o recuperado). Devuelve el editor de su primera celda."""
        catalog = self._coordinator.catalog
        if notebook is None:
            self._editor_numbers += 1
            name = tr("Query {0}").format(self._editor_numbers)
            database = catalog.root if catalog is not None else None  # la raíz de la sesión
            notebook = Notebook(name, [Cell(sql=text, database=database)])
        name = notebook.name
        view = NotebookView(notebook, self._make_editor)
        view.changed.connect(self._schedule_save)
        view.confirm_delete = lambda w: self.confirm_close(tr("This cell"))
        view.run_requested.connect(self.run_cell)
        view.active_changed.connect(lambda _w: self._render(self._coordinator.state))
        view.cell_created.connect(self._setup_cell)
        for widget in view.cell_widgets():
            self._setup_cell(widget)
        view.show_databases(catalog)
        index = self.editor_tabs.addTab(view, name)
        self.editor_tabs.setTabToolTip(index, notebook.path or name)
        self.editor_tabs.setCurrentIndex(index)
        self._refresh_notebooks()
        self._schedule_save()
        editor = view.cell_widgets()[0].editor
        editor.setFocus()
        return editor

    def _setup_cell(self, widget: CellWidget) -> None:
        """Botones de la celda que dependen del panel: «Cargar en QGIS ▾» (inventario V29) y «Copiar»."""
        button = QToolButton()
        button.setObjectName("geoduckLoadButton")
        button.setProperty("geoduck", "load")
        button.setIcon(QgsApplication.getThemeIcon("mActionAddLayer.svg"))
        button.setText(tr("Load"))  # corto, como la celda; la ayuda y el nombre accesible lo dicen entero
        button.setToolTip(tr("Loads the full result as a QGIS layer"))
        button.setAccessibleName(tr("Load into QGIS"))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        menu = QMenu(button)
        menu.setObjectName("geoduckLoadMenu")
        button.setMenu(menu)
        button.clicked.connect(lambda _c=False, w=widget: self._load_cell(w))
        menu.aboutToShow.connect(lambda w=widget: self._fill_load_menu(self._cell_view(w), w.load_menu))
        widget.load_button, widget.load_menu = button, menu
        widget.load_slot.addWidget(button)
        # «Exportar ▾» (G7 · E3): la consulta completa, nunca la vista previa
        export = QToolButton()
        export.setObjectName("geoduckExportButton")
        export.setIcon(QgsApplication.getThemeIcon("mActionFileSaveAs.svg"))
        export.setText(tr("Export"))
        export.setToolTip(tr("Exports the full query to CSV or Parquet (not only the preview)"))
        export.setAccessibleName(tr("Export the result"))
        export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        export_menu = QMenu(export)
        for fmt, text in ((ExportFormat.CSV, tr("CSV…")), (ExportFormat.PARQUET, tr("Parquet…"))):
            action = export_menu.addAction(text)
            action.setObjectName(f"geoduckExport_{fmt.value}")
            action.triggered.connect(lambda _c=False, w=widget, f=fmt: self.export_cell(w, f))
        export.setMenu(export_menu)
        widget.export_button = export
        widget.load_slot.insertWidget(0, export)
        widget.results.currentChanged.connect(lambda _i: self._render(self._coordinator.state))
        # ▶ ▾, como la DuckDB UI: celda, selección, celda y avanzar
        for text, slot in (
            (tr("Run cell (Ctrl+Enter)"), lambda w=widget: self.run_cell(w)),
            (tr("Run selection (Ctrl+Shift+Enter)"), lambda w=widget: self.run_selection(w)),
            (tr("Run cell and advance (Shift+Enter)"), lambda w=widget: self.run_cell(w, advance=True)),
        ):
            action = widget.run_menu.addAction(text)
            action.triggered.connect(lambda _c=False, s=slot: s())
        catalog = self._coordinator.catalog  # el selector de base, ya al crear la celda (no al ejecutarla)
        widget.show_databases(catalog)
        self._render_cell(widget, self._coordinator.state)

    def close_current_editor_tab(self) -> bool:
        return self.close_editor_tab(self.editor_tabs.currentIndex())

    def close_editor_tab(self, index: int) -> bool:
        """Cierra un cuaderno: con SQL, pregunta antes; con una celda ejecutándose, no se cierra. Si era el
        último, queda uno vacío."""
        view = self.editor_tabs.widget(index)
        if view is None:
            return False
        name = self.editor_tabs.tabText(index)
        widgets = view.cell_widgets()
        if self._running and self._run_cell in widgets:
            self._on_message(tr("«{0}» is running: wait for it to finish or cancel it.").format(name))
            return False
        if any(w.cell.sql.strip() for w in widgets) and not self.confirm_close(name):
            return False
        self.editor_tabs.removeTab(index)
        editors = {id(w.editor) for w in widgets}
        for key in editors:
            self._completers.pop(key, None)
        self._run_editors = {k: e for k, e in self._run_editors.items() if id(e) not in editors}
        self._run_cells = {k: w for k, w in self._run_cells.items() if w not in widgets}
        view.deleteLater()
        if self.editor_tabs.count() == 0:
            self.new_editor_tab()
        self._refresh_notebooks()
        self._schedule_save()
        return True

    # -- cuadernos en disco (ADR-0014) --------------------------------------------------------------------

    def _setup_runner(self, coordinator: SessionCoordinator) -> None:
        self.runner = NotebookRunner(coordinator, coordinator.dispatcher)
        self.runner.on_start = self._cell_started
        self.runner.on_cell = self._cell_done

    def _setup_notebook_files(self) -> None:
        """Archivo `.sql` elegido por el usuario y copia de recuperación. Los diálogos (ruta sugerida → ruta,
        o "" si se cancela) y la pregunta de recuperar, sustituibles en las pruebas."""
        self.choose_save_path: Callable[[str], str] = self._ask_save_path
        self.choose_open_path: Callable[[str], str] = self._ask_open_path
        self.ask_recover: Callable[[int], bool] = self._ask_recover
        self.recovery = RecoveryStore()
        self.recovery_enabled = bool(QgsSettings().value(RECOVERY_SETTING, True, type=bool))
        self._notebook_dir = ""
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_MS)
        self._save_timer.timeout.connect(self._autosave)

    def save_notebook(self, index: int | None = None, *, choose: bool = False) -> bool:
        """«Guardar cuaderno» (Ctrl+S) en su archivo; sin archivo, o con «Guardar como…», pide uno."""
        index = self.editor_tabs.currentIndex() if index is None else index
        view = self.editor_tabs.widget(index)
        if not isinstance(view, NotebookView):
            return False
        notebook = view.notebook
        path = notebook.path
        if choose or not path:
            folder = Path(self._notebook_dir or (Path(path).parent if path else Path.home()))
            path = self.choose_save_path(str(folder / (_file_name(notebook.name) + NOTEBOOK_SUFFIX)))
            if not path:
                return False
            if not path.lower().endswith(NOTEBOOK_SUFFIX):
                path += NOTEBOOK_SUFFIX
        try:
            save_notebook(notebook, path)
        except OSError as exc:
            self._on_message(tr("Cannot save the notebook: {0}").format(exc))
            return False
        notebook.path = path
        self._notebook_dir = str(Path(path).parent)
        self.rename_notebook(index, Path(path).stem)  # el cuaderno se llama como su archivo
        self._on_message(tr("Notebook saved in {0}; from now on it is saved by itself").format(path))
        return True

    def open_notebook_file(self, path: str = "") -> bool:
        """«Abrir cuaderno…» (Ctrl+O): un `.sql` con marcas de celda, o cualquier `.sql` como una celda."""
        path = path or self.choose_open_path(self._notebook_dir or str(Path.home()))
        if not path:
            return False
        for i, view in enumerate(self.notebook_views()):
            if view.notebook.path and Path(view.notebook.path).resolve() == Path(path).resolve():
                self.editor_tabs.setCurrentIndex(i)  # ya abierto: se muestra
                return True
        try:
            notebook = open_notebook(path)
        except (OSError, UnicodeDecodeError) as exc:
            self._on_message(tr("Cannot open the notebook: {0}").format(exc))
            return False
        self._notebook_dir = str(Path(path).parent)
        self._add_notebook(notebook)
        return True

    def _add_notebook(self, notebook: Notebook) -> None:
        """Abre `notebook`; si solo había un cuaderno vacío y sin archivo, lo sustituye."""
        views = self.notebook_views()
        empty = (
            len(views) == 1
            and not views[0].notebook.path
            and not any(c.sql.strip() for c in views[0].notebook.cells)
        )
        self.new_editor_tab(notebook=notebook)
        if empty:
            self.close_editor_tab(0)

    def _schedule_save(self) -> None:
        if hasattr(self, "_save_timer"):
            self._save_timer.start()

    def _autosave(self) -> None:
        """Tras cada cambio: los cuadernos con archivo, en su archivo; todos, en la copia de recuperación."""
        notebooks = [view.notebook for view in self.notebook_views()]
        for notebook in notebooks:
            if notebook.path:
                try:
                    save_notebook(notebook, notebook.path)
                except OSError as exc:
                    self._on_message(tr("Cannot save «{0}»: {1}").format(notebook.name, exc))
        if self.recovery_enabled:
            try:
                self.recovery.save(notebooks)
            except OSError as exc:
                self._on_message(tr("Cannot write the recovery copy: {0}").format(exc))

    def set_recovery_enabled(self, enabled: bool) -> None:
        """«Copia de recuperación» (por defecto, sí). Al apagarla, se borra la copia de esta sesión."""
        self.recovery_enabled = enabled
        QgsSettings().setValue(RECOVERY_SETTING, enabled)
        self.recovery_action.setChecked(enabled)
        if enabled:
            self._autosave()
        else:
            self.recovery.stop()

    def check_recovery(self) -> None:
        """Al abrir GeoDuck: si QGIS se cerró sin borrar su copia (fallo o cuelgue), ofrece recuperarla."""
        orphans = self.recovery.orphans()
        if not orphans:
            return
        notebooks = [notebook for folder in orphans for notebook in RecoveryStore.read(folder)]
        if notebooks and self.ask_recover(len(notebooks)):
            for notebook in notebooks:
                self._add_notebook(notebook)
            count = len(notebooks)
            self._on_message(
                tr("Notebook recovered") if count == 1 else tr("{0} notebooks recovered").format(count)
            )
        for folder in orphans:
            RecoveryStore.discard(folder)
        self._schedule_save()

    def _ask_recover(self, count: int) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("Recover notebooks"))
        question = (
            tr("GeoDuck did not close properly. Recover its notebook?")
            if count == 1
            else tr("GeoDuck did not close properly. Recover its {0} notebooks?").format(count)
        )
        box.setText(question)
        recover = box.addButton(tr("Recover"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Discard"), QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        return box.clickedButton() is recover

    def _ask_save_path(self, suggested: str) -> str:
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("Save notebook"), suggested, tr("SQL notebooks (*.sql)")
        )
        return str(path)

    def _ask_open_path(self, folder: str) -> str:
        path, _filter = QFileDialog.getOpenFileName(
            self, tr("Open notebook"), folder, tr("SQL notebooks (*.sql);;All files (*)")
        )
        return str(path)

    def _build_notebook_menu(self) -> QMenu:
        """«⋯» de «Cuadernos» (ventana) y del selector (panel)."""
        menu = QMenu(self)
        menu.setObjectName("geoduckNotebookMenu")
        for text, keys, slot in (
            (tr("Open notebook…"), "Ctrl+O", self.open_notebook_file),
            (tr("Save notebook"), "Ctrl+S", self.save_notebook),
            (tr("Save notebook as…"), "", lambda: self.save_notebook(choose=True)),
        ):
            action = menu.addAction(text)
            if keys:  # solo se muestra: el atajo real es del panel
                action.setShortcut(QKeySequence(keys))
                action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            action.triggered.connect(lambda _c=False, s=slot: s())
        menu.addSeparator()
        self.recovery_action = menu.addAction(tr("Recovery copy if QGIS closes unexpectedly"))
        self.recovery_action.setCheckable(True)
        self.recovery_action.setChecked(self.recovery_enabled)
        self.recovery_action.setToolTip(
            tr("Keeps a copy of the SQL of every notebook in the QGIS profile; deleted when QGIS closes")
        )
        self.recovery_action.toggled.connect(self.set_recovery_enabled)
        return menu

    def _ask_close(self, name: str) -> bool:
        answer = QMessageBox.question(
            self,
            tr("Close tab"),
            tr("«{0}» has SQL that will be lost when closing it. Close it?").format(name),
        )
        return answer == QMessageBox.StandardButton.Yes

    # -- construcción ------------------------------------------------------------------------------

    def _color_editor(self, editor: Any) -> None:
        """Palabras clave en el color de la paleta, solo en este editor (inventario §0.3)."""
        lexer = editor.lexer()
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
        # El resumen del resultado (GD-NB-004) es la ayuda ⓘ del rótulo de cada celda, en ventana y panel
        # (decisión del propietario, 2026-11-03: sin columna derecha)
        box.addWidget(self.editor_tabs, 1)
        box.addWidget(self._build_cell_foot())  # solo en el panel
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
        """Panel estrecho: se ocultan los atajos de los botones; ninguna acción se
        quita (ui-ux-spec §8). El atajo sigue en la ayuda de cada botón."""
        for button in self.action_buttons:
            button.set_hint_visible(not compact)
        self.compact = compact

    def _build_actions(self) -> QHBoxLayout:
        self.run_all_button = HintButton(tr("Run all"), "", "primary", "▶")
        self.run_all_button.setToolTip(tr("Runs every cell of the notebook, in order"))
        self.cancel_button = HintButton(tr("Cancel"))
        self.cancel_button.setToolTip(tr("Cancels the running execution"))
        self.action_buttons = (
            self.run_all_button,
            self.cancel_button,
        )
        self.compact = False
        actions = QHBoxLayout()
        actions.setSpacing(8)
        # Ventana: ◫ pliega la barra lateral «Cuadernos + Bases de datos» (Ctrl+B; propietario, 2026-11-03)
        self.sidebar_button = QToolButton()
        self.sidebar_button.setObjectName("geoduckSidebarButton")
        self.sidebar_button.setText("◫")
        self.sidebar_button.setCheckable(True)
        self.sidebar_button.setChecked(True)
        self.sidebar_button.setAutoRaise(True)
        self.sidebar_button.setToolTip(tr("Shows or hides the side bar: notebooks and databases (Ctrl+B)"))
        self.sidebar_button.setAccessibleName(tr("Side bar"))
        actions.addWidget(self.sidebar_button)
        # Maqueta G7: a la izquierda, el nombre del cuaderno (ventana) o su selector (panel)
        self.notebook_title = QLabel("")
        self.notebook_title.setObjectName("geoduckNotebookTitle")
        title_font = self.notebook_title.font()
        title_font.setBold(True)
        self.notebook_title.setFont(title_font)
        actions.addWidget(self.notebook_title)
        actions.addWidget(self.notebook_selector, 1)  # solo en el panel (`set_presentation`)
        actions.addStretch(1)
        for button in self.action_buttons:
            actions.addWidget(button)
        return actions

    def _place_load_button(self, *, wide: bool) -> None:
        """Ventana: «Copiar», «Exportar ▾» y «Cargar ▾» en cada celda. Panel (minimalista, maqueta G7): al
        pie, para la celda activa."""
        self.cell_foot.setVisible(not wide)

    def _build_cell_foot(self) -> QWidget:
        self.cell_foot = QWidget()
        self.cell_foot.setObjectName("geoduckCellFoot")
        row = QHBoxLayout(self.cell_foot)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.foot_export = QToolButton()
        self.foot_export.setIcon(QgsApplication.getThemeIcon("mActionFileSaveAs.svg"))
        self.foot_export.setText(tr("Export"))
        self.foot_export.setToolTip(tr("Exports the full query to CSV or Parquet (not only the preview)"))
        self.foot_export.setAccessibleName(tr("Export the result"))
        self.foot_export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.foot_export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        export_menu = QMenu(self.foot_export)
        for fmt, text in ((ExportFormat.CSV, tr("CSV…")), (ExportFormat.PARQUET, tr("Parquet…"))):
            action = export_menu.addAction(text)
            action.triggered.connect(lambda _c=False, f=fmt: self.export_cell(self.cell, f))
        self.foot_export.setMenu(export_menu)
        self.foot_load = QToolButton()
        self.foot_load.setProperty("geoduck", "load")
        self.foot_load.setIcon(QgsApplication.getThemeIcon("mActionAddLayer.svg"))
        self.foot_load.setText(tr("Load into QGIS"))
        self.foot_load.setToolTip(tr("Loads the full result as a QGIS layer"))
        self.foot_load.setAccessibleName(tr("Load into QGIS"))
        self.foot_load.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.foot_load.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.foot_load.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        load_menu = QMenu(self.foot_load)
        self.foot_load.setMenu(load_menu)
        self.foot_load.clicked.connect(lambda _c=False: self._load_cell(self.cell))
        load_menu.aboutToShow.connect(lambda: self._fill_load_menu(self.current_view(), load_menu))
        row.addWidget(self.foot_export)
        row.addWidget(self.foot_load, 1)
        self.cell_foot.hide()
        return self.cell_foot

    def _build_log_card(self) -> QFrame:
        frame = card(name="geoduckLogCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 10, 12, 8)
        box.setSpacing(6)
        header = QHBoxLayout()
        header.setSpacing(8)
        # Ventana: plegado por defecto, una línea con sus cifras (decisión del propietario, 2026-11-03)
        self.log_toggle = QToolButton()
        self.log_toggle.setObjectName("geoduckLogToggle")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setAutoRaise(True)
        self.log_toggle.setAccessibleName(tr("Show the log"))
        self.log_toggle.setToolTip(tr("Shows or hides the log of the session"))
        self.log_toggle.toggled.connect(self.set_log_open)
        header.addWidget(self.log_toggle)
        self.log_title = bold(QLabel(tr("Log")))
        header.addWidget(self.log_title)
        header.addWidget(self._build_log_filters())
        header.addStretch(1)
        box.addLayout(header)
        box.addWidget(self.log, 1)
        self.log_open = True
        self.set_log_open(False)
        return frame

    def set_log_open(self, open_: bool) -> None:
        """Registro abierto (la tabla) o plegado (solo su línea con «Todo / OK / Error»). En el panel, el
        registro va en su pestaña y siempre está abierto."""
        open_ = open_ or not getattr(self, "_log_foldable", True)
        changed = open_ != self.log_open
        self.log_open = open_
        self.log.setVisible(open_)
        self.log_toggle.blockSignals(True)
        self.log_toggle.setChecked(open_)
        self.log_toggle.blockSignals(False)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        self.log_toggle.setAccessibleName(tr("Hide the log") if open_ else tr("Show the log"))
        section = getattr(self, "log_section", None)
        if section is not None:
            section.setMaximumHeight(16777215 if open_ else section.minimumSizeHint().height())
        if changed:
            self.log_open_changed.emit(open_)

    def set_presentation(self, *, wide: bool, tabs: QTabWidget | None = None) -> None:
        """Ventana (`wide`): registro debajo (plegable) y «Cargar en QGIS ▾» junto a las pestañas. Panel: el
        registro en la pestaña «Registro» de `tabs`, «Cargar en QGIS ▾» al pie y títulos compactos. Los
        mismos widgets."""
        if wide:
            self.splitter.addWidget(self.log_section)  # addWidget lo saca de la pestaña
            self.splitter.setStretchFactor(1, 2)
            self.splitter.setCollapsible(1, True)
            self.log_title.show()
            self._log_foldable = True
            self.log_toggle.show()
            self.set_log_open(self._log_open_wide)
        elif tabs is not None:
            if self._log_foldable:
                self._log_open_wide = self.log_open  # al volver a la ventana, como estaba
            tabs.insertTab(2, self.log_section, tr("Log"))
            self.log_title.hide()  # el título ya está en la pestaña
            self._log_foldable = False
            self.log_toggle.hide()
            self.set_log_open(True)
        self.short_titles = not wide
        self.notebook_selector.setVisible(not wide)  # en la ventana, la lista «Cuadernos» (columna izquierda)
        self.notebook_title.setVisible(wide)
        self.sidebar_button.setVisible(wide)
        self._place_load_button(wide=wide)
        self._retitle()
        self._render(self._coordinator.state)  # p. ej. el «ⓘ» del rótulo del resultado en el panel

    def dock_log(self, tabs: QTabWidget | None) -> None:  # compatibilidad con E4
        self.set_presentation(wide=tabs is None, tabs=tabs)

    def _retitle(self) -> None:
        palette = self._palette
        for cell in self.cell_widgets():
            results = cell.results
            for i in range(results.count()):
                view = results.widget(i)
                if isinstance(view, (ResultView, ErrorView)):
                    results.setTabText(i, view.tab_text(self.short_titles))
                    if isinstance(view, ErrorView):
                        results.tabBar().setTabTextColor(i, theme.color(palette.error))

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
            button.clicked.connect(lambda _c=False: self.set_log_open(True))  # filtrar abre el registro
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
            ("all", tr("All"), total),
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
        self.log.setToolTip(
            tr("Double-click: select the statement in the editor")
            + "\n"
            + tr("Right-click: open its SQL in a new tab")
        )
        self.log.setAccessibleName(tr("Execution log"))
        self.log.setMinimumHeight(48)

    # -- acciones ----------------------------------------------------------------------------------

    # -- celdas (G7 · E2): todas, una celda o la selección de una celda -----------------------------------

    def run_notebook(self) -> None:
        """«Ejecutar todo»: todas las celdas del cuaderno, en orden, cada una con su base."""
        if self._coordinator.state is SessionState.READY:
            self.runner.run(
                [w.cell for w in self.notebook_view.cell_widgets()],
                preview_limit=DEFAULT_PREVIEW_LIMIT,
            )

    def run_cell(self, widget: CellWidget, *, advance: bool = False) -> None:
        """▶ de la celda (Ctrl+Intro): toda la celda con su base. `advance` (Mayús+Intro): pasa a la
        siguiente (la crea si es la última), como la DuckDB UI."""
        if self._coordinator.state is not SessionState.READY:
            return
        view = self.notebook_view
        view.set_active(widget)
        self.runner.run([widget.cell], preview_limit=DEFAULT_PREVIEW_LIMIT)
        if advance:
            cells = view.cell_widgets()
            index = cells.index(widget)
            target = cells[index + 1] if index + 1 < len(cells) else view.add_cell(len(cells))
            view.set_active(target)
            target.editor.setFocus()

    def _cell_started(self, cell: Cell, run_id: int) -> None:
        widget = next((w for w in self.cell_widgets() if w.cell is cell), None)
        if widget is None:
            return
        widget.editor.clearWarnings()
        self._clear_results(widget)
        self._run_text = widget.editor.text()
        self._run_editor = widget.editor
        self._run_cell = widget
        self._run_cells[run_id] = widget
        self._run_editors[run_id] = widget.editor
        self._running = True

    def _cell_done(self, outcome: CellOutcome) -> None:
        if outcome.error is not None and not outcome.notified:
            self._on_message(outcome.error)  # p. ej. la base de la celda ya no está adjunta

    def run_selection(self, widget: CellWidget) -> None:
        """«Ejecutar selección» (Ctrl+Mayús+Intro): solo el texto seleccionado de la celda, con su base."""
        if self._coordinator.state is not SessionState.READY or self.runner.running:
            return
        self.notebook_view.set_active(widget)
        if not widget.editor.hasSelectedText():
            self._on_message(tr("Select the SQL to run first"))
            return
        problem = widget.cell.database_problem(self._coordinator.catalog)
        if problem is not None:
            self._on_message(problem)
            return
        editor = widget.editor  # la ejecución queda ligada a esta celda
        full_text = editor.text()
        line_from, index_from, _l, _i = editor.getSelection()
        base = offset_from(full_text, line_from, index_from)
        text = editor.selectedText()
        if not text.strip():
            return
        editor.clearWarnings()
        self._clear_results(widget)
        self._run_text = full_text
        self._run_editor = editor
        self._run_cell = widget
        self._running = True
        try:
            run_id = self._coordinator.execute_sql(
                text,
                RunScope.SELECTION,
                base=base,
                preview_limit=DEFAULT_PREVIEW_LIMIT,
                database=widget.cell.database,
            )
            self._run_editors[run_id] = editor
            self._run_cells[run_id] = widget
        except GeoDuckError as exc:  # p. ej. DETACH con capas Conectadas sin guardar (§5.5)
            self._running = False
            self._on_message(exc.message)

    def detach(self) -> None:
        """Al descargar GeoDuck (también al cerrar QGIS): lo pendiente a sus archivos y se borra la copia."""
        self._unsubscribe()
        self._save_timer.stop()
        for notebook in (view.notebook for view in self.notebook_views()):
            if notebook.path:
                with contextlib.suppress(OSError):
                    save_notebook(notebook, notebook.path)
        self.recovery.stop()

    # -- eventos -----------------------------------------------------------------------------------

    def _on_event(self, event: AppEvent) -> None:
        if isinstance(event, (ColumnsListed, VocabularyChanged)):
            self.completer.refresh()
        elif isinstance(event, CatalogChanged):
            self._coordinator.vocabulary()  # se pide ya, para que el autocompletado lo tenga a tiempo
            for view in self.notebook_views():
                view.show_databases(event.catalog)
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
        elif isinstance(event, (ExportFinished, ExportFailed)):
            self._on_export_done(event)
        elif isinstance(event, ScriptRejected):
            self._running = False
            self._on_message(f"[{event.code.value}] {event.message}")

    def _on_statement(self, event: StatementFinished) -> None:
        result = event.result
        cell = self._cell_for(event.run_id)
        title = result_title(self._run_text, result.statement)
        self._statements[(event.run_id, result.statement.index)] = result.statement
        self._add_log(event, title)
        tab: ResultView | ErrorView | None = None
        if result.preview is not None:
            tab = ResultView(event, title)
            tab.load_button = cell.load_button
            tab.load_menu = cell.load_menu
        elif result.status is StatementStatus.FAILED:
            tab = ErrorView(event, title)
            tab.go_button.clicked.connect(lambda _c=False, k=tab.key: self._select_statement(k))
        if tab is not None:
            results = cell.results
            index = results.addTab(tab, tab.tab_text(self.short_titles))
            results.setTabToolTip(index, result.statement.text.strip()[:500])
            if isinstance(tab, ErrorView):
                results.tabBar().setTabTextColor(index, theme.color(self._palette.error))
            cell.show_result_area()
        if result.status is StatementStatus.FAILED and result.error_offset is not None:
            self._point_error(result.error_offset, result.message)
        self._render(self._coordinator.state)

    def _on_script(self, event: ScriptFinished) -> None:
        run = event.run
        cell = self._cell_for(run.run_id)
        if run.run_id in self._run_cells and not self.runner.running:
            # «Ejecutar selección» en la celda: sigue al `USE` escrito en ella. Lo que se
            # ejecuta fuera del panel (p. ej. el explorador) no cambia la base de ninguna celda.
            cell.cell.follow_use(run.current_database, self._coordinator.catalog)
        self._summarize(cell, run)
        if run.parse_error:
            self._on_message(tr("Syntax error: nothing was run.") + f" {run.parse_error}")
            if run.parse_error_offset is not None:
                self._point_error(run.parse_error_offset, run.parse_error)
        elif run.failed:
            failed = next(r for r in run.results if r.status is not StatementStatus.OK)
            code = failed.error_code.value if failed.error_code else ""
            self._on_message(f"[{code}] {failed.message}")
        if cell.results.count():
            cell.results.setCurrentIndex(cell.results.count() - 1)
        catalog = self._coordinator.catalog
        cell.show_databases(catalog)
        self._render_cell(cell, self._coordinator.state)  # resumen y su «ⓘ»

    def _cell_for(self, run_id: int) -> CellWidget:
        """La celda donde se pidió la ejecución `run_id`; si ya se cerró, la activa."""
        cell = self._run_cells.get(run_id)
        return cell if cell is not None and self._cell_of(cell.editor) is not None else self.cell

    def _summarize(self, cell: CellWidget, run: ScriptRun) -> None:
        """«N filas en X ms» (con varias sentencias, «N filas · K sentencias en X ms»), como la DuckDB UI."""
        ran = [r for r in run.results if r.status is not StatementStatus.SKIPPED]
        duration = sum(r.duration_ms for r in ran)
        last = next((r for r in reversed(ran) if r.preview is not None), None)
        if last is None or last.preview is None:
            text = tr("{0} ms").format(f"{duration:.0f}")
        else:
            rows = len(last.preview.rows)
            count = f"{rows}+" if last.preview.truncated else str(rows)
            text = (tr("{0} row") if count == "1" else tr("{0} rows")).format(count)
        if len(ran) > 1:
            text += " · " + tr("{0} statements").format(len(ran))
        if last is not None:
            text += " · " + tr("{0} ms").format(f"{duration:.0f}")
        cell.status_label.setText(text)
        cell.show_result_area()

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
                item.setToolTip(tr("Run {} · statement {}").format(event.run_id, r.statement.index + 1))
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
        """Selecciona la sentencia en la pestaña donde se ejecutó (si sigue abierta), y pasa a ella."""
        statement = self._statements.get(key)
        editor = self._run_editors.get(key[0])
        cell = self._cell_of(editor)
        if statement is None or editor is None or cell is None:
            return
        text = editor.text()
        if statement.end > len(text):
            return
        self._show_cell(cell)
        start = statement.start + len(statement.text) - len(statement.text.lstrip())
        editor.setSelection(*line_index_from(text, start), *line_index_from(text, statement.end))
        editor.setFocus()

    def _cell_of(self, editor: object) -> CellWidget | None:
        """La celda (de cualquier cuaderno abierto) que contiene `editor`; None si se cerró."""
        return next((w for w in self.cell_widgets() if w.editor is editor), None)

    def _show_cell(self, cell: CellWidget) -> None:
        for view in self.notebook_views():
            if view.widget_for(cell.cell) is cell:
                self.editor_tabs.setCurrentWidget(view)
                view.set_active(cell)
                view.ensureWidgetVisible(cell)
                return

    def _point_error(self, offset: int, message: str) -> None:
        editor = self._run_editor if self._cell_of(self._run_editor) is not None else self.editor
        line, index = line_index_from(editor.text(), offset)
        editor.addWarning(line, message)
        editor.setCursorPosition(line, index)

    # -- historial de la sesión (G6 · E3): «Abrir en el editor» desde el registro ---------------------

    def logged_sql(self, row: int) -> str | None:
        """SQL que ejecutó la fila `row` del registro (solo en memoria, mientras dure el panel): el texto que
        delimitó DuckDB, sin los espacios de los extremos ni el `;` final (DuckDB 1.5 y 2.0 no lo incluyen
        igual), para que sea el mismo en cualquier versión."""
        item = self.log.item(row, 0)
        key = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        statement = self._statements.get(tuple(key)) if key else None
        if statement is None:
            return None
        text = statement.text.strip()
        return text[:-1].rstrip() if text.endswith(";") else text

    def open_logged_sql(self, row: int) -> Any:
        """Copia el SQL de la fila a una pestaña nueva, sin ejecutarlo."""
        sql = self.logged_sql(row)
        return self.new_editor_tab(sql) if sql else None

    def _log_menu(self, pos: Any) -> None:
        item = self.log.itemAt(pos)
        if item is None or self.logged_sql(item.row()) is None:
            return
        menu = QMenu(self)
        action = menu.addAction(tr("Open in the editor"))
        action.setToolTip(tr("Copies this SQL to a new tab, without running it"))
        row = item.row()
        action.triggered.connect(lambda: self.open_logged_sql(row))
        menu.exec(self.log.viewport().mapToGlobal(pos))

    def _clear_results(self, cell: CellWidget) -> None:
        results = cell.results
        while results.count():
            widget = results.widget(0)
            results.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        cell.results_stack.setCurrentWidget(cell.empty_results)
        cell.status_label.setText("")

    @staticmethod
    def _cell_view(cell: CellWidget) -> ResultView | None:
        view = cell.results.currentWidget()
        return view if isinstance(view, ResultView) else None

    def current_view(self) -> ResultView | None:
        notebook = self.editor_tabs.currentWidget()  # al cerrar el último cuaderno, por un momento no hay
        if not isinstance(notebook, NotebookView) or notebook.active is None:
            return None
        return self._cell_view(notebook.active)

    def _load_current(self) -> None:
        view = self.current_view()
        if view is not None:
            self._load(view)

    # -- «Exportar ▾» (G7 · E3, GD-NB-007) ------------------------------------------------------------------

    def export_cell(self, cell: CellWidget, fmt: ExportFormat) -> None:
        """Exporta la consulta completa del resultado de la celda (solo lectura repetible), en su base."""
        view = self._cell_view(cell)
        if view is None or not view.loadable or self._coordinator.state is not SessionState.READY:
            return
        path = self.choose_export_path(fmt, _file_name(view.title) + fmt.suffix)
        if not path:
            return
        if not path.lower().endswith(fmt.suffix):
            path += fmt.suffix
        self._export_dir = str(Path(path).parent)
        self._exporting = True  # antes: al pasar a BUSY, «Cancelar» ya debe estar activo
        try:
            self._coordinator.export(ExportRequest(view.statement.text, path, fmt, view.database))
        except GeoDuckError as exc:
            self._exporting = False
            self._on_message(tr("Cannot export: ") + exc.message)
            return
        self._on_message(tr("Exporting the full query to {0}…").format(Path(path).name))

    def _ask_export_path(self, fmt: ExportFormat, name: str) -> str:
        folder = self._export_dir or str(Path.home())
        pattern = tr("CSV files (*.csv)") if fmt is ExportFormat.CSV else tr("Parquet files (*.parquet)")
        path, _filter = QFileDialog.getSaveFileName(
            self, tr("Export the result"), str(Path(folder) / name), pattern
        )
        return str(path)

    def _on_export_done(self, event: ExportFinished | ExportFailed) -> None:
        self._exporting = False
        if isinstance(event, ExportFinished):
            report = event.report
            text = tr("Exported {0} rows to {1}").format(report.rows, Path(report.path).name)
            self._on_message(" ".join((text, *report.warnings)))
        elif event.cancelled:
            self._on_message(tr("Export cancelled: no file was written"))
        else:
            self._on_message(tr("Cannot export: ") + event.message)

    def _load_cell(self, cell: CellWidget) -> None:
        view = self._cell_view(cell)
        if view is not None:
            self._load(view)

    def _load(self, view: ResultView, mode: LoadMode | None = None) -> None:
        if self._load_flow is not None and view.loadable:
            self._load_flow.start(view.statement.text, view.title, mode=mode, database=view.database)

    def _fill_load_menu(self, view: ResultView | None, menu: QMenu | None = None) -> None:
        """Las tres modalidades en dos líneas; las no disponibles, desactivadas con el motivo."""
        menu = menu if menu is not None else self.load_menu
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
        """Resultados de todas las celdas de todos los cuadernos (p. ej. para marcarlos obsoletos)."""
        views = [c.results.widget(i) for c in self.cell_widgets() for i in range(c.results.count())]
        return [v for v in views if isinstance(v, ResultView)]

    def _render(self, state: SessionState) -> None:
        ready = state is SessionState.READY
        self.run_all_button.setEnabled(ready)
        foot = getattr(self, "foot_load", None)
        if foot is not None:  # pie del panel: el resultado de la celda activa
            view = self.current_view()
            loadable = view is not None and view.loadable and ready
            self.foot_load.setEnabled(loadable and self._load_flow is not None)
            self.foot_export.setEnabled(loadable)
        loading = self._load_flow is not None and self._load_flow.loading
        busy_here = self._running or loading or self._exporting
        self.cancel_button.setEnabled(state is SessionState.BUSY and busy_here)
        for cell in self.cell_widgets():
            self._render_cell(cell, state)

    def _render_cell(self, cell: CellWidget, state: SessionState) -> None:
        if cell.load_button is None:
            return
        ready = state is SessionState.READY
        view = self._cell_view(cell)
        cell.load_button.setEnabled(
            view is not None and view.loadable and ready and self._load_flow is not None
        )
        if view is not None and not view.loadable:
            cell.load_button.setToolTip(tr("Only read queries can be loaded: this statement is not repeated"))
        else:
            cell.load_button.setToolTip(tr("Loads the full result as a QGIS layer"))
        # Opción A (propietario): los botones solo con una tabla; en el panel, al pie (celda activa)
        in_cell = view is not None and not self.short_titles
        for button in (cell.export_button, cell.load_button):
            if button is not None:
                button.setVisible(in_cell)
        # Resumen (GD-NB-004): en la ayuda del rótulo; en el panel, con su «ⓘ»
        preview = view.preview if view is not None else None
        cell.status_label.setToolTip(summary_text(preview) if preview is not None else "")
        text = cell.status_label.text().removesuffix(" ⓘ")
        cell.status_label.setText(text + " ⓘ" if preview is not None and text else text)
        if cell.export_button is not None:
            cell.export_button.setEnabled(view is not None and view.loadable and ready)
        cell.run_button.setEnabled(ready)
