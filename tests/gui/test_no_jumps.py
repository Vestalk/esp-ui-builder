"""Editing a value must not rebuild the panels (that made the window jump and lose focus)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QWidget
from pytestqt.qtbot import QtBot

from espui.core.models import Condition
from espui.gui.main_window import MainWindow
from tests.gui.conftest import ROOT

WEATHER = ROOT / "examples" / "weather.espui"


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 600)  # short: the panels scroll
    win.show()
    win.open_file(WEATHER)
    win.doc.select("st_dot")  # a widget with conditions
    QApplication.processEvents()
    return win


def rows(window: MainWindow) -> list[QWidget]:
    return list(window.properties.rules_editor.rows)


def layer_widgets(window: MainWindow) -> list[QWidget | None]:
    layers = window.layers
    return [layers.itemWidget(layers.item(i)) for i in range(layers.count())]


def test_dragging_the_angle_keeps_every_panel_in_place(window: MainWindow) -> None:
    props = window.properties
    bar = props.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum() // 2)
    scroll = bar.value()
    before_rows, before_layers = rows(window), layer_widgets(window)
    params_list = window.parameters.list
    before_params = [
        params_list.itemWidget(params_list.item(i)) for i in range(params_list.count())
    ]
    props.angle_slider.setFocus()
    for angle in range(5, 60, 5):  # like a slider being dragged
        props.angle_slider.setValue(angle)
        QApplication.processEvents()
        assert bar.value() == scroll
        assert rows(window) == before_rows  # the condition rows are the same widgets
        assert layer_widgets(window) == before_layers
        assert [
            params_list.itemWidget(params_list.item(i)) for i in range(params_list.count())
        ] == before_params
        assert QApplication.focusWidget() is props.angle_slider
    widget = window.doc.page.widget("st_dot")
    assert widget is not None
    assert widget.rotation_deg == 55


def test_test_values_only_repaint_the_highlight(window: MainWindow) -> None:
    before = rows(window)
    window.doc.set_test_value("status", "Помилка")
    QApplication.processEvents()
    assert rows(window) == before
    assert before[1].property("active")  # Помилка -> red: highlighted
    window.doc.set_test_value("status", "Норма")
    assert not before[1].property("active")


def test_typing_in_a_rule_keeps_the_field_and_undo_rebuilds(window: MainWindow) -> None:
    editor = window.properties.rules_editor
    doc = window.doc
    doc.select("card")
    card = doc.page.widget("card")
    assert card is not None
    rule = {"if": ["temperature", ">", 20], "set": "color", "to": "#ff0000"}
    doc.change_widget(card.model_copy(update={"rules": [Condition.model_validate(rule)]}))
    QApplication.processEvents()
    spin = editor.rows[0].findChildren(QDoubleSpinBox)[0]
    first_rows = rows(window)
    spin.setFocus()
    spin.setValue(30)
    QApplication.processEvents()
    assert rows(window) == first_rows  # the field being edited is still there
    assert QApplication.focusWidget() in (spin, spin.lineEdit())
    widget = window.doc.page.widget("card")
    assert widget is not None
    (rule,) = widget.rules
    assert isinstance(rule, Condition)
    assert rule.value == 30
    window.doc.undo_stack.undo()  # back to the value before: the rows show it again
    QApplication.processEvents()
    assert rows(window) != first_rows
    shown = editor.rows[0].findChildren(QDoubleSpinBox)[0].value()
    widget = window.doc.page.widget("card")
    assert widget is not None
    (rule,) = widget.rules
    assert isinstance(rule, Condition)
    assert shown == rule.value == 20


def test_structural_edits_still_rebuild(window: MainWindow) -> None:
    editor = window.properties.rules_editor
    window.doc.select("card")
    editor.add_condition.click()
    before = rows(window)
    combo = editor.rows[0].findChildren(type(window.properties.type_combo))[1]  # operator
    combo.setCurrentIndex(combo.findData("in"))
    combo.activated.emit(combo.currentIndex())
    QApplication.processEvents()
    assert rows(window) != before
    assert editor.rows[0].findChild(QDoubleSpinBox, "range_from") is not None
