"""Groups, the project palette, collapsible blocks, the start window and the help."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton
from pytestqt.qtbot import QtBot

from espui.core import serializer
from espui.gui.help import TOPICS, HelpDialog, show_help
from espui.gui.layers import LayerRow
from espui.gui.main_window import MainWindow
from espui.gui.start_dialog import SHOW_KEY, StartDialog, show_on_start
from tests.gui.test_multiselect import LEFT, WEATHER, at, click, drag, pos


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    win.open_file(WEATHER)
    win.workspace.zoom_reset()
    QApplication.processEvents()
    return win


# ------------------------------------------------------------------ 5: groups
def test_group_picks_all_its_widgets_and_moves_together(window: MainWindow) -> None:
    ws, doc = window.workspace, window.doc
    doc.select_many(["st_dot", "st_txt"])
    assert window.act_group.isEnabled()
    assert window.group_selected()
    assert {w.group for w in doc.page.widgets if w.id in ("st_dot", "st_txt")} == {"group_1"}
    doc.select(None)
    click(ws, 158, 198)  # one click on the dot: the whole group
    assert doc.selected_ids == ["st_dot", "st_txt"]
    assert doc.selected == "st_dot"
    item = ws.active_item()
    assert item is not None
    assert item.group_frame is not None  # a frame around the group
    before = pos(window, "st_txt")
    QTest.qWait(QApplication.doubleClickInterval() + 50)  # not a double click
    drag(ws, at(ws, 158, 198), at(ws, 178, 198))
    assert pos(window, "st_txt")[0] > before[0]  # moved with the dot
    QTest.qWait(QApplication.doubleClickInterval() + 50)
    QTest.mouseClick(
        ws.viewport(), LEFT, Qt.KeyboardModifier.ControlModifier, at(ws, 240, 197).toPoint()
    )
    assert doc.selected_ids == ["st_txt"]  # Ctrl+click: one widget of the group
    QTest.qWait(QApplication.doubleClickInterval() + 50)
    drag(ws, at(ws, 140, 182), at(ws, 182, 205))  # a frame touching only the (moved) dot
    assert doc.selected_ids == ["st_dot", "st_txt"]  # takes the whole group
    rows = [window.layers.itemWidget(window.layers.item(i)) for i in range(window.layers.count())]
    assert sum("▣ group_1" in r.label.text() for r in rows if isinstance(r, LayerRow)) == 2
    assert window.ungroup_selected()
    assert not any(w.group for w in doc.page.widgets)
    doc.undo_stack.undo()
    assert {w.group for w in doc.page.widgets if w.group} == {"group_1"}


def test_pasted_group_is_a_new_group(window: MainWindow) -> None:
    doc = window.doc
    doc.select_many(["st_dot", "st_txt"])
    window.group_selected()
    assert window.duplicate_widget()
    groups = {w.id: w.group for w in doc.page.widgets if w.group}
    assert groups == {
        "st_dot": "group_1",
        "st_txt": "group_1",
        "st_dot_2": "group_2",
        "st_txt_2": "group_2",
    }
    assert doc.selected_ids == ["st_dot_2", "st_txt_2"]


def test_groups_are_editor_only(window: MainWindow, tmp_path: object) -> None:
    from pathlib import Path

    from espui.generators.micropython.generator import generate

    doc = window.doc
    before = generate(doc.project).files
    doc.select_many(["title", "city_txt"])
    window.group_selected()
    assert generate(doc.project).files == before
    path = Path(str(tmp_path)) / "g.espui"
    serializer.save(doc.project, path)
    title = serializer.load(path).pages[0].widget("title")
    assert title is not None
    assert title.group == "group_1"


# ------------------------------------------------------------------ 12: blocks
def test_blocks_collapse_with_a_summary_and_all_at_once(window: MainWindow) -> None:
    props, doc = window.properties, window.doc
    doc.select("t_val")
    widget = doc.page.widget("t_val")
    assert widget is not None
    props.tap.set_collapsed(True)
    assert not props.tap.body.isVisibleTo(props)
    props.rules_section.set_collapsed(True)
    assert props.rules_section.header.text() == f"▸ Умови · {len(widget.rules)}"
    props.collapse_all.click()
    assert all(s.collapsed for s in props.sections())
    props.expand_all.click()
    assert not any(s.collapsed for s in props.sections())
    assert props.on_tap_edit.parentWidget() is props.tap.body  # "При натиску": its own block


# ------------------------------------------------------------------ 13: palette
def test_project_palette(window: MainWindow) -> None:
    props, doc = window.properties, window.doc
    doc.select("title")
    title = doc.page.widget("title")
    assert title is not None
    props.swatches.add_button.click()  # the title's colour into the palette
    assert doc.project.colors == [title.color.lower()]
    assert title.color.lower() in props.swatches.buttons
    doc.add_color("#ff8800")
    doc.select("card")
    props.swatches.buttons["#ff8800"].click()  # one click applies it
    card = doc.page.widget("card")
    assert card is not None
    assert card.color == "#ff8800"
    assert not doc.add_color("#ff8800")  # once
    used = [c for c in props.swatches.buttons if c not in doc.project.colors]
    assert used  # the page's other colours are offered too
    doc.remove_color("#ff8800")
    assert "#ff8800" not in doc.project.colors
    doc.undo_stack.undo()
    assert "#ff8800" in doc.project.colors
    doc.select_many(["st_dot", "alarm_lbl"])  # several: the same swatches
    props.many_swatches.buttons["#ff8800"].click()
    assert {w.color for w in doc.page.widgets if w.id in ("st_dot", "alarm_lbl")} == {"#ff8800"}


# ------------------------------------------------------------------ 16: start window
def test_start_window_lists_and_choices(window: MainWindow, qtbot: QtBot) -> None:
    dialog = StartDialog(window)
    qtbot.addWidget(dialog)
    assert dialog.samples.count() >= 5  # the examples of the checkout
    first = dialog.samples.item(0)
    assert first.text().startswith("Погода")
    assert dialog.recent.count() >= 1  # weather.espui was opened by the fixture
    dialog.samples.itemActivated.emit(first)
    assert (dialog.choice, dialog.path) == ("file", WEATHER.resolve())
    assert show_on_start()
    dialog.show_again.setChecked(False)
    assert not show_on_start()
    from PySide6.QtCore import QSettings

    QSettings().setValue(SHOW_KEY, True)


def test_start_window_opens_an_example(window: MainWindow) -> None:
    def pick() -> None:
        dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, StartDialog))
        item = next(
            dialog.samples.item(i)
            for i in range(dialog.samples.count())
            if dialog.samples.item(i).data(Qt.ItemDataRole.UserRole).endswith("sensors.espui")
        )
        dialog.samples.itemActivated.emit(item)

    QTimer.singleShot(0, pick)
    assert window.show_start() == "file"
    assert window.windowTitle().startswith("sensors.espui")


# ------------------------------------------------------------------ 17: help
def test_help_topics_search_and_context(window: MainWindow, qtbot: QtBot) -> None:
    dialog = show_help("touch", window)
    qtbot.addWidget(dialog)
    assert isinstance(dialog, HelpDialog)
    assert dialog.topic == "touch"
    assert "calibrate_touch" in dialog.text.toPlainText()
    dialog.search.setText("калібрування")
    shown = [dialog.topics.item(i) for i in range(dialog.topics.count())]
    visible = [i.data(Qt.ItemDataRole.UserRole) for i in shown if not i.isHidden()]
    assert "touch" in visible
    assert "keys" not in visible
    dialog.search.setText("щосьнеіснуюче")
    assert "Нічого не знайдено" in dialog.text.toPlainText()
    window.properties.on_tap_edit.setFocus()
    QApplication.processEvents()
    if QApplication.focusWidget() is window.properties.on_tap_edit:
        assert window.context_topic() == "properties"
    window.workspace.setFocus()
    QApplication.processEvents()
    if QApplication.focusWidget() is window.workspace:
        assert window.context_topic() == "canvas"
    help_buttons = window.properties.findChildren(QToolButton, "section_help")
    assert len(help_buttons) >= 5  # "?" in the block headers
    help_buttons[0].click()
    assert dialog.isVisible() or any(
        isinstance(w, HelpDialog) and w.isVisible() for w in QApplication.topLevelWidgets()
    )
    assert set(TOPICS) >= {"start", "canvas", "arrange", "touch", "keys"}
