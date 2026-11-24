"""Ctrl+C / Ctrl+V / Ctrl+D on the canvas and the layers; Edit menu."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from espui.gui.main_window import MainWindow
from tests.gui.conftest import ROOT

WEATHER = ROOT / "examples" / "weather.espui"


@pytest.fixture
def window(qtbot: QtBot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1300, 850)
    win.show()
    win.open_file(WEATHER)
    QApplication.processEvents()
    return win


def ids(window: MainWindow) -> list[str]:
    return [w.id for w in window.doc.page.widgets]


def test_duplicate_with_ctrl_d_on_the_canvas(window: MainWindow) -> None:
    window.doc.select("card")
    window.workspace.setFocus()
    QTest.keyClick(window.workspace, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert ids(window)[-1] == "card_2"
    assert window.doc.selected == "card_2"  # the copy is selected, ready to move
    original, copy = window.doc.page.widget("card"), window.doc.page.widget("card_2")
    assert original is not None
    assert copy is not None
    assert (copy.x - original.x, copy.y - original.y) == (8, 8)
    assert "Вставлено «card_2»" in window.statusBar().currentMessage()
    window.doc.undo_stack.undo()  # one step
    assert "card_2" not in ids(window)


def test_copy_and_paste_onto_another_page(window: MainWindow) -> None:
    window.doc.select("t_val")  # bound to "temperature"
    window.workspace.setFocus()
    QTest.keyClick(window.workspace, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert "espui-widget" in QGuiApplication.clipboard().text()
    window.doc.add_page()  # an empty page, current now
    assert window.doc.page.widgets == []
    window.workspace.setFocus()
    QTest.keyClick(window.workspace, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert ids(window) == ["t_val"]
    widget = window.doc.page.widget("t_val")
    assert widget is not None
    assert widget.bind == "temperature"
    # bound to "temperature", a condition on "alarm": both came along
    assert [p.name for p in window.doc.page.parameters] == ["temperature", "alarm"]
    assert "додано параметр «temperature»" in window.statusBar().currentMessage()


def test_menu_entries_and_nothing_to_paste(window: MainWindow) -> None:
    titles = [a.text() for a in window.menuBar().actions()[1].menu().actions()]  # type: ignore[union-attr]
    for title in ("Копіювати елемент", "Вставити елемент", "Дублювати елемент"):
        assert title in titles
    QGuiApplication.clipboard().setText("просто текст")
    before = ids(window)
    assert not window.paste_widget()
    assert ids(window) == before
    assert "немає скопійованого елемента" in window.statusBar().currentMessage()
    window.doc.select(None)
    window.act_duplicate.trigger()
    assert "Спершу виберіть елемент" in window.statusBar().currentMessage()


def test_ctrl_c_in_a_text_field_copies_text(window: MainWindow) -> None:
    window.doc.select("card")
    field = window.properties.id_edit
    field.setFocus()
    field.selectAll()
    QGuiApplication.clipboard().setText("")
    QTest.keyClick(field, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QGuiApplication.clipboard().text() == "card"  # the text, not a widget
