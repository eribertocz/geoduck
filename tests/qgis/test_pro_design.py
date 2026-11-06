# SPDX-License-Identifier: GPL-2.0-or-later
"""Sistema de diseño de Workspace Pro (G9 · E1; workspace-pro-spec §10, §11; AT-WSP-001 parcial).

PyQGIS real en Qt 5 y Qt 6: la hoja solo afecta a GeoDuck, sigue el tema de QGIS, y las piezas tienen nombre
accesible, ayuda y teclado.
"""

from __future__ import annotations

import pytest
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtGui import QColor, QFocusEvent, QFontInfo, QPalette
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from geoduck.ui.pro import icons, style
from geoduck.ui.pro.tokens import DARK, FONT_FAMILIES, LIGHT, METRICS
from geoduck.ui.pro.widgets import Chip, SearchField, Segmented, Toast, button, icon_button, label

pytestmark = pytest.mark.qgis


def root(dark: bool = False) -> QWidget:
    widget = QWidget()
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#16181d" if dark else "#f0f0f0"))
    widget.setPalette(palette)
    QVBoxLayout(widget)
    return widget


def test_the_style_stays_inside_geoduck(qgis_app):
    before = QApplication.instance().styleSheet()
    outside = QPushButton("de QGIS")
    pro = root()
    colors = style.apply(pro)
    inside = button("de GeoDuck", "primary")
    pro.layout().addWidget(inside)
    pro.show()
    outside.show()
    QApplication.processEvents()
    assert QApplication.instance().styleSheet() == before  # QGIS no cambia (ADR-0011)
    assert pro.objectName() == style.ROOT and colors is LIGHT
    assert outside.styleSheet() == "" and outside.window() is not pro
    family = style.first_family(FONT_FAMILIES)
    assert QFontInfo(inside.font()).pixelSize() == METRICS.font or family not in style.installed_families()
    pro.close()
    outside.close()


def test_it_follows_the_qgis_theme(qgis_app):
    assert style.apply(root(dark=True)) is DARK
    assert style.apply(root(dark=False)) is LIGHT


def test_buttons_always_have_a_name_and_help(qgis_app):
    colors = LIGHT
    for widget in (button("Ver SQL", "ghost"), icon_button("refresh", "Releer las bases", colors)):
        assert widget.accessibleName() and widget.toolTip()
    assert icon_button("more", "Más acciones", colors).text() == ""  # solo icono, pero nunca mudo


def test_chip_is_removed_with_its_button_or_the_keyboard(qgis_app):
    chip = Chip("ConsumoKwh", ">", "50", LIGHT, remove_tip="Quitar filtro")
    removed = []
    chip.removed.connect(lambda: removed.append(1))
    chip.close_button.click()
    chip.show()
    chip.setFocus()
    QTest.keyClick(chip, Qt.Key.Key_Delete)
    assert removed == [1, 1]
    assert chip.accessibleName() == "ConsumoKwh > 50"
    assert chip.close_button.accessibleName() == "Quitar filtro"


def test_segmented_has_one_option_at_a_time(qgis_app):
    seg = Segmented(["Datos", "Estructura"], accessible_name="Vista")
    changes = []
    seg.changed.connect(changes.append)
    assert seg.current == 0
    seg.buttons[1].click()
    assert seg.current == 1 and changes == [1]
    assert seg.buttons[0].isChecked() is False


def test_search_field_marks_its_focus(qgis_app):
    pro = root()
    style.apply(pro)
    field = SearchField("Buscar tablas…", LIGHT, shortcut="Ctrl K", accessible_name="Buscar")
    pro.layout().addWidget(field)
    pro.show()
    QApplication.sendEvent(field.edit, QFocusEvent(QEvent.Type.FocusIn))  # sin ventana activa (offscreen)
    assert field.property("focused") is True
    QApplication.sendEvent(field.edit, QFocusEvent(QEvent.Type.FocusOut))
    assert field.property("focused") is False
    assert field.edit.accessibleName() == "Buscar"
    pro.close()


def test_toast_runs_its_action_and_goes_away(qgis_app):
    pro = root()
    style.apply(pro)
    pro.resize(800, 500)
    pro.show()
    toast = Toast(pro, "Tabla <b>zonas</b> creada", seconds=0)
    opened = []
    action = toast.add_action("Abrir", lambda: opened.append(1))
    toast.show_at_corner()
    assert toast.isVisible() and toast.geometry().right() <= pro.width()
    action.click()
    assert opened == [1] and not toast.isVisible()
    pro.close()


def test_every_icon_renders_in_any_color(qgis_app):
    for name in icons.PATHS:
        for color in (LIGHT.text, DARK.text):
            pix = icons.pixmap(name, color, 16)
            assert not pix.isNull()
            image = pix.toImage()
            painted = any(
                image.pixelColor(x, y).alpha() > 0
                for x in range(0, image.width(), 2)
                for y in range(0, image.height(), 2)
            )
            assert painted, name


def test_labels_carry_their_role(qgis_app):
    assert label("NULL", "null").property("pro") == "null"
    assert isinstance(label("x"), QLabel) and label("x").property("pro") is None


def test_icons_for_stylesheets_are_png_files(qgis_app):
    from pathlib import Path

    path = Path(icons.file("chevron-down", LIGHT.muted))
    assert path.is_file() and path.suffix == ".png"
    assert icons.file("chevron-down", LIGHT.muted) == path.as_posix()  # una vez por nombre y color
