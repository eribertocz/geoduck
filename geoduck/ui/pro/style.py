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
    r = f"#{ROOT}"
    return f"""
{r}, {r} QWidget {{ font-family: "{family}"; font-size: {m.font}px; color: {c.text}; }}
{r} {{ background: {c.bg}; }}
{r} *[pro="side"] {{ background: {c.side}; }}
{r} *[pro="head"] {{ background: {c.head}; }}
{r} *[pro="rule-bottom"] {{ border-bottom: 1px solid {c.border}; }}
{r} *[pro="rule-top"] {{ border-top: 1px solid {c.border}; }}
{r} *[pro="rule-right"] {{ border-right: 1px solid {c.border}; }}
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
{r} QPushButton[pro="add-chip"] {{ border: 1px dashed {c.null}; border-radius: {m.pill}px;
    background: transparent; color: {c.muted}; padding: 0 11px; }}
{r} QPushButton[pro="segment"] {{ border: 0; border-radius: {m.radius_sm}px; background: transparent;
    color: {c.muted}; min-height: {m.control - 6}px; padding: 0 {m.space_md}px; }}
{r} QPushButton[pro="segment"]:checked {{ background: {c.bg}; color: {c.text}; font-weight: 600; }}
{r} QPushButton[pro="icon"] {{ border: 1px solid transparent; background: transparent; padding: 0;
    min-width: {m.control - 2}px; max-width: {m.control - 2}px; }}
{r} QPushButton[pro="icon"]:hover {{ background: {c.segment}; }}

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
"""


def apply(root: QWidget) -> Colors:
    """Convierte `root` en la raíz de Workspace Pro: su nombre, su fondo y la hoja del tema de QGIS."""
    from qgis.PyQt.QtCore import Qt  # noqa: PLC0415

    root.setObjectName(ROOT)
    root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    colors = colors_for(root)
    root.setStyleSheet(stylesheet(colors))
    return colors
