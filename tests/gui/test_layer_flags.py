"""👁 hide in the editor and 🔒 lock: editor-only, the board draws the page the same."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from espui.gui.layers import LayerRow
from espui.gui.main_window import MainWindow
from espui.gui.workspace import Workspace
from tests.gui.test_multiselect import WEATHER, at, click, drag, pos

ROLE = Qt.ItemDataRole.UserRole


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


def row(window: MainWindow, wid: str) -> LayerRow:
    layers = window.layers
    for i in range(layers.count()):
        if layers.item(i).data(ROLE) == wid:
            widget = layers.itemWidget(layers.item(i))
            assert isinstance(widget, LayerRow)
            return widget
    raise AssertionError(wid)


def pixel(ws: Workspace, x: int, y: int) -> int:
    item = ws.active_item()
    assert item is not None
    return item.image.pixel(x, y)


def generated(window: MainWindow) -> dict[str, bytes]:
    from espui.generators.micropython.generator import generate

    return generate(window.doc.project).files


def test_eye_hides_in_the_editor_only(window: MainWindow) -> None:
    doc, ws = window.doc, window.workspace
    before_code = generated(window)
    dot = pixel(ws, 158, 198)  # the middle of st_dot
    doc.select("st_dot")
    row(window, "st_dot").eye.click()
    st_dot = doc.page.widget("st_dot")
    assert st_dot is not None
    assert st_dot.editor_hidden
    assert pixel(ws, 158, 198) != dot  # not drawn in the editor
    assert doc.selected is None  # hidden: out of the selection
    assert row(window, "st_dot").eye.isChecked()
    assert not row(window, "st_dot").label.isEnabled()  # the row reads greyed out
    click(ws, 158, 198)  # can't be picked: what lies below (the empty page here)
    assert doc.selected != "st_dot"
    assert generated(window) == before_code  # the board draws it as before
    doc.undo_stack.undo()
    st_dot = doc.page.widget("st_dot")
    assert st_dot is not None
    assert not st_dot.editor_hidden
    assert pixel(ws, 158, 198) == dot


def test_lock_keeps_a_widget_from_the_canvas(window: MainWindow) -> None:
    doc, ws = window.doc, window.workspace
    row(window, "card").lock.click()  # the background card: the usual one to lock
    card = doc.page.widget("card")
    assert card is not None
    assert card.locked
    assert row(window, "card").lock.isChecked()
    before = pos(window, "card")
    click(ws, 300, 60)  # on the card, nothing else there: an empty place
    assert doc.selected_ids == []
    drag(ws, at(ws, 300, 60), at(ws, 260, 30))  # a frame, not a move
    assert pos(window, "card") == before
    assert "card" not in doc.selected_ids
    drag(ws, at(ws, 1, 1), at(ws, 319, 239))  # a frame over everything skips it
    assert "card" not in doc.selected_ids
    assert "title" in doc.selected_ids
    doc.select("card")  # from "Шари" it can still be selected (and edited)
    ws.setFocus()
    QTest.keyClick(ws, Qt.Key.Key_Right)
    assert pos(window, "card") == before  # but not moved
    assert "заблоковано" in window.statusBar().currentMessage()
    item = ws.active_item()
    assert item is not None
    assert not any(h.isVisible() for h in item.selection.handles.values())  # no handles


def test_lock_in_a_group_stays_put(window: MainWindow) -> None:
    doc, ws = window.doc, window.workspace
    doc.select_many(["st_dot", "alarm_lbl"])
    doc.toggle_flag("locked", ["alarm_lbl"])
    doc.select_many(["st_dot", "alarm_lbl"])
    before = pos(window, "alarm_lbl")
    drag(ws, at(ws, 158, 198), at(ws, 178, 186))
    assert pos(window, "alarm_lbl") == before
    assert pos(window, "st_dot") != (150, 190)


def test_menu_toggles_the_selection_and_unhide_all(window: MainWindow) -> None:
    doc = window.doc
    doc.select_many(["title", "city_txt"])
    window.act_lock.trigger()
    assert all(w.locked for w in doc.page.widgets if w.id in ("title", "city_txt"))
    window.act_lock.trigger()  # all locked: unlock
    assert not any(w.locked for w in doc.page.widgets)
    window.act_hide.trigger()
    assert {w.id for w in doc.page.widgets if w.editor_hidden} == {"title", "city_txt"}
    doc.toggle_flag("locked", ["sep"])
    assert window.unhide_all()
    assert not any(w.editor_hidden or w.locked for w in doc.page.widgets)
    doc.undo_stack.undo()  # one step back: hidden and locked again
    assert {w.id for w in doc.page.widgets if w.editor_hidden or w.locked} == {
        "title",
        "city_txt",
        "sep",
    }
    doc.select(None)
    window.act_hide.trigger()
    assert "Спершу виберіть" in window.statusBar().currentMessage()


def test_flags_are_saved(window: MainWindow, tmp_path: object) -> None:
    from pathlib import Path

    from espui.core import serializer

    window.doc.toggle_flag("locked", ["card"])
    window.doc.toggle_flag("editor_hidden", ["sep"])
    path = Path(str(tmp_path)) / "flags.espui"
    serializer.save(window.doc.project, path)
    page = serializer.load(path).pages[0]
    card, sep = page.widget("card"), page.widget("sep")
    assert card is not None and sep is not None  # noqa: PT018
    assert (card.locked, sep.editor_hidden) == (True, True)
