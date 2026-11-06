# SPDX-License-Identifier: GPL-2.0-or-later
"""Estilos de Workspace Pro generados de los tokens (workspace-pro-spec §10; ADR-0011; F-123).

La hoja se aplica **solo** a la raíz de GeoDuck (`ROOT`) y a sus hijos: nunca a QGIS. Las piezas se eligen por
la propiedad `pro` (`pro="primary"`, `pro="chip"`…), así que un widget de QGIS dentro de GeoDuck (el editor
SQL, un selector de SRC) conserva su aspecto salvo el color de texto y la fuente.

F-123: con una hoja de estilos, Qt no propaga la fuente del contenedor a sus hijos y la hoja de Qt 5 no admite
varias familias; por eso la fuente va en la regla general, con la primera familia instalada de la lista.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import QT_VERSION_STR
from qgis.PyQt.QtGui import QFont, QFontDatabase, QPalette
from qgis.PyQt.QtWidgets import QWidget

from geoduck.ui.pro import icons
from geoduck.ui.pro.tokens import DARK, FONT_FAMILIES, LIGHT, METRICS, MONO_FAMILIES, Colors

#: Nombre de objeto de la raíz de Workspace Pro: la hoja no sale de aquí.
ROOT = "geoduckPro"
#: Tamaño del editor SQL, en puntos (QScintilla no admite píxeles; 10 pt ≈ 13 px, el texto de GeoDuck).
EDITOR_POINTS = 10


def installed_families() -> set[str]:
    if QT_VERSION_STR.startswith("5"):
        return set(QFontDatabase().families())
    return set(QFontDatabase.families())


def first_family(candidates: tuple[str, ...]) -> str:
    """La primera familia instalada de la lista; si ninguna, la última (Qt elige una parecida)."""
    installed = installed_families()
    return next((name for name in candidates if name in installed), candidates[-1])


def is_dark(widget: QWidget) -> bool:
    """El tema de QGIS es oscuro si el fondo de su paleta lo es (Workspace Pro lo sigue)."""
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


def colors_for(widget: QWidget) -> Colors:
    return DARK if is_dark(widget) else LIGHT


def ui_font(size: int = METRICS.font, *, mono: bool = False, bold: bool = False) -> QFont:
    """Fuente de GeoDuck en píxeles (para pintar a mano: encabezados, grilla, avisos)."""
    font = QFont(first_family(MONO_FAMILIES if mono else FONT_FAMILIES))
    if mono:
        font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(size)
    font.setBold(bold)
    return font


def stylesheet(c: Colors) -> str:
    m = METRICS
    family = first_family(FONT_FAMILIES)
    mono = first_family(MONO_FAMILIES)
    arrow = icons.file("chevron-down", c.muted)
    closed = icons.file("chevron-right", c.faint)
    opened = icons.file("chevron-down", c.faint)
    close = icons.file("close", c.muted, 7)
    r = f"#{ROOT}"
    return f"""
{r}, {r} QWidget {{ font-family: "{family}"; font-size: {m.font}px; color: {c.text}; }}
{r} {{ background: {c.bg}; }}
{r} *[pro="side"] {{ background: {c.side}; }}
{r} *[pro="head"] {{ background: {c.head}; }}
{r} *[pro="rule-bottom"] {{ border-bottom: 1px solid {c.border}; }}
{r} *[pro="rule-top"] {{ border-top: 1px solid {c.border}; }}
{r} *[pro="rule-right"] {{ border-right: 1px solid {c.border}; }}
{r} QFrame[pro="divider"] {{ background: {c.border}; border: 0; }}
{r} *[pro="rule-left"] {{ border-left: 1px solid {c.border}; }}

{r} QLabel {{ background: transparent; }}
{r} QLabel[pro="muted"] {{ color: {c.muted}; }}
{r} QLabel[pro="faint"] {{ color: {c.faint}; font-size: {m.font_tiny}px; }}
{r} QLabel[pro="title"] {{ font-size: {m.font_title}px; font-weight: 600; }}
{r} QLabel[pro="section"] {{ color: {c.muted}; font-size: {m.font_tiny}px; font-weight: 600; }}
{r} QLabel[pro="mono"] {{ font-family: "{mono}"; font-size: {m.font_small}px; }}
{r} QLabel[pro="null"] {{ color: {c.null}; font-style: italic; }}
{r} QLabel[pro="error"] {{ color: {c.error}; }}
{r} QLabel[pro="link"] {{ color: {c.accent}; }}
{r} QLabel[pro="kbd"] {{ color: {c.faint}; font-size: {m.font_tiny}px; border: 1px solid {c.border};
    border-radius: 4px; padding: 0 4px; }}
{r} QLabel[pro="badge"] {{ color: {c.muted}; background: {c.segment}; font-size: {m.font_tiny}px;
    border-radius: 8px; padding: 1px 7px; }}

{r} QPushButton {{ min-height: {m.control - 2}px; padding: 0 {m.space_md}px; border-radius: {m.radius}px;
    border: 1px solid {c.border}; background: {c.bg}; color: {c.text}; }}
{r} QPushButton:hover {{ border-color: {c.faint}; }}
{r} QPushButton:focus {{ border-color: {c.accent}; outline: none; }}
{r} QPushButton:disabled {{ color: {c.null}; border-color: {c.line}; }}
{r} QPushButton[pro="primary"] {{ background: {c.accent_fill}; border-color: {c.accent_fill};
    color: {c.on_accent}; font-weight: 600; padding: 0 {m.space_lg - 2}px; }}
{r} QPushButton[pro="primary"]:hover {{ background: {c.accent_hover}; border-color: {c.accent_hover}; }}
{r} QPushButton[pro="primary"]:disabled {{ background: {c.segment}; border-color: {c.segment};
    color: {c.null}; }}
{r} QPushButton[pro="danger"] {{ color: {c.error}; border-color: {c.error}; }}
{r} QPushButton[pro="danger"]:hover {{ background: {c.error_soft}; }}
{r} QPushButton[pro="ghost"] {{ border: 1px solid transparent; background: transparent; color: {c.muted}; }}
{r} QPushButton[pro="ghost"]:hover {{ background: {c.segment}; color: {c.text}; }}
{r} QPushButton[pro="ghost"]:disabled {{ color: {c.null}; }}
{r} QPushButton[pro="add-chip"] {{ border: 1px dashed {c.null}; border-radius: {m.pill}px;
    background: transparent; color: {c.muted}; padding: 0 11px; }}
{r} QPushButton[pro="segment"] {{ border: 0; border-radius: {m.radius_sm}px; background: transparent;
    color: {c.muted}; min-height: {m.control - 6}px; padding: 0 {m.space_md}px; }}
{r} QPushButton[pro="segment"]:checked {{ background: {c.bg}; color: {c.text}; font-weight: 600; }}
{r} QPushButton[pro="icon"] {{ border: 1px solid transparent; background: transparent; padding: 0;
    min-width: {m.control - 2}px; max-width: {m.control - 2}px; }}
{r} QPushButton[pro="icon"]:hover {{ background: {c.segment}; }}
{r} QPushButton[pro="search-button"] {{ text-align: left; color: {c.muted}; padding: 0 {m.space_sm + 1}px; }}

{r} QFrame[pro="segmented"] {{ background: {c.segment}; border-radius: {m.radius}px; }}
{r} QFrame[pro="chip"] {{ background: {c.chip_bg}; border: 1px solid {c.chip_border};
    border-radius: {m.pill}px; }}
{r} QFrame[pro="field"] {{ background: {c.bg}; border: 1px solid {c.border}; border-radius: {m.radius}px; }}
{r} QFrame[pro="field"][focused="true"] {{ border-color: {c.accent}; }}
{r} QFrame[pro="card"] {{ background: {c.bg}; border: 1px solid {c.border}; border-radius: {m.radius_lg}px; }}
{r} QFrame[pro="toast"] {{ background: {c.toast}; border-radius: {m.radius_lg}px; }}
{r} QFrame[pro="toast"] QLabel {{ color: {c.toast_text}; }}
{r} QFrame[pro="toast"] QPushButton {{ border: 0; background: transparent; color: {c.toast_link};
    padding: 0 {m.space_xs}px; min-height: 0; }}
{r} QFrame[pro="toast"] QPushButton:hover {{ text-decoration: underline; }}

{r} QLineEdit {{ background: {c.bg}; border: 1px solid {c.border}; border-radius: {m.radius}px;
    padding: 0 {m.space_sm + 1}px; min-height: {m.control - 2}px; selection-background-color: {c.accent};
    selection-color: {c.on_accent}; }}
{r} QLineEdit:focus {{ border-color: {c.accent}; }}
{r} QLineEdit:disabled {{ color: {c.null}; }}
{r} QFrame[pro="field"]:disabled {{ background: {c.side}; border-color: {c.line}; }}
{r} QFrame[pro="field"] QLineEdit {{ border: 0; background: transparent; padding: 0; }}
{r} QComboBox {{ background: {c.bg}; border: 1px solid {c.border}; border-radius: {m.radius}px;
    padding: 0 {m.space_sm}px; min-height: {m.control - 2}px; }}
{r} QComboBox::drop-down {{ border: 0; width: 22px; }}
{r} QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
{r} QComboBox QAbstractItemView {{ background: {c.bg}; border: 1px solid {c.border};
    selection-background-color: {c.accent_soft}; selection-color: {c.text}; outline: 0; }}
{r} QCheckBox {{ spacing: {m.space_sm}px; }}

{r} QScrollBar:vertical {{ width: 10px; background: transparent; margin: 0; }}
{r} QScrollBar::handle:vertical {{ background: {c.border}; border-radius: 5px; min-height: 30px; }}
{r} QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 0; }}
{r} QScrollBar::handle:horizontal {{ background: {c.border}; border-radius: 5px; min-width: 30px; }}
{r} QScrollBar::handle:hover {{ background: {c.faint}; }}
{r} QScrollBar::add-line, {r} QScrollBar::sub-line {{ width: 0; height: 0; }}
{r} QScrollBar::add-page, {r} QScrollBar::sub-page {{ background: transparent; }}

{r} QToolTip {{ background: {c.toast}; color: {c.toast_text}; border: 0; padding: 4px 8px; }}

{r} QsciScintilla {{ font-family: "{mono}"; font-size: {EDITOR_POINTS}pt; }}
{r} QSplitter::handle {{ background: {c.border}; }}
{r} QMenu {{ background: {c.bg}; border: 1px solid {c.border}; padding: 4px; }}
{r} QMenu::item {{ padding: 6px 28px 6px 10px; border-radius: {m.radius_sm}px; }}
{r} QMenu::item:selected {{ background: {c.accent_soft}; color: {c.text}; }}
{r} QMenu::item:disabled {{ color: {c.null}; }}
{r} QMenu::separator {{ height: 1px; background: {c.line}; margin: 4px 6px; }}

{r} QTreeWidget[pro="nav"] {{ background: transparent; border: 0; outline: 0; show-decoration-selected: 1; }}
{r} QTreeWidget[pro="nav"]::item {{ min-height: 28px; border: 0; padding: 0 2px; }}
{r} QTreeWidget[pro="nav"]::item:hover {{ background: {c.segment}; }}
{r} QTreeWidget[pro="nav"]::item:selected {{ background: {c.accent_soft}; color: {c.text}; }}
{r} QTreeWidget[pro="nav"]::branch {{ background: transparent; }}
{r} QTreeWidget[pro="nav"]::branch:has-children:closed {{ image: url("{closed}"); }}
{r} QTreeWidget[pro="nav"]::branch:has-children:open {{ image: url("{opened}"); }}

{r} QTabBar[pro="tabs"] {{ background: transparent; }}
{r} QTabBar[pro="tabs"]::tab {{ height: {m.bar - 16}px; padding: 0 6px 0 12px; margin-right: 2px;
    color: {c.muted}; background: transparent; border: 1px solid transparent; border-bottom: 0;
    border-top-left-radius: {m.radius_lg}px; border-top-right-radius: {m.radius_lg}px; }}
{r} QTabBar[pro="tabs"]::tab:selected {{ color: {c.text}; background: {c.bg}; border-color: {c.border};
    font-weight: 600; }}
{r} QTabBar[pro="tabs"]::tab:hover:!selected {{ color: {c.text}; }}
{r} QTabBar[pro="tabs"]::close-button {{ image: url("{close}"); subcontrol-position: right; width: 16px;
    height: 16px; border-radius: 4px; }}
{r} QTabBar[pro="tabs"]::close-button:hover {{ background: {c.segment}; }}
{r} QTabBar[pro="tabs"] QToolButton {{ background: {c.head}; border: 0; }}

{r} QTableView[pro="grid"] {{ background: {c.bg}; border: 0; outline: 0; gridline-color: {c.line};
    selection-background-color: {c.row_selected}; selection-color: {c.text}; }}
{r} QTableView[pro="grid"]::item {{ padding: 0 10px; border-bottom: 1px solid {c.line}; }}
{r} QTableView[pro="grid"]::item:selected {{ background: {c.row_selected}; color: {c.text}; }}
{r} QTableView[pro="grid"] QHeaderView {{ background: {c.head}; }}
{r} QTableView[pro="grid"] QHeaderView::section:vertical {{ background: {c.bg}; color: {c.faint}; border: 0;
    border-bottom: 1px solid {c.line}; padding: 0 10px 0 0; font-size: {m.font_small}px; }}
{r} QTableView[pro="grid"] QTableCornerButton::section {{ background: {c.head}; border: 0;
    border-bottom: 1px solid {c.border}; }}
{r} QTableWidget[pro="list"] {{ background: {c.bg}; border: 0; outline: 0; gridline-color: {c.line}; }}
{r} QTableWidget[pro="list"]::item {{ padding: 0 10px; border-bottom: 1px solid {c.line}; }}
{r} QTableWidget[pro="list"] QHeaderView::section {{ background: {c.head}; color: {c.muted}; border: 0;
    border-bottom: 1px solid {c.border}; padding: 0 10px; height: {m.header}px; font-weight: 600; }}
{r} QPlainTextEdit[pro="code"] {{ background: {c.side}; border: 1px solid {c.border};
    border-radius: {m.radius}px; font-family: "{mono}"; font-size: {m.font_small}px; padding: 8px; }}
{r} QScrollArea[pro="plain"] {{ background: transparent; border: 0; }}
{r} QScrollArea[pro="plain"] > QWidget > QWidget {{ background: transparent; }}
{r} QFrame[pro="popup"] {{ background: {c.bg}; border: 1px solid {c.border}; }}
{r} QFrame[pro="palette"] {{ background: {c.bg}; border: 1px solid {c.border};
    border-radius: {m.radius_lg}px; }}
{r} QFrame[pro="palette"] QLineEdit {{ border: 0; background: transparent; font-size: {m.font_title}px;
    min-height: 44px; padding: 0; }}
{r} QListWidget[pro="palette-list"] {{ background: transparent; border: 0; border-top: 1px solid {c.line};
    outline: 0; }}
"""


def apply(root: QWidget) -> Colors:
    """Convierte `root` en la raíz de Workspace Pro: su nombre, su fondo y la hoja del tema de QGIS."""
    from qgis.PyQt.QtCore import Qt  # noqa: PLC0415

    root.setObjectName(ROOT)
    root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    colors = colors_for(root)
    root.setStyleSheet(stylesheet(colors))
    return colors
