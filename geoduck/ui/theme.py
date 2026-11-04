# SPDX-License-Identifier: GPL-2.0-or-later
"""Identidad visual de GeoDuck (docs/g5/maqueta/inventario.md §0; decisión del propietario, 2026-11-02).

Paleta corporativa medida en la maqueta (tema claro) y su variante para el tema oscuro de QGIS. La hoja de
estilo se aplica **solo a los widgets de GeoDuck** (al contenido y a sus shells), por nombre de objeto o por
la propiedad `geoduck`; nunca a la aplicación ni a la configuración de QGIS (ADR-0011). Los diálogos que
GeoDuck abre heredan solo lo que se aplica por esos selectores.
"""

from __future__ import annotations

from dataclasses import dataclass

from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QWidget


@dataclass(frozen=True)
class Palette:
    primary: str  # Verde GeoDuck: «Ejecutar», «Iniciar sesión», «Lista», «OK»
    primary_hover: str
    action: str  # Azul QGIS: «Cargar en QGIS ▾», enlaces
    action_hover: str
    error: str
    busy: str
    text: str
    muted: str
    window: str
    card: str
    header: str
    border: str
    border_soft: str
    selection: str
    chip: str
    success_bg: str
    success_border: str
    error_bg: str
    error_border: str
    keyword: str
    on_color: str  # texto sobre verde o azul


LIGHT = Palette(
    primary="#2D7A3E",
    primary_hover="#256634",
    action="#1F5FA8",
    action_hover="#1A508E",
    error="#B42318",
    busy="#9A6700",
    text="#1F2328",
    muted="#57606A",
    window="#EEF0F2",
    card="#FFFFFF",
    header="#F6F7F8",
    border="#D0D4D9",
    border_soft="#E3E6E9",
    selection="#E3EDF8",
    chip="#EEF4FB",
    success_bg="#EEF6F0",
    success_border="#B7DCC0",
    error_bg="#FBF4F3",
    error_border="#E7B8B5",
    keyword="#8250DF",
    on_color="#FFFFFF",
)

DARK = Palette(
    primary="#3FA45B",
    primary_hover="#4BB868",
    action="#4C8DDB",
    action_hover="#5E9BE3",
    error="#F06A5F",
    busy="#D4A72C",
    text="#E6EDF3",
    muted="#9198A1",
    window="#0D1117",
    card="#161B22",
    header="#1C2128",
    border="#30363D",
    border_soft="#262C34",
    selection="#1F3550",
    chip="#18283B",
    success_bg="#14261A",
    success_border="#2E5A3A",
    error_bg="#2A1715",
    error_border="#6B2C27",
    keyword="#B392F0",
    on_color="#0D1117",
)


def is_dark(widget: QWidget) -> bool:
    """El tema de QGIS es oscuro si el fondo de su paleta lo es."""
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


def palette_for(widget: QWidget) -> Palette:
    return DARK if is_dark(widget) else LIGHT


def color(value: str) -> QColor:
    return QColor(value)


def stylesheet(p: Palette) -> str:
    """Hoja de estilo del workspace. Selectores: nombres de objeto `geoduck*` y la propiedad `geoduck`."""
    return f"""
#geoduckWorkspace, #geoduckWindowCentral, #geoduckDockBody {{ background: {p.window}; }}
QLabel {{ color: {p.text}; }}
*[geoduck="muted"] {{ color: {p.muted}; }}
*[geoduck="error-text"] {{ color: {p.error}; }}

#geoduckSessionBar {{ background: {p.card}; border: none; border-bottom: 1px solid {p.border}; }}
#geoduckDockTitle {{ background: {p.card}; border-bottom: 1px solid {p.border}; }}
*[geoduck="card"] {{ background: {p.card}; border: 1px solid {p.border}; border-radius: 8px; }}
*[geoduck="card"] QLabel {{ background: transparent; }}
*[geoduck="card-footer"] {{ border: none; border-top: 1px solid {p.border_soft}; }}

QPushButton[geoduck="primary"], QPushButton[geoduck="action"], QPushButton[geoduck="secondary"],
QToolButton[geoduck="square"] {{
    border-radius: 6px; padding: 5px 12px; min-height: 18px;
}}
QPushButton[geoduck="primary"] {{
    background: {p.primary}; color: {p.on_color}; border: 1px solid {p.primary}; font-weight: 600;
}}
QPushButton[geoduck="primary"]:hover {{ background: {p.primary_hover}; }}
QPushButton[geoduck="action"] {{
    background: {p.action}; color: {p.on_color}; border: 1px solid {p.action}; font-weight: 600;
}}
QPushButton[geoduck="action"]:hover {{ background: {p.action_hover}; }}
QPushButton[geoduck="action"]::menu-indicator {{ subcontrol-position: right center; right: 8px; }}
QPushButton[geoduck="secondary"], QToolButton[geoduck="square"] {{
    background: {p.card}; color: {p.text}; border: 1px solid {p.border};
}}
QPushButton[geoduck="secondary"]:hover, QToolButton[geoduck="square"]:hover {{ background: {p.header}; }}
QPushButton[geoduck="primary"]:disabled, QPushButton[geoduck="action"]:disabled,
QPushButton[geoduck="secondary"]:disabled, QToolButton[geoduck="square"]:disabled {{
    background: {p.header}; color: {p.muted}; border: 1px solid {p.border_soft};
}}
QToolButton[geoduck="square"] {{ padding: 4px; min-width: 22px; }}
QPushButton[geoduck] QLabel {{ background: transparent; }}
QPushButton[geoduck="primary"] QLabel, QPushButton[geoduck="action"] QLabel {{ color: {p.on_color}; }}
QPushButton[geoduck="secondary"] QLabel {{ color: {p.text}; }}
QPushButton[geoduck] QLabel[geoduck="hint"] {{ color: {p.muted}; }}
QPushButton[geoduck="primary"] QLabel[geoduck="hint"] {{ color: rgba(255, 255, 255, 190); }}
QPushButton[geoduck]:disabled QLabel {{ color: {p.muted}; }}
QPushButton[geoduck="primary"]:disabled QLabel {{ color: {p.muted}; }}

QToolButton[geoduck="load"] {{
    background: {p.action}; color: {p.on_color}; border: 1px solid {p.action}; border-radius: 6px;
    padding: 6px 30px 6px 12px; font-weight: 600; margin: 2px 4px;
}}
QToolButton[geoduck="load"]:hover {{ background: {p.action_hover}; }}
QToolButton[geoduck="load"]:disabled {{
    background: {p.header}; color: {p.muted}; border: 1px solid {p.border_soft};
}}
QToolButton[geoduck="load"]::menu-button {{
    border: none; border-left: 1px solid rgba(255, 255, 255, 90); width: 22px;
    border-top-right-radius: 6px; border-bottom-right-radius: 6px;
}}
QToolButton[geoduck="square"]::menu-indicator {{ image: none; width: 0px; }}
QPushButton[geoduck="danger"] {{
    background: {p.card}; color: {p.error}; border: 1px solid {p.error_border};
    border-radius: 6px; padding: 5px 12px;
}}

QPushButton[geoduck="link"] {{
    border: none; background: transparent; color: {p.action}; text-decoration: underline; padding: 0px 2px;
}}
QPushButton[geoduck="link"]:disabled {{ color: {p.muted}; text-decoration: none; }}

QPushButton[geoduck="chip"] {{
    background: {p.card}; color: {p.text}; border: 1px solid {p.border};
    border-radius: 11px; padding: 2px 12px; min-height: 18px;
}}
QPushButton[geoduck="chip"]:checked {{ background: {p.chip}; border: 1px solid {p.primary}; }}

QLineEdit[geoduck="search"] {{
    background: {p.card}; color: {p.text}; border: 1px solid {p.border}; border-radius: 6px; padding: 5px 6px;
}}
QLineEdit[geoduck="search"]:focus {{ border: 1px solid {p.action}; }}

*[geoduck="card"] QTreeWidget, *[geoduck="card"] QTableWidget {{
    background: {p.card}; color: {p.text}; border: none; outline: 0;
    selection-background-color: {p.selection}; selection-color: {p.text};
    gridline-color: {p.border_soft};
}}
*[geoduck="card"] QTreeWidget::item {{ padding: 3px 0px; }}
*[geoduck="card"] QTreeWidget::item:selected {{ background: {p.selection}; color: {p.text}; }}
*[geoduck="card"] QHeaderView::section {{
    background: {p.header}; color: {p.text}; border: none; border-bottom: 1px solid {p.border_soft};
    padding: 6px 8px;
}}
*[geoduck="card"] QTableWidget QTableCornerButton::section {{ background: {p.header}; border: none; }}
QHeaderView[geoduck="rownumbers"]::section {{
    background: {p.card}; color: {p.muted}; border: none; padding: 0px 8px;
}}

QTabWidget[geoduck="results"]::pane {{ border: none; border-top: 1px solid {p.border_soft}; }}
QTabWidget[geoduck="results"] > QTabBar::tab {{
    background: transparent; border: none; padding: 8px 14px; border-bottom: 2px solid transparent;
}}
QTabWidget[geoduck="results"] > QTabBar::tab:selected {{
    border-bottom: 2px solid {p.primary}; font-weight: 600;
}}
QTabWidget[geoduck="panel-tabs"]::pane {{ border: none; }}

/* Cuaderno (G7 · E4, maqueta docs/g7/maqueta): celda como tarjeta, la activa con el borde de acento */
QFrame[geoduck="cell"] {{ background: {p.card}; border: 1px solid {p.border}; border-radius: 8px; }}
QFrame[geoduck="cell"][active="true"] {{ border: 2px solid {p.action}; }}
QFrame[geoduck="cell"] QLabel {{ background: transparent; }}
*[geoduck="cell-result"] {{ background: {p.header}; border: none; border-top: 1px solid {p.border_soft}; }}
QToolButton[geoduck="run-cell"] {{
    color: {p.action}; border: 1px solid {p.border}; border-radius: 4px; padding: 1px 6px;
}}
QComboBox[geoduck="database"] {{
    background: {p.card}; color: {p.text}; border: 1px solid {p.border}; border-radius: 4px;
    padding: 1px 6px;
}}
QComboBox[geoduck="database"]:hover, QComboBox[geoduck="database"]:focus {{ border: 1px solid {p.action}; }}
QComboBox[geoduck="database"][problem="true"] {{
    background: {p.error_bg}; color: {p.error}; border: 1px solid {p.error_border};
}}
QToolButton[geoduck="run-cell"]::menu-button {{ border: none; width: 12px; }}
QToolButton[geoduck="add-cell"] {{
    background: {p.card}; color: {p.muted}; border: 1px dashed {p.border}; border-radius: 6px; padding: 6px;
}}
QToolButton[geoduck="add-cell"]:hover {{ color: {p.text}; }}
QToolButton[geoduck="more"]::menu-indicator {{ image: none; width: 0px; }}
QTabWidget[geoduck="panel-tabs"] > QTabBar::tab {{
    background: transparent; color: {p.muted}; border: none; padding: 8px 12px;
    border-bottom: 2px solid transparent;
}}
QTabWidget[geoduck="panel-tabs"] > QTabBar::tab:selected {{
    color: {p.text}; border-bottom: 2px solid {p.primary};
}}

*[geoduck="message-success"] {{
    background: {p.success_bg}; color: {p.text}; border: 1px solid {p.success_border}; border-radius: 6px;
    padding: 6px 10px;
}}
*[geoduck="message-error"] {{
    background: {p.error_bg}; color: {p.text}; border: 1px solid {p.error_border}; border-radius: 6px;
    padding: 6px 10px;
}}
*[geoduck="message-info"] {{ color: {p.text}; padding: 2px 0px; }}

*[geoduck="option-card"] {{ background: {p.card}; border: 1px solid {p.border}; border-radius: 8px; }}
*[geoduck="option-card"][selected="true"] {{ background: {p.chip}; border: 1px solid {p.primary}; }}
*[geoduck="option-card"] QLabel, *[geoduck="option-card"] QRadioButton {{ background: transparent; }}
*[geoduck="option-card"] QRadioButton {{ spacing: 0px; }}
*[geoduck="option-card"] QRadioButton::indicator {{ width: 0px; height: 0px; }}
*[geoduck="option-card"] QRadioButton:disabled {{ color: {p.muted}; }}
QLabel[geoduck="notice"] {{
    background: {p.header}; border: 1px solid {p.border_soft}; border-radius: 6px; padding: 6px 10px;
}}

QMenu#geoduckLoadMenu {{
    background: {p.card}; border: 1px solid {p.border}; border-radius: 8px; padding: 6px;
}}
*[geoduck="menu-item"] {{ background: transparent; border-radius: 6px; padding: 8px 12px; }}
*[geoduck="menu-item"]:hover, *[geoduck="menu-item"][active="true"] {{ background: {p.selection}; }}
*[geoduck="menu-item"] QLabel {{ background: transparent; color: {p.text}; }}
*[geoduck="menu-item"] QLabel[geoduck="muted"] {{ color: {p.muted}; }}
*[geoduck="menu-item"][enabled="false"] QLabel {{ color: {p.muted}; }}
"""
