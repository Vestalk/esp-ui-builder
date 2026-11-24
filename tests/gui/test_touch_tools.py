"""Touch in the editor: tap zones, "Перегляд" with simulated taps, advice, calibration."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from espui.core.models import Display, Touch
from espui.gui.display_dialog import DisplayDialog
from espui.gui.main_window import MainWindow
from tests.gui.test_multiselect import WEATHER, at, click, drag, pos


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    win.open_file(WEATHER)
    win.workspace.zoom_reset()
    doc = win.doc
    # a touch panel, a big button (the card) and a small one (the status dot)
    data = doc.project.display.model_dump()
    data["touch"] = Touch(kind="xpt2046", cs=14, irq=15).model_dump()
    data["pins"]["miso"] = 13
    doc.set_display(Display.model_validate(data))
    doc.set_on_widgets(["card"], "on_tap", "open_card", "При натиску")
    doc.set_on_widgets(["st_dot"], "on_tap", "toggle", "При натиску")
    QApplication.processEvents()
    return win


def test_tap_zones_are_outlined(window: MainWindow) -> None:
    item = window.workspace.active_item()
    assert item is not None
    assert not item.show_taps
    window.act_taps.trigger()
    assert item.show_taps
    zones = {z.widget.id: z for z in item.taps}
    assert set(zones) == {"card", "st_dot"}
    assert zones["st_dot"].small  # 16×16: orange
    assert not zones["card"].small
    before = item.image.copy()
    window.act_taps.trigger()
    assert not item.show_taps
    assert item.image == before  # an overlay: the page itself is drawn the same


def test_preview_simulates_taps_as_on_the_board(window: MainWindow) -> None:
    ws, doc = window.workspace, window.doc
    doc.select("title")
    window.act_preview.trigger()
    assert ws.preview
    item = ws.active_item()
    assert item is not None
    assert item.show_taps  # zones always shown in "Перегляд"
    assert not item.selection.isVisible()
    before = pos(window, "card")
    click(ws, 158, 198)  # the status dot, over the card
    assert ws.last_tap == (158, 198, "st_dot")
    assert "«st_dot»: toggle()" in window.statusBar().currentMessage()
    assert item.flash is not None
    click(ws, 30, 60)  # the value text lies over the card: the tap still reaches the card
    assert ws.last_tap == (30, 60, "card")
    click(ws, 100, 200)  # nothing tappable there
    assert ws.last_tap == (100, 200, None)
    assert "немає елемента" in window.statusBar().currentMessage()
    drag(ws, at(ws, 30, 60), at(ws, 80, 90))  # nothing moves, nothing gets selected
    assert pos(window, "card") == before
    assert doc.selected == "title"
    ws.setFocus()
    QTest.keyClick(ws, Qt.Key.Key_Delete)  # no editing in "Перегляд"
    assert doc.page.widget("title") is not None
    QTest.keyClick(ws, Qt.Key.Key_Escape)  # back to editing
    assert not ws.preview
    assert not window.act_preview.isChecked()
    assert not item.show_taps
    assert item.selection.isVisible()


def test_preview_follows_the_test_values(window: MainWindow) -> None:
    """A widget hidden by a condition (with the test values) doesn't catch the tap."""
    ws, doc = window.workspace, window.doc
    rule = {"if": ["alarm", "==", True], "set": "visible", "to": False}
    dot = doc.page.widget("st_dot")
    assert dot is not None
    doc.change_widget(dot.model_validate({**dot.model_dump(by_alias=True), "rules": [rule]}))
    window.act_preview.trigger()
    doc.set_test_value("alarm", True)
    assert ws.simulate_tap(158, 198) is None  # the dot is hidden: nothing catches the tap
    doc.set_test_value("alarm", False)
    hit = ws.simulate_tap(158, 198)
    assert hit is not None
    assert hit.id == "st_dot"


def test_properties_warn_about_a_small_button(window: MainWindow) -> None:
    props, doc = window.properties, window.doc
    doc.select("st_dot")
    assert props.tap_hint.isVisibleTo(props)
    assert "16×16 px" in props.tap_hint.text()
    doc.select("card")
    assert not props.tap_hint.isVisibleTo(props)


def test_dialog_takes_the_calibration_line_from_the_board(qtbot: QtBot) -> None:
    dialog = DisplayDialog(Display())
    qtbot.addWidget(dialog)
    dialog.touch_kind.setCurrentIndex(dialog.touch_kind.findData("xpt2046"))
    assert dialog.cal_paste.isVisibleTo(dialog)
    dialog.cal_copy.click()
    assert "calibrate_touch()" in QGuiApplication.clipboard().text()
    dialog.cal_paste.setText(">>> ESPUI-CAL x_min=3810 x_max=290 y_min=240 y_max=3705 swap_xy=1")
    touch = dialog.display().touch
    assert touch is not None
    assert (touch.x_min, touch.x_max, touch.y_min, touch.y_max, touch.swap_xy) == (
        3810,
        290,
        240,
        3705,
        True,
    )
    assert "✓" in dialog.cal_status.text()
    dialog.cal_paste.setText("щось інше")
    assert "⚠" in dialog.cal_status.text()
    dialog.touch_kind.setCurrentIndex(dialog.touch_kind.findData("cst816s"))
    assert not dialog.cal_paste.isVisibleTo(dialog)  # capacitive: nothing to calibrate
