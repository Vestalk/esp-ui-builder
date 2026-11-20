"""Colours, compatibility tables and small helpers."""

from __future__ import annotations

import pytest

from espui.core.colors import (
    RGB,
    blend,
    from_rgb565,
    is_hex,
    normalize_hex,
    parse_hex,
    quantize,
    rgb565,
    swap16,
    to_hex,
    to_wire,
)
from espui.core.compat import (
    condition_props,
    mapping_props,
    operators_for,
    prop_value_problem,
)
from espui.core.issues import Issue, format_path
from tests.unit.core.conftest import FLAG, LEVEL, MODE, NAME, SERIES, TEMP, make_page


# ------------------------------------------------------------------ colours
@pytest.mark.parametrize(
    ("value", "ok"),
    [("#fff", True), ("#A1b2C3", True), ("fff", False), ("#ffff", False), ("#ggg", False)],
)
def test_is_hex(value: str, ok: bool) -> None:
    assert is_hex(value) is ok


def test_normalize_and_parse() -> None:
    assert normalize_hex("#AbC") == "#aabbcc"
    assert parse_hex("#ff8000") == RGB(255, 128, 0)
    with pytest.raises(ValueError, match="#rrggbb"):
        normalize_hex("red")


def test_to_hex_clamps() -> None:
    assert to_hex((300, -5, 16)) == "#ff0010"


@pytest.mark.parametrize(
    ("color", "value", "wire"),
    [
        ("#ff0000", 0xF800, 0x00F8),  # same as ui_st7789.color(255, 0, 0)
        ("#00ff00", 0x07E0, 0xE007),
        ("#0000ff", 0x001F, 0x1F00),
        ("#ffffff", 0xFFFF, 0xFFFF),
    ],
)
def test_rgb565_and_wire_order(color: str, value: int, wire: int) -> None:
    assert rgb565(parse_hex(color)) == value
    assert to_wire(color) == wire
    assert swap16(wire) == value


def test_rgb565_round_trip() -> None:
    assert from_rgb565(0xFFFF) == RGB(255, 255, 255)
    assert from_rgb565(0x0000) == RGB(0, 0, 0)
    assert quantize("#123456") == "#103452"
    assert quantize("#ffffff") == "#ffffff"


@pytest.mark.parametrize(
    ("alpha", "expected"),
    [(0, "#000000"), (1, "#ffffff"), (0.5, "#808080"), (2, "#ffffff"), (-1, "#000000")],
)
def test_blend(alpha: float, expected: str) -> None:
    assert blend("#ffffff", "#000000", alpha) == expected


# ------------------------------------------------------------------ compat tables
def test_operators_per_type() -> None:
    params = {p.name: p for p in make_page([TEMP, LEVEL, FLAG, MODE, NAME, SERIES]).parameters}
    assert operators_for(params["t"]) == (">", "<", ">=", "<=", "==", "!=")
    assert operators_for(params["n"]) == operators_for(params["t"])
    assert operators_for(params["on"]) == ("==",)
    assert operators_for(params["mode"]) == ("==", "!=")
    assert operators_for(params["label"]) == ("==", "!=")
    assert operators_for(params["s"]) == ()


def test_props_per_widget_type() -> None:
    assert condition_props("text") == ("color", "text", "visible", "opacity", "angle", "x", "y")
    assert condition_props("rect") == ("color", "visible", "opacity", "angle", "x", "y")
    assert condition_props("chart") == ("color", "visible", "opacity", "x", "y")
    assert mapping_props("arc") == ("opacity", "angle", "x", "y")
    assert mapping_props("chart") == ("opacity", "x", "y")


@pytest.mark.parametrize(
    ("prop", "value", "problem"),
    [
        ("color", "#fff", None),
        ("text", "a", None),
        ("visible", True, None),
        ("opacity", 0, None),
        ("angle", -720, None),
        ("x", float("nan"), "очікується число"),
        ("y", True, "очікується число"),
    ],
)
def test_prop_values(prop: str, value: object, problem: str | None) -> None:
    assert prop_value_problem(prop, value) == problem


# ------------------------------------------------------------------ issues
def test_format_path_and_issue() -> None:
    assert format_path(("pages", 0, "widgets", 2, "x")) == "pages[0].widgets[2].x"
    assert format_path(()) == ""
    assert str(Issue("", "порожній файл")) == "(проєкт): порожній файл"
