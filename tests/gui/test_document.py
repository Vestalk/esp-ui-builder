"""Document: pages and display changes with undo (no widgets needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from espui.core import serializer
from espui.core.hardware import Chip
from espui.gui.document import Document
from tests.gui.conftest import PAGES


@pytest.fixture
def doc(qtbot: QtBot) -> Document:
    return Document(serializer.load(PAGES), PAGES)


def names(doc: Document) -> list[str]:
    return [p.name for p in doc.project.pages]


def test_add_empty_and_copy_with_undo(doc: Document) -> None:
    doc.add_page()
    assert names(doc) == ["main", "page", "settings"]
    assert doc.current == 1
    assert doc.page.widgets == []
    assert doc.page.background == "#0b1a22"  # takes the background of the page it was added after
    doc.set_current(0)
    doc.add_page(copy_current=True)
    assert names(doc) == ["main", "main_copy", "page", "settings"]
    assert len(doc.page.widgets) == len(doc.project.pages[0].widgets)
    assert doc.page.widgets[0] is not doc.project.pages[0].widgets[0]  # a deep copy
    assert doc.dirty
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert names(doc) == ["main", "settings"]
    assert doc.undo_stack.isClean()  # back to the saved state
    doc.undo_stack.redo()
    assert names(doc) == ["main", "page", "settings"]


def test_free_page_names(doc: Document) -> None:
    doc.add_page()
    doc.add_page()
    assert {"page", "page_2"} <= set(names(doc))
    assert doc.free_page_name("display") == "display_2"  # reserved name skipped


def test_remove_page_with_undo(doc: Document) -> None:
    doc.set_current(1)
    assert doc.remove_page(1)
    assert names(doc) == ["main"]
    assert doc.current == 0
    assert not doc.remove_page(0)  # the last page stays
    doc.undo_stack.undo()
    assert names(doc) == ["main", "settings"]
    assert doc.current == 1


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("settings", "сторінка «settings» вже є"),
        ("Main", "лише латинські малі літери"),
        ("fonts", "ui_fonts.py вже зайнято спільним файлом"),
        ("class", "зарезервоване слово Python"),
        ("", "назва порожня"),
    ],
)
def test_rename_problems(doc: Document, name: str, problem: str) -> None:
    result = doc.rename_page(0, name)
    assert result is not None
    assert problem in result
    assert names(doc) == ["main", "settings"]
    assert not doc.dirty


def test_rename_with_undo(doc: Document) -> None:
    assert doc.rename_page(0, "home") is None
    assert names(doc) == ["home", "settings"]
    assert doc.rename_page(0, "home") is None  # same name: no extra undo step
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert names(doc) == ["main", "settings"]


def test_display_change_and_widgets_outside(doc: Document) -> None:
    assert doc.widgets_outside() == []
    display = doc.project.display.model_copy(update={"rotation": 0, "mcu": Chip.ESP32})
    doc.set_display(display)
    assert doc.project.display.size == (240, 320)
    assert "main/head" in doc.widgets_outside()  # 300 px wide text on a 240 px wide screen
    doc.set_display(display)  # unchanged: nothing pushed
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert doc.project.display.rotation == 1


def test_save_and_open(doc: Document, tmp_path: Path, qtbot: QtBot) -> None:
    doc.rename_page(0, "home")
    with qtbot.waitSignal(doc.file_changed):
        doc.save(tmp_path / "copy.espui")
    assert not doc.dirty
    other = Document()
    assert other.title == "Без назви.espui"
    with pytest.raises(ValueError, match="no file name"):
        other.save()
    with qtbot.waitSignal(other.changed):
        other.open(tmp_path / "copy.espui")
    assert names(other) == ["home", "settings"]
    assert other.title == "copy.espui"
    other.open(PAGES.parent.parent / "tests" / "fixtures" / "mockup_weather.espui.json")
    assert other.path is None  # a mock-up export is saved as a new .espui
