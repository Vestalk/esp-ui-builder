"""Stage 11: building a page with the mouse, properties, layers, undo/redo."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from espui.core import serializer
from espui.core.models import Widget
from espui.gui.document import Document
from espui.gui.main_window import MainWindow
from espui.gui.properties import Section
from espui.gui.widgets_catalog import DEFAULTS, change_type, new_widget
from espui.gui.workspace import WIDGET_MIME, Workspace, snap
from espui.gui.workspace import resize_box as resize
from tests.gui.conftest import ROOT

WEATHER = ROOT / "examples" / "weather.espui"


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1400, 900)
    win.show()
    win.open_file(WEATHER)
    win.workspace.zoom_reset()
    return win


def doc_of(window: MainWindow) -> Document:
    return window.doc


def view_point(ws: Workspace, page_x: float, page_y: float) -> QPoint:
    """Viewport coordinates of a point of the active page."""
    item = ws.active_item()
    assert item is not None
    return ws.mapFromScene(item.mapToScene(QPointF(page_x, page_y)))


def drag(ws: Workspace, start: QPoint, end: QPoint, steps: int = 4) -> None:
    viewport = ws.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for i in range(1, steps + 1):
        point = start + (end - start) * i / steps
        QTest.mouseMove(viewport, point)
    QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)


# ------------------------------------------------------------------ palette
def test_click_in_palette_adds_in_the_centre(window: MainWindow) -> None:
    doc = doc_of(window)
    count = len(doc.page.widgets)
    item = window.widget_palette.item(0)  # Прямокутник
    window.widget_palette.itemClicked.emit(item)
    widget = doc.page.widgets[-1]
    assert len(doc.page.widgets) == count + 1
    assert (widget.id, widget.type, widget.w, widget.h) == ("rect_1", "rect", 120, 60)
    assert (widget.x + widget.w // 2, widget.y + widget.h // 2) == (160, 120)  # centre of 320x240
    assert doc.selected == "rect_1"
    window.widget_palette.itemClicked.emit(item)
    assert doc.page.widgets[-1].id == "rect_2"
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert len(doc.page.widgets) == count
    assert doc.selected is None


def test_palette_drag_carries_the_type(window: MainWindow) -> None:
    palette = window.widget_palette
    data = palette.mimeData([palette.item(3)])
    assert bytes(data.data(WIDGET_MIME).data()) == b"text"
    assert palette.mimeTypes() == [WIDGET_MIME]


def test_drop_on_the_canvas(window: MainWindow) -> None:
    ws = window.workspace
    data = QMimeData()
    data.setData(WIDGET_MIME, b"circle")
    pos = view_point(ws, 50, 200)
    event = QDropEvent(QPointF(pos), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)  # fmt: skip
    ws.dropEvent(event)
    widget = doc_of(window).page.widgets[-1]
    assert widget.type == "circle"
    assert (widget.x + widget.w // 2, widget.y + widget.h // 2) == (52, 200)  # snapped to 4 px


# ------------------------------------------------------------------ canvas
@pytest.mark.parametrize("zoom", [0.5, 1.0, 4.0])
def test_move_with_the_mouse(window: MainWindow, zoom: float) -> None:
    ws = window.workspace
    doc = doc_of(window)
    ws.set_zoom(zoom)
    ws.centerOn(ws.active_item().mapToScene(QPointF(300, 80)))  # type: ignore[union-attr]
    before = doc.page.widget("card")
    assert before is not None
    steps_before = doc.undo_stack.count()
    drag(ws, view_point(ws, 305, 85), view_point(ws, 305 + 37, 85 + 22))  # only the card is there
    after = doc.page.widget("card")
    assert after is not None
    assert (after.x, after.y) == (snap(before.x + 37), snap(before.y + 22))  # on the 4 px grid
    assert (after.x % 4, after.y % 4) == (0, 0)
    assert doc.undo_stack.count() == steps_before + 1  # one step for the whole gesture
    assert doc.selected == "card"
    doc.undo_stack.undo()
    assert doc.page.widget("card") == before


def test_click_selects_top_most_and_thin_lines(window: MainWindow) -> None:
    ws = window.workspace
    doc = doc_of(window)
    QTest.mouseClick(
        ws.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        view_point(ws, 100, 60),
    )
    assert doc.selected == "t_val"  # over the card
    ws.set_zoom(4.0)
    ws.centerOn(ws.active_item().mapToScene(QPointF(100, 105)))  # type: ignore[union-attr]
    # The separator line is 2 px thick; at 400 % a click 1 page px away still grabs it.
    QTest.mouseClick(
        ws.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        view_point(ws, 100, 103.2),
    )
    assert doc.selected == "sep"
    QTest.mouseClick(
        ws.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        view_point(ws, 100, 180),
    )
    assert doc.selected is None or doc.selected != "sep"


def test_resize_with_a_handle(window: MainWindow) -> None:
    ws = window.workspace
    doc = doc_of(window)
    doc.select("card")
    QApplication.processEvents()
    card = doc.page.widget("card")
    assert card is not None
    corner = view_point(ws, card.x + card.w, card.y + card.h)  # "se" handle
    drag(ws, corner, view_point(ws, card.x + card.w - 50, card.y + card.h + 10))
    resized = doc.page.widget("card")
    assert resized is not None
    right, bottom = snap(card.x + card.w - 50), snap(card.y + card.h + 10)  # edges on the grid
    assert (resized.x, resized.y, resized.w, resized.h) == (
        card.x,
        card.y,
        right - card.x,
        bottom - card.y,
    )
    assert doc.undo_stack.undoText().startswith("Змінити розмір")


def test_resize_rules() -> None:
    assert resize((10, 10, 40, 20), "w", 100, 0, False, False) == (46, 10, 4, 20)  # min 4 px
    assert resize((10, 10, 40, 20), "n", 0, 50, False, False) == (10, 26, 40, 4)
    assert resize((10, 10, 40, 0), "s", 0, -5, True, False) == (10, 10, 40, 0)  # a line: height 0
    assert resize((10, 10, 40, 20), "nw", -3, -3, False, True) == (7, 7, 43, 23)  # Alt: no grid
    assert resize((10, 10, 40, 20), "se", 5, 5, False, False) == (10, 10, 46, 26)  # edges 56/36


def test_arrows_and_delete(window: MainWindow, qtbot: QtBot) -> None:
    ws = window.workspace
    doc = doc_of(window)
    doc.select("st_dot")
    ws.setFocus()
    dot = doc.page.widget("st_dot")
    assert dot is not None
    steps = doc.undo_stack.count()
    qtbot.keyClick(ws, Qt.Key.Key_Right)
    qtbot.keyClick(ws, Qt.Key.Key_Right)
    qtbot.keyClick(ws, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    moved = doc.page.widget("st_dot")
    assert moved is not None
    assert (moved.x, moved.y) == (dot.x + 2, dot.y + 10)
    assert doc.undo_stack.count() == steps + 1  # nudges merge into one step
    qtbot.keyClick(ws, Qt.Key.Key_Delete)
    assert doc.page.widget("st_dot") is None
    assert doc.selected is None
    doc.undo_stack.undo()
    assert doc.page.widget("st_dot") is not None
    doc.select("st_dot")
    window.properties.delete_button.click()
    assert doc.page.widget("st_dot") is None


# ------------------------------------------------------------------ properties
def test_properties_edit_and_merge(window: MainWindow) -> None:
    doc = doc_of(window)
    panel = window.properties
    doc.select("title")
    assert panel.id_edit.text() == "title"
    steps = doc.undo_stack.count()
    for value in (20, 21, 22):
        panel.box_spins["x"].setValue(value)
    assert doc.page.widget("title").x == 22  # type: ignore[union-attr]
    assert doc.undo_stack.count() == steps + 1  # one step for one field
    panel.color_edit.setText("#FF0000")
    panel.color_edit.editingFinished.emit()
    assert doc.page.widget("title").color == "#ff0000"  # type: ignore[union-attr]
    panel.color_edit.setText("red")
    panel.color_edit.editingFinished.emit()
    assert "#rrggbb" in panel.error.text()
    panel.size_spin.setValue(30)
    assert doc.page.widget("title").font_size == 30  # type: ignore[union-attr]
    panel.font_combo.setCurrentIndex(panel.font_combo.findData("pixel"))
    panel.font_combo.activated.emit(panel.font_combo.currentIndex())
    assert doc.page.widget("title").font == "pixel"  # type: ignore[union-attr]
    panel.font_all.click()
    fonts = {w.font for w in doc.page.widgets if w.font is not None}
    assert fonts == {"pixel"}


def test_rename_id(window: MainWindow) -> None:
    doc = doc_of(window)
    panel = window.properties
    doc.select("title")
    panel.id_edit.setText("card")
    panel.id_edit.editingFinished.emit()
    assert "елемент «card» вже є" in panel.error.text()
    panel.id_edit.setText("heading")
    panel.id_edit.editingFinished.emit()
    assert doc.selected == "heading"
    assert doc.page.widget("heading") is not None


def test_type_change_drops_incompatible_binding(window: MainWindow) -> None:
    doc = doc_of(window)
    panel = window.properties
    messages: list[str] = []
    panel.message.connect(messages.append)
    doc.select("city_txt")  # text bound to a str parameter
    panel.type_combo.setCurrentIndex(panel.type_combo.findData("bar"))
    panel.type_combo.activated.emit(panel.type_combo.currentIndex())
    widget = doc.page.widget("city_txt")
    assert widget is not None
    assert (widget.type, widget.bind, widget.w, widget.h) == (
        "bar",
        None,
        DEFAULTS["bar"].w,
        DEFAULTS["bar"].h,
    )
    assert messages == ["Прив'язку до «city» знято: смуга прогресу не може її показати."]
    doc.undo_stack.undo()
    assert doc.page.widget("city_txt").type == "text"  # type: ignore[union-attr]


def test_change_type_rules() -> None:
    project = serializer.load(WEATHER)
    page = project.pages[0]
    st_txt = page.widget("st_txt")
    assert st_txt is not None
    rect, messages = change_type(st_txt, "rect", page)
    assert rect.rules == []  # a "text" condition doesn't apply to a rectangle
    assert messages == [
        "Прив'язку до «status» знято: прямокутник не може її показати.",
        "Умов, що не підходять до нового типу, видалено: 1.",
    ]
    same, none = change_type(st_txt, "text", page)
    assert (same, none) == (st_txt, [])
    assert new_widget(page, "line", 0, 0, centered=False).h == 0


def test_image_block(window: MainWindow, tmp_path: Path) -> None:
    doc = doc_of(window)
    panel = window.properties
    window.workspace.add_widget("image")
    assert panel.image.isVisible()
    frames = [Image.new("RGB", (8, 8), (i * 30, 0, 0)) for i in range(4)]
    frames[0].save(
        tmp_path / "blink.gif", save_all=True, append_images=frames[1:], duration=90, loop=0
    )
    assert panel.add_image_file(str(tmp_path / "blink.gif"))
    widget = doc.widget
    assert widget is not None
    assert widget.image is not None
    assert widget.image.file == "blink"
    assert panel.delay_spin.value() == 90
    assert doc.widget.image.play == "once"  # type: ignore[union-attr]  # by default: once
    assert not panel.loop_check.isChecked()
    panel.loop_check.setChecked(True)  # "Програвати циклічно"
    assert doc.widget.image.play == "loop"  # type: ignore[union-attr]
    panel.delay_spin.setValue(120)
    assert doc.project.images["blink"].delay_ms == 120
    panel.native_size.click()
    assert (doc.widget.w, doc.widget.h) == (8, 8)  # type: ignore[union-attr]
    assert not panel.add_image_file(str(WEATHER))  # not a picture
    assert "не схожий на картинку" in panel.error.text()
    panel.restart_button.click()  # restarts the preview animation, no error


def test_chart_block(window: MainWindow) -> None:
    doc = doc_of(window)
    panel = window.properties
    window.workspace.add_widget("chart")
    panel.axis_y.setText("°C")
    panel.axis_y.editingFinished.emit()
    panel.y_bounds["y_max"].setText("30")
    panel.y_bounds["y_max"].editingFinished.emit()
    panel.style_combo.setCurrentIndex(panel.style_combo.findData("bars"))
    panel.style_combo.activated.emit(panel.style_combo.currentIndex())
    panel.grid_check.setChecked(False)
    chart = doc.widget.chart  # type: ignore[union-attr]
    assert chart is not None
    assert (chart.axis_y, chart.y_max, chart.style, chart.grid) == ("°C", 30, "bars", False)


def test_sections_collapse_and_remember(qtbot: QtBot) -> None:
    QSettings().remove("sections/Тест")
    section = Section("Тест")
    qtbot.addWidget(section)
    assert section.header.isChecked()  # expanded
    section.header.click()
    assert section.header.text() == "▸ Тест"
    assert section.body.isHidden()
    again = Section("Тест")
    qtbot.addWidget(again)
    assert again.collapsed  # remembered between sessions
    again.header.click()
    QSettings().remove("sections/Тест")


# ------------------------------------------------------------------ layers
def layer_ids(window: MainWindow) -> list[str]:
    return window.layers.ids()


def test_layers_list_top_first(window: MainWindow) -> None:
    ids = layer_ids(window)
    assert ids[0] == "alarm_lbl"  # the last widget is drawn over all others
    assert ids[-1] == "card"
    text = window.layers.itemWidget(window.layers.item(ids.index("t_val"))).label.text()  # type: ignore[attr-defined]
    assert text == "4  t_val · Число · temperature  умов: 1"


def test_layer_order_three_ways(window: MainWindow, qtbot: QtBot) -> None:
    doc = doc_of(window)
    layers = window.layers
    # 1) the ↑ button of a row
    row = layers.itemWidget(layers.item(layer_ids(window).index("sep")))
    row.up.click()  # type: ignore[attr-defined]
    assert [w.id for w in doc.page.widgets].index("sep") == 5
    # 2) ↓ with the focus in the list
    doc.select("sep")
    layers.setFocus()
    qtbot.keyClick(layers, Qt.Key.Key_Down)
    assert [w.id for w in doc.page.widgets].index("sep") == 4
    # 3) Ctrl/⌘+↑ from anywhere
    window.act_layer_up.trigger()
    assert [w.id for w in doc.page.widgets].index("sep") == 5
    # 4) drag & drop of a row: card (bottom) moved to the top
    item = layers.takeItem(layers.count() - 1)
    layers.insertItem(0, item)
    layers.reordered("card")
    assert doc.page.widgets[-1].id == "card"
    assert layer_ids(window)[0] == "card"
    for _ in range(4):
        doc.undo_stack.undo()
    assert [w.id for w in doc.page.widgets] == [
        w.id for w in serializer.load(WEATHER).pages[0].widgets
    ]


def test_layer_click_selects(window: MainWindow) -> None:
    layers = window.layers
    layers.setCurrentRow(layer_ids(window).index("p_arc"))
    assert doc_of(window).selected == "p_arc"
    assert window.properties.id_edit.text() == "p_arc"


def test_undo_redo_round_trip(window: MainWindow) -> None:
    doc = doc_of(window)
    original = doc.project.model_copy(deep=True)
    window.workspace.add_widget("arc")
    doc.select("title")
    window.properties.box_spins["w"].setValue(100)
    doc.raise_layer("title", 3)
    doc.remove_widget("sep")
    while doc.undo_stack.canUndo():
        doc.undo_stack.undo()
    assert doc.project == original
    while doc.undo_stack.canRedo():
        doc.undo_stack.redo()
    assert doc.page.widget("sep") is None
    assert doc.page.widget("arc_1") is not None


def test_widgets_validate() -> None:
    assert Widget.model_validate({"id": "a", "type": "rect"}).w == 0
