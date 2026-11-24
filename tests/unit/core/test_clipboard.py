"""Copy / paste / duplicate of widgets: ids, places, parameters that come along."""

from __future__ import annotations

import json

import pytest

from espui.core import serializer
from espui.core.clipboard import ClipboardError, copy_payload, free_copy_id, paste
from espui.core.models import Page


def page(widgets: list[dict], parameters: list[dict] | None = None) -> Page:
    project = serializer.from_dict(
        {"pages": [{"name": "main", "parameters": parameters or [], "widgets": widgets}]}
    )
    return project.pages[0]


BUTTON = {"id": "btn", "type": "rect", "x": 10, "y": 20, "w": 80, "h": 30, "on_tap": "go"}
TEMP = {"name": "t", "type": "float", "min": 0, "max": 50, "default": 20}


def test_duplicate_on_the_same_page_gets_a_new_id_and_moves() -> None:
    src = page([BUTTON])
    text = copy_payload(src, src.widgets[0])
    first = paste(src, text)
    assert first.widget_id == "btn_2"
    copy = first.page.widget("btn_2")
    assert copy is not None
    assert (copy.x, copy.y, copy.on_tap) == (18, 28, "go")  # next to the original
    second = paste(first.page, text)
    assert second.widget_id == "btn_3"
    copy3 = second.page.widget("btn_3")
    assert copy3 is not None
    assert (copy3.x, copy3.y) == (26, 36)  # not on top of the first copy either
    assert [w.id for w in second.page.widgets] == ["btn", "btn_2", "btn_3"]  # on top
    assert src.widgets == [src.widgets[0]]  # the source page is not changed


def test_another_page_keeps_the_id_and_place_and_gets_the_parameters() -> None:
    value = {
        "id": "t_val",
        "type": "value",
        "x": 5,
        "y": 5,
        "w": 80,
        "h": 20,
        "bind": "t",
        "format": "%.1f",
        "rules": [{"if": ["on", "==", True], "set": "color", "to": "#f00"}],
    }
    src = page([value], [TEMP, {"name": "on", "type": "bool"}])
    pasted = paste(page([]), copy_payload(src, src.widgets[0]))  # fmt: skip
    assert pasted.widget_id == "t_val"
    widget = pasted.page.widget("t_val")
    assert widget is not None
    assert (widget.x, widget.y, widget.bind) == (5, 5, "t")
    assert [p.name for p in pasted.page.parameters] == ["t", "on"]  # came along
    assert pasted.notes == ["додано параметр «t»", "додано параметр «on»"]


def test_a_parameter_of_another_type_drops_the_references() -> None:
    value = {
        "id": "t_val",
        "type": "value",
        "w": 80,
        "h": 20,
        "bind": "t",
        "format": "%.1f",
        "rules": [{"if": ["t", ">", 30], "set": "color", "to": "#f00"}],
    }
    src = page([value], [TEMP])
    target = page([], [{"name": "t", "type": "str"}])
    pasted = paste(target, copy_payload(src, src.widgets[0]))  # fmt: skip
    widget = pasted.page.widget("t_val")
    assert widget is not None
    assert (widget.bind, widget.rules) == (None, [])
    assert [p.type for p in pasted.page.parameters] == ["str"]  # the target's own stays
    assert "прив'язку й умови з ним прибрано" in pasted.notes[0]


@pytest.mark.parametrize(
    ("taken", "wanted", "result"),
    [
        ([], "btn", "btn"),
        (["btn"], "btn", "btn_2"),
        (["btn", "btn_2"], "btn_2", "btn_3"),
        (["rect_1"], "rect_1", "rect_2"),
        (["a" * 32], "a" * 32, "a" * 30 + "_2"),  # ids stay within 32 characters
    ],
)
def test_free_copy_id(taken: list[str], wanted: str, result: str) -> None:
    widgets = [{"id": i, "type": "rect", "x": n * 10, "w": 5, "h": 5} for n, i in enumerate(taken)]
    assert free_copy_id(page(widgets), wanted) == result


@pytest.mark.parametrize("text", ["", "просто текст", json.dumps({"format": "other"}),
                                  json.dumps({"format": "espui-widget/1", "widget": {}})])  # fmt: skip
def test_not_a_copied_widget(text: str) -> None:
    with pytest.raises(ClipboardError):
        paste(page([]), text)
