"""Stage 13: conditions & mappings, locked fields, look, pivot, position frames, images, chart."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox
from pytestqt.qtbot import QtBot

from espui.core.models import Condition, MappingRule, PivotPoint
from espui.gui.main_window import MainWindow
from espui.gui.workspace import Workspace
from tests.gui.conftest import ROOT

WEATHER = ROOT / "examples" / "weather.espui"
IMAGES = ROOT / "examples" / "images.espui"


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1500, 950)
    win.show()
    win.open_file(WEATHER)
    win.workspace.zoom_reset()
    return win


def rules_of(window: MainWindow, widget_id: str) -> list[Condition | MappingRule]:
    widget = window.doc.page.widget(widget_id)
    assert widget is not None
    return list(widget.rules)


def view_point(ws: Workspace, x: float, y: float) -> QPointF:
    item = ws.active_item()
    assert item is not None
    return QPointF(ws.mapFromScene(item.mapToScene(QPointF(x, y))))


def drag(ws: Workspace, start: QPointF, end: QPointF) -> None:
    viewport = ws.viewport()
    QTest.mousePress(
        viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start.toPoint()
    )
    for i in range(1, 5):
        QTest.mouseMove(viewport, (start + (end - start) * i / 4).toPoint())
    QTest.mouseRelease(
        viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end.toPoint()
    )


# ------------------------------------------------------------------ conditions block
def test_conditions_block_lists_and_highlights(window: MainWindow) -> None:
    doc = window.doc
    editor = window.properties.rules_editor
    doc.select("st_dot")
    assert len(editor.rows) == 2  # Увага -> orange, Помилка -> red
    assert not any(row.property("active") for row in editor.rows)
    doc.set_test_value("status", "Помилка")
    assert editor.rows[1].property("active")  # the matching one is highlighted
    assert not editor.rows[0].property("active")


def test_add_and_edit_a_condition(window: MainWindow) -> None:
    doc = window.doc
    editor = window.properties.rules_editor
    doc.select("card")
    assert editor.rows == []
    editor.add_condition.click()
    (rule,) = rules_of(window, "card")
    assert isinstance(rule, Condition)
    assert (rule.param, rule.op, rule.prop, rule.to) == ("temperature", ">", "color", "#ff4b55")
    # the parameter: operators and value follow its type
    p_combo = editor.rows[0].findChildren(QComboBox)[0]
    p_combo.setCurrentIndex(p_combo.findData("status"))
    p_combo.activated.emit(p_combo.currentIndex())
    (rule,) = rules_of(window, "card")
    assert (rule.param, rule.op, rule.value) == ("status", "==", "Норма")  # type: ignore[union-attr]
    # the property: a sensible value
    prop_combo = editor.rows[0].findChildren(QComboBox)[3]
    prop_combo.setCurrentIndex(prop_combo.findData("x"))
    prop_combo.activated.emit(prop_combo.currentIndex())
    (rule,) = rules_of(window, "card")
    assert isinstance(rule, Condition)
    assert (rule.prop, rule.to) == ("x", 6 + 40)
    assert window.doc.undo_stack.undoText().startswith("Умови")


def test_condition_on_a_range(window: MainWindow) -> None:
    doc = window.doc
    editor = window.properties.rules_editor
    doc.select("card")
    editor.add_condition.click()  # temperature > 15
    op_combo = editor.rows[0].findChildren(QComboBox)[1]
    assert op_combo.findText("у діапазоні") >= 0
    assert op_combo.findText("поза діапазоном") >= 0
    op_combo.setCurrentIndex(op_combo.findData("in"))
    op_combo.activated.emit(op_combo.currentIndex())
    (rule,) = rules_of(window, "card")
    assert isinstance(rule, Condition)
    start = rule.value
    assert isinstance(start, tuple)
    assert rule.op == "in"
    lo = editor.rows[0].findChild(QDoubleSpinBox, "range_from")
    hi = editor.rows[0].findChild(QDoubleSpinBox, "range_to")
    assert lo is not None
    assert hi is not None
    assert (lo.value(), hi.value()) == start
    lo.setValue(10)
    hi = editor.rows[0].findChild(QDoubleSpinBox, "range_to")  # the block was rebuilt
    assert hi is not None
    hi.setValue(20)
    (rule,) = rules_of(window, "card")
    assert isinstance(rule, Condition)
    assert rule.when == ("temperature", "in", (10, 20))
    doc.set_test_value("temperature", 20)  # the end is included
    assert editor.rows[0].property("active")
    doc.set_test_value("temperature", 25)
    assert not editor.rows[0].property("active")
    # back to a single value: "від" is kept
    op_combo = editor.rows[0].findChildren(QComboBox)[1]
    op_combo.setCurrentIndex(op_combo.findData(">="))
    op_combo.activated.emit(op_combo.currentIndex())
    (rule,) = rules_of(window, "card")
    assert isinstance(rule, Condition)
    assert rule.when == ("temperature", ">=", 10)
    assert editor.rows[0].findChild(QDoubleSpinBox, "range_from") is None


def test_add_mapping_with_sensible_ends(window: MainWindow) -> None:
    doc = window.doc
    editor = window.properties.rules_editor
    doc.select("st_dot")
    editor.add_mapping.click()
    mapping = rules_of(window, "st_dot")[-1]
    assert isinstance(mapping, MappingRule)
    assert (mapping.param, mapping.prop, mapping.at_min, mapping.at_max) == (
        "temperature",
        "opacity",
        0,
        100,
    )
    prop_combo = editor.rows[-1].findChildren(QComboBox)[1]
    prop_combo.setCurrentIndex(prop_combo.findData("x"))
    prop_combo.activated.emit(prop_combo.currentIndex())
    mapping = rules_of(window, "st_dot")[-1]
    assert isinstance(mapping, MappingRule)
    assert (mapping.prop, mapping.at_min, mapping.at_max) == (
        "x",
        150,
        250,
    )  # x .. x + 100 within 320


def test_rule_errors_next_to_the_block(window: MainWindow) -> None:
    doc = window.doc
    editor = window.properties.rules_editor
    doc.select("st_dot")
    editor.add_mapping.click()
    spin = editor.rows[-1].findChild(QDoubleSpinBox, "at_max")
    assert spin is not None
    spin.setValue(150)  # opacity over 100 %
    assert editor.errors.isVisibleTo(editor)
    assert "запис 3: непрозорість від 0 до 100 %" in editor.errors.text()


def test_remove_rule_and_no_parameters(window: MainWindow) -> None:
    doc = window.doc
    editor = window.properties.rules_editor
    doc.select("alarm_lbl")
    editor.rows[0].remove_button.click()
    assert rules_of(window, "alarm_lbl") == []
    for name in [p.name for p in doc.page.parameters]:
        doc.remove_parameter(name)
    doc.select("card")
    assert not editor.add_condition.isEnabled()
    assert not editor.add_mapping.isEnabled()


# ------------------------------------------------------------------ locked fields & look
def test_fields_controlled_by_rules_are_locked(window: MainWindow) -> None:
    doc = window.doc
    panel = window.properties
    doc.select("t_val")  # its colour depends on "alarm"
    assert not panel.color_edit.isEnabled()
    assert panel.color_edit.toolTip() == "Керується в «Умовах»: alarm"
    assert panel.box_spins["x"].isEnabled()
    assert panel.controlled_hint.text() == "Змінюється умовами: колір (alarm)"
    panel.rules_editor.rows[0].remove_button.click()
    assert panel.color_edit.isEnabled()  # the last rule for the colour is gone
    doc.select("st_txt")
    assert not panel.format_edit.isEnabled()


def test_look_block(window: MainWindow) -> None:
    doc = window.doc
    panel = window.properties
    doc.select("card")
    panel.opacity_slider.setValue(60)
    assert doc.page.widget("card").opacity == 60  # type: ignore[union-attr]
    assert panel.opacity_spin.value() == 60
    panel.opacity_all.click()
    assert {w.opacity for w in doc.page.widgets} == {60}
    panel.angle_slider.setValue(-30)
    assert doc.page.widget("card").rotation_deg == -30  # type: ignore[union-attr]
    window.workspace.add_widget("chart")
    assert not panel.angle_row.isVisibleTo(panel)  # a chart doesn't rotate


# ------------------------------------------------------------------ canvas
def test_drag_the_pivot_cross(window: MainWindow) -> None:
    doc = window.doc
    ws = window.workspace
    doc.select("card")
    item = ws.active_item()
    assert item is not None
    assert item.pivot.isVisible()
    assert (item.pivot.pos().x(), item.pivot.pos().y()) == (6 + 154, 4 + 46)  # the centre
    drag(ws, view_point(ws, 160, 50), view_point(ws, 20, 10))
    pivot = doc.page.widget("card").pivot  # type: ignore[union-attr]
    assert isinstance(pivot, PivotPoint)
    assert (pivot.x, pivot.y) == (14, 6)  # relative to the widget
    assert doc.undo_stack.undoText().startswith("Точка повороту")


def test_rotated_selection_and_hit_test(window: MainWindow) -> None:
    doc = window.doc
    ws = window.workspace
    doc.select("sep")
    window.properties.angle_slider.setValue(90)  # a vertical line around its centre
    item = ws.active_item()
    assert item is not None
    assert not item.selection.transform().isIdentity()
    doc.select(None)
    QTest.mouseClick(ws.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     view_point(ws, 161, 30).toPoint())  # fmt: skip
    assert doc.selected == "sep"  # the turned line, far above its unrotated box


def test_position_frames_and_moving_together(window: MainWindow, qtbot: QtBot) -> None:
    doc = window.doc
    ws = window.workspace
    doc.select("st_dot")
    editor = window.properties.rules_editor
    editor.add_mapping.click()
    prop_combo = editor.rows[-1].findChildren(QComboBox)[1]
    prop_combo.setCurrentIndex(prop_combo.findData("x"))
    prop_combo.activated.emit(prop_combo.currentIndex())
    item = ws.active_item()
    assert item is not None
    frames = item.ghosts.frames
    assert [(f.x(), label) for f, label in frames] == [(150, "мін"), (250, "макс")]
    ws.setFocus()
    qtbot.keyClick(ws, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    widget = doc.page.widget("st_dot")
    assert widget is not None
    mapping = [r for r in widget.rules if isinstance(r, MappingRule)][-1]
    assert (widget.x, mapping.at_min, mapping.at_max) == (160, 160, 260)  # all moved by 10
    assert [f.x() for f, _ in item.ghosts.frames] == [160, 260]


def test_hidden_widgets_are_outlined_on_the_active_page(window: MainWindow) -> None:
    doc = window.doc
    item = window.workspace.active_item()
    assert item is not None
    label = doc.page.widget("alarm_lbl")
    assert label is not None
    assert [(r.x(), r.y()) for r in item.hidden] == [(label.x, label.y)]  # alarm = false
    doc.set_test_value("alarm", True)
    assert item.hidden == []


# ------------------------------------------------------------------ pictures and chart
def test_pictures_on_the_board(window: MainWindow, tmp_path: Path) -> None:
    window.open_file(IMAGES)
    doc = window.doc
    panel = window.properties
    doc.select("icon")  # takes the path from "weather_icon"
    assert panel.board_list.isVisibleTo(panel)
    assert not panel.files_row.isVisibleTo(panel)
    texts = [panel.board_list.item(i).text() for i in range(panel.board_list.count())]
    assert texts[0] == "▶ /img/sun.bin · sun.png"  # the current test value
    panel.board_list.itemClicked.emit(panel.board_list.item(1))
    assert doc.page.value_of("weather_icon") == "/img/cloud.bin"
    assert panel.board_list.item(1).text().startswith("▶ ")
    Image.new("RGB", (4, 4)).save(tmp_path / "moon.png")
    Image.new("RGB", (4, 4)).save(tmp_path / "star.png")
    assert panel.add_board_files([str(tmp_path / "moon.png"), str(tmp_path / "star.png")])
    assert {"moon", "star"} <= set(doc.project.images)
    panel.board_list.setCurrentRow(panel.board_list.count() - 1)
    panel.board_remove.click()
    assert "star" not in doc.project.images
    doc.select("logo")
    assert panel.image_hint.text() == "На платі: /img/logo.bin · 14,1 КБ"


def test_chart_bounds_empty_is_auto(window: MainWindow) -> None:
    window.workspace.add_widget("chart")
    panel = window.properties
    low, high = panel.y_bounds["y_min"], panel.y_bounds["y_max"]
    low.setText("10")
    high.setText("5")
    high.editingFinished.emit()
    assert panel.error.text() == "Графік: Y мін має бути менше за Y макс"
    high.setText("")
    high.editingFinished.emit()
    chart = window.doc.widget.chart  # type: ignore[union-attr]
    assert chart is not None
    assert (chart.y_min, chart.y_max) == (10, None)
    low.setText("abc")
    low.editingFinished.emit()
    assert "не число" in panel.error.text()


# ------------------------------------------------------------------ old projects
def test_old_project_is_migrated_into_conditions(window: MainWindow, tmp_path: Path) -> None:
    old = {
        "pages": [{
            "name": "main",
            "parameters": [{"name": "t", "type": "float", "min": 0, "max": 50, "default": 10},
                           {"name": "on", "type": "bool"}],
            "widgets": [{"id": "w", "type": "rect", "w": 20, "h": 20,
                         "show": {"param": "on", "when": True},
                         "omode": "param", "opp": "t", "o0": 20, "o1": 100,
                         "rmode": "param", "rp": "t", "a0": 0, "a1": 90}],
        }]
    }  # fmt: skip
    path = tmp_path / "old.espui"
    path.write_text(json.dumps(old), "utf-8")
    assert window.open_file(path)
    window.doc.select("w")
    rules = rules_of(window, "w")
    assert [type(r).__name__ for r in rules] == ["Condition", "MappingRule", "MappingRule"]
    assert len(window.properties.rules_editor.rows) == 3
    assert not window.properties.opacity_spin.isEnabled()  # now controlled by a mapping


def test_rows_are_rebuilt_not_duplicated(window: MainWindow) -> None:
    """Reloading the block several times in a row keeps one row per record."""
    doc = window.doc
    editor = window.properties.rules_editor
    doc.select("st_dot")
    editor.add_mapping.click()
    for _ in range(3):
        window.properties.load()
    from espui.gui.rules_editor import RuleRow

    # old rows are taken out of the editor at once (deleteLater only runs in the event loop)
    assert len(editor.findChildren(RuleRow)) == len(editor.rows) == 3
