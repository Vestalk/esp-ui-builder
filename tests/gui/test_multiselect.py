"""Several widgets selected: Shift+click, a frame, the layers; moved, deleted, coloured together."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from espui.gui.main_window import MainWindow
from espui.gui.workspace import Workspace
from tests.gui.conftest import ROOT

WEATHER = ROOT / "examples" / "weather.espui"
SHIFT = Qt.KeyboardModifier.ShiftModifier
NONE = Qt.KeyboardModifier.NoModifier
LEFT = Qt.MouseButton.LeftButton


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


def at(ws: Workspace, x: float, y: float) -> QPointF:
    item = ws.active_item()
    assert item is not None
    return QPointF(ws.mapFromScene(item.mapToScene(QPointF(x, y))))


def click(ws: Workspace, x: float, y: float, mods: Qt.KeyboardModifier = NONE) -> None:
    QTest.mouseClick(ws.viewport(), LEFT, mods, at(ws, x, y).toPoint())


def drag(ws: Workspace, start: QPointF, end: QPointF, mods: Qt.KeyboardModifier = NONE) -> None:
    viewport = ws.viewport()
    QTest.mousePress(viewport, LEFT, mods, start.toPoint())
    for i in range(1, 5):
        QTest.mouseMove(viewport, (start + (end - start) * i / 4).toPoint())
    QTest.mouseRelease(viewport, LEFT, mods, end.toPoint())


def pos(window: MainWindow, wid: str) -> tuple[int, int]:
    widget = window.doc.page.widget(wid)
    assert widget is not None
    return widget.x, widget.y


def test_shift_click_adds_and_removes(window: MainWindow) -> None:
    ws, doc = window.workspace, window.doc
    click(ws, 150 + 8, 190 + 8)  # st_dot
    click(ws, 150 + 50, 212 + 12, SHIFT)  # alarm_lbl
    assert doc.selected_ids == ["st_dot", "alarm_lbl"]
    assert doc.selected == "alarm_lbl"  # the last one clicked shows in the properties
    item = ws.active_item()
    assert item is not None
    assert len(item.group_boxes) == 1  # the other one: a dashed outline
    click(ws, 150 + 50, 212 + 12, SHIFT)  # again: out of the selection
    assert doc.selected_ids == ["st_dot"]
    click(ws, 150 + 50, 212 + 12)  # a plain click: just that one
    assert doc.selected_ids == ["alarm_lbl"]


def test_frame_selects_what_it_touches(window: MainWindow) -> None:
    ws, doc = window.workspace, window.doc
    drag(ws, at(ws, 140, 182), at(ws, 319, 239))  # around st_dot, st_txt, alarm_lbl
    assert doc.selected_ids == ["st_dot", "st_txt", "alarm_lbl"]
    drag(ws, at(ws, 1, 101), at(ws, 30, 108), SHIFT)  # Shift: + the separator line
    assert doc.selected_ids == ["sep", "st_dot", "st_txt", "alarm_lbl"]
    click(ws, 318, 100)  # an empty place: nothing selected
    assert doc.selected_ids == []


def test_drag_moves_the_whole_selection_in_one_step(window: MainWindow) -> None:
    ws, doc = window.workspace, window.doc
    doc.select_many(["st_dot", "alarm_lbl"])
    before = pos(window, "st_dot"), pos(window, "alarm_lbl"), pos(window, "card")
    drag(ws, at(ws, 158, 198), at(ws, 158 + 20, 198 - 12))  # grab st_dot
    (x1, y1), (x2, y2) = pos(window, "st_dot"), pos(window, "alarm_lbl")
    shift = (x1 - before[0][0], y1 - before[0][1])
    assert shift == (22, -10)  # 20, -12 snapped: st_dot lands on the 4 px grid (172, 180)
    assert (x2 - before[1][0], y2 - before[1][1]) == shift  # the other one: the same step
    assert pos(window, "card") == before[2]
    assert doc.selected_ids == ["st_dot", "alarm_lbl"]  # still selected
    doc.undo_stack.undo()  # one step for the whole drag
    assert (pos(window, "st_dot"), pos(window, "alarm_lbl")) == before[:2]


def test_arrows_and_delete_act_on_all(window: MainWindow) -> None:
    ws, doc = window.workspace, window.doc
    doc.select_many(["st_dot", "st_txt"])
    before = pos(window, "st_dot"), pos(window, "st_txt")
    ws.setFocus()
    QTest.keyClick(ws, Qt.Key.Key_Right, SHIFT)
    QTest.keyClick(ws, Qt.Key.Key_Down)
    assert pos(window, "st_dot") == (before[0][0] + 10, before[0][1] + 1)
    assert pos(window, "st_txt") == (before[1][0] + 10, before[1][1] + 1)
    QTest.keyClick(ws, Qt.Key.Key_Delete)
    assert doc.page.widget("st_dot") is None
    assert doc.page.widget("st_txt") is None
    assert doc.selected_ids == []
    doc.undo_stack.undo()  # both come back in one step
    assert doc.page.widget("st_dot") is not None
    assert doc.page.widget("st_txt") is not None


def test_layers_and_canvas_share_the_selection(window: MainWindow) -> None:
    doc, layers = window.doc, window.layers
    role = Qt.ItemDataRole.UserRole
    doc.select_many(["title", "city_txt"])  # canvas -> layers
    assert sorted(i.data(role) for i in layers.selectedItems()) == ["city_txt", "title"]
    layers.clearSelection()  # layers -> canvas
    rows = {layers.item(i).data(role): layers.item(i) for i in range(layers.count())}
    rows["card"].setSelected(True)
    rows["sep"].setSelected(True)
    assert doc.selected_ids == ["card", "sep"]


def test_properties_colour_and_opacity_for_all(window: MainWindow) -> None:
    doc, props = window.doc, window.properties
    doc.select_many(["st_dot", "alarm_lbl"])
    assert props.many.isVisibleTo(props)
    assert not props.main.isVisibleTo(props)
    assert "Вибрано 2" in props.many_label.text()
    assert props.many_color_edit.text() == ""  # different colours
    props.many_color_edit.setText("#123456")
    props.many_color_edit.editingFinished.emit()
    props.many_opacity.setValue(40)
    for wid in ("st_dot", "alarm_lbl"):
        widget = doc.page.widget(wid)
        assert widget is not None
        assert (widget.color, widget.opacity) == ("#123456", 40)
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    st_dot = doc.page.widget("st_dot")
    assert st_dot is not None
    assert st_dot.color != "#123456"
    doc.select("st_dot")  # one widget: the usual properties again
    assert props.main.isVisibleTo(props)
    assert not props.many.isVisibleTo(props)


def test_copy_paste_and_duplicate_a_group(window: MainWindow) -> None:
    doc = window.doc
    doc.select_many(["st_dot", "st_txt"])
    assert window.duplicate_widget()
    assert doc.selected_ids == ["st_dot_2", "st_txt_2"]  # the copies, selected
    dot, dot2 = doc.page.widget("st_dot"), doc.page.widget("st_dot_2")
    txt, txt2 = doc.page.widget("st_txt"), doc.page.widget("st_txt_2")
    assert dot is not None and dot2 is not None and txt is not None and txt2 is not None  # noqa: PT018
    assert (dot2.x - dot.x, txt2.x - txt.x) == (8, 8)  # the same layout, moved together
    assert window.copy_widget()
    doc.add_page()
    assert window.paste_widget()
    assert [w.id for w in doc.page.widgets] == ["st_dot_2", "st_txt_2"]
    assert "елементів: 2" in window.statusBar().currentMessage()


# ------------------------------------------------------------------ align / distribute
def test_arrange_menu_and_buttons(window: MainWindow) -> None:
    doc, props = window.doc, window.properties
    titles = [a.text() for a in window.menuBar().actions() if a.text() == "Розташування"]
    assert titles == ["Розташування"]
    doc.select(None)
    assert not window.act_align["left"].isEnabled()
    doc.select_many(["st_dot", "st_txt", "alarm_lbl"])
    assert window.act_distribute["vertical"].isEnabled()
    window.act_align["left"].trigger()  # to the leftmost of the three (x = 150)
    assert {pos(window, i)[0] for i in ("st_dot", "st_txt", "alarm_lbl")} == {150}
    doc.undo_stack.undo()  # one step
    assert pos(window, "st_txt")[0] == 172
    props.arrange_buttons["top"].click()  # the same from the properties
    assert {pos(window, i)[1] for i in ("st_dot", "st_txt", "alarm_lbl")} == {186}
    assert props.arrange_buttons["vertical"].isEnabled()


def test_one_widget_centres_on_the_screen(window: MainWindow) -> None:
    window.doc.select("st_dot")  # 16×16 on a 320×240 screen
    assert window.act_align["hcenter"].isEnabled()
    assert not window.act_distribute["horizontal"].isEnabled()  # needs three
    window.act_align["hcenter"].trigger()
    window.act_align["vcenter"].trigger()
    assert pos(window, "st_dot") == (152, 112)
    assert not window.align_selected("hcenter")  # already there: nothing to undo
    assert "Уже вирівняно відносно екрана" in window.statusBar().currentMessage()
